"""Tests for the Bright Data media fetcher (§11.8) — offline, mocked BD client."""

from __future__ import annotations

import base64

import pytest

from rogue.harvest.media_fetch import BrightDataMediaFetcher

_PNG = b"\x89PNG\r\n\x1a\n" + b"fake-png-bytes"
_PNG_B64 = base64.b64encode(_PNG).decode("ascii")
_HTML = b"<html>403 forbidden</html>"


class _FakeClient:
    """Records calls; configurable search results + per-url byte responses."""

    def __init__(self, *, api_key="k", urls=None, bytes_for=None):
        self.api_key = api_key
        self._urls = urls if urls is not None else ["https://x/a.png"]
        self._bytes_for = bytes_for or {}
        self.search_calls = 0
        self.download_calls = 0

    async def serp_image_search(self, query, count=5, *, session=None):
        self.search_calls += 1
        return list(self._urls[:count])

    async def fetch_image_bytes(self, url, *, session=None):
        self.download_calls += 1
        return self._bytes_for.get(url, _PNG), "image/png"


@pytest.mark.asyncio
async def test_fetch_downloads_and_caches(tmp_path) -> None:
    client = _FakeClient(urls=["https://x/a.png"])
    f = BrightDataMediaFetcher(client, cache_dir=tmp_path)
    b64 = await f.fetch_base_image_b64("bank login screenshot")
    assert b64 == _PNG_B64
    # cached on disk as a raw image file the base_image slot can read
    cp = f.cached_path("bank login screenshot")
    assert cp is not None and cp.read_bytes() == _PNG
    assert client.search_calls == 1 and client.download_calls == 1


@pytest.mark.asyncio
async def test_cache_hit_skips_bd(tmp_path) -> None:
    client = _FakeClient()
    f = BrightDataMediaFetcher(client, cache_dir=tmp_path)
    await f.fetch_base_image_b64("meme template")          # populates cache
    calls = (client.search_calls, client.download_calls)
    again = await f.fetch_base_image_b64("meme template")   # served from disk
    assert again == _PNG_B64
    assert (client.search_calls, client.download_calls) == calls  # no new BD calls


@pytest.mark.asyncio
async def test_skips_non_image_candidate(tmp_path) -> None:
    """First URL returns HTML (a 403 page) → fall through to the second."""
    client = _FakeClient(
        urls=["https://x/bad.html", "https://x/good.png"],
        bytes_for={"https://x/bad.html": _HTML, "https://x/good.png": _PNG},
    )
    f = BrightDataMediaFetcher(client, cache_dir=tmp_path)
    b64 = await f.fetch_base_image_b64("tax form scan")
    assert b64 == _PNG_B64
    assert client.download_calls == 2  # tried bad then good


@pytest.mark.asyncio
async def test_no_api_key_degrades_to_none(tmp_path) -> None:
    client = _FakeClient(api_key="")
    f = BrightDataMediaFetcher(client, cache_dir=tmp_path)
    assert await f.fetch_base_image_b64("anything") is None
    assert client.search_calls == 0  # never called BD


@pytest.mark.asyncio
async def test_empty_search_returns_none(tmp_path) -> None:
    client = _FakeClient(urls=[])
    f = BrightDataMediaFetcher(client, cache_dir=tmp_path)
    assert await f.fetch_base_image_b64("nothing matches") is None


@pytest.mark.asyncio
async def test_blank_query_returns_none(tmp_path) -> None:
    client = _FakeClient()
    f = BrightDataMediaFetcher(client, cache_dir=tmp_path)
    assert await f.fetch_base_image_b64("   ") is None
    assert client.search_calls == 0
