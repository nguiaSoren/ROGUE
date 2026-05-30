"""Tests for the harvest media-download step (Feature A) — offline, mocked BD client.

Covers ``rogue.harvest.media_ingest.MediaIngestor``: download + per-URL disk
cache (so a re-harvest never re-spends BD credit), non-image rejection, the
no-credentials degrade, and ``ingest_for_document`` over a ``RawDocument``'s
structural + body-derived images.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from rogue.harvest.media_ingest import IngestedImage, MediaIngestor
from rogue.schemas import RawDocument

_PNG = b"\x89PNG\r\n\x1a\n" + b"real-png-bytes"
_JPEG = b"\xff\xd8\xff\xe0" + b"real-jpeg-bytes"
_HTML = b"<html>403 forbidden</html>"


class _FakeClient:
    """Records calls; configurable per-url byte/content-type responses."""

    def __init__(self, *, api_key="k", bytes_for=None, ctype_for=None):
        self.api_key = api_key
        self._bytes_for = bytes_for or {}
        self._ctype_for = ctype_for or {}
        self.download_calls = 0

    async def fetch_image_bytes(self, url, *, session=None):
        self.download_calls += 1
        return self._bytes_for.get(url, _PNG), self._ctype_for.get(url, "image/png")


def _doc(*, media_urls=None, content="text", content_format="text", url="https://x.com/p/status/1"):
    return RawDocument(
        url=url,
        source_type="x",
        bright_data_product="web_scraper_api",
        fetched_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
        raw_content=content,
        content_format=content_format,
        archive_hash=hashlib.sha256(content.encode()).hexdigest(),
        http_status=200,
        media_urls=media_urls or [],
    )


@pytest.mark.asyncio
async def test_ingest_url_downloads_caches_and_sniffs_media_type(tmp_path) -> None:
    url = "https://pbs.twimg.com/media/a.jpg"
    client = _FakeClient(bytes_for={url: _JPEG}, ctype_for={url: "image/jpeg"})
    ing = MediaIngestor(client, cache_dir=tmp_path)

    img = await ing.ingest_url(url, source_url="https://x.com/p/status/1")
    assert isinstance(img, IngestedImage)
    assert img.media_type == "image/jpeg"
    assert img.path.read_bytes() == _JPEG
    # Sidecar provenance written next to the bytes.
    key = img.path.stem
    assert (tmp_path / f"{key}.json").exists()
    assert client.download_calls == 1


@pytest.mark.asyncio
async def test_cache_hit_skips_second_download(tmp_path) -> None:
    url = "https://pbs.twimg.com/media/b.png"
    client = _FakeClient(bytes_for={url: _PNG})
    ing = MediaIngestor(client, cache_dir=tmp_path)

    first = await ing.ingest_url(url)
    second = await ing.ingest_url(url)  # served from disk
    assert first.path == second.path
    assert second.b64 == first.b64
    assert client.download_calls == 1  # no new BD call


@pytest.mark.asyncio
async def test_non_image_response_rejected(tmp_path) -> None:
    url = "https://blocked.example/x.png"
    client = _FakeClient(bytes_for={url: _HTML})
    ing = MediaIngestor(client, cache_dir=tmp_path)
    assert await ing.ingest_url(url) is None


@pytest.mark.asyncio
async def test_no_api_key_degrades_to_none(tmp_path) -> None:
    client = _FakeClient(api_key="")
    ing = MediaIngestor(client, cache_dir=tmp_path)
    assert await ing.ingest_url("https://x/a.png") is None
    assert client.download_calls == 0


@pytest.mark.asyncio
async def test_ingest_for_document_structural_media_urls(tmp_path) -> None:
    urls = ["https://pbs.twimg.com/media/1.jpg", "https://pbs.twimg.com/media/2.jpg"]
    client = _FakeClient(
        bytes_for={urls[0]: _JPEG, urls[1]: _PNG},
        ctype_for={urls[0]: "image/jpeg", urls[1]: "image/png"},
    )
    ing = MediaIngestor(client, cache_dir=tmp_path)
    out = await ing.ingest_for_document(_doc(media_urls=urls))
    assert [i.url for i in out] == urls
    assert [i.media_type for i in out] == ["image/jpeg", "image/png"]


@pytest.mark.asyncio
async def test_ingest_for_document_body_derived_html(tmp_path) -> None:
    body = '<p>jb</p><img src="https://cdn.example/shot.png">'
    client = _FakeClient(bytes_for={"https://cdn.example/shot.png": _PNG})
    ing = MediaIngestor(client, cache_dir=tmp_path)
    out = await ing.ingest_for_document(
        _doc(content=body, content_format="html", url="https://blog.example/post")
    )
    assert len(out) == 1
    assert out[0].url == "https://cdn.example/shot.png"


@pytest.mark.asyncio
async def test_ingest_for_document_respects_per_doc_cap(tmp_path) -> None:
    urls = [f"https://pbs.twimg.com/media/{i}.png" for i in range(6)]
    client = _FakeClient(bytes_for={u: _PNG for u in urls})
    ing = MediaIngestor(client, cache_dir=tmp_path, max_images_per_doc=2)
    out = await ing.ingest_for_document(_doc(media_urls=urls))
    assert len(out) == 2
    assert client.download_calls == 2


@pytest.mark.asyncio
async def test_ingest_for_document_no_images_is_noop(tmp_path) -> None:
    client = _FakeClient()
    ing = MediaIngestor(client, cache_dir=tmp_path)
    out = await ing.ingest_for_document(_doc(content="just text", content_format="text"))
    assert out == []
    assert client.download_calls == 0
