"""arXiv listing harvest plugin (source #4 in docs/sources.md).

Covers the cs.CR (Cryptography & Security) and cs.CL (Computation & Language)
``/new`` listings, then follows through to each abstract page.

  * **Primary product:** Web Unlocker (``website/WEB-UNLOCKER/``).
    arXiv doesn't gate behind a heavy WAF but Web Unlocker normalizes
    rate-limit + retry behavior across all blog/index plugins, so we keep
    everything static-HTML on the same path.
  * **Fallback:** none — if Web Unlocker can't fetch arXiv, the source goes
    stale and the harvest run continues without it (§9.3 source-level
    failure handling).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone

from rogue.harvest.bright_data_client import BrightDataClient
from rogue.schemas import RawDocument

from .base import SourcePlugin

__all__ = ["ArxivListingPlugin"]


DEFAULT_LISTINGS = [
    # Primary categories (security + NLP).
    "https://arxiv.org/list/cs.CR/new",  # Cryptography & Security
    "https://arxiv.org/list/cs.CL/new",  # Computation & Language (NLP / LLMs)
    # Secondary (added 2026-05-26): prompt-injection / abliteration / red-team
    # papers regularly cross-list into cs.AI + cs.LG without appearing in
    # cs.CR/CL. Higher volume, more noise — the extraction LLM's
    # commentary-filter drops non-jailbreak abstracts downstream. If these
    # turn out to be too noisy in practice, the right cut is to wire
    # arxiv's API search (export.arxiv.org/api/query?search_query=all:%22prompt+injection%22)
    # so we only pull papers actually matching attack keywords across ALL
    # categories — Day-2+ work; tracked on the §STATUS bullet list.
    "https://arxiv.org/list/cs.AI/new",  # Artificial Intelligence (broad)
    "https://arxiv.org/list/cs.LG/new",  # Machine Learning (training-time attacks, weight abliteration)
]

# Match the listing page's `<a href="/abs/2605.18239">` style links. Catches
# both new-style YYMM.NNNNN and legacy `category/YYMMNNN` IDs.
#
# 2026-05-26 fix: arXiv ships markup with a literal SPACE before `=` —
# `<a href ="/abs/2605.22842" title="Abstract">`. The original regex required
# `href="..."` with no whitespace and silently returned 0 hits on every
# harvest. Allow optional whitespace either side of `=` so both old- and
# new-vintage HTML keep matching.
ABS_HREF_RE = re.compile(r'href\s*=\s*"/abs/([0-9]{4}\.[0-9]{4,6}(?:v\d+)?)"')


class ArxivListingPlugin(SourcePlugin):
    """arXiv cs.CR + cs.CL new-listing harvester (Web Unlocker)."""

    name = "arxiv_listing"
    source_type = "arxiv"
    bright_data_product = "web_unlocker"

    def __init__(self, listings: list[str] | None = None) -> None:
        self.listings = listings if listings is not None else list(DEFAULT_LISTINGS)
        self.call_errors: list[str] = []

    def serp_queries(self, since: datetime) -> list[str]:
        """arXiv SERP queries (docs/sources.md §4)."""
        date_str = (since - timedelta(days=1)).strftime("%Y-%m-%d")
        return [
            f'site:arxiv.org "prompt injection" after:{date_str}',
            f'site:arxiv.org "jailbreak" "LLM" after:{date_str}',
            f'site:arxiv.org "adversarial" "language model" after:{date_str}',
            f'site:arxiv.org "red team" "LLM" after:{date_str}',
        ]

    async def fetch_since(
        self,
        client: BrightDataClient,
        since: datetime,
    ) -> list[RawDocument]:
        """Fetch each listing in parallel, then each abstract in chunked parallel.

        Pre-2026-05-26 PM this method ran serially: ~120 sequential abstract
        Web Unlocker fetches × ~5s each = ~10 min for the 4-listing default.
        Parallelization in chunks of 16 (Semaphore-bounded so we don't burst
        past BD's per-zone concurrency limit) brings that to ~1-2 min.
        """
        self.call_errors = []
        logger = logging.getLogger(__name__)
        fetched_at = datetime.now(timezone.utc)

        async def fetch_listing(listing_url: str) -> tuple[str, list[str]]:
            try:
                listing = await client.web_unlock(listing_url, format="html")
            except NotImplementedError:
                raise
            except Exception as exc:
                self.call_errors.append(
                    f"listing:{listing_url}: {type(exc).__name__}: {exc}"
                )
                logger.warning("arxiv listing fetch failed: %s", listing_url)
                return listing_url, []
            ids = ABS_HREF_RE.findall(listing.content)
            if not ids:
                self.call_errors.append(
                    f"listing:{listing_url}: 0 arxiv IDs matched in "
                    f"{len(listing.content)}-byte response — verify ABS_HREF_RE"
                )
                logger.warning("arxiv: 0 IDs for %s", listing_url)
            return listing_url, ids

        # Parallel listing fetches (cheap, ~4 calls).
        listing_results = await asyncio.gather(
            *(fetch_listing(u) for u in self.listings)
        )

        # Collapse across listings + dedupe IDs. Keep the FULL (versioned) id
        # as the §11.7 freshness token — an arXiv abstract is immutable per
        # version, so `2605.18239v2` unchanged ⇒ skip the re-fetch; a new
        # version (`...v3`) changes the token ⇒ re-fetch.
        seen_ids: set[str] = set()
        id_to_listing: dict[str, str] = {}
        id_to_token: dict[str, str] = {}
        for listing_url, raw_ids in listing_results:
            for raw_id in raw_ids:
                arxiv_id = raw_id.split("v")[0]  # strip version suffix
                if arxiv_id in seen_ids:
                    continue
                seen_ids.add(arxiv_id)
                id_to_listing[arxiv_id] = listing_url
                id_to_token[arxiv_id] = raw_id

        # Bounded-concurrency abstract fetches. Semaphore cap of 16 is the
        # rule-of-thumb safe number for BD Web Unlocker (no published limit;
        # 16 is well under any practical zone burst cap).
        sem = asyncio.Semaphore(16)

        async def fetch_one_abstract(
            arxiv_id: str, listing_url: str, version_token: str
        ) -> RawDocument | None:
            abs_url = f"https://arxiv.org/abs/{arxiv_id}"
            # §11.7 Tier B — skip the Web Unlocker fetch when the versioned id
            # is unchanged since the last run (abstract is immutable per version).
            if self.should_skip_fetch(abs_url, version_token):
                return None
            async with sem:
                try:
                    page = await client.web_unlock(abs_url, format="html")
                except NotImplementedError:
                    raise
                except Exception:
                    return None
            raw_content = page.content
            archive_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
            try:
                return RawDocument(
                    url=abs_url,
                    source_type=self.source_type,
                    bright_data_product=self.bright_data_product,
                    fetched_at=fetched_at,
                    raw_content=raw_content,
                    content_format="html",
                    archive_hash=archive_hash,
                    http_status=page.status_code,
                    metadata={
                        "arxiv_id": arxiv_id,
                        "listing_url": listing_url,
                        "version_token": version_token,
                    },
                    discovered_via=None,
                )
            except Exception:
                return None

        abstract_results = await asyncio.gather(
            *(
                fetch_one_abstract(aid, lurl, id_to_token[aid])
                for aid, lurl in id_to_listing.items()
            )
        )
        _ = since
        return [d for d in abstract_results if d is not None]
