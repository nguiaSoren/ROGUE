"""The ``local_pdf`` fetcher backend — local, free, always-available PDF→markdown.

A PDF *specialist*: declares ``UNLOCK`` + ``handles_pdf`` + ``pdf_only``, so the registry never
resolves it for general (HTML) UNLOCK — :class:`~rogue.harvest.fetchers.routing.RoutingFetcher`
reaches it only for PDF URLs, ahead of the rate-limited Firecrawl. It downloads the PDF bytes
(a direct GET — a PDF link needs no anti-bot) and parses them locally:

- **Floor (always on):** ``pypdf`` — pure-Python text extraction; a core dependency, so this backend
  is ALWAYS available and the harvest never depends on a 3rd-party (rate-limited Firecrawl) for PDFs.
- **Upgrade:** ``pymupdf4llm`` (the optional ``rogue[pdf]`` extra) — richer LLM-ready markdown with
  layout/tables. Used automatically when installed.

Either way it's local + free + unlimited — the preferred PDF parser (BD/``direct`` return raw bytes).
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
from datetime import datetime, timezone

import httpx

from rogue.harvest.bright_data_client import UnlockedPage

from .base import Fetcher
from .capabilities import Capability

__all__ = ["LocalPdfFetcher"]

logger = logging.getLogger("rogue.harvest.fetchers.local_pdf")

_UA = "Mozilla/5.0 (compatible; ROGUE-harvest/1.0; +https://rogue-eosin.vercel.app)"


def _parse_pdf(data: bytes) -> str:
    """PDF bytes → text/markdown. Prefers pymupdf4llm (rich) when installed, else pypdf (core)."""
    if importlib.util.find_spec("pymupdf4llm") is not None:
        import pymupdf  # type: ignore[import-not-found]
        import pymupdf4llm  # type: ignore[import-not-found]

        doc = pymupdf.open(stream=data, filetype="pdf")
        try:
            return pymupdf4llm.to_markdown(doc) or ""
        finally:
            doc.close()

    import io

    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(data))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


class LocalPdfFetcher(Fetcher):
    """Local PDF→markdown backend (PDF-only). Capability: ``UNLOCK`` (PDF URLs only)."""

    name = "local_pdf"
    capabilities = frozenset({Capability.UNLOCK})
    handles_pdf = True
    pdf_only = True  # only ever used for PDF URLs (cannot fetch general HTML)

    def __init__(self) -> None:
        self._http: httpx.AsyncClient | None = None

    @classmethod
    def is_available(cls) -> bool:
        """Always available: the ``pypdf`` floor is a core dependency (pymupdf4llm is the upgrade)."""
        return importlib.util.find_spec("pypdf") is not None

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            from .proxy import harvest_proxy_url

            self._http = httpx.AsyncClient(
                headers={"User-Agent": _UA},
                timeout=httpx.Timeout(60.0, connect=10.0),
                follow_redirects=True,
                proxy=harvest_proxy_url(),  # ROGUE_PROXY_URL (None = our own IP)
            )
        return self._http

    async def unlock(self, url: str, format: str = "markdown") -> UnlockedPage:
        """Download the PDF at ``url`` and parse it to markdown/text locally.

        ``format`` is accepted for the :class:`Fetcher` contract but PDFs only yield text content, so
        the returned :class:`UnlockedPage` is always ``content_format="markdown"``. The CPU-bound
        parse runs in a worker thread so the event loop isn't blocked.
        """
        client = self._get_http()
        response = await client.get(url)
        response.raise_for_status()
        data = response.content
        status = response.status_code

        markdown = await asyncio.to_thread(_parse_pdf, data)

        return UnlockedPage(
            url=str(response.url) or url,
            fetched_at=datetime.now(timezone.utc),
            content=markdown,
            content_format="markdown",
            status_code=status,
        )

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None
