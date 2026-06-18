"""The ``firecrawl`` fetcher backend — self-hosted (free) or cloud.

Calls the Firecrawl REST API directly via ``httpx`` (no ``firecrawl-py`` SDK;
zero new dependencies). Works in three modes:

**Self-hosted (free)**
    Set ``FIRECRAWL_BASE_URL`` to your instance, e.g.
    ``http://localhost:3002``. No API key required for self-hosted deployments.
    The instance must be running; :meth:`is_available` returns ``True`` whenever
    the env var is set regardless of whether the instance is reachable.

**Cloud**
    Set ``FIRECRAWL_API_KEY`` (obtain from https://firecrawl.dev). The base URL
    defaults to ``https://api.firecrawl.dev``. The cloud API key is sent as
    ``Authorization: Bearer {key}``.

**Keyless (free, no signup)**
    Set ``FIRECRAWL_KEYLESS=1`` (and leave both vars above unset) to use
    Firecrawl's keyless free tier on the public cloud — no account, no
    ``Authorization`` header (announced 2026-06-18). This makes Firecrawl a
    zero-key ``UNLOCK``/``BROWSER`` backend, so the harvest gets a real anti-bot
    stack with no Bright Data and no signup. It is **opt-in** (off by default) so
    target URLs are never silently sent to a third party. The free tier is
    rate-limited — ideal for the demo / low-volume harvest; sign up + set
    ``FIRECRAWL_API_KEY`` to scale. A 429/limit surfaces as a normal fetch error
    and the registry skips that source (never a crash).

Precedence: ``FIRECRAWL_BASE_URL`` wins over ``FIRECRAWL_API_KEY`` (self-hosted
isn't accidentally billed), and an explicit key/URL wins over keyless.

Capabilities declared:
  :attr:`~rogue.harvest.fetchers.capabilities.Capability.UNLOCK` — Firecrawl
  fetches any URL through its own proxy/anti-bot stack, returning ``markdown``
  or ``html`` on request. Maps 1:1 to :class:`UnlockedPage`.

  :attr:`~rogue.harvest.fetchers.capabilities.Capability.BROWSER` — Firecrawl
  renders JavaScript by default (no extra flag needed). The same ``/v1/scrape``
  endpoint returns JS-rendered HTML + markdown; this maps to
  :class:`ScrapedPage`. ``wait_for_selector`` is passed as Firecrawl's
  ``waitFor`` action; ``scroll_pages`` and ``storage_state`` have no Firecrawl
  equivalent and are noted in the docstring.

API contract targeted (verified 2026-06-15 against docs.firecrawl.dev):

  Request::

      POST /v1/scrape
      Authorization: Bearer {FIRECRAWL_API_KEY}   # cloud only; omit for self-hosted
      Content-Type: application/json

      {
          "url": "https://example.com",
          "formats": ["markdown", "html"]
          // optional: "waitFor": "CSS selector" or integer ms
          // optional: "onlyMainContent": true  (default)
      }

  Response::

      {
          "success": true,
          "data": {
              "markdown": "...",
              "html": "...",
              "metadata": {
                  "statusCode": 200,
                  "sourceURL": "https://example.com",
                  "title": "...",
                  ...
              }
          }
      }

  On failure (HTTP 4xx/5xx, or ``"success": false``):

      {"success": false, "error": "reason string"}
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from rogue.harvest.bright_data_client import ScrapedPage, SerpResponse, UnlockedPage

from .base import Fetcher
from .capabilities import Capability

__all__ = ["FirecrawlFetcher"]

logger = logging.getLogger("rogue.harvest.fetchers.firecrawl")

# Cloud base URL — used for the cloud key path AND the keyless free tier.
_CLOUD_BASE = "https://api.firecrawl.dev"

# Env values that enable the opt-in keyless free tier.
_TRUTHY = {"1", "true", "yes", "on"}


def _keyless_enabled() -> bool:
    return os.environ.get("FIRECRAWL_KEYLESS", "").strip().lower() in _TRUTHY


class FirecrawlFetcher(Fetcher):
    """Firecrawl-backed fetcher (self-hosted free OR cloud OR keyless free tier).

    Capabilities: ``UNLOCK``, ``BROWSER``, ``SERP``.

    A single :class:`httpx.AsyncClient` is lazy-initialized on first use and
    released by :meth:`aclose`. Construction is zero-IO: credentials are read
    from the environment at ``__init__`` time, but no network calls are made
    until a capability method is invoked.

    Use :meth:`is_available` to check whether the backend is configured before
    registering it.
    """

    name = "firecrawl"
    capabilities = frozenset({Capability.UNLOCK, Capability.BROWSER, Capability.SERP})
    # Firecrawl parses PDFs → clean markdown via the same /v1/scrape endpoint (BD/direct return raw
    # bytes). RoutingFetcher prefers a handles_pdf backend for PDF URLs.
    handles_pdf = True

    #: Process-wide rate-limit telemetry. The keyless free tier hits a per-IP/day 429 cap (and the
    #: keyed free tier ~10 req/min), so a full multi-source harvest WILL exhaust it — the harvest
    #: skips the rate-limited fetches and the runner can surface ``rate_limited_count`` at the end.
    rate_limited_count: int = 0
    _rate_limit_notified: bool = False

    def _note_rate_limited(self) -> None:
        """Record a 429 and emit ONE prominent, actionable notice per process (not per fetch)."""
        FirecrawlFetcher.rate_limited_count += 1
        if FirecrawlFetcher._rate_limit_notified:
            return
        FirecrawlFetcher._rate_limit_notified = True
        if self._api_key is None:
            logger.warning(
                "⚠️  Firecrawl KEYLESS rate limit reached (HTTP 429). The free keyless tier is "
                "per-IP/day capped, so some fetches are being skipped this run. For full coverage, "
                "best→cheapest: install crawl4ai (free, local, UNLIMITED — `pip install "
                "\"rogue[crawl4ai]\"`), set FIRECRAWL_API_KEY (1,000 free credits, 10 req/min), or add "
                "BRIGHTDATA_* keys — or just wait and re-run later."
            )
        else:
            logger.warning(
                "⚠️  Firecrawl rate limit reached (HTTP 429) — the free tier is ~10 req/min. Some "
                "fetches are being skipped; slow the harvest or upgrade your Firecrawl plan."
            )

    def __init__(self) -> None:
        # Read config at construction; no network calls here.
        base_url = os.environ.get("FIRECRAWL_BASE_URL", "").strip()
        api_key = os.environ.get("FIRECRAWL_API_KEY", "").strip()

        if base_url:
            # Self-hosted: use the provided base URL; key optional.
            self._base_url: str = base_url.rstrip("/")
            self._api_key: str | None = api_key or None
        elif api_key:
            # Cloud: use the default cloud base + the key.
            self._base_url = _CLOUD_BASE
            self._api_key = api_key
        else:
            # No key/URL: keyless free cloud tier (if FIRECRAWL_KEYLESS is on) —
            # cloud base, no Authorization header. If keyless is off the backend
            # is simply unavailable (is_available() returns False).
            self._base_url = _CLOUD_BASE
            self._api_key = None
            if _keyless_enabled():
                logger.info(
                    "FirecrawlFetcher: keyless free tier (no API key) — rate-limited; "
                    "set FIRECRAWL_API_KEY to scale."
                )

        self._http: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    @classmethod
    def is_available(cls) -> bool:
        """Return ``True`` iff Firecrawl is configured in any of its three modes.

        Self-hosted availability is declared by ``FIRECRAWL_BASE_URL``; cloud by
        ``FIRECRAWL_API_KEY``; the opt-in keyless free tier by
        ``FIRECRAWL_KEYLESS`` (truthy). At least one must be present.
        """
        return bool(
            os.environ.get("FIRECRAWL_BASE_URL", "").strip()
            or os.environ.get("FIRECRAWL_API_KEY", "").strip()
            or _keyless_enabled()
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_http(self) -> httpx.AsyncClient:
        """Lazy-initialize the shared httpx client."""
        if self._http is None:
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            self._http = httpx.AsyncClient(
                base_url=self._base_url,
                headers=headers,
                timeout=httpx.Timeout(60.0, connect=10.0),
                follow_redirects=True,
            )
        return self._http

    async def _post_scrape(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST ``/v1/scrape`` and return the ``data`` dict on success.

        Raises :class:`httpx.HTTPStatusError` on non-2xx HTTP responses, and
        :class:`RuntimeError` when the response body carries ``"success": false``,
        mirroring the BD client's error surface so callers handle both the same.
        """
        client = self._get_http()
        response = await client.post("/v1/scrape", json=payload)
        if response.status_code == 429:
            self._note_rate_limited()
        response.raise_for_status()

        body: dict[str, Any] = response.json()
        if not body.get("success", False):
            error = body.get("error", "unknown error")
            raise RuntimeError(
                f"FirecrawlFetcher: /v1/scrape returned success=false — {error}"
            )

        data: dict[str, Any] = body.get("data") or {}
        return data

    # ------------------------------------------------------------------
    # UNLOCK — anti-bot single-page fetch
    # ------------------------------------------------------------------

    async def unlock(self, url: str, format: str = "markdown") -> UnlockedPage:
        """Fetch ``url`` via Firecrawl's proxy/anti-bot stack → :class:`UnlockedPage`.

        ``format="markdown"`` (default): returns ``data.markdown``.
        ``format="html"``: returns ``data.html``.

        Firecrawl always renders JavaScript; for purely static content this is
        equivalent to (and slightly slower than) a direct HTTP GET, but the
        anti-bot layer makes it useful for protected pages.

        Raises :class:`httpx.HTTPStatusError` on HTTP-level failures or
        :class:`RuntimeError` on ``success: false`` API errors.
        """
        fmt = (format or "markdown").lower()
        if fmt not in ("html", "markdown"):
            raise ValueError(f"FirecrawlFetcher.unlock: unsupported format {format!r}")

        data = await self._post_scrape({"url": url, "formats": ["markdown", "html"]})

        if fmt == "markdown":
            content: str = data.get("markdown") or data.get("html") or ""
        else:
            content = data.get("html") or data.get("markdown") or ""

        metadata: dict[str, Any] = data.get("metadata") or {}
        status_code: int = int(metadata.get("statusCode") or 200)
        final_url: str = metadata.get("sourceURL") or metadata.get("url") or url

        return UnlockedPage(
            url=final_url,
            fetched_at=datetime.now(timezone.utc),
            content=content,
            content_format=fmt,  # type: ignore[arg-type]
            status_code=status_code,
        )

    # ------------------------------------------------------------------
    # BROWSER — JS / heavy-anti-bot render
    # ------------------------------------------------------------------

    async def browser(
        self,
        url: str,
        wait_for_selector: str | None = None,
        scroll_pages: int = 1,
        *,
        storage_state: dict[str, Any] | None = None,
    ) -> ScrapedPage:
        """Render ``url`` via Firecrawl (JS-rendered by default) → :class:`ScrapedPage`.

        Firecrawl always executes JavaScript, so this is equivalent to a
        headless-browser render without requiring a local Chromium install.

        Parameters with Firecrawl equivalents:
          - ``wait_for_selector``: passed as ``waitFor`` in the request payload;
            Firecrawl accepts a CSS selector string here to delay scraping until
            the element is present.

        Parameters without Firecrawl equivalents (silently ignored):
          - ``scroll_pages``: Firecrawl has no multi-scroll control; the page
            is rendered in a single pass. Content visible after JS execution is
            captured; lazy-loaded content beyond the initial viewport may be
            absent.
          - ``storage_state``: Firecrawl does not accept cookie/localStorage
            injection via the REST API. Authenticated-page scraping would
            require a Firecrawl profile feature (not yet in the public API).

        Raises :class:`httpx.HTTPStatusError` on HTTP-level failures or
        :class:`RuntimeError` on ``success: false`` API errors.
        """
        if scroll_pages > 1:
            logger.debug(
                "FirecrawlFetcher.browser: scroll_pages=%d ignored (Firecrawl renders in a "
                "single pass; use PlaywrightFetcher for multi-scroll)",
                scroll_pages,
            )
        if storage_state:
            logger.warning(
                "FirecrawlFetcher.browser: storage_state is not supported by the Firecrawl "
                "REST API and will be ignored. Use PlaywrightFetcher for cookie/localStorage injection."
            )

        payload: dict[str, Any] = {"url": url, "formats": ["markdown", "html"]}
        if wait_for_selector:
            # Firecrawl accepts "waitFor" as a CSS selector string (or int ms).
            payload["waitFor"] = wait_for_selector

        data = await self._post_scrape(payload)

        html: str = data.get("html") or data.get("rawHtml") or ""
        # Use markdown as "rendered text" — it's a clean text extraction of the
        # JS-rendered DOM, which is what sources use rendered_text for.
        rendered_text: str = data.get("markdown") or ""

        return ScrapedPage(
            url=url,
            fetched_at=datetime.now(timezone.utc),
            html=html,
            rendered_text=rendered_text,
        )

    # ------------------------------------------------------------------
    # SERP — web search (Firecrawl /v1/search; keyless-capable)
    # ------------------------------------------------------------------

    async def serp(
        self,
        query: str,
        count: int = 10,
        engine: str = "google",  # accepted for contract-compat; Firecrawl manages its own source
    ) -> SerpResponse:
        """Web search via Firecrawl ``/v1/search`` → :class:`SerpResponse`.

        ``engine`` is accepted for :class:`~rogue.harvest.fetchers.base.Fetcher`
        signature compatibility but ignored (Firecrawl picks the search source).

        Each Firecrawl result (``{url, title, description}``) maps to an
        ``organic_results`` entry carrying both ``link`` and ``url`` (plus
        ``title``/``description``/``snippet``) so the harvest's tolerant URL
        extraction works unchanged.

        Degrade-safe, mirroring the DDG backend: any network/API failure or
        ``success: false`` returns an empty :class:`SerpResponse` rather than
        raising — a SERP miss never crashes a harvest run.
        """
        empty = SerpResponse(
            query=query,
            engine="firecrawl",
            fetched_at=datetime.now(timezone.utc),
            organic_results=[],
            knowledge_panel=None,
            raw_json={},
        )
        try:
            client = self._get_http()
            response = await client.post("/v1/search", json={"query": query, "limit": count})
            if response.status_code == 429:
                self._note_rate_limited()
            response.raise_for_status()
            body: dict[str, Any] = response.json()
            if not body.get("success", False):
                logger.warning("FirecrawlFetcher.serp: success=false — %s", body.get("error"))
                return empty

            data = body.get("data")
            # Firecrawl returns data as a list of results; tolerate a {"web": [...]} dict too.
            if isinstance(data, dict):
                data = data.get("web") or data.get("results") or []
            results = data if isinstance(data, list) else []

            organic = [
                {
                    "link": r.get("url"),
                    "url": r.get("url"),
                    "title": r.get("title"),
                    "description": r.get("description"),
                    "snippet": r.get("description"),
                }
                for r in results
                if isinstance(r, dict) and r.get("url")
            ]
            return SerpResponse(
                query=query,
                engine="firecrawl",
                fetched_at=datetime.now(timezone.utc),
                organic_results=organic,
                knowledge_panel=None,
                raw_json={"result_count": len(organic)},
            )
        except Exception as exc:  # noqa: BLE001 — never crash a harvest run
            logger.warning("FirecrawlFetcher.serp: %s — returning empty", exc)
            return empty

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        """Release the shared HTTP client. Idempotent."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None
