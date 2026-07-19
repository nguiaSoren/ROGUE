"""The ``crawl4ai`` fetcher backend — free local headless Chromium via the OSS Crawl4AI library.

Crawl4AI wraps Playwright's Chromium under the hood, providing automatic JS rendering,
anti-bot stealth heuristics, and first-class markdown extraction.  It is a superset of
the :mod:`.playwright` backend for the ``UNLOCK`` capability (cleaner markdown output)
and an equivalent for ``BROWSER``.

Capabilities declared:
  :attr:`~rogue.harvest.fetchers.capabilities.Capability.UNLOCK` — runs the URL through
  Crawl4AI's ``AsyncWebCrawler`` and returns either ``result.markdown.raw_markdown``
  (default ``format="markdown"``) or ``result.html`` (``format="html"``).

  :attr:`~rogue.harvest.fetchers.capabilities.Capability.BROWSER` — same crawl, but
  surfaces the raw ``html`` + ``rendered_text`` (cleaned_html text) as a
  :class:`~rogue.harvest.bright_data_client.ScrapedPage`, matching the
  :mod:`.playwright` backend's output contract exactly.

**Optional dependency.** ``crawl4ai`` is NOT a hard pyproject dep — list it under
``rogue[crawl4ai]``.  This module is safe to *import* even when crawl4ai is absent:
all library imports are deferred inside methods (same pattern as :mod:`.playwright`).

**Browser install.** Crawl4AI uses Playwright's Chromium internally.  After installing
the ``rogue[crawl4ai]`` extra run ``crawl4ai-setup`` (or ``playwright install chromium``)
once to download the Chromium binary.  Without it, :meth:`Crawl4AIFetcher.is_available`
returns ``False`` and the registry will not route here.

**API note.** Verified against Crawl4AI v0.8.9 (docs.crawl4ai.com v0.8.x, 2026-06).
- ``AsyncWebCrawler`` is the async context-manager entry point.
- ``arun(url, config=CrawlerRunConfig(...))`` returns a ``CrawlResult``.
- ``result.markdown`` is a ``MarkdownGenerationResult`` object; access raw text via
  ``result.markdown.raw_markdown``.
- ``result.html`` is the raw page HTML; ``result.cleaned_html`` is the sanitized HTML.
- ``result.status_code`` is the HTTP status (``Optional[int]``).
- ``result.success`` is ``True`` iff the crawl completed without major errors.
- ``CrawlerRunConfig(wait_for="css:<selector>")`` waits for a CSS selector.
- Scrolling uses ``CrawlerRunConfig(js_code="window.scrollTo(0, document.body.scrollHeight);")``.
"""

from __future__ import annotations

import asyncio
import glob
import importlib.util
import logging
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any

from rogue.harvest.bright_data_client import ScrapedPage, UnlockedPage

from .base import Fetcher
from .capabilities import Capability

__all__ = ["Crawl4AIFetcher"]

logger = logging.getLogger("rogue.harvest.fetchers.crawl4ai")


def _chromium_binary_on_disk() -> bool:
    """True iff a Playwright Chromium browser is installed on disk — a loop-safe alternative to the
    ``sync_playwright()`` probe (which raises inside an asyncio loop). Checks ``PLAYWRIGHT_BROWSERS_PATH``
    then the per-OS default browser cache for a ``chromium*`` install."""
    roots: list[str] = []
    env_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if env_path:
        roots.append(env_path)
    home = os.path.expanduser("~")
    roots += [
        os.path.join(home, "Library", "Caches", "ms-playwright"),          # macOS
        os.path.join(home, ".cache", "ms-playwright"),                     # Linux
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright"),  # Windows
    ]
    return any(root and glob.glob(os.path.join(root, "chromium*")) for root in roots)


def _crawler_kwargs() -> dict[str, Any]:
    """``AsyncWebCrawler(**kwargs)`` carrying the ROGUE_PROXY_URL proxy, or ``{}`` when unset.

    Defensive: crawl4ai's proxy API varies across versions, so a config mismatch logs and falls back
    to no-proxy rather than breaking the backend (crawl4ai isn't installed in CI to verify live)."""
    from .proxy import playwright_proxy

    proxy = playwright_proxy()  # crawl4ai BrowserConfig uses the same {server,username,password} shape
    if not proxy:
        return {}
    try:
        from crawl4ai import BrowserConfig  # type: ignore[import-not-found]

        return {"config": BrowserConfig(proxy_config=proxy)}
    except Exception:  # noqa: BLE001 — never break the backend on a proxy-config API mismatch
        logger.warning(
            "crawl4ai: could not apply ROGUE_PROXY_URL (BrowserConfig/proxy_config API mismatch); "
            "proceeding without proxy",
            exc_info=True,
        )
        return {}


def _strip_html_to_text(html: str) -> str:
    """Minimal HTML → plain-text fallback for when markdown extraction is unavailable."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


class Crawl4AIFetcher(Fetcher):
    """OSS Crawl4AI backend — headless Chromium with built-in markdown extraction.

    Mirrors the UNLOCK and BROWSER paths of the BD client so source plugins
    need no changes (same parameters, same return types).

    The backend is UNLOCK + BROWSER; it performs real JS rendering for every
    request (unlike :mod:`.direct` which is plain httpx).  For purely static
    bot-tolerant pages :class:`.DirectFetcher` is lighter-weight; prefer
    Crawl4AI when markdown quality or JS rendering matters.
    """

    name: str = "crawl4ai"
    capabilities: frozenset[Capability] = frozenset({Capability.UNLOCK, Capability.BROWSER})

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    @classmethod
    def is_available(cls) -> bool:
        """Return ``True`` iff ``crawl4ai`` is importable AND a Chromium executable
        is installed (i.e. ``crawl4ai-setup`` or ``playwright install chromium`` was run).

        Import failures and missing-browser errors are both caught; the method
        never raises.

        CRITICAL: ``sync_playwright()`` **raises inside a running asyncio loop** ("Sync API inside
        asyncio"), which is exactly the harvest's context — so the sync probe would falsely report
        crawl4ai UNAVAILABLE during every async harvest, silently forcing the rate-limited keyless-
        Firecrawl path (2026-07-10 fix). When called from within an event loop we therefore skip the
        sync probe and check the Playwright browser cache on disk instead (equally authoritative:
        registration only needs to know the binary exists, not launch it).
        """
        if importlib.util.find_spec("crawl4ai") is None:
            return False
        if importlib.util.find_spec("playwright") is None:
            return False
        try:
            asyncio.get_running_loop()
            in_async_loop = True
        except RuntimeError:
            in_async_loop = False
        if in_async_loop:
            return _chromium_binary_on_disk()
        try:
            from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

            with sync_playwright() as pw:
                _ = pw.chromium.executable_path
            return True
        except Exception:  # noqa: BLE001 — sync API in a loop, or a genuinely missing browser
            return _chromium_binary_on_disk()

    # ------------------------------------------------------------------
    # UNLOCK — anti-bot single-page fetch
    # ------------------------------------------------------------------

    async def unlock(self, url: str, format: str = "markdown") -> UnlockedPage:
        """Fetch ``url`` via Crawl4AI's headless Chromium → :class:`UnlockedPage`.

        ``format="markdown"`` (default): returns ``result.markdown.raw_markdown``
        — Crawl4AI's built-in HTML→Markdown conversion (higher quality than the
        regex-based fallback in :mod:`.direct`).

        ``format="html"``: returns the raw page ``result.html``.

        On crawl failure (``result.success is False``) raises :class:`RuntimeError`
        so the orchestrator/source handles it the same way BD client errors are handled.
        """
        # Check availability: prefer sys.modules (covers test stubs); fall back to find_spec.
        # We avoid calling find_spec on a module already in sys.modules because stub
        # modules created via types.ModuleType have __spec__=None which causes ValueError.
        _crawl4ai_available = (
            "crawl4ai" in sys.modules
            or (importlib.util.find_spec("crawl4ai") is not None)
        )
        if not _crawl4ai_available:
            raise ImportError(
                "Crawl4AIFetcher requires crawl4ai but it is not installed. "
                "Add 'crawl4ai' to your dependencies and run 'crawl4ai-setup'."
            )

        # Deferred imports — only reached when the package is present.
        # Imported here (not at module top) so tests can patch at this location.
        from crawl4ai import AsyncWebCrawler  # type: ignore[import-not-found]
        from crawl4ai.async_configs import CrawlerRunConfig  # type: ignore[import-not-found]

        fmt = (format or "markdown").lower()
        if fmt not in ("html", "markdown"):
            raise ValueError(f"Crawl4AIFetcher.unlock: unsupported format {format!r}")

        run_config = CrawlerRunConfig()

        async with AsyncWebCrawler(**_crawler_kwargs()) as crawler:
            result = await crawler.arun(url=url, config=run_config)

        if not result.success:
            raise RuntimeError(
                f"Crawl4AIFetcher.unlock failed for {url!r}: "
                f"{getattr(result, 'error_message', 'unknown error')}"
            )

        if fmt == "markdown":
            md = result.markdown
            if md is not None and hasattr(md, "raw_markdown"):
                content = md.raw_markdown or ""
            elif isinstance(md, str):
                # Older/simplified build returns a plain string
                content = md
            else:
                # Fallback: strip tags from html
                content = _strip_html_to_text(result.html or "")
        else:
            content = result.html or ""

        status_code: int = result.status_code if result.status_code is not None else 200

        return UnlockedPage(
            url=url,
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
        """Render ``url`` via Crawl4AI's headless Chromium → :class:`ScrapedPage`.

        Mirrors :meth:`BrightDataClient.scrape_browser` and
        :meth:`PlaywrightFetcher.browser` in parameters and return shape.

        - ``wait_for_selector``: mapped to Crawl4AI's ``CrawlerRunConfig(wait_for=...)``
          using the ``"css:<selector>"`` prefix syntax.
        - ``scroll_pages``: scroll ``scroll_pages - 1`` additional viewport-heights via
          ``js_code`` (Crawl4AI has no native scroll_pages parameter; we compose JS).
          ``scroll_pages=1`` means no extra scrolling (same semantic as the playwright
          backend).
        - ``storage_state``: Crawl4AI does not expose a direct storage-state injection
          API equivalent to Playwright's ``add_cookies`` / ``add_init_script``; this
          parameter is accepted for interface compatibility but **has no effect** —
          a warning is emitted if a non-None value is supplied.

        On crawl failure raises :class:`RuntimeError`.
        """
        _crawl4ai_available = (
            "crawl4ai" in sys.modules
            or (importlib.util.find_spec("crawl4ai") is not None)
        )
        if not _crawl4ai_available:
            raise ImportError(
                "Crawl4AIFetcher requires crawl4ai but it is not installed. "
                "Add 'crawl4ai' to your dependencies and run 'crawl4ai-setup'."
            )

        if storage_state is not None:
            logger.warning(
                "Crawl4AIFetcher.browser: storage_state is not supported by Crawl4AI's "
                "public API; the auth state will NOT be injected.  Use PlaywrightFetcher "
                "for storage_state-authenticated pages (e.g. LeakHub)."
            )

        # Deferred imports — only reached when the package is present.
        from crawl4ai import AsyncWebCrawler  # type: ignore[import-not-found]
        from crawl4ai.async_configs import CrawlerRunConfig  # type: ignore[import-not-found]

        # Build wait_for string: Crawl4AI uses "css:<selector>" prefix.
        wait_for: str | None = None
        if wait_for_selector:
            wait_for = f"css:{wait_for_selector}"

        # Build scroll JS: scroll (scroll_pages - 1) extra viewport-heights.
        js_code: str | None = None
        extra_scrolls = max(0, scroll_pages - 1)
        if extra_scrolls > 0:
            js_code = (
                f"for (let i = 0; i < {extra_scrolls}; i++) {{"
                f"  window.scrollBy(0, window.innerHeight);"
                f"}}"
            )

        run_config_kwargs: dict[str, Any] = {}
        if wait_for is not None:
            run_config_kwargs["wait_for"] = wait_for
        if js_code is not None:
            run_config_kwargs["js_code"] = js_code

        run_config = CrawlerRunConfig(**run_config_kwargs)

        async with AsyncWebCrawler(**_crawler_kwargs()) as crawler:
            result = await crawler.arun(url=url, config=run_config)

        if not result.success:
            raise RuntimeError(
                f"Crawl4AIFetcher.browser failed for {url!r}: "
                f"{getattr(result, 'error_message', 'unknown error')}"
            )

        html: str = result.html or ""
        # cleaned_html gives the sanitized HTML (scripts/styles stripped); extract
        # its text as rendered_text to match PlaywrightFetcher's page.innerText output.
        cleaned: str = result.cleaned_html or ""
        rendered_text: str = _strip_html_to_text(cleaned) if cleaned else _strip_html_to_text(html)

        return ScrapedPage(
            url=url,
            fetched_at=datetime.now(timezone.utc),
            html=html,
            rendered_text=rendered_text,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        """No persistent state to release — Crawl4AI is context-managed per call."""
        return None
