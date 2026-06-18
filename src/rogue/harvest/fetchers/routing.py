"""``RoutingFetcher`` — a :class:`Fetcher` facade that dispatches each capability to the registry.

A single source can need multiple capabilities served by *different* backends — e.g. ``github_search``
needs ``SERP`` + ``UNLOCK``, which on the free path resolve to ``ddg`` + ``direct``. Rather than thread
per-capability backends through every source, the harvest hands a source ONE ``RoutingFetcher``: it
implements the full :class:`Fetcher` interface and routes each method to the backend the
:class:`FetcherRegistry` resolves for that method's capability. Source refactors therefore stay a
mechanical ``client.<m>(...)`` → ``fetcher.<m>(...)`` swap, no matter how many backends fan out behind it.

If no registered backend serves a capability, the routed call raises :class:`CapabilityNotSupported`.
The orchestrator pre-checks each source's ``required_capabilities`` and skips-with-warning *before*
calling, so a raise here only fires on a genuine misconfiguration. ``resolve_redirect`` is best-effort:
with no REDIRECT backend it degrades to returning the input URL rather than raising.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from .base import Fetcher
from .capabilities import Capability, CapabilityNotSupported
from .registry import FetcherRegistry

# Sites that serve both PDF and HTML — rewrite the PDF URL to the (easier-to-parse) HTML version.
# arXiv: /pdf/<id> → /abs/<id> (the HTML abstract + metadata page the arxiv source already uses).
_ARXIV_PDF_RE = re.compile(r"^(https?://(?:www\.)?arxiv\.org)/pdf/([^?#]+?)(?:\.pdf)?/?$", re.IGNORECASE)


def _prefer_html_url(url: str) -> str:
    """Rewrite a known PDF URL to its HTML equivalent (HTML is easier + cheaper to parse than a PDF).
    Currently arXiv only; returns the input unchanged otherwise."""
    m = _ARXIV_PDF_RE.match(url)
    if m:
        return f"{m.group(1)}/abs/{m.group(2)}"
    return url


def _looks_like_pdf(url: str) -> bool:
    """Best-effort pre-fetch PDF detection: a ``.pdf`` path suffix or a ``/pdf/`` segment (catches
    explicit PDF links and arXiv ``/pdf/<id>`` URLs). Not content-type-accurate, but enough to keep
    PDFs off backends that would return raw bytes. Content-type-based re-routing is a later refinement."""
    path = urlparse(url).path.lower()
    return path.endswith(".pdf") or "/pdf/" in path

if TYPE_CHECKING:
    from rogue.harvest.bright_data_client import (
        HFDiscussion,
        RedditPost,
        ScrapedPage,
        SerpResponse,
        UnlockedPage,
        XPost,
    )

__all__ = ["RoutingFetcher"]


class RoutingFetcher(Fetcher):
    """Implements the full :class:`Fetcher` surface by dispatching per-capability to a registry."""

    name = "routing"

    def __init__(self, registry: FetcherRegistry) -> None:
        self._registry = registry

    @property  # type: ignore[override]  # class-attr → property: the caps it can actually serve
    def capabilities(self) -> frozenset[Capability]:
        return frozenset(c for c in Capability if self._registry.for_capability(c) is not None)

    def _route(self, capability: Capability) -> Fetcher:
        backend = self._registry.for_capability(capability)
        if backend is None:
            raise CapabilityNotSupported(self.name, capability)
        return backend

    async def unlock(self, url: str, format: str = "markdown") -> "UnlockedPage":
        # Prefer the HTML version of a known dual-format source (e.g. arXiv /pdf/ → /abs/) before
        # routing — HTML is easier to parse than the PDF and routes to a normal UNLOCK backend.
        url = _prefer_html_url(url)
        return await self._unlock_backend(url).unlock(url, format=format)

    def _unlock_backend(self, url: str) -> Fetcher:
        """The UNLOCK backend for ``url`` — normally the registry's first choice, but a PDF URL goes
        to the first registered ``handles_pdf`` UNLOCK backend in preference order (e.g. the local
        ``pymupdf4llm`` ahead of the rate-limited Firecrawl, both ahead of a default that returns raw
        bytes). Falls back to the default UNLOCK backend when no ``handles_pdf`` backend is registered."""
        default = self._route(Capability.UNLOCK)  # raises CapabilityNotSupported if none
        if _looks_like_pdf(url):
            for name in self._registry.list():
                backend = self._registry.get(name)
                if backend is not None and Capability.UNLOCK in backend.capabilities and backend.handles_pdf:
                    return backend
        return default

    async def serp(
        self,
        query: str,
        count: int = 10,
        engine: str = "google",
    ) -> "SerpResponse":
        return await self._route(Capability.SERP).serp(query, count=count, engine=engine)

    async def serp_image(self, query: str, count: int = 5) -> list[str]:
        return await self._route(Capability.SERP_IMAGE).serp_image(query, count=count)

    async def browser(
        self,
        url: str,
        wait_for_selector: str | None = None,
        scroll_pages: int = 1,
        *,
        storage_state: dict[str, Any] | None = None,
    ) -> "ScrapedPage":
        return await self._route(Capability.BROWSER).browser(
            url,
            wait_for_selector=wait_for_selector,
            scroll_pages=scroll_pages,
            storage_state=storage_state,
        )

    async def reddit_subreddit(self, subreddit: str, limit: int = 100) -> list["RedditPost"]:
        return await self._route(Capability.REDDIT).reddit_subreddit(subreddit, limit=limit)

    async def reddit_keyword(
        self,
        keyword: str,
        date_range: str = "Past week",
        num_of_posts: int = 50,
    ) -> list["RedditPost"]:
        return await self._route(Capability.REDDIT).reddit_keyword(
            keyword, date_range=date_range, num_of_posts=num_of_posts
        )

    async def x_user_posts(self, profile_url: str, limit: int = 50) -> list["XPost"]:
        return await self._route(Capability.X).x_user_posts(profile_url, limit=limit)

    async def hf_discussion(self, model_id: str) -> list["HFDiscussion"]:
        return await self._route(Capability.HF).hf_discussion(model_id)

    async def fetch_image_bytes(self, url: str) -> tuple[bytes, str]:
        return await self._route(Capability.IMAGE_BYTES).fetch_image_bytes(url)

    async def resolve_redirect(self, url: str) -> str:
        backend = self._registry.for_capability(Capability.REDIRECT)
        if backend is None:
            return url  # best-effort: no REDIRECT backend → return the input unchanged
        return await backend.resolve_redirect(url)

    async def aclose(self) -> None:
        # The registry / orchestrator owns each backend's lifecycle; routing never double-closes.
        return None
