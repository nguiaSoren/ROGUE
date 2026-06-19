"""The ``playwright`` fetcher backend — free local headless Chromium.

Handles JS-heavy / SPA pages that require a real browser engine: community
archives, dashboard pages, cookie/localStorage-authenticated SPAs (LeakHub).

Capabilities declared:
  :attr:`~rogue.harvest.fetchers.capabilities.Capability.BROWSER` — the
  primary reason this backend exists; renders a URL in Chromium, optionally
  waits on a CSS selector and scrolls N viewport-heights.

  :attr:`~rogue.harvest.fetchers.capabilities.Capability.UNLOCK` — plain
  non-JS pages work fine via a headed-Chrome GET too; declared as an
  opportunistic extra so the registry can route UNLOCK here when Bright Data
  is absent, though :mod:`.direct` is cheaper for static sites.

**Optional dependency.** ``playwright`` is NOT a hard pyproject dep — it is
listed (by the caller, not this file) under ``rogue[browser]``.  This module
is safe to *import* even when playwright is absent: all provider SDK imports
are deferred inside :meth:`PlaywrightFetcher.browser` and
:meth:`PlaywrightFetcher.is_available`.

**Browser install.** After installing the ``rogue[browser]`` extra, run
``playwright install chromium`` once to download the Chromium binary.
Without it, :meth:`is_available` returns ``False`` and the registry will not
route here.
"""

from __future__ import annotations

import importlib.util
import json as _json
import logging
from datetime import datetime, timezone
from typing import Any

from rogue.harvest.bright_data_client import ScrapedPage, UnlockedPage

from .base import Fetcher
from .capabilities import Capability

__all__ = ["PlaywrightFetcher"]

logger = logging.getLogger("rogue.harvest.fetchers.playwright")


class PlaywrightFetcher(Fetcher):
    """Local headless Chromium via :mod:`playwright.async_api`.

    Mirrors the BROWSER path of :meth:`BrightDataClient.scrape_browser`
    (parameters, storage_state injection pattern, ``ScrapedPage`` field
    mapping) so sources using :meth:`Fetcher.browser` need no change.

    The backend is BROWSER-first; UNLOCK is supported opportunistically (a
    plain ``page.goto`` with no selector/scroll — cheap and correct for
    static sites, though :class:`.DirectFetcher` is lighter-weight when
    playwright is only registered for BROWSER use-cases).
    """

    name: str = "playwright"
    capabilities: frozenset[Capability] = frozenset({Capability.BROWSER, Capability.UNLOCK})

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    @staticmethod
    def is_available() -> bool:
        """Return ``True`` iff ``playwright`` is importable AND a Chromium
        executable is installed (i.e. ``playwright install chromium`` was run).

        Import failures and missing-browser errors are both caught; the method
        never raises.
        """
        if importlib.util.find_spec("playwright") is None:
            return False
        try:
            # Lazy import — only reached when the package is present.
            from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

            with sync_playwright() as pw:
                # ``executable_path`` returns the path but does NOT launch;
                # it raises if the browser hasn't been installed.
                _ = pw.chromium.executable_path
            return True
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------
    # BROWSER
    # ------------------------------------------------------------------

    async def browser(
        self,
        url: str,
        wait_for_selector: str | None = None,
        scroll_pages: int = 1,
        *,
        storage_state: dict[str, Any] | None = None,
    ) -> ScrapedPage:
        """Render ``url`` in local headless Chromium → :class:`ScrapedPage`.

        Mirrors :meth:`BrightDataClient.scrape_browser` exactly:
        - ``wait_for_selector``: optional CSS selector to await before snapshot.
        - ``scroll_pages``: number of viewport-height scrolls (1 = no extra scroll).
        - ``storage_state``: Playwright-native ``{cookies, origins}`` blob;
          cookies applied via ``add_cookies``; localStorage entries injected
          via ``add_init_script`` (same pattern as the BD scrape_browser path,
          verified 2026-05-26 against LeakHub's Convex auth).

        Raises :class:`ImportError` if ``playwright`` is not installed.
        Raises :class:`RuntimeError` on navigation / browser launch failure
        with a clear message (mirrors the BD client's error shape so callers
        handle it uniformly).
        """
        if importlib.util.find_spec("playwright") is None:
            raise ImportError(
                "PlaywrightFetcher.browser requires playwright but it is not installed. "
                "Run: pip install 'rogue[browser]' && playwright install chromium"
            )

        # Deferred import — only reached when the package is present.
        # Imported here (not at module top) so patching
        # ``playwright.async_api.async_playwright`` in tests intercepts it.
        from playwright.async_api import async_playwright  # type: ignore[import-not-found]

        html: str = ""
        rendered_text: str = ""

        from .proxy import playwright_proxy

        launch_kwargs: dict = {"headless": True}
        proxy = playwright_proxy()  # ROGUE_PROXY_URL → {server, username, password}, or None
        if proxy:
            launch_kwargs["proxy"] = proxy

        async with async_playwright() as pw:
            browser_inst = await pw.chromium.launch(**launch_kwargs)
            try:
                context = await browser_inst.new_context()

                # --- storage_state injection (matches BD scrape_browser pattern) ---
                if storage_state and storage_state.get("cookies"):
                    await context.add_cookies(storage_state["cookies"])

                if storage_state and storage_state.get("origins"):
                    for origin_entry in storage_state["origins"]:
                        ls_entries = origin_entry.get("localStorage", [])
                        if not ls_entries:
                            continue
                        init_js = (
                            "(() => { const entries = "
                            + _json.dumps(ls_entries)
                            + "; for (const e of entries) { try { "
                            + "window.localStorage.setItem(e.name, e.value); "
                            + "} catch (err) {} } })();"
                        )
                        await context.add_init_script(init_js)

                page = await context.new_page()
                await page.goto(url, timeout=2 * 60_000)

                if wait_for_selector:
                    await page.wait_for_selector(wait_for_selector, timeout=30_000)

                # Extra scroll passes for lazy-loaded content (same as BD path).
                for _ in range(max(0, scroll_pages - 1)):
                    await page.evaluate("window.scrollBy(0, window.innerHeight);")

                html = await page.content()
                rendered_text = await page.evaluate("document.body.innerText") or ""
            finally:
                await browser_inst.close()

        return ScrapedPage(
            url=url,
            fetched_at=datetime.now(timezone.utc),
            html=html,
            rendered_text=rendered_text,
        )

    # ------------------------------------------------------------------
    # UNLOCK (opportunistic — prefer DirectFetcher for static pages)
    # ------------------------------------------------------------------

    async def unlock(self, url: str, format: str = "markdown") -> UnlockedPage:
        """Fetch a page via headless Chromium → :class:`UnlockedPage`.

        Uses the same browser launch as :meth:`browser` but with no selector
        wait, no scroll, and no storage_state — appropriate for content that
        simply needs JS execution but no auth or lazy loading.

        ``format`` is accepted for interface compatibility; this backend always
        returns both ``html`` and ``text`` (the registry caller may discard
        whichever it does not need).
        """
        page = await self.browser(url)
        # ``format`` governs which slice of the ScrapedPage we surface as
        # the ``content`` field.  Chromium always yields both raw HTML and
        # rendered text; we pick whichever the caller prefers.
        content = page.rendered_text if format == "markdown" else page.html
        return UnlockedPage(
            url=url,
            fetched_at=page.fetched_at,
            content=content,
            content_format="markdown" if format == "markdown" else "html",
            status_code=200,  # Playwright does not surface the HTTP status code
        )
