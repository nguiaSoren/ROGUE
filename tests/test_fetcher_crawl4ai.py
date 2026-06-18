"""Unit tests for :class:`~rogue.harvest.fetchers.crawl4ai.Crawl4AIFetcher`.

All network and browser I/O is mocked — no real Chromium is launched, no HTTP
requests are made.  The suite verifies:

1. The module imports cleanly even when ``crawl4ai`` is absent.
2. :func:`~rogue.harvest.fetchers.conformance.assert_conforms` passes (structural contract).
3. :meth:`~Crawl4AIFetcher.unlock` builds the correct :class:`UnlockedPage` for both
   ``format="markdown"`` (default) and ``format="html"``.
4. :meth:`~Crawl4AIFetcher.browser` builds the correct :class:`ScrapedPage`, maps
   ``wait_for_selector`` to ``CrawlerRunConfig(wait_for="css:<selector>")`` and
   maps ``scroll_pages`` to a ``js_code`` scroll snippet.
5. :meth:`~Crawl4AIFetcher.is_available` returns ``True`` when both ``crawl4ai``
   and ``playwright`` (with a valid chromium path) are importable, and ``False``
   when either is absent or the chromium check fails.
6. Crawl failure (``result.success=False``) raises :class:`RuntimeError`.
7. ``storage_state`` triggers a warning (accepted for compatibility, not injected).
"""

from __future__ import annotations

import importlib
import sys
import types
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers to build a fake CrawlResult
# ---------------------------------------------------------------------------


def _fake_markdown_result(raw: str) -> MagicMock:
    """Return a mock MarkdownGenerationResult with .raw_markdown set."""
    md = MagicMock()
    md.raw_markdown = raw
    return md


def _fake_crawl_result(
    *,
    success: bool = True,
    html: str = "<html><body>Hello</body></html>",
    cleaned_html: str = "<body>Hello</body>",
    markdown_raw: str = "# Hello",
    status_code: int = 200,
    error_message: str = "",
) -> MagicMock:
    r = MagicMock()
    r.success = success
    r.html = html
    r.cleaned_html = cleaned_html
    r.markdown = _fake_markdown_result(markdown_raw)
    r.status_code = status_code
    r.error_message = error_message
    return r


# ---------------------------------------------------------------------------
# Context-manager-compatible mock for AsyncWebCrawler
# ---------------------------------------------------------------------------


def _make_crawler_cm(crawl_result: MagicMock) -> MagicMock:
    """Return a mock AsyncWebCrawler usable as ``async with ... as crawler``."""
    crawler = MagicMock()
    crawler.arun = AsyncMock(return_value=crawl_result)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=crawler)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# Fixture: ensure crawl4ai is importable for the main test body
# (the module under test does lazy imports, so we inject stubs into sys.modules)
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_crawl4ai(monkeypatch):
    """Inject a minimal fake ``crawl4ai`` + ``crawl4ai.async_configs`` into sys.modules.

    The stubs are removed after the test so they do not leak into other tests.
    """
    # ---- crawl4ai.async_configs stub ----
    configs_mod = types.ModuleType("crawl4ai.async_configs")

    class FakeCrawlerRunConfig:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    configs_mod.CrawlerRunConfig = FakeCrawlerRunConfig  # type: ignore[attr-defined]

    # ---- crawl4ai stub ----
    crawl4ai_mod = types.ModuleType("crawl4ai")
    # AsyncWebCrawler — patched per-test via patch(); default is a no-op class
    crawl4ai_mod.AsyncWebCrawler = MagicMock  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "crawl4ai", crawl4ai_mod)
    monkeypatch.setitem(sys.modules, "crawl4ai.async_configs", configs_mod)

    # Force a reload so the lazy-imported names resolve to our stubs
    # (the module may already be imported; reload picks up the new sys.modules entries)
    import rogue.harvest.fetchers.crawl4ai as mod

    return mod, crawl4ai_mod, configs_mod


# ---------------------------------------------------------------------------
# 1. Module import is safe when crawl4ai is absent
# ---------------------------------------------------------------------------


def test_module_imports_without_crawl4ai(monkeypatch):
    """The module must be importable even when crawl4ai is not installed."""
    # Remove crawl4ai from sys.modules (if present) so find_spec returns None
    monkeypatch.delitem(sys.modules, "crawl4ai", raising=False)
    monkeypatch.delitem(sys.modules, "crawl4ai.async_configs", raising=False)

    # Re-import the fetcher module — must not raise
    import rogue.harvest.fetchers.crawl4ai as mod  # noqa: F401

    assert hasattr(mod, "Crawl4AIFetcher")


# ---------------------------------------------------------------------------
# 2. Conformance
# ---------------------------------------------------------------------------


def test_conforms():
    """assert_conforms must pass for the structural contract."""
    from rogue.harvest.fetchers.conformance import assert_conforms

    from rogue.harvest.fetchers.crawl4ai import Crawl4AIFetcher

    assert_conforms(Crawl4AIFetcher())


# ---------------------------------------------------------------------------
# 3. unlock — markdown format (default)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unlock_markdown(fake_crawl4ai, monkeypatch):
    mod, crawl4ai_mod, configs_mod = fake_crawl4ai

    crawl_result = _fake_crawl_result(
        html="<html><body><h1>Test</h1></body></html>",
        cleaned_html="<body><h1>Test</h1></body>",
        markdown_raw="# Test",
        status_code=200,
    )
    cm = _make_crawler_cm(crawl_result)
    crawl4ai_mod.AsyncWebCrawler = MagicMock(return_value=cm)

    from rogue.harvest.fetchers.crawl4ai import Crawl4AIFetcher

    fetcher = Crawl4AIFetcher()
    page = await fetcher.unlock("https://example.com")

    assert page.url == "https://example.com"
    assert page.content == "# Test"
    assert page.content_format == "markdown"
    assert page.status_code == 200
    assert isinstance(page.fetched_at, datetime)
    assert page.fetched_at.tzinfo is not None


@pytest.mark.asyncio
async def test_unlock_html_format(fake_crawl4ai, monkeypatch):
    mod, crawl4ai_mod, configs_mod = fake_crawl4ai

    raw_html = "<html><body><p>Hello world</p></body></html>"
    crawl_result = _fake_crawl_result(html=raw_html)
    cm = _make_crawler_cm(crawl_result)
    crawl4ai_mod.AsyncWebCrawler = MagicMock(return_value=cm)

    from rogue.harvest.fetchers.crawl4ai import Crawl4AIFetcher

    fetcher = Crawl4AIFetcher()
    page = await fetcher.unlock("https://example.com", format="html")

    assert page.content == raw_html
    assert page.content_format == "html"


@pytest.mark.asyncio
async def test_unlock_raises_on_failure(fake_crawl4ai):
    mod, crawl4ai_mod, configs_mod = fake_crawl4ai

    crawl_result = _fake_crawl_result(success=False, error_message="navigation timeout")
    cm = _make_crawler_cm(crawl_result)
    crawl4ai_mod.AsyncWebCrawler = MagicMock(return_value=cm)

    from rogue.harvest.fetchers.crawl4ai import Crawl4AIFetcher

    with pytest.raises(RuntimeError, match="navigation timeout"):
        await Crawl4AIFetcher().unlock("https://example.com")


@pytest.mark.asyncio
async def test_unlock_fallback_when_markdown_is_none(fake_crawl4ai):
    """When result.markdown is None, fall back to stripping the html."""
    mod, crawl4ai_mod, configs_mod = fake_crawl4ai

    crawl_result = _fake_crawl_result(html="<p>Fallback text</p>")
    crawl_result.markdown = None  # simulate missing markdown
    cm = _make_crawler_cm(crawl_result)
    crawl4ai_mod.AsyncWebCrawler = MagicMock(return_value=cm)

    from rogue.harvest.fetchers.crawl4ai import Crawl4AIFetcher

    page = await Crawl4AIFetcher().unlock("https://example.com", format="markdown")
    # HTML-stripped fallback should contain the visible text
    assert "Fallback text" in page.content


# ---------------------------------------------------------------------------
# 4. browser — ScrapedPage mapping + wait_for + scroll_pages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_browser_returns_scraped_page(fake_crawl4ai):
    mod, crawl4ai_mod, configs_mod = fake_crawl4ai

    html = "<html><body>Rendered content</body></html>"
    cleaned = "<body>Rendered content</body>"
    crawl_result = _fake_crawl_result(html=html, cleaned_html=cleaned)
    cm = _make_crawler_cm(crawl_result)
    crawl4ai_mod.AsyncWebCrawler = MagicMock(return_value=cm)

    from rogue.harvest.fetchers.crawl4ai import Crawl4AIFetcher

    page = await Crawl4AIFetcher().browser("https://example.com")

    assert page.url == "https://example.com"
    assert page.html == html
    assert "Rendered content" in page.rendered_text
    assert isinstance(page.fetched_at, datetime)
    assert page.fetched_at.tzinfo is not None


@pytest.mark.asyncio
async def test_browser_wait_for_selector(fake_crawl4ai):
    """wait_for_selector must translate to CrawlerRunConfig(wait_for='css:<selector>')."""
    mod, crawl4ai_mod, configs_mod = fake_crawl4ai

    captured_configs: list[Any] = []
    original_config_cls = configs_mod.CrawlerRunConfig

    class CapturingConfig(original_config_cls):  # type: ignore[valid-type]
        def __init__(self, **kwargs: Any) -> None:
            captured_configs.append(kwargs)
            super().__init__(**kwargs)

    configs_mod.CrawlerRunConfig = CapturingConfig

    cm = _make_crawler_cm(_fake_crawl_result())
    crawl4ai_mod.AsyncWebCrawler = MagicMock(return_value=cm)

    from rogue.harvest.fetchers.crawl4ai import Crawl4AIFetcher

    await Crawl4AIFetcher().browser("https://example.com", wait_for_selector=".my-class")

    assert len(captured_configs) == 1
    assert captured_configs[0].get("wait_for") == "css:.my-class"


@pytest.mark.asyncio
async def test_browser_scroll_pages_emits_js(fake_crawl4ai):
    """scroll_pages > 1 must add a js_code scroll snippet to CrawlerRunConfig."""
    mod, crawl4ai_mod, configs_mod = fake_crawl4ai

    captured_configs: list[Any] = []
    original_config_cls = configs_mod.CrawlerRunConfig

    class CapturingConfig(original_config_cls):  # type: ignore[valid-type]
        def __init__(self, **kwargs: Any) -> None:
            captured_configs.append(kwargs)
            super().__init__(**kwargs)

    configs_mod.CrawlerRunConfig = CapturingConfig

    cm = _make_crawler_cm(_fake_crawl_result())
    crawl4ai_mod.AsyncWebCrawler = MagicMock(return_value=cm)

    from rogue.harvest.fetchers.crawl4ai import Crawl4AIFetcher

    await Crawl4AIFetcher().browser("https://example.com", scroll_pages=3)

    assert len(captured_configs) == 1
    js = captured_configs[0].get("js_code", "")
    assert "scrollBy" in js
    # scroll_pages=3 → 2 extra scrolls
    assert "2" in js


@pytest.mark.asyncio
async def test_browser_scroll_pages_1_no_js(fake_crawl4ai):
    """scroll_pages=1 (default) must NOT add js_code."""
    mod, crawl4ai_mod, configs_mod = fake_crawl4ai

    captured_configs: list[Any] = []
    original_config_cls = configs_mod.CrawlerRunConfig

    class CapturingConfig(original_config_cls):  # type: ignore[valid-type]
        def __init__(self, **kwargs: Any) -> None:
            captured_configs.append(kwargs)
            super().__init__(**kwargs)

    configs_mod.CrawlerRunConfig = CapturingConfig

    cm = _make_crawler_cm(_fake_crawl_result())
    crawl4ai_mod.AsyncWebCrawler = MagicMock(return_value=cm)

    from rogue.harvest.fetchers.crawl4ai import Crawl4AIFetcher

    await Crawl4AIFetcher().browser("https://example.com", scroll_pages=1)

    assert "js_code" not in captured_configs[0]


@pytest.mark.asyncio
async def test_browser_raises_on_failure(fake_crawl4ai):
    mod, crawl4ai_mod, configs_mod = fake_crawl4ai

    cm = _make_crawler_cm(_fake_crawl_result(success=False, error_message="ERR_NAME_NOT_RESOLVED"))
    crawl4ai_mod.AsyncWebCrawler = MagicMock(return_value=cm)

    from rogue.harvest.fetchers.crawl4ai import Crawl4AIFetcher

    with pytest.raises(RuntimeError, match="ERR_NAME_NOT_RESOLVED"):
        await Crawl4AIFetcher().browser("https://doesnotexist.invalid")


@pytest.mark.asyncio
async def test_browser_storage_state_warns(fake_crawl4ai, caplog):
    """Passing storage_state must emit a warning (not crash)."""
    import logging

    mod, crawl4ai_mod, configs_mod = fake_crawl4ai

    cm = _make_crawler_cm(_fake_crawl_result())
    crawl4ai_mod.AsyncWebCrawler = MagicMock(return_value=cm)

    from rogue.harvest.fetchers.crawl4ai import Crawl4AIFetcher

    with caplog.at_level(logging.WARNING, logger="rogue.harvest.fetchers.crawl4ai"):
        page = await Crawl4AIFetcher().browser(
            "https://example.com",
            storage_state={"cookies": [], "origins": []},
        )

    assert page is not None  # returned normally
    assert any("storage_state" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 5. is_available
# ---------------------------------------------------------------------------


def test_is_available_true_when_both_present(monkeypatch):
    """is_available() returns True when crawl4ai + playwright (with chromium) are present."""
    # Inject a minimal crawl4ai stub
    crawl4ai_stub = types.ModuleType("crawl4ai")
    monkeypatch.setitem(sys.modules, "crawl4ai", crawl4ai_stub)

    # Mock importlib.util.find_spec to return a truthy spec for both packages
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name: str):
        if name in ("crawl4ai", "playwright"):
            return MagicMock()  # truthy
        return real_find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    # Mock sync_playwright so the chromium path check succeeds
    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.executable_path = "/usr/bin/chromium"
    mock_sync_pw = MagicMock()
    mock_sync_pw.__enter__ = MagicMock(return_value=mock_pw_instance)
    mock_sync_pw.__exit__ = MagicMock(return_value=False)

    playwright_mod = types.ModuleType("playwright")
    sync_api_mod = types.ModuleType("playwright.sync_api")
    sync_api_mod.sync_playwright = MagicMock(return_value=mock_sync_pw)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", playwright_mod)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api_mod)

    from rogue.harvest.fetchers.crawl4ai import Crawl4AIFetcher

    assert Crawl4AIFetcher.is_available() is True


def test_is_available_false_when_crawl4ai_absent(monkeypatch):
    """is_available() returns False when crawl4ai is not installed."""
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name: str):
        if name == "crawl4ai":
            return None  # not installed
        return real_find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    from rogue.harvest.fetchers.crawl4ai import Crawl4AIFetcher

    assert Crawl4AIFetcher.is_available() is False


def test_is_available_false_when_playwright_absent(monkeypatch):
    """is_available() returns False when playwright is not installed (even if crawl4ai is)."""
    crawl4ai_stub = types.ModuleType("crawl4ai")
    monkeypatch.setitem(sys.modules, "crawl4ai", crawl4ai_stub)

    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name: str):
        if name == "crawl4ai":
            return MagicMock()  # present
        if name == "playwright":
            return None  # absent
        return real_find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    from rogue.harvest.fetchers.crawl4ai import Crawl4AIFetcher

    assert Crawl4AIFetcher.is_available() is False


def test_is_available_false_when_chromium_not_installed(monkeypatch):
    """is_available() returns False when chromium binary is missing (executable_path raises)."""
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name: str):
        if name in ("crawl4ai", "playwright"):
            return MagicMock()
        return real_find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    # sync_playwright raises when chromium isn't installed
    mock_pw_instance = MagicMock()
    type(mock_pw_instance.chromium).executable_path = property(
        lambda self: (_ for _ in ()).throw(Exception("Chromium not found"))
    )
    mock_sync_pw = MagicMock()
    mock_sync_pw.__enter__ = MagicMock(return_value=mock_pw_instance)
    mock_sync_pw.__exit__ = MagicMock(return_value=False)

    sync_api_mod = types.ModuleType("playwright.sync_api")
    sync_api_mod.sync_playwright = MagicMock(return_value=mock_sync_pw)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api_mod)

    playwright_mod = types.ModuleType("playwright")
    monkeypatch.setitem(sys.modules, "playwright", playwright_mod)

    from rogue.harvest.fetchers.crawl4ai import Crawl4AIFetcher

    assert Crawl4AIFetcher.is_available() is False


# ---------------------------------------------------------------------------
# 6. unlock: raises ImportError when crawl4ai absent at call time
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unlock_importerror_when_absent(monkeypatch):
    """unlock() raises ImportError (not a crash) when crawl4ai is not installed."""
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name: str):
        if name == "crawl4ai":
            return None
        return real_find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    # Remove from sys.modules too to prevent stale import
    monkeypatch.delitem(sys.modules, "crawl4ai", raising=False)
    monkeypatch.delitem(sys.modules, "crawl4ai.async_configs", raising=False)

    from rogue.harvest.fetchers.crawl4ai import Crawl4AIFetcher

    with pytest.raises(ImportError, match="crawl4ai"):
        await Crawl4AIFetcher().unlock("https://example.com")


@pytest.mark.asyncio
async def test_browser_importerror_when_absent(monkeypatch):
    """browser() raises ImportError (not a crash) when crawl4ai is not installed."""
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name: str):
        if name == "crawl4ai":
            return None
        return real_find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    monkeypatch.delitem(sys.modules, "crawl4ai", raising=False)
    monkeypatch.delitem(sys.modules, "crawl4ai.async_configs", raising=False)

    from rogue.harvest.fetchers.crawl4ai import Crawl4AIFetcher

    with pytest.raises(ImportError, match="crawl4ai"):
        await Crawl4AIFetcher().browser("https://example.com")


# ---------------------------------------------------------------------------
# 7. aclose is a no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aclose_noop():
    from rogue.harvest.fetchers.crawl4ai import Crawl4AIFetcher

    fetcher = Crawl4AIFetcher()
    await fetcher.aclose()  # must not raise


# ---------------------------------------------------------------------------
# 8. Capability + name identity
# ---------------------------------------------------------------------------


def test_name_and_capabilities():
    from rogue.harvest.fetchers.capabilities import Capability

    from rogue.harvest.fetchers.crawl4ai import Crawl4AIFetcher

    f = Crawl4AIFetcher()
    assert f.name == "crawl4ai"
    assert Capability.UNLOCK in f.capabilities
    assert Capability.BROWSER in f.capabilities
    assert isinstance(f.capabilities, frozenset)
