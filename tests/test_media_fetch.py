"""Tests for the media fetcher (§11.8) — offline, mocked Fetcher."""

from __future__ import annotations

import base64

import pytest

from rogue.harvest.media_fetch import BrightDataMediaFetcher

_PNG = b"\x89PNG\r\n\x1a\n" + b"fake-png-bytes"
_PNG_B64 = base64.b64encode(_PNG).decode("ascii")
_HTML = b"<html>403 forbidden</html>"


class _FakeFetcher:
    """Records calls; configurable image-search results + per-url byte responses.

    Implements the :class:`~rogue.harvest.fetchers.Fetcher` surface used by
    :class:`BrightDataMediaFetcher` (``serp_image`` + ``fetch_image_bytes``).
    """

    def __init__(self, *, urls=None, bytes_for=None, raise_on_search=False):
        self._urls = urls if urls is not None else ["https://x/a.png"]
        self._bytes_for = bytes_for or {}
        self._raise_on_search = raise_on_search
        self.search_calls = 0
        self.download_calls = 0

    async def serp_image(self, query, count=5):
        self.search_calls += 1
        if self._raise_on_search:
            raise RuntimeError("search failed")
        return list(self._urls[:count])

    async def fetch_image_bytes(self, url):
        self.download_calls += 1
        return self._bytes_for.get(url, _PNG), "image/png"


_PID = "01TESTPRIM0000000000000000"


@pytest.mark.asyncio
async def test_fetch_downloads_and_caches_per_attack(tmp_path) -> None:
    import json
    fetcher = _FakeFetcher(urls=["https://x/a.png"])
    f = BrightDataMediaFetcher(fetcher, cache_dir=tmp_path)
    path = await f.fetch_base_image_path(
        "bank login screenshot", _PID, source_url="https://src/paper"
    )
    # per-attack folder, real extension, opens as the downloaded bytes
    assert path == tmp_path / _PID / "carrier.png"
    assert path.read_bytes() == _PNG
    # meta.json records provenance
    meta = json.loads((tmp_path / _PID / "meta.json").read_text())
    assert meta["source_url"] == "https://src/paper"
    assert meta["media_query"] == "bank login screenshot"
    assert meta["fetched_from"] == "https://x/a.png"
    assert f.cached_path(_PID) == path
    assert fetcher.search_calls == 1 and fetcher.download_calls == 1


@pytest.mark.asyncio
async def test_cache_hit_skips_fetcher(tmp_path) -> None:
    fetcher = _FakeFetcher()
    f = BrightDataMediaFetcher(fetcher, cache_dir=tmp_path)
    await f.fetch_base_image_path("meme template", _PID)          # populates cache
    calls = (fetcher.search_calls, fetcher.download_calls)
    again = await f.fetch_base_image_path("meme template", _PID)  # served from disk
    assert again == tmp_path / _PID / "carrier.png"
    assert (fetcher.search_calls, fetcher.download_calls) == calls  # no new fetcher calls


@pytest.mark.asyncio
async def test_skips_non_image_candidate(tmp_path) -> None:
    """First URL returns HTML (a 403 page) → fall through to the second."""
    fetcher = _FakeFetcher(
        urls=["https://x/bad.html", "https://x/good.png"],
        bytes_for={"https://x/bad.html": _HTML, "https://x/good.png": _PNG},
    )
    f = BrightDataMediaFetcher(fetcher, cache_dir=tmp_path)
    path = await f.fetch_base_image_path("tax form scan", _PID)
    assert path is not None and path.read_bytes() == _PNG
    assert fetcher.download_calls == 2  # tried bad then good


@pytest.mark.asyncio
async def test_search_failure_degrades_to_none(tmp_path) -> None:
    """A fetcher that raises on serp_image → degrade to None, no crash."""
    fetcher = _FakeFetcher(raise_on_search=True)
    f = BrightDataMediaFetcher(fetcher, cache_dir=tmp_path)
    assert await f.fetch_base_image_path("anything", _PID) is None
    assert fetcher.search_calls == 1  # attempted once, then gave up


@pytest.mark.asyncio
async def test_empty_search_returns_none(tmp_path) -> None:
    fetcher = _FakeFetcher(urls=[])
    f = BrightDataMediaFetcher(fetcher, cache_dir=tmp_path)
    assert await f.fetch_base_image_path("nothing matches", _PID) is None


@pytest.mark.asyncio
async def test_blank_query_or_pid_returns_none(tmp_path) -> None:
    fetcher = _FakeFetcher()
    f = BrightDataMediaFetcher(fetcher, cache_dir=tmp_path)
    assert await f.fetch_base_image_path("   ", _PID) is None
    assert await f.fetch_base_image_path("ok query", "") is None
    assert fetcher.search_calls == 0
