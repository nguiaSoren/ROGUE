"""Unit tests for :class:`FirecrawlFetcher`.

All HTTP calls are mocked — no real network required. Tests cover:

  1. ``is_available()`` env-var gating (no key, base-URL only, API-key only, both,
     and the opt-in ``FIRECRAWL_KEYLESS`` free tier).
  2. ``unlock()`` — markdown and html format; UnlockedPage field mapping.
  2b. ``serp()`` — /v1/search result mapping + degrade-safe empty on error.
  3. ``browser()`` — ScrapedPage field mapping; waitFor passthrough;
     scroll_pages + storage_state silently ignored with warnings.
  4. ``_post_scrape()`` error paths — HTTP 4xx and ``success: false``.
  5. ``assert_conforms`` structural conformance.
  6. ``aclose()`` idempotency.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from rogue.harvest.fetchers.firecrawl import FirecrawlFetcher
from rogue.harvest.fetchers.conformance import assert_conforms
from rogue.harvest.bright_data_client import UnlockedPage, ScrapedPage


# ---------------------------------------------------------------------------
# Helpers — build a minimal Firecrawl /v1/scrape response
# ---------------------------------------------------------------------------

def _firecrawl_response(
    *,
    markdown: str = "# Hello\n\nSome text.",
    html: str = "<h1>Hello</h1><p>Some text.</p>",
    status_code: int = 200,
    source_url: str = "https://example.com/page",
    success: bool = True,
    error: str | None = None,
) -> dict[str, Any]:
    if not success:
        return {"success": False, "error": error or "scrape failed"}
    return {
        "success": True,
        "data": {
            "markdown": markdown,
            "html": html,
            "rawHtml": html,
            "links": [],
            "metadata": {
                "title": "Example Page",
                "statusCode": status_code,
                "sourceURL": source_url,
                "url": source_url,
                "contentType": "text/html",
                "error": None,
            },
        },
    }


def _mock_http_response(
    body: dict[str, Any],
    status: int = 200,
) -> MagicMock:
    """Return a mock httpx.Response that delivers ``body`` as JSON."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.json.return_value = body
    if status >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status}",
            request=MagicMock(),
            response=resp,
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# is_available() — env-var gating
# ---------------------------------------------------------------------------

class TestIsAvailable:
    def test_no_env_vars(self, monkeypatch):
        monkeypatch.delenv("FIRECRAWL_BASE_URL", raising=False)
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        monkeypatch.delenv("FIRECRAWL_KEYLESS", raising=False)
        assert FirecrawlFetcher.is_available() is False

    def test_keyless_flag_makes_available(self, monkeypatch):
        # Opt-in keyless free tier: no key/URL, just FIRECRAWL_KEYLESS=1.
        monkeypatch.delenv("FIRECRAWL_BASE_URL", raising=False)
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        monkeypatch.setenv("FIRECRAWL_KEYLESS", "1")
        assert FirecrawlFetcher.is_available() is True
        # Keyless → cloud base, no api key → _get_http() adds no Authorization header.
        fc = FirecrawlFetcher()
        assert fc._base_url == "https://api.firecrawl.dev"
        assert fc._api_key is None

    def test_keyless_falsey_value_not_available(self, monkeypatch):
        monkeypatch.delenv("FIRECRAWL_BASE_URL", raising=False)
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        monkeypatch.setenv("FIRECRAWL_KEYLESS", "0")
        assert FirecrawlFetcher.is_available() is False

    def test_base_url_only(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_BASE_URL", "http://localhost:3002")
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        assert FirecrawlFetcher.is_available() is True

    def test_api_key_only(self, monkeypatch):
        monkeypatch.delenv("FIRECRAWL_BASE_URL", raising=False)
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-testkey123")
        assert FirecrawlFetcher.is_available() is True

    def test_both_set(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_BASE_URL", "http://localhost:3002")
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-testkey123")
        assert FirecrawlFetcher.is_available() is True

    def test_empty_strings_not_available(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_BASE_URL", "  ")
        monkeypatch.setenv("FIRECRAWL_API_KEY", "")
        assert FirecrawlFetcher.is_available() is False


# ---------------------------------------------------------------------------
# Constructor — base URL + auth header selection
# ---------------------------------------------------------------------------

class TestConstructor:
    def test_self_hosted_uses_base_url(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_BASE_URL", "http://localhost:3002")
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        fc = FirecrawlFetcher()
        assert fc._base_url == "http://localhost:3002"
        assert fc._api_key is None

    def test_cloud_uses_cloud_base(self, monkeypatch):
        monkeypatch.delenv("FIRECRAWL_BASE_URL", raising=False)
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-key")
        fc = FirecrawlFetcher()
        assert fc._base_url == "https://api.firecrawl.dev"
        assert fc._api_key == "fc-key"

    def test_base_url_wins_over_key(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_BASE_URL", "http://firecrawl.internal:3002")
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-key")
        fc = FirecrawlFetcher()
        assert fc._base_url == "http://firecrawl.internal:3002"
        # key is still stored (self-hosted may optionally require it)
        assert fc._api_key == "fc-key"

    def test_trailing_slash_stripped(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_BASE_URL", "http://localhost:3002/")
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        fc = FirecrawlFetcher()
        assert fc._base_url == "http://localhost:3002"


# ---------------------------------------------------------------------------
# unlock() — UnlockedPage field mapping
# ---------------------------------------------------------------------------

class TestUnlock:
    @pytest.fixture
    def fetcher(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_BASE_URL", "http://localhost:3002")
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        return FirecrawlFetcher()

    async def _call_unlock(self, fetcher: FirecrawlFetcher, url: str, format: str, body: dict) -> UnlockedPage:
        mock_resp = _mock_http_response(body)
        mock_post = AsyncMock(return_value=mock_resp)
        with patch.object(fetcher._get_http(), "post", mock_post):
            return await fetcher.unlock(url, format=format)

    @pytest.mark.asyncio
    async def test_unlock_markdown_format(self, fetcher):
        url = "https://example.com/page"
        body = _firecrawl_response(
            markdown="# Title\n\nBody text.",
            html="<h1>Title</h1><p>Body text.</p>",
            status_code=200,
            source_url=url,
        )
        # Inject mock at the client level
        mock_resp = _mock_http_response(body)
        mock_post = AsyncMock(return_value=mock_resp)
        # Force lazy init then patch
        _ = fetcher._get_http()
        with patch.object(fetcher._http, "post", mock_post):
            page = await fetcher.unlock(url, format="markdown")

        assert isinstance(page, UnlockedPage)
        assert page.url == url
        assert page.content == "# Title\n\nBody text."
        assert page.content_format == "markdown"
        assert page.status_code == 200
        assert isinstance(page.fetched_at, datetime)
        # Verify the /v1/scrape path and payload
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[0][0] == "/v1/scrape"
        payload = call_kwargs[1]["json"]
        assert payload["url"] == url
        assert "markdown" in payload["formats"]
        assert "html" in payload["formats"]

    @pytest.mark.asyncio
    async def test_unlock_html_format(self, fetcher):
        url = "https://example.com/page"
        body = _firecrawl_response(
            markdown="# Title",
            html="<h1>Title</h1>",
            status_code=200,
            source_url=url,
        )
        mock_resp = _mock_http_response(body)
        mock_post = AsyncMock(return_value=mock_resp)
        _ = fetcher._get_http()
        with patch.object(fetcher._http, "post", mock_post):
            page = await fetcher.unlock(url, format="html")

        assert page.content == "<h1>Title</h1>"
        assert page.content_format == "html"

    @pytest.mark.asyncio
    async def test_unlock_uses_source_url_from_metadata(self, fetcher):
        original_url = "https://short.url/abc"
        final_url = "https://example.com/full-page"
        body = _firecrawl_response(source_url=final_url)
        mock_resp = _mock_http_response(body)
        mock_post = AsyncMock(return_value=mock_resp)
        _ = fetcher._get_http()
        with patch.object(fetcher._http, "post", mock_post):
            page = await fetcher.unlock(original_url, format="markdown")

        assert page.url == final_url

    @pytest.mark.asyncio
    async def test_unlock_fallback_to_input_url_when_no_source_url(self, fetcher):
        url = "https://example.com/page"
        # Metadata without sourceURL or url
        body = {
            "success": True,
            "data": {
                "markdown": "content",
                "html": "<p>content</p>",
                "metadata": {"statusCode": 200},
            },
        }
        mock_resp = _mock_http_response(body)
        mock_post = AsyncMock(return_value=mock_resp)
        _ = fetcher._get_http()
        with patch.object(fetcher._http, "post", mock_post):
            page = await fetcher.unlock(url)

        assert page.url == url

    @pytest.mark.asyncio
    async def test_unlock_invalid_format_raises(self, fetcher):
        with pytest.raises(ValueError, match="unsupported format"):
            await fetcher.unlock("https://example.com", format="pdf")

    @pytest.mark.asyncio
    async def test_unlock_success_false_raises_runtime_error(self, fetcher):
        body = _firecrawl_response(success=False, error="Rate limit exceeded")
        mock_resp = _mock_http_response(body, status=200)
        mock_post = AsyncMock(return_value=mock_resp)
        _ = fetcher._get_http()
        with patch.object(fetcher._http, "post", mock_post):
            with pytest.raises(RuntimeError, match="success=false"):
                await fetcher.unlock("https://example.com")

    @pytest.mark.asyncio
    async def test_unlock_http_error_propagates(self, fetcher):
        mock_resp = _mock_http_response({}, status=429)
        mock_post = AsyncMock(return_value=mock_resp)
        _ = fetcher._get_http()
        with patch.object(fetcher._http, "post", mock_post):
            with pytest.raises(httpx.HTTPStatusError):
                await fetcher.unlock("https://example.com")


# ---------------------------------------------------------------------------
# browser() — ScrapedPage field mapping
# ---------------------------------------------------------------------------

class TestBrowser:
    @pytest.fixture
    def fetcher(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-testkey")
        monkeypatch.delenv("FIRECRAWL_BASE_URL", raising=False)
        return FirecrawlFetcher()

    @pytest.mark.asyncio
    async def test_browser_scraped_page_fields(self, fetcher):
        url = "https://example.com/spa"
        body = _firecrawl_response(
            markdown="Rendered text extracted from JS page.",
            html="<html><body><h1>JS Page</h1></body></html>",
            source_url=url,
        )
        mock_resp = _mock_http_response(body)
        mock_post = AsyncMock(return_value=mock_resp)
        _ = fetcher._get_http()
        with patch.object(fetcher._http, "post", mock_post):
            page = await fetcher.browser(url)

        assert isinstance(page, ScrapedPage)
        assert page.url == url
        assert page.html == "<html><body><h1>JS Page</h1></body></html>"
        assert page.rendered_text == "Rendered text extracted from JS page."
        assert isinstance(page.fetched_at, datetime)

    @pytest.mark.asyncio
    async def test_browser_passes_wait_for_selector(self, fetcher):
        url = "https://example.com/spa"
        body = _firecrawl_response(source_url=url)
        mock_resp = _mock_http_response(body)
        mock_post = AsyncMock(return_value=mock_resp)
        _ = fetcher._get_http()
        with patch.object(fetcher._http, "post", mock_post):
            await fetcher.browser(url, wait_for_selector=".content-ready")

        call_kwargs = mock_post.call_args
        payload = call_kwargs[1]["json"]
        assert payload.get("waitFor") == ".content-ready"

    @pytest.mark.asyncio
    async def test_browser_no_wait_for_when_none(self, fetcher):
        url = "https://example.com/page"
        body = _firecrawl_response(source_url=url)
        mock_resp = _mock_http_response(body)
        mock_post = AsyncMock(return_value=mock_resp)
        _ = fetcher._get_http()
        with patch.object(fetcher._http, "post", mock_post):
            await fetcher.browser(url, wait_for_selector=None)

        call_kwargs = mock_post.call_args
        payload = call_kwargs[1]["json"]
        assert "waitFor" not in payload

    @pytest.mark.asyncio
    async def test_browser_scroll_pages_ignored_with_debug_log(self, fetcher, caplog):
        url = "https://example.com/page"
        body = _firecrawl_response(source_url=url)
        mock_resp = _mock_http_response(body)
        mock_post = AsyncMock(return_value=mock_resp)
        _ = fetcher._get_http()
        with caplog.at_level(logging.DEBUG, logger="rogue.harvest.fetchers.firecrawl"):
            with patch.object(fetcher._http, "post", mock_post):
                await fetcher.browser(url, scroll_pages=3)
        assert "scroll_pages" in caplog.text

    @pytest.mark.asyncio
    async def test_browser_storage_state_ignored_with_warning(self, fetcher, caplog):
        url = "https://example.com/page"
        body = _firecrawl_response(source_url=url)
        mock_resp = _mock_http_response(body)
        mock_post = AsyncMock(return_value=mock_resp)
        _ = fetcher._get_http()
        with caplog.at_level(logging.WARNING, logger="rogue.harvest.fetchers.firecrawl"):
            with patch.object(fetcher._http, "post", mock_post):
                await fetcher.browser(url, storage_state={"cookies": []})
        assert "storage_state" in caplog.text

    @pytest.mark.asyncio
    async def test_browser_success_false_raises(self, fetcher):
        body = _firecrawl_response(success=False, error="blocked")
        mock_resp = _mock_http_response(body)
        mock_post = AsyncMock(return_value=mock_resp)
        _ = fetcher._get_http()
        with patch.object(fetcher._http, "post", mock_post):
            with pytest.raises(RuntimeError, match="success=false"):
                await fetcher.browser("https://example.com")


# ---------------------------------------------------------------------------
# Auth header — cloud vs self-hosted
# ---------------------------------------------------------------------------

class TestAuthHeader:
    def test_cloud_http_client_has_bearer_header(self, monkeypatch):
        monkeypatch.delenv("FIRECRAWL_BASE_URL", raising=False)
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-secret")
        fc = FirecrawlFetcher()
        client = fc._get_http()
        auth_header = client.headers.get("authorization", "")
        assert auth_header == "Bearer fc-secret"

    def test_self_hosted_no_key_no_auth_header(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_BASE_URL", "http://localhost:3002")
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        fc = FirecrawlFetcher()
        client = fc._get_http()
        # No Authorization header when self-hosted without a key
        assert "authorization" not in client.headers


# ---------------------------------------------------------------------------
# aclose() — idempotency
# ---------------------------------------------------------------------------

class TestAclose:
    @pytest.mark.asyncio
    async def test_aclose_idempotent(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_BASE_URL", "http://localhost:3002")
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        fc = FirecrawlFetcher()
        _ = fc._get_http()  # force init
        assert fc._http is not None
        await fc.aclose()
        assert fc._http is None
        # Second close is a no-op (must not raise)
        await fc.aclose()
        assert fc._http is None

    @pytest.mark.asyncio
    async def test_aclose_before_init_is_noop(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_BASE_URL", "http://localhost:3002")
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        fc = FirecrawlFetcher()
        # Never called _get_http(); _http is None — must not raise
        await fc.aclose()


# ---------------------------------------------------------------------------
# Conformance — structural check (no network)
# ---------------------------------------------------------------------------

class TestConformance:
    def test_assert_conforms_passes(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_BASE_URL", "http://localhost:3002")
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        fc = FirecrawlFetcher()
        report = assert_conforms(fc)
        assert report.passed, str(report)


# ---------------------------------------------------------------------------
# serp() — Firecrawl /v1/search (keyless-capable)
# ---------------------------------------------------------------------------

class TestSerp:
    @pytest.fixture
    def fetcher(self, monkeypatch):
        # Exercise the keyless mode end-to-end.
        monkeypatch.delenv("FIRECRAWL_BASE_URL", raising=False)
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        monkeypatch.setenv("FIRECRAWL_KEYLESS", "1")
        return FirecrawlFetcher()

    def test_serp_in_capabilities(self):
        from rogue.harvest.fetchers.capabilities import Capability

        assert Capability.SERP in FirecrawlFetcher.capabilities

    @pytest.mark.asyncio
    async def test_serp_maps_results(self, fetcher):
        body = {
            "success": True,
            "data": [
                {"url": "https://a.com", "title": "A", "description": "da"},
                {"url": "https://b.com", "title": "B", "description": "db"},
            ],
        }
        mock_post = AsyncMock(return_value=_mock_http_response(body))
        with patch.object(fetcher._get_http(), "post", mock_post):
            resp = await fetcher.serp("prompt injection", count=2)

        assert resp.engine == "firecrawl"
        assert [r["link"] for r in resp.organic_results] == ["https://a.com", "https://b.com"]
        assert resp.organic_results[0]["url"] == "https://a.com"
        assert resp.organic_results[0]["title"] == "A"
        # Hit the search endpoint with the query + limit.
        assert mock_post.call_args.args[0] == "/v1/search"
        assert mock_post.call_args.kwargs["json"]["query"] == "prompt injection"
        assert mock_post.call_args.kwargs["json"]["limit"] == 2

    @pytest.mark.asyncio
    async def test_serp_degrades_to_empty_on_success_false(self, fetcher):
        mock_post = AsyncMock(return_value=_mock_http_response({"success": False, "error": "boom"}))
        with patch.object(fetcher._get_http(), "post", mock_post):
            resp = await fetcher.serp("q")
        assert resp.organic_results == []
        assert resp.engine == "firecrawl"

    @pytest.mark.asyncio
    async def test_serp_degrades_to_empty_on_http_error(self, fetcher):
        mock_post = AsyncMock(return_value=_mock_http_response({}, status=429))
        with patch.object(fetcher._get_http(), "post", mock_post):
            resp = await fetcher.serp("q")
        assert resp.organic_results == []


# ---------------------------------------------------------------------------
# Rate-limit notification — keyless 429 telemetry + one-time actionable notice
# ---------------------------------------------------------------------------

class TestRateLimitNotice:
    @pytest.fixture(autouse=True)
    def _reset(self):
        FirecrawlFetcher.rate_limited_count = 0
        FirecrawlFetcher._rate_limit_notified = False
        yield
        FirecrawlFetcher.rate_limited_count = 0
        FirecrawlFetcher._rate_limit_notified = False

    @pytest.fixture
    def fetcher(self, monkeypatch):
        monkeypatch.delenv("FIRECRAWL_BASE_URL", raising=False)
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        monkeypatch.setenv("FIRECRAWL_KEYLESS", "1")
        return FirecrawlFetcher()

    @pytest.mark.asyncio
    async def test_429_on_unlock_counts_and_raises(self, fetcher):
        mock_post = AsyncMock(return_value=_mock_http_response({}, status=429))
        with patch.object(fetcher._get_http(), "post", mock_post):
            with pytest.raises(httpx.HTTPStatusError):
                await fetcher.unlock("https://x.com/p")
        assert FirecrawlFetcher.rate_limited_count == 1

    @pytest.mark.asyncio
    async def test_429_notice_emitted_once(self, fetcher, caplog):
        mock_post = AsyncMock(return_value=_mock_http_response({}, status=429))
        with caplog.at_level(logging.WARNING):
            with patch.object(fetcher._get_http(), "post", mock_post):
                for _ in range(3):
                    with pytest.raises(httpx.HTTPStatusError):
                        await fetcher.unlock("https://x.com/p")
        assert FirecrawlFetcher.rate_limited_count == 3  # counts every hit
        notices = [r for r in caplog.records if "rate limit reached" in r.getMessage().lower()]
        assert len(notices) == 1  # but the notice is deduped to once per process

    @pytest.mark.asyncio
    async def test_serp_429_counts_and_returns_empty(self, fetcher):
        mock_post = AsyncMock(return_value=_mock_http_response({}, status=429))
        with patch.object(fetcher._get_http(), "post", mock_post):
            resp = await fetcher.serp("q")
        assert resp.organic_results == []
        assert FirecrawlFetcher.rate_limited_count == 1
