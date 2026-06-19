"""Unit tests for :class:`~rogue.harvest.fetchers.direct.DirectFetcher`.

All network I/O is mocked — no real HTTP calls are made.  Tests cover:
  - ``is_available()`` class method
  - ``unlock()`` for both ``format="markdown"`` and ``format="html"``
  - ``unlock()`` HTML→markdown conversion (minimal tag-strip path)
  - ``unlock()`` propagates HTTP errors (``raise_for_status``)
  - ``fetch_image_bytes()`` happy path + error propagation
  - ``resolve_redirect()`` happy-path (HEAD redirect + GET fallback)
  - ``resolve_redirect()`` degrades to input on network error
  - ``assert_conforms(DirectFetcher())`` structural conformance
  - ``aclose()`` is idempotent
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from rogue.harvest.bright_data_client import UnlockedPage
from rogue.harvest.fetchers.capabilities import Capability, CapabilityNotSupported
from rogue.harvest.fetchers.conformance import assert_conforms
from rogue.harvest.fetchers.direct import DirectFetcher, _html_to_markdown


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(
    *,
    status_code: int = 200,
    text: str = "",
    content: bytes = b"",
    content_type: str = "text/html; charset=utf-8",
    final_url: str = "https://example.com/final",
) -> MagicMock:
    """Build a minimal ``httpx.Response``-like mock."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    resp.content = content or text.encode()
    resp.headers = {"content-type": content_type}
    resp.url = httpx.URL(final_url)
    resp.raise_for_status = MagicMock()  # no-op for 2xx
    return resp


def _mock_error_response(status_code: int = 403) -> MagicMock:
    resp = _mock_response(status_code=status_code)
    error = httpx.HTTPStatusError(
        f"{status_code}",
        request=MagicMock(),
        response=resp,
    )
    resp.raise_for_status = MagicMock(side_effect=error)
    return resp


# ---------------------------------------------------------------------------
# Conformance (structural, no network)
# ---------------------------------------------------------------------------

def test_conformance():
    """DirectFetcher must pass the full structural conformance suite."""
    fetcher = DirectFetcher()
    report = assert_conforms(fetcher)
    assert report.passed, str(report)


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------

def test_is_available():
    assert DirectFetcher.is_available() is True


# ---------------------------------------------------------------------------
# capability set
# ---------------------------------------------------------------------------

def test_capabilities_declared():
    f = DirectFetcher()
    assert Capability.UNLOCK in f.capabilities
    assert Capability.IMAGE_BYTES in f.capabilities
    assert Capability.REDIRECT in f.capabilities
    # must NOT declare unsupported capabilities
    assert Capability.SERP not in f.capabilities
    assert Capability.BROWSER not in f.capabilities
    assert Capability.REDDIT not in f.capabilities
    assert Capability.X not in f.capabilities
    assert Capability.HF not in f.capabilities
    assert Capability.SERP_IMAGE not in f.capabilities


# ---------------------------------------------------------------------------
# Undeclared capabilities raise CapabilityNotSupported
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_undeclared_serp_raises():
    f = DirectFetcher()
    with pytest.raises(CapabilityNotSupported) as exc_info:
        await f.serp("probe")
    assert exc_info.value.backend_name == "direct"
    assert exc_info.value.capability == Capability.SERP


@pytest.mark.asyncio
async def test_undeclared_browser_raises():
    f = DirectFetcher()
    with pytest.raises(CapabilityNotSupported) as exc_info:
        await f.browser("https://example.invalid")
    assert exc_info.value.backend_name == "direct"
    assert exc_info.value.capability == Capability.BROWSER


# ---------------------------------------------------------------------------
# html_to_markdown unit (no network)
# ---------------------------------------------------------------------------

def test_html_to_markdown_strips_tags():
    html = "<html><body><h1>Hello</h1><p>World</p></body></html>"
    result = _html_to_markdown(html)
    assert "Hello" in result
    assert "World" in result
    assert "<h1>" not in result
    assert "<p>" not in result


def test_html_to_markdown_skips_script():
    html = "<body><script>evil()</script><p>Good text</p></body>"
    result = _html_to_markdown(html)
    assert "evil" not in result
    assert "Good text" in result


def test_html_to_markdown_collapses_whitespace():
    html = "<p>A  B\n\n\nC</p>"
    result = _html_to_markdown(html)
    # Multiple spaces / newlines collapsed
    assert "A B" in result or "A  B" not in result


def test_html_to_markdown_malformed_fallback():
    """Malformed HTML must not raise — degrade to tag-strip regex."""
    html = "<<<bad>>><p>Still readable</p>"
    result = _html_to_markdown(html)
    assert "Still readable" in result


# ---------------------------------------------------------------------------
# unlock — happy path (markdown)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unlock_markdown_returns_unlocked_page():
    html_body = "<html><body><h1>Title</h1><p>Content</p></body></html>"
    mock_resp = _mock_response(
        text=html_body,
        final_url="https://example.com/page",
    )

    fetcher = DirectFetcher()
    with patch.object(fetcher, "_get_http") as mock_get_http:
        client = AsyncMock()
        client.get = AsyncMock(return_value=mock_resp)
        mock_get_http.return_value = client

        result = await fetcher.unlock("https://example.com/page", format="markdown")

    assert isinstance(result, UnlockedPage)
    assert result.url == "https://example.com/page"  # post-redirect URL from mock
    assert result.content_format == "markdown"
    assert result.status_code == 200
    assert "Title" in result.content
    assert "Content" in result.content
    assert "<h1>" not in result.content
    assert isinstance(result.fetched_at, datetime)


# ---------------------------------------------------------------------------
# unlock — html format
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unlock_html_returns_raw_html():
    html_body = "<html><body><p>Raw HTML</p></body></html>"
    mock_resp = _mock_response(text=html_body, final_url="https://example.com/page")

    fetcher = DirectFetcher()
    with patch.object(fetcher, "_get_http") as mock_get_http:
        client = AsyncMock()
        client.get = AsyncMock(return_value=mock_resp)
        mock_get_http.return_value = client

        result = await fetcher.unlock("https://example.com/page", format="html")

    assert result.content_format == "html"
    assert result.content == html_body


# ---------------------------------------------------------------------------
# unlock — bad format raises ValueError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unlock_bad_format_raises():
    fetcher = DirectFetcher()
    with pytest.raises(ValueError, match="unsupported format"):
        await fetcher.unlock("https://example.com", format="pdf")


# ---------------------------------------------------------------------------
# unlock — HTTP error propagates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unlock_http_error_propagates():
    mock_resp = _mock_error_response(status_code=403)

    fetcher = DirectFetcher()
    with patch.object(fetcher, "_get_http") as mock_get_http:
        client = AsyncMock()
        client.get = AsyncMock(return_value=mock_resp)
        mock_get_http.return_value = client

        with pytest.raises(httpx.HTTPStatusError):
            await fetcher.unlock("https://example.com/blocked")


# ---------------------------------------------------------------------------
# fetch_image_bytes — happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_image_bytes_returns_bytes_and_content_type():
    image_bytes = b"\x89PNG\r\n\x1a\n"  # PNG magic bytes
    mock_resp = _mock_response(
        content=image_bytes,
        content_type="image/png",
        final_url="https://example.com/img.png",
    )

    fetcher = DirectFetcher()
    with patch.object(fetcher, "_get_http") as mock_get_http:
        client = AsyncMock()
        client.get = AsyncMock(return_value=mock_resp)
        mock_get_http.return_value = client

        data, ct = await fetcher.fetch_image_bytes("https://example.com/img.png")

    assert data == image_bytes
    assert ct == "image/png"


# ---------------------------------------------------------------------------
# fetch_image_bytes — HTTP error propagates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_image_bytes_http_error_propagates():
    mock_resp = _mock_error_response(status_code=404)

    fetcher = DirectFetcher()
    with patch.object(fetcher, "_get_http") as mock_get_http:
        client = AsyncMock()
        client.get = AsyncMock(return_value=mock_resp)
        mock_get_http.return_value = client

        with pytest.raises(httpx.HTTPStatusError):
            await fetcher.fetch_image_bytes("https://example.com/missing.png")


# ---------------------------------------------------------------------------
# resolve_redirect — happy path (HEAD succeeds)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_redirect_follows_head():
    final = "https://real-destination.example.com/article"
    mock_resp = _mock_response(status_code=200, final_url=final)

    async def fake_head(url, **kwargs):
        return mock_resp

    with patch("rogue.harvest.fetchers.direct.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        instance.head = AsyncMock(return_value=mock_resp)
        MockClient.return_value = instance

        fetcher = DirectFetcher()
        result = await fetcher.resolve_redirect("https://t.co/shortlink")

    assert result == final


# ---------------------------------------------------------------------------
# resolve_redirect — HEAD 405 → GET fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_redirect_get_fallback_on_405():
    """If HEAD returns 4xx, GET is attempted and the GET final URL is returned."""
    head_resp = _mock_response(status_code=405, final_url="https://t.co/shortlink")
    get_resp = _mock_response(status_code=200, final_url="https://real.example.com/")

    with patch("rogue.harvest.fetchers.direct.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        instance.head = AsyncMock(return_value=head_resp)
        instance.get = AsyncMock(return_value=get_resp)
        MockClient.return_value = instance

        fetcher = DirectFetcher()
        result = await fetcher.resolve_redirect("https://t.co/shortlink")

    assert result == "https://real.example.com/"


# ---------------------------------------------------------------------------
# resolve_redirect — degrade to input on network error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_redirect_degrades_on_error():
    with patch("rogue.harvest.fetchers.direct.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        instance.head = AsyncMock(side_effect=httpx.ConnectError("refused"))
        MockClient.return_value = instance

        fetcher = DirectFetcher()
        original = "https://t.co/broken"
        result = await fetcher.resolve_redirect(original)

    assert result == original


# ---------------------------------------------------------------------------
# aclose — idempotent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aclose_idempotent():
    fetcher = DirectFetcher()
    # No client created yet — aclose is a no-op.
    await fetcher.aclose()
    await fetcher.aclose()

    # Force client creation then close twice.
    _ = fetcher._get_http()
    await fetcher.aclose()
    await fetcher.aclose()
    assert fetcher._http is None
