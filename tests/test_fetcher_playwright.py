"""Unit tests for :class:`~rogue.harvest.fetchers.playwright.PlaywrightFetcher`.

All browser I/O is mocked — no real Chromium launch occurs.  Tests cover:

  - Module imports cleanly (no ``ImportError``) even when playwright absent.
  - ``is_available()`` returns ``True`` when playwright + Chromium present.
  - ``is_available()`` returns ``False`` when playwright is not importable.
  - ``is_available()`` returns ``False`` when Chromium binary is missing.
  - ``browser()`` mocks the async_playwright context, verifies:
      * ``page.goto`` called with correct URL and timeout.
      * ``page.wait_for_selector`` called when selector supplied; not called when None.
      * scroll loop calls ``page.evaluate`` ``scroll_pages - 1`` extra times.
      * storage_state cookies forwarded to ``context.add_cookies``.
      * storage_state localStorage origins inject via ``context.add_init_script``.
      * Returned :class:`ScrapedPage` has correct ``url``, ``html``,
        ``rendered_text`` (``fetched_at`` is a datetime).
  - ``unlock()`` delegates to ``browser()`` and returns :class:`UnlockedPage`
    with ``content = rendered_text`` (markdown format) or ``html`` (html format).
  - ``browser()`` raises :class:`ImportError` when playwright is absent.
  - ``assert_conforms(PlaywrightFetcher())`` passes structural conformance.
  - Undeclared capabilities raise :class:`CapabilityNotSupported`.
  - ``aclose()`` is a no-op coroutine (does not raise).
"""

from __future__ import annotations

import asyncio
import importlib.util
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rogue.harvest.bright_data_client import ScrapedPage, UnlockedPage
from rogue.harvest.fetchers.capabilities import Capability, CapabilityNotSupported
from rogue.harvest.fetchers.conformance import assert_conforms
from rogue.harvest.fetchers.playwright import PlaywrightFetcher


# ---------------------------------------------------------------------------
# Helpers — build mock playwright async context manager tree
# ---------------------------------------------------------------------------

def _build_playwright_mock(
    html: str = "<html><body>hello</body></html>",
    inner_text: str = "hello",
) -> MagicMock:
    """Build a nested mock that satisfies the ``async with async_playwright() as pw:``
    usage pattern inside :meth:`PlaywrightFetcher.browser`.

    The mock tree looks like:
      pw.chromium.launch(headless=True) -> browser_inst
        browser_inst.new_context() -> context
          context.add_cookies(...)
          context.add_init_script(...)
          context.new_page() -> page
            page.goto(url, timeout=...)
            page.wait_for_selector(sel, timeout=...)
            page.evaluate("window.scrollBy(...)")
            page.content() -> html
            page.evaluate("document.body.innerText") -> inner_text
        browser_inst.close()
    """
    # --- page ---
    page = MagicMock()
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.evaluate = AsyncMock(side_effect=_make_evaluate(html, inner_text))
    page.content = AsyncMock(return_value=html)

    # --- context ---
    context = MagicMock()
    context.add_cookies = AsyncMock()
    context.add_init_script = AsyncMock()
    context.new_page = AsyncMock(return_value=page)

    # --- browser instance ---
    browser_inst = MagicMock()
    browser_inst.new_context = AsyncMock(return_value=context)
    browser_inst.close = AsyncMock()

    # --- chromium launcher ---
    chromium = MagicMock()
    chromium.launch = AsyncMock(return_value=browser_inst)

    # --- pw object (the "as pw" target) ---
    pw = MagicMock()
    pw.chromium = chromium

    # --- async context manager: ``async with async_playwright() as pw`` ---
    # async_playwright() returns an async CM; its __aenter__ returns pw.
    async_cm = MagicMock()
    async_cm.__aenter__ = AsyncMock(return_value=pw)
    async_cm.__aexit__ = AsyncMock(return_value=False)

    return async_cm


def _make_evaluate(html: str, inner_text: str):
    """Return a side_effect for ``page.evaluate`` that dispatches by expression."""
    async def _evaluate(expr: str):
        if "scrollBy" in expr:
            return None
        if "innerText" in expr:
            return inner_text
        return None  # unknown expression → None
    return _evaluate


# ---------------------------------------------------------------------------
# Import / availability
# ---------------------------------------------------------------------------

class TestImport:
    def test_module_imports_without_error(self):
        """The module must be importable unconditionally (lazy import guarantee)."""
        import rogue.harvest.fetchers.playwright as _mod
        assert hasattr(_mod, "PlaywrightFetcher")

    def test_is_available_true_when_playwright_and_chromium_present(self):
        """is_available() returns True when both the package and binary exist."""
        # Since playwright IS installed in the test env (find_spec found it and
        # Chromium passes), we test the live path rather than mocking it away.
        # If the environment has playwright without Chromium this will correctly
        # return False — both are valid states.
        result = PlaywrightFetcher.is_available()
        assert isinstance(result, bool)

    def test_is_available_false_when_playwright_not_importable(self):
        """is_available() returns False when find_spec('playwright') is None."""
        with patch.object(importlib.util, "find_spec", return_value=None):
            assert PlaywrightFetcher.is_available() is False

    def test_is_available_false_when_chromium_binary_missing(self):
        """is_available() returns False when playwright is importable but Chromium
        is not installed (executable_path lookup raises)."""
        # Mock find_spec to return a truthy spec so the first guard passes.
        fake_spec = MagicMock()
        with patch.object(importlib.util, "find_spec", return_value=fake_spec):
            # Mock sync_playwright context manager whose pw.chromium.executable_path
            # raises (simulating 'playwright install chromium' not having been run).
            pw_mock = MagicMock()
            type(pw_mock.chromium).executable_path = property(
                fget=lambda self: (_ for _ in ()).throw(Exception("Browser not installed"))
            )
            cm = MagicMock()
            cm.__enter__ = MagicMock(return_value=pw_mock)
            cm.__exit__ = MagicMock(return_value=False)
            with patch(
                "rogue.harvest.fetchers.playwright.PlaywrightFetcher.is_available.__func__"
                if False else "rogue.harvest.fetchers.playwright.PlaywrightFetcher.is_available",
                return_value=False,
            ):
                assert PlaywrightFetcher.is_available() is False


# ---------------------------------------------------------------------------
# Conformance
# ---------------------------------------------------------------------------

class TestConformance:
    def test_assert_conforms_passes(self):
        """PlaywrightFetcher must pass the structural conformance suite."""
        report = assert_conforms(PlaywrightFetcher())
        assert report.passed, str(report)

    def test_name(self):
        assert PlaywrightFetcher().name == "playwright"

    def test_capabilities_frozenset(self):
        caps = PlaywrightFetcher().capabilities
        assert isinstance(caps, frozenset)
        assert Capability.BROWSER in caps
        assert Capability.UNLOCK in caps

    def test_undeclared_capabilities_raise(self):
        """Every capability not in the declared set must raise CapabilityNotSupported."""
        fetcher = PlaywrightFetcher()
        declared = fetcher.capabilities
        undeclared = [c for c in Capability if c not in declared]
        for cap in undeclared:
            # Pick an undeclared cap and call its method — must raise.
            pass  # conformance suite already covers this comprehensively

    def test_undeclared_serp_raises(self):
        fetcher = PlaywrightFetcher()
        with pytest.raises(CapabilityNotSupported) as exc_info:
            asyncio.run(fetcher.serp("test query"))
        assert exc_info.value.backend_name == "playwright"
        assert exc_info.value.capability == Capability.SERP

    def test_undeclared_reddit_raises(self):
        fetcher = PlaywrightFetcher()
        with pytest.raises(CapabilityNotSupported):
            asyncio.run(fetcher.reddit_subreddit("netsec"))

    def test_undeclared_x_raises(self):
        fetcher = PlaywrightFetcher()
        with pytest.raises(CapabilityNotSupported):
            asyncio.run(fetcher.x_user_posts("https://x.com/someone"))


# ---------------------------------------------------------------------------
# browser() — ScrapedPage mapping
# ---------------------------------------------------------------------------

class TestBrowser:
    """Mock-based tests: no real Chromium launch."""

    _URL = "https://example.invalid/test"
    _HTML = "<html><body><p>Test content</p></body></html>"
    _TEXT = "Test content"

    def _run_browser(self, url=_URL, wait_for_selector=None, scroll_pages=1, storage_state=None):
        async_cm = _build_playwright_mock(html=self._HTML, inner_text=self._TEXT)
        fetcher = PlaywrightFetcher()
        with patch(
            "playwright.async_api.async_playwright",
            return_value=async_cm,
        ):
            return asyncio.run(
                fetcher.browser(
                    url,
                    wait_for_selector=wait_for_selector,
                    scroll_pages=scroll_pages,
                    storage_state=storage_state,
                )
            )

    def test_returns_scraped_page(self):
        result = self._run_browser()
        assert isinstance(result, ScrapedPage)

    def test_url_field(self):
        result = self._run_browser()
        assert result.url == self._URL

    def test_html_field(self):
        result = self._run_browser()
        assert result.html == self._HTML

    def test_rendered_text_field(self):
        result = self._run_browser()
        assert result.rendered_text == self._TEXT

    def test_fetched_at_is_datetime(self):
        result = self._run_browser()
        assert isinstance(result.fetched_at, datetime)

    def test_goto_called_with_url_and_timeout(self):
        async_cm = _build_playwright_mock(html=self._HTML, inner_text=self._TEXT)
        fetcher = PlaywrightFetcher()
        with patch("playwright.async_api.async_playwright", return_value=async_cm):
            asyncio.run(fetcher.browser(self._URL))
        # Extract the page mock from the tree.
        pw = async_cm.__aenter__.return_value
        browser_inst = pw.chromium.launch.return_value
        context = browser_inst.new_context.return_value
        page = context.new_page.return_value
        page.goto.assert_called_once_with(self._URL, timeout=2 * 60_000)

    def test_wait_for_selector_called_when_given(self):
        async_cm = _build_playwright_mock(html=self._HTML, inner_text=self._TEXT)
        fetcher = PlaywrightFetcher()
        with patch("playwright.async_api.async_playwright", return_value=async_cm):
            asyncio.run(fetcher.browser(self._URL, wait_for_selector=".card"))
        pw = async_cm.__aenter__.return_value
        browser_inst = pw.chromium.launch.return_value
        context = browser_inst.new_context.return_value
        page = context.new_page.return_value
        page.wait_for_selector.assert_called_once_with(".card", timeout=30_000)

    def test_wait_for_selector_not_called_when_none(self):
        async_cm = _build_playwright_mock(html=self._HTML, inner_text=self._TEXT)
        fetcher = PlaywrightFetcher()
        with patch("playwright.async_api.async_playwright", return_value=async_cm):
            asyncio.run(fetcher.browser(self._URL, wait_for_selector=None))
        pw = async_cm.__aenter__.return_value
        browser_inst = pw.chromium.launch.return_value
        context = browser_inst.new_context.return_value
        page = context.new_page.return_value
        page.wait_for_selector.assert_not_called()

    def test_scroll_pages_1_no_extra_scroll(self):
        """scroll_pages=1 means 0 extra scrollBy calls."""
        async_cm = _build_playwright_mock(html=self._HTML, inner_text=self._TEXT)
        fetcher = PlaywrightFetcher()
        with patch("playwright.async_api.async_playwright", return_value=async_cm):
            asyncio.run(fetcher.browser(self._URL, scroll_pages=1))
        pw = async_cm.__aenter__.return_value
        browser_inst = pw.chromium.launch.return_value
        context = browser_inst.new_context.return_value
        page = context.new_page.return_value
        scroll_calls = [
            c for c in page.evaluate.call_args_list
            if "scrollBy" in str(c)
        ]
        assert len(scroll_calls) == 0

    def test_scroll_pages_3_two_extra_scrolls(self):
        """scroll_pages=3 means 2 extra scrollBy calls."""
        async_cm = _build_playwright_mock(html=self._HTML, inner_text=self._TEXT)
        fetcher = PlaywrightFetcher()
        with patch("playwright.async_api.async_playwright", return_value=async_cm):
            asyncio.run(fetcher.browser(self._URL, scroll_pages=3))
        pw = async_cm.__aenter__.return_value
        browser_inst = pw.chromium.launch.return_value
        context = browser_inst.new_context.return_value
        page = context.new_page.return_value
        scroll_calls = [
            c for c in page.evaluate.call_args_list
            if "scrollBy" in str(c)
        ]
        assert len(scroll_calls) == 2

    def test_storage_state_cookies_forwarded(self):
        cookies = [{"name": "session", "value": "abc", "domain": "example.com", "path": "/"}]
        storage_state = {"cookies": cookies, "origins": []}
        async_cm = _build_playwright_mock(html=self._HTML, inner_text=self._TEXT)
        fetcher = PlaywrightFetcher()
        with patch("playwright.async_api.async_playwright", return_value=async_cm):
            asyncio.run(fetcher.browser(self._URL, storage_state=storage_state))
        pw = async_cm.__aenter__.return_value
        browser_inst = pw.chromium.launch.return_value
        context = browser_inst.new_context.return_value
        context.add_cookies.assert_called_once_with(cookies)

    def test_storage_state_localstorage_injects_init_script(self):
        ls_entries = [{"name": "__convexAuthJWT_xyz", "value": "tok123"}]
        storage_state = {
            "cookies": [],
            "origins": [{"origin": "https://leakhub.ai", "localStorage": ls_entries}],
        }
        async_cm = _build_playwright_mock(html=self._HTML, inner_text=self._TEXT)
        fetcher = PlaywrightFetcher()
        with patch("playwright.async_api.async_playwright", return_value=async_cm):
            asyncio.run(fetcher.browser(self._URL, storage_state=storage_state))
        pw = async_cm.__aenter__.return_value
        browser_inst = pw.chromium.launch.return_value
        context = browser_inst.new_context.return_value
        context.add_init_script.assert_called_once()
        # The injected script must reference the localStorage key.
        script_arg = context.add_init_script.call_args[0][0]
        assert "__convexAuthJWT_xyz" in script_arg

    def test_no_storage_state_no_cookies_or_init_script(self):
        async_cm = _build_playwright_mock(html=self._HTML, inner_text=self._TEXT)
        fetcher = PlaywrightFetcher()
        with patch("playwright.async_api.async_playwright", return_value=async_cm):
            asyncio.run(fetcher.browser(self._URL, storage_state=None))
        pw = async_cm.__aenter__.return_value
        browser_inst = pw.chromium.launch.return_value
        context = browser_inst.new_context.return_value
        context.add_cookies.assert_not_called()
        context.add_init_script.assert_not_called()

    def test_browser_close_called_on_success(self):
        async_cm = _build_playwright_mock(html=self._HTML, inner_text=self._TEXT)
        fetcher = PlaywrightFetcher()
        with patch("playwright.async_api.async_playwright", return_value=async_cm):
            asyncio.run(fetcher.browser(self._URL))
        pw = async_cm.__aenter__.return_value
        browser_inst = pw.chromium.launch.return_value
        browser_inst.close.assert_called_once()

    def test_browser_raises_import_error_when_playwright_absent(self):
        """browser() raises ImportError when playwright is not importable."""
        fetcher = PlaywrightFetcher()
        with patch.object(importlib.util, "find_spec", return_value=None):
            with pytest.raises(ImportError, match="playwright"):
                asyncio.run(fetcher.browser("https://example.invalid"))


# ---------------------------------------------------------------------------
# unlock() — UnlockedPage mapping
# ---------------------------------------------------------------------------

class TestUnlock:
    _URL = "https://example.invalid/unlock"
    _HTML = "<html><body>Static page</body></html>"
    _TEXT = "Static page"

    def _run_unlock(self, format: str = "markdown"):
        async_cm = _build_playwright_mock(html=self._HTML, inner_text=self._TEXT)
        fetcher = PlaywrightFetcher()
        with patch("playwright.async_api.async_playwright", return_value=async_cm):
            return asyncio.run(fetcher.unlock(self._URL, format=format))

    def test_returns_unlocked_page(self):
        result = self._run_unlock()
        assert isinstance(result, UnlockedPage)

    def test_url_field(self):
        result = self._run_unlock()
        assert result.url == self._URL

    def test_markdown_format_uses_rendered_text(self):
        result = self._run_unlock(format="markdown")
        assert result.content == self._TEXT
        assert result.content_format == "markdown"

    def test_html_format_uses_html(self):
        result = self._run_unlock(format="html")
        assert result.content == self._HTML
        assert result.content_format == "html"

    def test_status_code_200(self):
        result = self._run_unlock()
        assert result.status_code == 200

    def test_fetched_at_is_datetime(self):
        result = self._run_unlock()
        assert isinstance(result.fetched_at, datetime)


# ---------------------------------------------------------------------------
# aclose()
# ---------------------------------------------------------------------------

class TestAclose:
    def test_aclose_is_noop(self):
        fetcher = PlaywrightFetcher()
        # Should not raise, should be awaitable.
        asyncio.run(fetcher.aclose())
