"""Embedded-image extraction from PDF bytes (Feature A — future-proof hook).

``media_extract.py`` handles URL-based images (HTML ``<img>`` / markdown
``![]()`` / JSON ``photos``). PDFs are different: their images are EMBEDDED
raster XObjects, not URLs — so a figure or a screenshot inside an arXiv PDF has
no URL to download. This module pulls those embedded rasters out with **pypdf**
(already a project dependency, used for text extraction) so they can be
vision-read by the extraction agent like any other ingested image.

**Why this is a hook, not yet wired into the daily run:** no source emits PDF
*bytes* today — a ``pdf_text`` ``RawDocument`` carries the already-extracted
TEXT, not the binary. When a future plugin fetches a real PDF (e.g. arXiv
full-text), it calls :meth:`MediaIngestor.ingest_pdf_bytes` with the bytes and
gets back the same ``IngestedImage`` objects the URL path produces — feeding the
exact same multimodal extraction + verbatim-reproduce path. The complementary
text-side scan (image URLs that survived PDF→text conversion) lives in
``media_extract.extract_media_urls`` under the ``pdf_text`` branch.

Degrades safely: a corrupt PDF, a missing pypdf, or a bad page never raises —
it just yields fewer (or zero) images.
"""

from __future__ import annotations

import hashlib
import io
import logging

__all__ = ["extract_pdf_images", "DEFAULT_PDF_MIN_PIXELS"]

logger = logging.getLogger("rogue.harvest.media_pdf")

# Drop sub-icon rasters (bullets, logos, rule lines, signature glyphs). 64×64 =
# 4096 px is comfortably below any real figure/screenshot but above UI chrome.
DEFAULT_PDF_MIN_PIXELS = 64 * 64

# PIL format → IANA media type (the vision dispatch accepts these).
_PIL_FORMAT_TO_MEDIA_TYPE = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "WEBP": "image/webp",
    "BMP": "image/bmp",
    "TIFF": "image/tiff",
}


def _media_type_from_bytes(data: bytes) -> str:
    """Sniff an IANA media type from an image's magic bytes (jpeg fallback)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF"):
        return "image/webp"
    if data.startswith(b"BM"):
        return "image/bmp"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    return "image/jpeg"


def extract_pdf_images(
    pdf_bytes: bytes,
    *,
    limit: int = 8,
    min_pixels: int = DEFAULT_PDF_MIN_PIXELS,
) -> list[tuple[bytes, str]]:
    """Extract embedded raster images from ``pdf_bytes`` → ``[(bytes, media_type)]``.

    Walks every page's image XObjects via pypdf, drops sub-``min_pixels`` rasters
    (icons/logos), de-dupes by content hash (a figure repeated on every page
    yields one entry), preserves document order, and caps at ``limit``. Returns
    ``[]`` — never raises — on empty input, a missing pypdf, an unreadable PDF,
    or a page that fails to decode.
    """
    if not pdf_bytes:
        return []
    try:
        from pypdf import PdfReader  # noqa: PLC0415 — lazy: only PDF docs pay the import
    except Exception as exc:  # noqa: BLE001 — degrade if the dep is absent
        logger.warning("pdf image extract: pypdf unavailable (%s)", exc)
        return []
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except Exception as exc:  # noqa: BLE001 — corrupt/encrypted PDF ⇒ no images
        logger.warning("pdf image extract: unreadable PDF (%s)", exc)
        return []

    out: list[tuple[bytes, str]] = []
    seen: set[str] = set()
    for page in reader.pages:
        try:
            page_images = list(page.images)
        except Exception:  # noqa: BLE001 — one bad page must not sink the rest
            continue
        for im in page_images:
            if len(out) >= limit:
                return out
            try:
                data = im.data
            except Exception:  # noqa: BLE001 — undecodable XObject ⇒ skip
                continue
            if not data:
                continue
            pil = getattr(im, "image", None)
            if pil is not None:
                try:
                    w, h = pil.size
                    if w * h < min_pixels:
                        continue
                    media_type = _PIL_FORMAT_TO_MEDIA_TYPE.get((pil.format or "").upper())
                except Exception:  # noqa: BLE001 — size/format probe failed; keep, sniff
                    media_type = None
            else:
                media_type = None
            if media_type is None:
                media_type = _media_type_from_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            out.append((data, media_type))
    return out
