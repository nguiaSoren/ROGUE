"""The ``direct`` fetcher backend — keyless httpx, no Bright Data account required.

Targets **static, bot-tolerant sources** (arXiv, GitHub raw, academic blogs, Pliny
mirror pages, plain-HTML research sites).  Anti-bot or JS-heavy pages will return
403/429/empty — that is expected; the :class:`~rogue.harvest.fetchers.registry.FetcherRegistry`
falls back to Bright Data when a BD key is present, or skips the source with a warning.

Capabilities declared: :attr:`~rogue.harvest.fetchers.capabilities.Capability.UNLOCK`,
:attr:`~rogue.harvest.fetchers.capabilities.Capability.IMAGE_BYTES`,
:attr:`~rogue.harvest.fetchers.capabilities.Capability.REDIRECT`.

HTML → markdown conversion: no ``markdownify`` / ``html2text`` in the project deps, so
we use a minimal regex-and-replace tag-strip that preserves readable text.  It handles
the static sources (arXiv abstract pages, GitHub README views, plain blog HTML) well
enough for the extraction LLM.  If richer conversion becomes a priority, add
``html2text`` or ``markdownify`` to ``pyproject.toml`` and swap in the import here.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from html.parser import HTMLParser

import httpx

from rogue.harvest.bright_data_client import UnlockedPage

from .base import Fetcher
from .capabilities import Capability

__all__ = ["DirectFetcher"]

logger = logging.getLogger("rogue.harvest.fetchers.direct")

# ---------------------------------------------------------------------------
# Browser-like request headers — mimics a current Chrome on macOS.
# Many static hosts (GitHub raw, arXiv) don't care, but plain blogs + CDNs
# sometimes reject obvious bot UAs.
# ---------------------------------------------------------------------------
_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
}

# Skip-tags: content inside these elements is discarded entirely before the
# text walk.  Covers scripts, styles, nav chrome, and boilerplate footer noise
# that the extraction LLM does not need.
_SKIP_TAGS: frozenset[str] = frozenset(
    {"script", "style", "noscript", "nav", "footer", "head", "aside"}
)

# Block-level tags that separate logical chunks — we insert a blank line around
# them to preserve paragraph structure in the stripped output.
_BLOCK_TAGS: frozenset[str] = frozenset(
    {"p", "div", "section", "article", "main", "header",
     "h1", "h2", "h3", "h4", "h5", "h6",
     "li", "blockquote", "pre", "table", "tr", "br"}
)


# ---------------------------------------------------------------------------
# Minimal HTML → markdown-ish converter (no external dep)
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    """Walk an HTML parse tree and extract human-readable text.

    Skips :data:`_SKIP_TAGS` subtrees entirely; inserts newlines around
    :data:`_BLOCK_TAGS`; collapses whitespace into single spaces within
    inline text runs.  The result is not strict Markdown but is clean
    enough for the extraction LLM to process.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth: int = 0  # >0 while inside a skipped subtree

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if self._skip_depth or tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth:
            self._skip_depth -= 1
            return
        if tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self._chunks.append(data)

    def get_text(self) -> str:
        raw = "".join(self._chunks)
        # Collapse runs of whitespace / blank lines to at most two newlines.
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", raw)
        return raw.strip()


def _html_to_markdown(html: str) -> str:
    """Strip HTML tags and return clean plain text / pseudo-markdown.

    Uses the stdlib :class:`html.parser.HTMLParser` — no extra dependency.
    The output preserves paragraph breaks and heading structure well enough
    for LLM extraction but is not full CommonMark Markdown.
    """
    parser = _TextExtractor()
    try:
        parser.feed(html)
        return parser.get_text()
    except Exception:  # noqa: BLE001 — malformed HTML is common; degrade to raw strip
        # Last-resort: just nuke every tag with a regex.
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
        return text.strip()


# ---------------------------------------------------------------------------
# DirectFetcher
# ---------------------------------------------------------------------------

class DirectFetcher(Fetcher):
    """Keyless httpx backend for bot-tolerant static pages.

    Capabilities: ``UNLOCK``, ``IMAGE_BYTES``, ``REDIRECT``.

    A single :class:`httpx.AsyncClient` is shared across calls (lazy-init on
    first use).  Call :meth:`aclose` at shutdown to release the connection pool.
    ``is_available()`` always returns ``True`` — no credentials needed.
    """

    name = "direct"
    capabilities = frozenset({Capability.UNLOCK, Capability.IMAGE_BYTES, Capability.REDIRECT})

    def __init__(self) -> None:
        self._http: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Class method — availability
    # ------------------------------------------------------------------

    @classmethod
    def is_available(cls) -> bool:
        """Always ``True`` — no credentials or optional deps required."""
        return True

    # ------------------------------------------------------------------
    # Internal shared client
    # ------------------------------------------------------------------

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            from .proxy import harvest_proxy_url

            self._http = httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(30.0, connect=10.0),
                headers=_DEFAULT_HEADERS,
                proxy=harvest_proxy_url(),  # ROGUE_PROXY_URL (None = our own IP)
            )
        return self._http

    async def aclose(self) -> None:
        """Release the shared HTTP client. Idempotent."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # UNLOCK — anti-bot single-page fetch
    # ------------------------------------------------------------------

    async def unlock(self, url: str, format: str = "markdown") -> UnlockedPage:
        """GET ``url`` with browser-like headers → :class:`UnlockedPage`.

        ``format="markdown"`` (default): converts HTML with a minimal tag-strip
        (no external dep).  ``format="html"``: returns raw response body.

        Raises :class:`httpx.HTTPStatusError` on 4xx/5xx responses, matching
        the BD client's ``raise_for_status`` behaviour so source plugins that
        check for HTTP errors work unchanged.
        """
        fmt = (format or "markdown").lower()
        if fmt not in ("html", "markdown"):
            raise ValueError(f"DirectFetcher.unlock: unsupported format {format!r}")

        client = self._get_http()
        response = await client.get(url)
        response.raise_for_status()

        if fmt == "markdown":
            content = _html_to_markdown(response.text)
        else:
            content = response.text

        return UnlockedPage(
            url=str(response.url),  # post-redirect final URL
            fetched_at=datetime.now(timezone.utc),
            content=content,
            content_format=fmt,  # type: ignore[arg-type]
            status_code=response.status_code,
        )

    # ------------------------------------------------------------------
    # IMAGE_BYTES — raw binary fetch
    # ------------------------------------------------------------------

    async def fetch_image_bytes(self, url: str) -> tuple[bytes, str]:
        """GET ``url`` as raw bytes → ``(content_bytes, content_type)``.

        Raises :class:`httpx.HTTPStatusError` on non-2xx, matching BD client
        behaviour so callers that check HTTP errors work unchanged.
        """
        client = self._get_http()
        response = await client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "application/octet-stream")
        return response.content, content_type

    # ------------------------------------------------------------------
    # REDIRECT — resolve shortlink → final URL
    # ------------------------------------------------------------------

    async def resolve_redirect(self, url: str) -> str:
        """Follow redirects for ``url`` and return the final destination URL.

        Degrades to returning the input ``url`` unchanged on any error or
        timeout, exactly matching the BD client's ``resolve_redirect``
        behaviour (degrade-safe — a failed resolution just means we use the
        short link as-is downstream).
        """
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(10.0, connect=5.0),
                headers=_DEFAULT_HEADERS,
            ) as client:
                resp = await client.head(url)
                # Some shorteners return 405/400 on HEAD — retry with GET.
                if resp.status_code >= 400:
                    resp = await client.get(url)
                final = str(resp.url)
                return final or url
        except Exception as exc:  # noqa: BLE001 — degrade to original url
            logger.debug("resolve_redirect failed for %s: %s", url[:120], exc)
            return url
