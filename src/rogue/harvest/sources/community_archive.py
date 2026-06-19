"""Community-archive harvest plugin (sources #10 + #15 in docs/sources.md).

Covers community-curated archives where the underlying site is heavy on JS
and infinite scroll, so neither Web Scraper API nor Web Unlocker is enough:

  * jailbreakchat archive (#15) — historical seed corpus
  * Promptfoo Discord public-archive mirrors (#10)

  * **Primary product:** Scraping Browser
    (``website/SCRAPING-BROWSER/quickstart.md``,
    ``website/SCRAPING-BROWSER/cdp-functions/``). Wrapped by
    :meth:`BrightDataClient.scrape_browser`, which optionally waits on a CSS
    selector and scrolls ``scroll_pages`` times to trigger lazy-loaded
    content.
  * **Fallback:** none — Scraping Browser is *itself* the fallback for the
    pipeline. If it fails, the source goes stale.

Constructor accepts ``source_type`` override so the same plugin can produce
``"discord_archive"`` or ``"community_archive"`` documents depending on the
URL list.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from rogue.harvest.fetchers import Capability, Fetcher
from rogue.schemas import RawDocument, SourceType

from .base import SourcePlugin

__all__ = ["CommunityArchivePlugin", "ArchiveTarget"]


@dataclass(frozen=True)
class ArchiveTarget:
    """One archive page to scrape via the Scraping Browser."""

    name: str
    url: str
    # CSS selector to wait for before snapshotting. None = no wait.
    # REVIEW Day 1: these selectors are educated guesses and very likely to
    # shift — verify each on Day-1 morning. jailbreakchat used to use a
    # `.prompt` card; the Promptfoo discord mirrors hang off whatever the
    # mirror author's static-site generator emits. Update from a live page.
    wait_for_selector: Optional[str] = None
    scroll_pages: int = 1


DEFAULT_ARCHIVES: tuple[ArchiveTarget, ...] = (
    # jailbreakchat.com is the canonical archive but has moved to a wayback
    # mirror multiple times — keep both as candidates.
    ArchiveTarget(
        name="jailbreakchat",
        url="https://www.jailbreakchat.com/",
        wait_for_selector=".prompt",
        scroll_pages=3,
    ),
    # Promptfoo Discord mirrors — placeholder URL, exact mirror site
    # confirmed Day 1.
    # REVIEW Day 1: pick a stable Promptfoo Discord-archive mirror from
    # discord-archived sites (e.g. discordapp.io / disboard / a Promptfoo-
    # community-run static export); current URL is a search-page stub.
    ArchiveTarget(
        name="promptfoo_discord",
        url="https://discord.com/channels/@me",
        wait_for_selector=None,
        scroll_pages=1,
    ),
)


class CommunityArchivePlugin(SourcePlugin):
    """Scraping-Browser-backed community archive harvester."""

    name = "community_archive"
    source_type = "community_archive"
    bright_data_product = "scraping_browser"
    required_capabilities: frozenset[Capability] = frozenset({Capability.BROWSER})

    def __init__(
        self,
        archives: Iterable[ArchiveTarget] | None = None,
        source_type: SourceType = "community_archive",
    ) -> None:
        self.archives: list[ArchiveTarget] = (
            list(archives) if archives is not None else list(DEFAULT_ARCHIVES)
        )
        # Per-instance override (overrides the class attribute on the produced
        # RawDocuments only). Lets callers spin up a "discord_archive"-labeled
        # instance and a "community_archive"-labeled instance in parallel.
        self._instance_source_type: SourceType = source_type

    def serp_queries(self, since: datetime) -> list[str]:
        """Discovery queries for Promptfoo Discord + jailbreakchat
        (docs/sources.md §10 + §15)."""
        date_str = (since - timedelta(days=1)).strftime("%Y-%m-%d")
        return [
            f'"discord" "promptfoo" jailbreak after:{date_str}',
            '"jailbreakchat" OR "jailbreakchat.com" "DAN" OR "Sigma" OR "AIM"',
        ]

    async def fetch_since(
        self,
        fetcher: Fetcher,
        since: datetime,
    ) -> list[RawDocument]:
        """Render each archive page via the Scraping Browser; emit one
        RawDocument per archive URL.

        REVIEW Day 1: this is the most fragile plugin in the suite. Community
        archive sites change layouts often, and Scraping Browser sessions are
        the priciest fetch — keep the per-run target list small. Backfill
        only; not part of the daily delta loop.
        """
        docs: list[RawDocument] = []
        fetched_at = datetime.now(timezone.utc)

        for target in self.archives:
            try:
                page = await fetcher.browser(
                    target.url,
                    wait_for_selector=target.wait_for_selector,
                    scroll_pages=target.scroll_pages,
                )
            except NotImplementedError:
                raise
            except Exception:
                continue

            # We prefer the rendered text (cleaner for the LLM) but fall back
            # to raw HTML if the renderer returns nothing.
            raw_content = page.rendered_text or page.html
            if not raw_content:
                continue

            content_format = "text" if page.rendered_text else "html"
            archive_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
            try:
                docs.append(
                    RawDocument(
                        url=target.url,
                        source_type=self._instance_source_type,
                        bright_data_product=self.bright_data_product,
                        fetched_at=fetched_at,
                        raw_content=raw_content,
                        content_format=content_format,
                        archive_hash=archive_hash,
                        http_status=200,  # scrape_browser doesn't expose a code
                        metadata={
                            "archive_name": target.name,
                            "scroll_pages": target.scroll_pages,
                            "wait_for_selector": target.wait_for_selector,
                        },
                        discovered_via=None,
                    )
                )
            except Exception:
                continue

        # `since` currently unused — archives are static historical seeds; the
        # extraction layer dedupes via archive_hash. Day 1: if we move
        # jailbreakchat into the daily loop, add a "have we seen this hash
        # before" check at the caller side.
        _ = since
        return docs
