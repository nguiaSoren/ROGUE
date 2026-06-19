"""The :class:`Fetcher` abstract base — the backend-agnostic harvest surface.

Every method maps 1:1 to a :class:`~rogue.harvest.bright_data_client.BrightDataClient` method the
codebase already calls, with the **same parameters and the same return types** (the existing Pydantic
shapes). A source plugin can therefore swap ``client.<method>(...)`` → ``fetcher.<method>(...)``
mechanically, with zero parsing changes — that is the frozen Wave-0 contract Wave-1 refactors against.

A concrete backend declares ``name: str`` and ``capabilities: frozenset[Capability]`` and overrides
only the methods for the capabilities it supports. The base implementation of every capability method
raises :class:`CapabilityNotSupported`, so an un-overridden capability fails cleanly (the registry
never routes an unsupported capability to a backend, but the guard makes a misconfiguration loud).

Layering: this module imports **no provider SDK**. The return types it references
(``RedditPost`` / ``XPost`` / ``HFDiscussion`` / ``SerpResponse`` / ``UnlockedPage`` / ``ScrapedPage``)
are ROGUE's own Pydantic wire models, imported under ``TYPE_CHECKING`` only — provider-specific HTTP
lives exclusively in the ``brightdata`` backend (and the Wave-1 free backends).
"""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Any

from .capabilities import Capability, CapabilityNotSupported

if TYPE_CHECKING:
    from rogue.harvest.bright_data_client import (
        HFDiscussion,
        RedditPost,
        ScrapedPage,
        SerpResponse,
        UnlockedPage,
        XPost,
    )

__all__ = ["Fetcher"]


class Fetcher(ABC):
    """Abstract scraper backend. Subclasses set ``name`` + ``capabilities`` and override methods.

    Each capability method on the base raises :class:`CapabilityNotSupported` via
    :meth:`_unsupported`; a backend implements only what it declares in ``capabilities``.
    """

    #: Short stable identifier used as the registry key + preference-order token
    #: (e.g. ``"brightdata"``, ``"direct"``, ``"ddg"``). Set on every subclass.
    name: str = ""

    #: The set of capabilities this backend implements. The base default is empty;
    #: every concrete backend overrides it. The conformance suite asserts that every
    #: declared capability's method is actually overridden (and undeclared ones still raise).
    capabilities: frozenset[Capability] = frozenset()

    #: Whether this backend returns *parsed* content (markdown/text) for PDF URLs. Most UNLOCK
    #: backends return the raw PDF *bytes* (garbage as extraction input); a backend that natively
    #: parses PDF→markdown (e.g. Firecrawl) sets this True so :class:`RoutingFetcher` can prefer it
    #: for PDF URLs over a default that would hand back binary. Default False.
    handles_pdf: bool = False

    #: A PDF *specialist* — declares ``UNLOCK`` + ``handles_pdf`` but can ONLY serve PDF URLs (it
    #: cannot fetch general HTML). The registry excludes ``pdf_only`` backends from general
    #: ``for_capability(UNLOCK)`` resolution; :class:`RoutingFetcher` uses them only for PDF URLs via
    #: the PDF guard. Default False. (e.g. the local PyMuPDF4LLM backend.)
    pdf_only: bool = False

    # ------------------------------------------------------------------
    # Internal guard
    # ------------------------------------------------------------------

    def _unsupported(self, capability: Capability) -> CapabilityNotSupported:
        """Build the :class:`CapabilityNotSupported` for this backend + ``capability``."""
        return CapabilityNotSupported(self.name, capability)

    # ------------------------------------------------------------------
    # UNLOCK — anti-bot single-page fetch (↔ BrightDataClient.web_unlock)
    # ------------------------------------------------------------------

    async def unlock(self, url: str, format: str = "markdown") -> "UnlockedPage":
        """Fetch a single page's content (``"html"`` or ``"markdown"``) → :class:`UnlockedPage`."""
        raise self._unsupported(Capability.UNLOCK)

    # ------------------------------------------------------------------
    # SERP — web search (↔ BrightDataClient.serp_search)
    # ------------------------------------------------------------------

    async def serp(
        self,
        query: str,
        count: int = 10,
        engine: str = "google",
    ) -> "SerpResponse":
        """Structured web-search results for ``query`` on ``engine`` → :class:`SerpResponse`."""
        raise self._unsupported(Capability.SERP)

    # ------------------------------------------------------------------
    # SERP_IMAGE — image search (↔ BrightDataClient.serp_image_search)
    # ------------------------------------------------------------------

    async def serp_image(self, query: str, count: int = 5) -> list[str]:
        """Image-search ``query`` → up to ``count`` candidate image URLs (``list[str]``)."""
        raise self._unsupported(Capability.SERP_IMAGE)

    # ------------------------------------------------------------------
    # BROWSER — JS / heavy-anti-bot render (↔ BrightDataClient.scrape_browser)
    # ------------------------------------------------------------------

    async def browser(
        self,
        url: str,
        wait_for_selector: str | None = None,
        scroll_pages: int = 1,
        *,
        storage_state: dict[str, Any] | None = None,
    ) -> "ScrapedPage":
        """Render ``url`` in a real browser → :class:`ScrapedPage` (html + rendered text)."""
        raise self._unsupported(Capability.BROWSER)

    # ------------------------------------------------------------------
    # REDDIT — structured subreddit + keyword (↔ scrape_reddit_subreddit / _keyword)
    # ------------------------------------------------------------------

    async def reddit_subreddit(self, subreddit: str, limit: int = 100) -> list["RedditPost"]:
        """Structured listing of ``subreddit`` → ``list[RedditPost]``."""
        raise self._unsupported(Capability.REDDIT)

    async def reddit_keyword(
        self,
        keyword: str,
        date_range: str = "Past week",
        num_of_posts: int = 50,
    ) -> list["RedditPost"]:
        """Global Reddit keyword search → ``list[RedditPost]``."""
        raise self._unsupported(Capability.REDDIT)

    # ------------------------------------------------------------------
    # X — structured user timeline (↔ BrightDataClient.scrape_x_user_posts)
    # ------------------------------------------------------------------

    async def x_user_posts(self, profile_url: str, limit: int = 50) -> list["XPost"]:
        """Most-recent posts for an X profile URL → ``list[XPost]``."""
        raise self._unsupported(Capability.X)

    # ------------------------------------------------------------------
    # HF — structured HuggingFace discussions (↔ scrape_huggingface_discussion)
    # ------------------------------------------------------------------

    async def hf_discussion(self, model_id: str) -> list["HFDiscussion"]:
        """HuggingFace model-card discussion threads for ``model_id`` → ``list[HFDiscussion]``."""
        raise self._unsupported(Capability.HF)

    # ------------------------------------------------------------------
    # IMAGE_BYTES — raw binary fetch (↔ BrightDataClient.fetch_image_bytes)
    # ------------------------------------------------------------------

    async def fetch_image_bytes(self, url: str) -> tuple[bytes, str]:
        """Download ``url`` raw → ``(content_bytes, content_type)``."""
        raise self._unsupported(Capability.IMAGE_BYTES)

    # ------------------------------------------------------------------
    # REDIRECT — resolve shortlink (↔ BrightDataClient.resolve_redirect)
    # ------------------------------------------------------------------

    async def resolve_redirect(self, url: str) -> str:
        """Resolve a short/redirect ``url`` to its final destination (degrade-safe → input on error)."""
        raise self._unsupported(Capability.REDIRECT)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        """Release any held network resources. Idempotent. Base default is a no-op."""
        return None
