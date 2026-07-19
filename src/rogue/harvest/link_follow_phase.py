"""Post→link following phase (Feature C, 2026-05-30).

A harvested post often only *teases* a technique and links OUT to the full
implementation — @akaclandestine's X post → ``giovannigatti.github.io/cve-bench/``.
This phase, run AFTER the plugins (mirroring ``bandit_serp_phase``), reads
outbound links from the high-signal *post* docs, resolves shorteners, fetches
each link 1-hop via Web Unlocker, and emits the result as an extra
``RawDocument`` tagged ``discovered_via=f"post_link:{source_post_url}"`` so the
provenance is honest.

Design (matches the SERP-phase precedent — see that file's header):
  * **1-hop only.** Links are extracted ONLY from the plugin/post docs passed in,
    never from pages this phase itself fetched (no links-of-links).
  * **Domain routing.** A discovered link is fetched via ``web_unlock`` and
    labeled with ``_infer_source_type`` (github.com → ``github``, arxiv.org →
    ``arxiv``, …). The arxiv/github/pliny plugins are *listing*-based with no
    single-URL entry point, so — exactly as the SERP phase already does — we
    web_unlock the URL and let the standard extraction handle it.
  * **Bounded.** ``max_links_per_doc`` (default 3) × ``max_total`` (default 25)
    caps Web-Unlocker spend. Links are mined from EVERY source by default
    (``source_types=None``); the same-site filter + caps keep it safe.
  * **Deduped.** Resolved URLs are checked against (and added to) ``seen_urls``
    — the plugin URLs, the SERP-phase URLs, and the cross-run ``fetch_cache``
    set — so we never double-pay for content already in the pipeline.

Serial by design: the run-wide ``max_total`` cap is exact, and ≤25 fetches is
cheap. Per-link failures are isolated; the phase never raises.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from rogue.harvest.bandit_serp_phase import _infer_source_type
from rogue.harvest.fetchers.base import Fetcher
from rogue.harvest.link_extract import (
    DEFAULT_LINKS_PER_DOC,
    extract_outbound_urls,
    is_shortener,
)
from rogue.schemas.raw_document import RawDocument

__all__ = [
    "LinkFollowPhaseResult",
    "run_link_follow_phase",
    "SUGGESTED_POST_SOURCE_TYPES",
    "DEFAULT_MAX_LINKS_TOTAL",
]

logger = logging.getLogger(__name__)

_UNLOCKER_COST_PER_PAGE = 0.0025

# Run-wide cap on followed links (Web-Unlocker spend bound).
DEFAULT_MAX_LINKS_TOTAL = 25

# Default is to follow links from EVERY source (``source_types=None``). The
# same-registrable-domain filter in ``link_extract`` already drops self-links
# (an arxiv abstract's links to arxiv, a github repo's links to github — whose
# content we're already processing), and the per-doc/total caps bound spend, so
# no source needs categorical exclusion. This preset is kept only as an OPTIONAL
# narrower set a caller can pass explicitly (the post/discussion sources where
# "teaser → full impl at <url>" is most common).
SUGGESTED_POST_SOURCE_TYPES: frozenset[str] = frozenset(
    {"x", "reddit", "blog", "huggingface", "community_archive", "leakhub"}
)


@dataclass(frozen=True)
class LinkFollowPhaseResult:
    """What the phase produces — consumed by ``DiscoveryAgent.run``."""

    docs: list[RawDocument]
    """RawDocuments fetched from followed links, tagged discovered_via=post_link:{url}."""

    followed: int
    """Count of links actually fetched (== len(docs) on full success)."""

    cost_usd: float = 0.0
    """Total Web-Unlocker spend attributed to this phase."""

    errors: list[str] = field(default_factory=list)
    """["resolve_failed ...", "fetch_failed ...", ...] for observability."""


async def run_link_follow_phase(
    fetcher: Fetcher,
    source_docs: list[RawDocument],
    *,
    seen_urls: set[str] | None = None,
    max_links_per_doc: int = DEFAULT_LINKS_PER_DOC,
    max_total: int = DEFAULT_MAX_LINKS_TOTAL,
    source_types: frozenset[str] | set[str] | None = None,
) -> LinkFollowPhaseResult:
    """Follow outbound links from ``source_docs`` 1-hop and emit tagged RawDocuments.

    Args:
        fetcher: a :class:`~rogue.harvest.fetchers.base.Fetcher` (typically a
            :class:`~rogue.harvest.fetchers.routing.RoutingFetcher`); uses
            :meth:`Fetcher.resolve_redirect` and :meth:`Fetcher.unlock`.
        source_docs: the plugin/post docs to mine for outbound links. 1-hop is
            enforced by the caller passing ONLY plugin docs (never this phase's
            own output or the SERP phase's).
        seen_urls: URLs to skip (already in the pipeline). Mutated in place —
            every resolved+followed URL (and its pre-resolution form) is added so
            a later doc in the same run can't re-follow it. ``None`` ⇒ skip
            nothing.
        max_links_per_doc: per-doc outbound-link cap (default 3).
        max_total: run-wide cap on links fetched (default 25).
        source_types: which ``source_type`` docs to mine. ``None`` (default) ⇒
            mine EVERY source. Pass a set (e.g.
            :data:`SUGGESTED_POST_SOURCE_TYPES`) to narrow it.

    Returns:
        :class:`LinkFollowPhaseResult` — never raises. Per-link failures land in
        ``errors``. Empty/over-budget input is a fast no-op (zero network calls).
    """
    follow_set = frozenset(source_types) if source_types is not None else None
    seen: set[str] = seen_urls if seen_urls is not None else set()

    docs: list[RawDocument] = []
    errors: list[str] = []
    cost = 0.0

    # PHASE 1 — collect the final URLs to fetch (dedup + shortener-resolve), capped at max_total.
    # This part is cheap (resolve_redirect only fires for the rare t.co-style shortener) so it stays
    # sequential; the expensive part is the unlock() fetch below, which we parallelize.
    targets: list[tuple[str, "RawDocument"]] = []
    for source_doc in source_docs:
        if len(targets) >= max_total:
            break
        if follow_set is not None and str(source_doc.source_type) not in follow_set:
            continue

        outbound = extract_outbound_urls(
            source_doc.raw_content,
            str(source_doc.content_format),
            str(source_doc.url),
            limit=max_links_per_doc,
        )
        if not outbound:
            continue

        for raw_url in outbound:
            if len(targets) >= max_total:
                break
            if raw_url in seen:
                continue
            seen.add(raw_url)

            # Resolve t.co-style shorteners to the real destination so dedup +
            # routing + provenance key on the true URL.
            if is_shortener(raw_url):
                try:
                    final_url = await fetcher.resolve_redirect(raw_url)
                except Exception as exc:  # noqa: BLE001 — degrade to the short link
                    errors.append(f"resolve_failed {raw_url}: {type(exc).__name__}: {exc}")
                    final_url = raw_url
            else:
                final_url = raw_url

            # If a shortener resolved to a URL already in the pipeline, skip; mark
            # the resolved form seen too. (For non-shorteners final == raw, which
            # is already in `seen` — don't re-check it against itself.)
            if final_url != raw_url:
                if final_url in seen:
                    continue
                seen.add(final_url)

            targets.append((final_url, source_doc))

    # PHASE 2 — fetch every target CONCURRENTLY (bounded). crawl4ai spawns a browser per unlock, so
    # the semaphore caps how many run at once. Default 12 (was effectively 1 — this loop used to
    # `await` each fetch serially); tune with HARVEST_FETCH_CONCURRENCY. Each fetch is fail-soft.
    concurrency = max(1, int(os.environ.get("HARVEST_FETCH_CONCURRENCY", "12")))
    sem = asyncio.Semaphore(concurrency)

    async def _fetch_one(final_url: str, source_doc: "RawDocument"):
        async with sem:
            try:
                page = await fetcher.unlock(final_url, format="markdown")
            except Exception as exc:  # noqa: BLE001 — one bad link must not sink the phase
                return None, f"fetch_failed {final_url}: {type(exc).__name__}: {exc}"
        try:
            doc = _page_to_raw_document(page=page, url=final_url, source_post_url=str(source_doc.url))
            return doc, None
        except Exception as exc:  # noqa: BLE001
            return None, f"raw_doc_build_failed {final_url}: {type(exc).__name__}: {exc}"

    results = await asyncio.gather(*(_fetch_one(u, d) for u, d in targets))
    for doc, err in results:
        if doc is not None:
            docs.append(doc)
            cost += _UNLOCKER_COST_PER_PAGE
        if err is not None:
            errors.append(err)
    followed = len(docs)

    logger.info(
        "link_follow_phase: followed %d links from %d source docs, $%.4f spend, %d errors "
        "(fetch concurrency=%d)",
        followed,
        len(source_docs),
        cost,
        len(errors),
        concurrency,
    )
    return LinkFollowPhaseResult(docs=docs, followed=followed, cost_usd=cost, errors=errors)


def _page_to_raw_document(
    *,
    page,  # UnlockedPage; typed loosely to avoid an import cycle in tests
    url: str,
    source_post_url: str,
) -> RawDocument:
    """Convert one Web Unlocker response to a RawDocument tagged with its origin post.

    ``source_type`` is inferred from the resolved URL's domain
    (``_infer_source_type``) so a followed github.com link is labeled ``github``,
    arxiv.org → ``arxiv``, etc.; ``discovered_via`` records the post it came
    from for honest attribution (mirrors ``serp_arm:{id}``).
    """
    raw = page.content or ""
    archive_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return RawDocument(
        url=url,
        source_type=_infer_source_type(url),
        bright_data_product="web_unlocker",
        fetched_at=page.fetched_at or datetime.now(timezone.utc),
        raw_content=raw,
        content_format=page.content_format,
        archive_hash=archive_hash,
        http_status=page.status_code,
        metadata={"source_post_url": source_post_url},
        discovered_via=f"post_link:{source_post_url}",
    )
