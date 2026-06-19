"""X harvest via SERP-discovery + Web Unlocker (the reliable X path).

BD's structured X scraper (``XUserTimelinePlugin``, discover-by-profile-URL)
times out / returns empty for the practitioner accounts we care about. But Web
Unlocker on an exact ``x.com/<user>/status/<id>`` URL works. This plugin bridges
the gap: for each handle it **SERP-discovers** recent status URLs
(``site:x.com/<handle> after:<date>``), then **Web-Unlocks each** and parses the
tweet text + screenshots (``x_status.parse_x_status``) into a ``RawDocument`` —
so attached jailbreak screenshots flow through Feature-A image ingestion and
outbound links through Feature-C following, like any source.

**Caveat (documented honestly):** discovery is bounded by Google's index of X,
which X heavily restricts — so very-fresh posts (last hours/days) may not be
SERP-discoverable yet. For a known-fresh post, ``scripts/harvest/harvest_url.py --url``
(direct Web-Unlock) is the reliable path.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from rogue.harvest.fetchers import Capability, Fetcher
from rogue.harvest.sources.x_user_timeline import DEFAULT_HANDLES
from rogue.harvest.x_status import is_x_status_url, parse_x_status
from rogue.schemas import RawDocument

from .base import SourcePlugin

__all__ = ["XViaUnlockerPlugin"]

logger = logging.getLogger(__name__)


class XViaUnlockerPlugin(SourcePlugin):
    """X harvester: SERP-discover status URLs → Web-Unlock + parse each."""

    name = "x_via_unlocker"
    source_type = "x"
    bright_data_product = "web_unlocker"
    required_capabilities: frozenset[Capability] = frozenset({Capability.SERP, Capability.UNLOCK})

    def __init__(
        self,
        handles: Optional[list[str]] = None,
        per_handle_limit: int = 10,
    ) -> None:
        self.handles = handles if handles is not None else list(DEFAULT_HANDLES)
        self.per_handle_limit = per_handle_limit
        self.call_errors: list[str] = []

    def serp_queries(self, since: datetime) -> list[str]:
        """One per-handle SERP discovery query, ``{date}`` substituted."""
        date_str = (since - timedelta(days=1)).strftime("%Y-%m-%d")
        return [f"site:x.com/{h} after:{date_str}" for h in self.handles]

    @staticmethod
    def _status_urls(serp_results: list[dict], limit: int) -> list[str]:
        """Pull deduped X status URLs out of SERP organic results (tolerant of
        the ``link``/``url``/``href`` field variants), stripping tracking params."""
        out: list[str] = []
        seen: set[str] = set()
        for r in serp_results or []:
            link = r.get("link") or r.get("url") or r.get("href") or ""
            if not isinstance(link, str) or not is_x_status_url(link):
                continue
            clean = link.split("?", 1)[0]
            if clean in seen:
                continue
            seen.add(clean)
            out.append(clean)
            if len(out) >= limit:
                break
        return out

    async def fetch_since(
        self,
        fetcher: Fetcher,
        since: datetime,
    ) -> list[RawDocument]:
        """SERP-discover each handle's recent posts, Web-Unlock + parse each."""
        self.call_errors = []
        docs: list[RawDocument] = []
        fetched_at = datetime.now(timezone.utc)

        for handle, query in zip(self.handles, self.serp_queries(since), strict=True):
            try:
                serp = await fetcher.serp(query, count=self.per_handle_limit)
            except NotImplementedError:
                raise
            except Exception as exc:  # noqa: BLE001 — one handle's SERP failure isn't fatal
                self.call_errors.append(f"@{handle} serp: {type(exc).__name__}: {exc}")
                logger.warning("x_via_unlocker SERP failed for @%s: %s", handle, exc)
                continue

            status_urls = self._status_urls(serp.organic_results, self.per_handle_limit)
            for url in status_urls:
                try:
                    page = await fetcher.unlock(url, format="html")
                except Exception as exc:  # noqa: BLE001 — one bad post isn't fatal
                    self.call_errors.append(f"{url} unlock: {type(exc).__name__}: {exc}")
                    continue

                body, media_urls = parse_x_status(page.content or "", url)
                if not body.strip():
                    continue
                archive_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
                try:
                    docs.append(
                        RawDocument(
                            url=url,
                            source_type=self.source_type,
                            bright_data_product=self.bright_data_product,
                            fetched_at=fetched_at,
                            raw_content=body,
                            content_format="text",
                            archive_hash=archive_hash,
                            http_status=page.status_code,
                            metadata={"handle": handle, "discovered_via_serp": query},
                            discovered_via=f"x_serp:{handle}",
                            media_urls=media_urls,
                        )
                    )
                except Exception:  # noqa: BLE001 — bad URL/oversize: drop, keep going
                    continue
        return docs
