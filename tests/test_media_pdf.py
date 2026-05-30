"""Tests for embedded-image extraction from PDF bytes (Feature A — future-proof).

Builds real PDFs in-memory via Pillow (`Image.save(..., format="PDF")`, a project
dep) so the pypdf extraction path is exercised against genuine embedded rasters —
no committed binary fixtures, no network. Covers ``media_pdf.extract_pdf_images``,
its size/dedupe/cap filters + graceful degradation, the
``MediaIngestor.ingest_pdf_bytes`` cache hook, and the ``pdf_text`` URL scan.
"""

from __future__ import annotations

import base64
import io

import pytest

from rogue.harvest.media_extract import extract_media_urls
from rogue.harvest.media_ingest import MediaIngestor
from rogue.harvest.media_pdf import extract_pdf_images

Image = pytest.importorskip("PIL.Image")


def _pdf_with_images(*sizes_colors, save_all: bool = False) -> bytes:
    """Build a PDF embedding one image per (size, color). save_all → multipage."""
    imgs = [Image.new("RGB", size, color) for size, color in sizes_colors]
    buf = io.BytesIO()
    if save_all and len(imgs) > 1:
        imgs[0].save(buf, format="PDF", save_all=True, append_images=imgs[1:])
    else:
        imgs[0].save(buf, format="PDF")
    return buf.getvalue()


def test_extracts_embedded_figure() -> None:
    pdf = _pdf_with_images(((220, 160), (90, 20, 160)))
    out = extract_pdf_images(pdf)
    assert len(out) == 1
    data, media_type = out[0]
    assert media_type in ("image/jpeg", "image/png")
    assert len(data) > 0


def test_filters_sub_icon_rasters() -> None:
    # 10×10 = 100 px, well below the 64×64 floor → dropped.
    pdf = _pdf_with_images(((10, 10), (0, 0, 0)))
    assert extract_pdf_images(pdf) == []


def test_dedupes_identical_image_across_pages() -> None:
    # Same image on 3 pages → one entry (content-hash dedupe).
    pdf = _pdf_with_images(
        ((200, 150), (12, 34, 56)),
        ((200, 150), (12, 34, 56)),
        ((200, 150), (12, 34, 56)),
        save_all=True,
    )
    assert len(extract_pdf_images(pdf)) == 1


def test_respects_limit() -> None:
    pdf = _pdf_with_images(
        ((200, 150), (10, 0, 0)),
        ((200, 150), (0, 10, 0)),
        ((200, 150), (0, 0, 10)),
        save_all=True,
    )
    assert len(extract_pdf_images(pdf, limit=2)) == 2


def test_corrupt_and_empty_degrade_to_empty() -> None:
    assert extract_pdf_images(b"") == []
    assert extract_pdf_images(b"not a pdf at all") == []


def test_ingest_pdf_bytes_caches_and_returns_ingested_images(tmp_path) -> None:
    pdf = _pdf_with_images(((200, 150), (90, 20, 160)))
    # No BD client needed — embedded bytes, no network.
    ing = MediaIngestor(object(), cache_dir=tmp_path)
    out = ing.ingest_pdf_bytes(pdf, source_url="https://arxiv.org/pdf/2605.1")
    assert len(out) == 1
    img = out[0]
    assert img.path.exists() and img.path.read_bytes() == base64.b64decode(img.b64)
    assert img.url.startswith("pdf-embedded:")
    # Sidecar provenance written.
    assert (tmp_path / f"{img.path.stem}.json").exists()


def test_ingest_pdf_bytes_is_idempotent(tmp_path) -> None:
    pdf = _pdf_with_images(((200, 150), (90, 20, 160)))
    ing = MediaIngestor(object(), cache_dir=tmp_path)
    first = ing.ingest_pdf_bytes(pdf)
    second = ing.ingest_pdf_bytes(pdf)  # same bytes → same cached path
    assert first[0].path == second[0].path


def test_pdf_text_url_scan_in_extract_media_urls() -> None:
    text = "As shown in https://i.imgur.com/fig.png, the attack works. End."
    out = extract_media_urls(text, "pdf_text", "https://arxiv.org/abs/2605.1")
    assert out == ["https://i.imgur.com/fig.png"]
