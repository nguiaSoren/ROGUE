"""Media ingestion (Feature A) — download a document's OWN images for extraction.

This is the harvest-side download step that turns ``RawDocument.media_urls``
(image URLs the source carried — a Pliny screenshot of a jailbreak prompt, an
arXiv figure, a blog ``<img>``) into local image bytes the extraction agent can
vision-read.

**How it differs from ``media_fetch.py`` (§11.8):** ``media_fetch`` *searches the
open web* for a generic CARRIER to composite a text attack onto
(``payload_slots["media_query"]`` → SERP image search → composite). This module
ingests the image that is ALREADY ATTACHED to the harvested document — a
candidate *payload*, not a carrier. The extraction LLM then decides which of the
three cases it is (text-in-image / image-is-payload / supplement; see
``extraction_v3.md``).

**Cache (why + layout):** downloads are cached on disk keyed by a hash of the
image URL, so (a) a daily re-harvest never re-spends Web-Unlocker credit on an
image we already have, and (b) an image-is-payload primitive can re-derive the
SAME local path at reproduction time (the path is stored in
``payload_slots["base_image"]``). Layout::

    data/media_cache/ingested/<sha256(url)[:16]>.<ext>   # the bytes
    data/media_cache/ingested/<sha256(url)[:16]>.json    # provenance sidecar

Network calls live HERE (harvest layer), never inside extraction or render().
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from rogue.harvest.media_extract import DEFAULT_MEDIA_LIMIT, media_urls_for_document
from rogue.harvest.media_fetch import _EXT_BY_CTYPE, _looks_like_image

if TYPE_CHECKING:  # pragma: no cover
    from rogue.harvest.bright_data_client import BrightDataClient
    from rogue.schemas import RawDocument

logger = logging.getLogger("rogue.harvest.media_ingest")

__all__ = ["IngestedImage", "MediaIngestor", "DEFAULT_INGEST_CACHE_DIR"]

DEFAULT_INGEST_CACHE_DIR = Path("data/media_cache/ingested")

# Extension → IANA media type for the vision API blocks. Mirrors the raster
# formats `_looks_like_image` accepts.
_MEDIA_TYPE_BY_EXT = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
}

# Inverse, for naming cached files by their sniffed media type (PDF path).
_EXT_BY_MEDIA_TYPE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/bmp": "bmp",
    "image/tiff": "tiff",
}


def _ext_and_media_type(content_type: str, data: bytes) -> tuple[str, str]:
    """Return ``(extension, media_type)`` from content-type, magic-byte fallback."""
    ct = (content_type or "").split(";")[0].strip().lower()
    ext = _EXT_BY_CTYPE.get(ct)
    if ext is None:
        if data.startswith(b"\x89PNG"):
            ext = "png"
        elif data.startswith(b"GIF"):
            ext = "gif"
        elif data.startswith(b"RIFF"):
            ext = "webp"
        elif data.startswith(b"BM"):
            ext = "bmp"
        else:
            ext = "jpg"
    return ext, _MEDIA_TYPE_BY_EXT.get(ext, "image/jpeg")


def _url_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class IngestedImage:
    """One downloaded document image, ready for the extraction agent / reproduce.

    ``path`` is the on-disk cache location (stable across runs); ``b64`` is the
    base64 of the bytes; ``media_type`` is the IANA type for the vision block.
    ``source_url`` is the original image URL (provenance).
    """

    url: str
    path: Path
    media_type: str
    b64: str

    @classmethod
    def from_path(cls, path: Path, url: str) -> "IngestedImage":
        data = path.read_bytes()
        ext = path.suffix.lstrip(".").lower()
        media_type = _MEDIA_TYPE_BY_EXT.get(ext, "image/jpeg")
        return cls(
            url=url,
            path=path,
            media_type=media_type,
            b64=base64.b64encode(data).decode("ascii"),
        )


class MediaIngestor:
    """Download + cache a harvested document's images via Bright Data Web Unlocker.

    ``client`` is a ``BrightDataClient`` (uses ``fetch_image_bytes``). A blank
    ``api_key`` degrades every call to a no-op (returns ``[]``) so offline /
    test runs never attempt a network call. Per-image failures are isolated —
    one bad URL never sinks the rest of the document's images.
    """

    def __init__(
        self,
        client: "BrightDataClient",
        cache_dir: Path = DEFAULT_INGEST_CACHE_DIR,
        *,
        max_images_per_doc: int = 4,
    ) -> None:
        self.client = client
        self.cache_dir = Path(cache_dir)
        self.max_images_per_doc = max_images_per_doc

    def cached_path(self, url: str) -> Optional[Path]:
        """Return the cached image path for ``url`` (any extension), or None."""
        key = _url_key(url)
        if self.cache_dir.is_dir():
            for f in sorted(self.cache_dir.glob(f"{key}.*")):
                if f.suffix != ".json" and f.is_file() and f.stat().st_size > 0:
                    return f
        return None

    async def ingest_url(
        self,
        url: str,
        *,
        source_url: Optional[str] = None,
        session=None,
    ) -> Optional[IngestedImage]:
        """Download (cache-first) one image URL → ``IngestedImage`` or None.

        Returns None (caller drops the image) on a blank URL, missing BD
        credentials, a download error, or a response that is not a valid image
        (e.g. an HTML 403 page). Never raises for the no-result path.
        """
        if not url or not url.strip():
            return None

        hit = self.cached_path(url)
        if hit is not None:
            return IngestedImage.from_path(hit, url)

        if not getattr(self.client, "api_key", ""):
            logger.info("media_ingest: no BD api_key — skipping download of %s", url[:80])
            return None

        try:
            data, ctype = await self.client.fetch_image_bytes(url, session=session)
        except Exception as exc:  # noqa: BLE001 — one bad image must not crash the doc
            logger.warning("media_ingest: download failed %s: %s", url[:80], exc)
            return None
        if not _looks_like_image(data):
            logger.info("media_ingest: %s is not a valid image (skipped)", url[:80])
            return None

        ext, media_type = _ext_and_media_type(ctype, data)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        key = _url_key(url)
        path = self.cache_dir / f"{key}.{ext}"
        path.write_bytes(data)
        (self.cache_dir / f"{key}.json").write_text(
            json.dumps(
                {
                    "image_url": url,
                    "source_url": source_url,
                    "content_type": ctype,
                    "media_type": media_type,
                    "bytes": len(data),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        logger.info("media_ingest: cached %s (%d bytes) from %s", path, len(data), url[:80])
        return IngestedImage(
            url=url,
            path=path,
            media_type=media_type,
            b64=base64.b64encode(data).decode("ascii"),
        )

    def ingest_pdf_bytes(
        self,
        pdf_bytes: bytes,
        *,
        source_url: str | None = None,
        limit: int | None = None,
    ) -> list[IngestedImage]:
        """Extract + cache EMBEDDED raster images from PDF bytes (Feature A hook).

        For a future PDF-carrying source (e.g. arXiv full-text): the figures /
        screenshots inside a PDF are embedded rasters with no URL, so the
        URL-download path can't reach them. This pulls them out with pypdf
        (``media_pdf.extract_pdf_images``), caches each to disk keyed by content
        hash (stable path → reproduce can re-derive it for a verbatim payload),
        and returns ``IngestedImage`` objects identical to the URL path's — so
        they feed the same multimodal extraction + verbatim-reproduce flow.

        Synchronous (pypdf is CPU-bound, no network). Degrades to ``[]`` on a bad
        PDF. ``source_url`` is recorded in each sidecar for provenance.
        """
        from rogue.harvest.media_pdf import extract_pdf_images  # noqa: PLC0415

        cap = self.max_images_per_doc if limit is None else min(limit, self.max_images_per_doc)
        images = extract_pdf_images(pdf_bytes, limit=cap)
        if not images:
            return []

        out: list[IngestedImage] = []
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        for data, media_type in images:
            digest = hashlib.sha256(data).hexdigest()[:16]
            ext = _EXT_BY_MEDIA_TYPE.get(media_type, "jpg")
            path = self.cache_dir / f"pdf_{digest}.{ext}"
            if not (path.exists() and path.stat().st_size > 0):
                path.write_bytes(data)
                (self.cache_dir / f"pdf_{digest}.json").write_text(
                    json.dumps(
                        {
                            "embedded_in_pdf": True,
                            "source_url": source_url,
                            "media_type": media_type,
                            "bytes": len(data),
                        },
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            out.append(
                IngestedImage(
                    url=f"pdf-embedded:{source_url or 'document'}#{digest}",
                    path=path,
                    media_type=media_type,
                    b64=base64.b64encode(data).decode("ascii"),
                )
            )
        return out

    async def ingest_for_document(
        self,
        doc: "RawDocument",
        *,
        session=None,
        limit: Optional[int] = None,
    ) -> list[IngestedImage]:
        """Download every image attached to ``doc`` (structural + body-derived).

        Merges ``doc.media_urls`` (X/Reddit JSON ``photos``) with images parsed
        from the body (``<img>`` / ``![]()`` for HTML/markdown sources) via
        ``media_urls_for_document``, capped at ``min(limit, max_images_per_doc)``.
        Returns the successfully-downloaded images in URL order; an empty list
        when the doc has no images, BD credentials are absent, or none download.
        """
        cap = self.max_images_per_doc if limit is None else min(limit, self.max_images_per_doc)
        urls = media_urls_for_document(
            media_urls=list(doc.media_urls),
            raw_content=doc.raw_content,
            content_format=doc.content_format,
            base_url=str(doc.url),
            limit=max(cap, DEFAULT_MEDIA_LIMIT),
        )[:cap]
        if not urls:
            return []

        out: list[IngestedImage] = []
        for url in urls:
            img = await self.ingest_url(url, source_url=str(doc.url), session=session)
            if img is not None:
                out.append(img)
        return out
