"""The ``ddg`` fetcher backend — keyless DuckDuckGo search, no account required.

Uses DuckDuckGo's HTML endpoint (``https://html.duckduckgo.com/html/``) via an
HTTP POST with a browser User-Agent.  The response is plain HTML that DDG serves
to text-only browsers — it is far more stable than the JS-rendered frontend and
requires no API key.

**Capabilities declared:**
  - :attr:`~rogue.harvest.fetchers.capabilities.Capability.SERP`
    — ``serp(query, count, engine)``; ``engine`` is accepted for signature
    compatibility but **always ignored** (this backend always queries DDG).
  - :attr:`~rogue.harvest.fetchers.capabilities.Capability.SERP_IMAGE`
    — ``serp_image(query, count)``; uses the DDG image-search lite endpoint.

**Rate-limit caveat:** DuckDuckGo does not publish an API or rate limits.
Empirically, a handful of queries per minute works fine for a daily harvest.
Do NOT run this in a tight loop or bulk-crawl — DDG will 202/block you.
This backend is intentionally "daily harvest" scale, not bulk.  The SERP bandit
bypasses this backend (cost≈0 makes the bandit math meaningless; the registry
spec calls that out in ``fetcher_abstraction_spec.md`` §SERP bandit caveat).

**Return types:** identical to :class:`~rogue.harvest.bright_data_client.SerpResponse`
and ``list[str]`` (image URLs) that source plugins already parse — no source
plugin changes required.

No external dependencies beyond ``httpx`` (already in ``pyproject.toml``).
HTML parsing uses the stdlib :mod:`html.parser`.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
import httpx

from rogue.harvest.bright_data_client import SerpResponse

from .base import Fetcher
from .capabilities import Capability

__all__ = ["DuckDuckGoFetcher"]

logger = logging.getLogger("rogue.harvest.fetchers.ddg")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HTML_ENDPOINT = "https://html.duckduckgo.com/html/"
_IMAGE_ENDPOINT = "https://duckduckgo.com/"

# A browser-like UA — DDG's HTML endpoint requires one; without it it returns
# a CAPTCHA page or a 403.
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_REQUEST_HEADERS: dict[str, str] = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Content-Type": "application/x-www-form-urlencoded",
    "DNT": "1",
}

# Polite inter-request pause so we don't hammer DDG.
_INTER_REQUEST_DELAY: float = 0.5  # seconds


# ---------------------------------------------------------------------------
# HTML parser — DDG HTML result page
# ---------------------------------------------------------------------------

class _DDGResultParser(HTMLParser):
    """Parse DDG's HTML search-result page into (title, url, snippet) triples.

    The structure of ``html.duckduckgo.com/html/`` result pages:

    Each organic result sits in a ``<div class="web-result">`` (or older
    ``<div class="result">``).  Inside it:

    - ``<a class="result__a" href="...">TITLE</a>`` — the result link + title.
      DDG wraps the href in a redirect (``https://duckduckgo.com/l/?uddg=...``)
      but also emits the real URL in the ``data-href`` attribute (when present)
      or we can decode the ``uddg`` query parameter.  We capture both and prefer
      ``data-href`` / decoded ``uddg`` over the raw redirect.
    - ``<a class="result__snippet" ...>SNIPPET</a>`` or
      ``<div class="result__snippet">SNIPPET</div>`` — the description text.

    We collect at most ``max_results`` entries.
    """

    def __init__(self, max_results: int) -> None:
        super().__init__(convert_charrefs=True)
        self._max = max_results

        # Accumulator for the result being built.
        self._results: list[dict] = []
        self._cur: dict | None = None          # result being assembled
        self._capture_title = False            # collecting text inside result__a
        self._capture_snippet = False          # collecting text inside result__snippet
        self._snippet_depth = 0               # nesting depth inside snippet element

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_real_url(href: str, attrs_dict: dict) -> str:
        """Resolve the real destination URL from a DDG result anchor.

        DDG wraps links as ``/l/?uddg=<percent-encoded URL>&...``.  We extract
        the ``uddg`` parameter and percent-decode it.  If ``data-href`` is
        present on the element, prefer that (it's already the clean URL).
        """
        if "data-href" in attrs_dict:
            return attrs_dict["data-href"]
        # Look for uddg=... in the href
        m = re.search(r"[?&]uddg=([^&]+)", href)
        if m:
            from urllib.parse import unquote
            return unquote(m.group(1))
        # href may already be a real URL (older layout or lite endpoint)
        if href.startswith("http") and "duckduckgo.com" not in href:
            return href
        return href  # fallback — keep the raw DDG redirect URL

    def _finish_cur(self) -> None:
        """Flush the current result if it has at least a URL."""
        if self._cur and self._cur.get("link"):
            self._results.append(self._cur)
        self._cur = None
        self._capture_title = False
        self._capture_snippet = False
        self._snippet_depth = 0

    # ------------------------------------------------------------------
    # HTMLParser callbacks
    # ------------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if len(self._results) >= self._max:
            return

        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "")

        # ---- result container -----------------------------------------------
        if tag == "div" and ("web-result" in cls or cls == "result"):
            self._finish_cur()
            self._cur = {"title": "", "link": "", "snippet": ""}
            return

        if self._cur is None:
            return

        # ---- result link / title --------------------------------------------
        if tag == "a" and "result__a" in cls:
            href = attrs_dict.get("href", "")
            self._cur["link"] = self._extract_real_url(href, attrs_dict)
            self._capture_title = True
            self._capture_snippet = False
            return

        # ---- snippet --------------------------------------------------------
        if "result__snippet" in cls:
            self._capture_snippet = True
            self._capture_title = False
            self._snippet_depth = 1
            return

        if self._capture_snippet:
            self._snippet_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._cur is None:
            return
        if self._capture_title and tag == "a":
            self._capture_title = False
            return
        if self._capture_snippet:
            self._snippet_depth -= 1
            if self._snippet_depth <= 0:
                self._capture_snippet = False
                self._snippet_depth = 0

    def handle_data(self, data: str) -> None:
        if self._cur is None:
            return
        if self._capture_title:
            self._cur["title"] += data
        elif self._capture_snippet:
            self._cur["snippet"] += data

    def get_results(self) -> list[dict]:
        self._finish_cur()
        out = []
        for r in self._results:
            r["title"] = r["title"].strip()
            r["snippet"] = re.sub(r"\s+", " ", r["snippet"]).strip()
            out.append(r)
        return out[: self._max]


# ---------------------------------------------------------------------------
# Image URL extractor from DDG image search
# ---------------------------------------------------------------------------

_IMAGE_URL_RE = re.compile(r'"image":"(https?://[^"]+)"')


def _extract_image_urls(html: str, count: int) -> list[str]:
    """Pull up to ``count`` image URLs from a DDG image-search response page.

    DDG's image endpoint embeds JSON data inline in the HTML for the thumbnail/
    original URLs.  We scan for ``"image":"<url>"`` patterns — robust to layout
    changes since we target the JSON data island, not fragile HTML structure.

    Only ``https://`` URLs that don't point back to DuckDuckGo are returned
    (DDG thumbnails proxy through their own domain; we want the source URLs).
    """
    urls: list[str] = []
    seen: set[str] = set()
    for m in _IMAGE_URL_RE.finditer(html):
        u = m.group(1)
        if u in seen:
            continue
        # Skip DDG-hosted proxy URLs; they require cookie state to resolve.
        if "duckduckgo.com" in u:
            continue
        seen.add(u)
        urls.append(u)
        if len(urls) >= count:
            break
    return urls


# ---------------------------------------------------------------------------
# DuckDuckGoFetcher
# ---------------------------------------------------------------------------

class DuckDuckGoFetcher(Fetcher):
    """Keyless DuckDuckGo fetcher backend.

    Capabilities: ``SERP``, ``SERP_IMAGE``.

    Uses ``https://html.duckduckgo.com/html/`` (POST form) for web search and
    ``https://duckduckgo.com/?iax=images&ia=images&q=...`` for image search.
    A single :class:`httpx.AsyncClient` is shared across calls (lazy-init on
    first use).  Call :meth:`aclose` at shutdown to release the connection pool.

    Rate-limit note: DDG has no published rate limit.  A half-second delay is
    inserted between calls.  Do not run this at bulk / high-frequency — use
    Bright Data SERP for that.  The SERP bandit skips this backend (see spec).
    """

    name = "ddg"
    capabilities = frozenset({Capability.SERP, Capability.SERP_IMAGE})

    def __init__(self) -> None:
        self._http: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Availability — always True (no credentials required)
    # ------------------------------------------------------------------

    @classmethod
    def is_available(cls) -> bool:
        """Always ``True`` — no API key or optional deps required."""
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
                headers=_REQUEST_HEADERS,
                proxy=harvest_proxy_url(),  # ROGUE_PROXY_URL — DDG HTML is IP-rate-limited
            )
        return self._http

    async def aclose(self) -> None:
        """Release the shared HTTP client. Idempotent."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # SERP — web search
    # ------------------------------------------------------------------

    async def serp(
        self,
        query: str,
        count: int = 10,
        engine: str = "google",  # accepted for signature-compat, always ignored
    ) -> SerpResponse:
        """Query DuckDuckGo HTML endpoint and return a :class:`SerpResponse`.

        The ``engine`` parameter is accepted for API signature compatibility with
        the :class:`~rogue.harvest.fetchers.base.Fetcher` contract but is
        **always ignored** — this backend always queries DuckDuckGo regardless of
        the value passed.  Source plugins that pass ``engine="google"`` will
        receive DDG results transparently; this is expected and documented here.

        Returns an empty :class:`SerpResponse` (``organic_results=[]``) on any
        parse or network failure — never raises from a harvest context.

        Rate-limit caveat: DuckDuckGo is best-effort; a small delay is inserted
        between calls.  Fine for a daily harvest; not suitable for bulk queries.
        """
        if engine != "google":
            logger.debug(
                "ddg.serp: engine=%r ignored — DuckDuckGoFetcher always queries DDG", engine
            )

        empty = SerpResponse(
            query=query,
            engine="ddg",
            fetched_at=datetime.now(timezone.utc),
            organic_results=[],
            knowledge_panel=None,
            raw_json={},
        )

        try:
            client = self._get_http()
            # DDG HTML endpoint expects a POST form with q= and b= (pagination offset).
            # Using b="" fetches the first page.
            form_data = {"q": query, "b": ""}
            response = await client.post(_HTML_ENDPOINT, data=form_data)
            response.raise_for_status()

            html = response.text
            parser = _DDGResultParser(max_results=count)
            parser.feed(html)
            results = parser.get_results()

            await asyncio.sleep(_INTER_REQUEST_DELAY)

            return SerpResponse(
                query=query,
                engine="ddg",
                fetched_at=datetime.now(timezone.utc),
                organic_results=results,
                knowledge_panel=None,
                raw_json={"result_count": len(results)},
            )

        except Exception as exc:  # noqa: BLE001 — never crash a harvest run
            logger.warning(
                "ddg.serp failed for query %r: %s: %s",
                query[:120],
                type(exc).__name__,
                exc,
            )
            return empty

    # ------------------------------------------------------------------
    # SERP_IMAGE — image search
    # ------------------------------------------------------------------

    async def serp_image(self, query: str, count: int = 5) -> list[str]:
        """Query DuckDuckGo image search and return up to ``count`` image URLs.

        Uses ``https://duckduckgo.com/?iax=images&ia=images&q=<query>`` with a
        GET request.  DDG embeds image JSON inline in the HTML response; we scan
        for ``"image":"<url>"`` patterns to extract source image URLs, skipping
        DDG-hosted proxy URLs that require session state.

        Returns an empty list on any parse or network failure — never raises.

        Rate-limit caveat: same as :meth:`serp` — daily-harvest scale only.
        """
        try:
            client = self._get_http()
            params = {
                "q": query,
                "iax": "images",
                "ia": "images",
            }
            response = await client.get(_IMAGE_ENDPOINT, params=params)
            response.raise_for_status()

            urls = _extract_image_urls(response.text, count)

            await asyncio.sleep(_INTER_REQUEST_DELAY)
            return urls

        except Exception as exc:  # noqa: BLE001 — never crash a harvest run
            logger.warning(
                "ddg.serp_image failed for query %r: %s: %s",
                query[:120],
                type(exc).__name__,
                exc,
            )
            return []
