"""Abstract base class for harvest-layer source plugins.

Position in the pipeline (ROGUE_PLAN.md §3.1 + §9.3)::

    DiscoveryAgent          (chooses which plugins to run today)
            │
            ▼
    SourcePlugin.fetch_since(fetcher, since_dt)        ◄──── each plugin file
            │                                                under harvest/sources/
            ▼
    list[RawDocument]
            │
            ▼
    ExtractionAgent.extract(raw_doc) ──► AttackPrimitive

Every concrete plugin under ``harvest/sources/`` subclasses :class:`SourcePlugin`
and owns:

  * its own SERP query templates (one per row in ``docs/sources.md``),
  * its own Bright Data product choice (Web Scraper API / SERP / Web Unlocker /
    Scraping Browser — see §6.1) — kept for telemetry/cost-log, no longer the
    dispatch key; dispatch is via :attr:`required_capabilities` + the
    :class:`~rogue.harvest.fetchers.FetcherRegistry`, and
  * its own parser from the fetcher's typed responses into
    :class:`rogue.schemas.RawDocument`.

Plugins are wired into ``DiscoveryAgent`` at Day-1 (currently a placeholder).
For Day 0 they only need to be import-safe + unit-testable on canned
``Fetcher`` responses — the live HTTP layer is filled in by the concrete
fetcher backend (e.g. ``BrightDataFetcher``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING

from rogue.harvest.fetchers import Capability, Fetcher
from rogue.schemas import BrightDataProduct, RawDocument, SourceType

if TYPE_CHECKING:
    pass

__all__ = ["SourcePlugin"]


class SourcePlugin(ABC):
    """Abstract harvest plugin. One concrete subclass per source type.

    Class attributes (declared on every subclass):

      * ``name`` — short stable identifier (e.g. ``"reddit_subreddit"``);
        used by the cost log + dashboard freshness panel.
      * ``source_type`` — which :data:`rogue.schemas.SourceType` literal this
        plugin emits on every ``RawDocument`` it produces.
      * ``bright_data_product`` — primary :data:`rogue.schemas.BrightDataProduct`
        used. Retained for telemetry/cost-log; no longer the dispatch key.
        If a plugin has a fallback path (e.g. HuggingFace falling back from
        the Web Scraper API to Web Unlocker), the subclass docstring lists the
        fallback explicitly; the value of this attribute is the *primary*.
      * ``required_capabilities`` — the set of :class:`~rogue.harvest.fetchers.Capability`
        members this source needs. The orchestrator resolves them against the
        :class:`~rogue.harvest.fetchers.FetcherRegistry` and **skips the source
        with a warning** if any required capability has no registered backend.
    """

    name: str
    source_type: SourceType
    bright_data_product: BrightDataProduct

    #: Capabilities this source needs. The orchestrator resolves a fetcher per
    #: required capability and skips the source (with a warning) if any are unmet.
    required_capabilities: frozenset[Capability] = frozenset()

    # §11.7 fetch-cache (Tier B). ``version_cache`` is a {url: version_token}
    # snapshot of the fetch_cache ledger, injected by ``harvest_once`` before a
    # run. Read via getattr in ``should_skip_fetch`` so a plugin that was never
    # injected (or only ever direct-fetches) simply never skips.
    version_cache: dict[str, str]
    skipped_unchanged: int

    def should_skip_fetch(self, url: str, version_token: str | None) -> bool:
        """§11.7 Tier B — True iff a prior run already fetched this URL with the
        SAME source freshness token (git blob SHA / arxiv versioned-id / ETag),
        meaning the content is unchanged and the fetch can be skipped up front.
        A ``None``/empty token means the source gave no freshness signal → never
        skip (can't prove it's unchanged). Increments ``skipped_unchanged`` for
        per-plugin telemetry when it skips.

        Only meaningful for per-URL fetch sources (UNLOCK). Bulk-scrape sources
        (REDDIT, HF) pull all content in one job, so there is no per-item fetch
        to skip — they rely on the Tier A content-hash gate to skip
        re-extraction instead.
        """
        if not version_token:
            return False
        cache = getattr(self, "version_cache", None) or {}
        if cache.get(url) == version_token:
            self.skipped_unchanged = getattr(self, "skipped_unchanged", 0) + 1
            return True
        return False

    @abstractmethod
    async def fetch_since(
        self,
        fetcher: Fetcher,
        since: datetime,
    ) -> list[RawDocument]:
        """Fetch every document published after ``since`` from this source.

        Returns ``0..N`` :class:`RawDocument` instances, ready for the
        extraction layer. Any HTTP / parse failure for a single document should
        be swallowed (logged) — never raise so the wider harvest run can
        continue past a single bad source. ``since`` is a timezone-aware UTC
        datetime; plugins should compare to source-side ``posted_at`` /
        ``published_at`` timestamps and drop everything older.
        """

    def serp_queries(self, since: datetime) -> list[str]:
        """Return the per-day SERP query strings, with ``{date}`` substituted.

        Default implementation returns ``[]`` — appropriate for plugins that
        only direct-fetch (e.g. arXiv listings, community archive browsers)
        and never hit the SERP API. Plugins that *do* use SERP override this
        with the templates from ``docs/sources.md``.
        """
        return []
