"""SearXNG backend — self-hosted metasearch for SERP + image search (preferred when SEARXNG_URL set)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from rogue.harvest.fetchers.capabilities import Capability
from rogue.harvest.fetchers.searxng import SearXNGFetcher


def _json_response(body: dict) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = body
    resp.raise_for_status.return_value = None
    return resp


def _fetcher(monkeypatch) -> SearXNGFetcher:
    monkeypatch.setenv("SEARXNG_URL", "http://localhost:8888")
    return SearXNGFetcher()


# --- availability ---------------------------------------------------------------------------------

def test_unavailable_without_url(monkeypatch):
    monkeypatch.delenv("SEARXNG_URL", raising=False)
    assert SearXNGFetcher.is_available() is False


def test_available_with_url(monkeypatch):
    monkeypatch.setenv("SEARXNG_URL", "http://localhost:8888")
    assert SearXNGFetcher.is_available() is True


def test_capabilities():
    assert Capability.SERP in SearXNGFetcher.capabilities
    assert Capability.SERP_IMAGE in SearXNGFetcher.capabilities


# --- serp -----------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_serp_maps_results(monkeypatch):
    fc = _fetcher(monkeypatch)
    body = {"results": [
        {"url": "https://a.com", "title": "A", "content": "ca"},
        {"url": "https://b.com", "title": "B", "content": "cb"},
    ]}
    with patch.object(fc._get_http(), "get", AsyncMock(return_value=_json_response(body))):
        resp = await fc.serp("prompt injection", count=2)
    assert resp.engine == "searxng"
    assert [r["link"] for r in resp.organic_results] == ["https://a.com", "https://b.com"]
    assert resp.organic_results[0]["url"] == "https://a.com"
    assert resp.organic_results[0]["title"] == "A"


@pytest.mark.asyncio
async def test_serp_respects_count(monkeypatch):
    fc = _fetcher(monkeypatch)
    body = {"results": [{"url": f"https://{i}.com", "title": str(i), "content": ""} for i in range(10)]}
    with patch.object(fc._get_http(), "get", AsyncMock(return_value=_json_response(body))):
        resp = await fc.serp("q", count=3)
    assert len(resp.organic_results) == 3


@pytest.mark.asyncio
async def test_serp_degrades_to_empty_on_error(monkeypatch):
    fc = _fetcher(monkeypatch)
    failing = AsyncMock(side_effect=httpx.ConnectError("down"))
    with patch.object(fc._get_http(), "get", failing):
        resp = await fc.serp("q")
    assert resp.organic_results == []
    assert resp.engine == "searxng"


# --- serp_image -----------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_serp_image_extracts_img_urls(monkeypatch):
    fc = _fetcher(monkeypatch)
    body = {"results": [
        {"img_src": "https://img/1.jpg", "url": "https://page/1"},
        {"thumbnail_src": "https://img/2.png", "url": "https://page/2"},
        {"url": "https://page/3"},  # no image src → falls back to url
    ]}
    with patch.object(fc._get_http(), "get", AsyncMock(return_value=_json_response(body))):
        urls = await fc.serp_image("napalm carrier", count=5)
    assert urls == ["https://img/1.jpg", "https://img/2.png", "https://page/3"]


@pytest.mark.asyncio
async def test_serp_image_degrades_to_empty(monkeypatch):
    fc = _fetcher(monkeypatch)
    with patch.object(fc._get_http(), "get", AsyncMock(side_effect=httpx.ConnectError("down"))):
        urls = await fc.serp_image("q")
    assert urls == []
