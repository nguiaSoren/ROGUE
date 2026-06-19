"""Media fetcher (§11.8) — real-image carriers for multimodal attacks.

When a harvested multimodal attack describes the *kind* of carrier it needs
(``payload_slots["media_query"]`` — e.g. "bank login screenshot", "tax form
scan", "meme template"), this fetches a matching REAL image from the open web via
the backend-agnostic :class:`~rogue.harvest.fetchers.Fetcher`: **SERP image
search** (:meth:`~Fetcher.serp_image`) to find a candidate, then
:meth:`~Fetcher.fetch_image_bytes` to download the bytes. The image is then
composited under the attack overlay via the renderers' existing ``base_image``
slot — turning synthetic Pillow canvases into real-world carriers.

**Disk cache (why):** the renderers are deterministic by contract (§10.3); a live
web image is not. Caching the first fetch (keyed by the query) freezes the carrier
so every replay composites onto the SAME bytes — deterministic again — and we
never re-spend backend credit on a repeat. This mirrors the §11.7 fetch-cache
idea, applied to media assets.

**Pipeline position:** extraction sets ``media_query`` → a *gated* resolve step
(this module) fetches once + caches + stamps ``payload_slots["base_image"]`` →
the offline ``render()`` composites onto it. The network call lives HERE (harvest
layer), never inside ``render()``.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover
    from rogue.harvest.fetchers import Fetcher

logger = logging.getLogger("rogue.harvest.media_fetch")

__all__ = ["BrightDataMediaFetcher", "DEFAULT_MEDIA_CACHE_DIR"]

DEFAULT_MEDIA_CACHE_DIR = Path("data/media_cache")

# Image magic bytes — guard against caching an HTML error page as an "image".
_IMAGE_MAGIC: tuple[bytes, ...] = (
    b"\xff\xd8\xff",          # JPEG
    b"\x89PNG\r\n\x1a\n",     # PNG
    b"GIF87a",                # GIF
    b"GIF89a",
    b"RIFF",                  # WEBP (RIFF....WEBP)
    b"BM",                    # BMP
)


def _looks_like_image(data: bytes) -> bool:
    return any(data.startswith(m) for m in _IMAGE_MAGIC)


# Carrier file extension by content-type (fallback to magic-byte sniff → jpg).
_EXT_BY_CTYPE = {
    "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png",
    "image/gif": "gif", "image/webp": "webp", "image/bmp": "bmp",
}


class BrightDataMediaFetcher:
    """Fetch + cache a real carrier image for a multimodal attack.

    ``fetcher`` is a backend-agnostic :class:`~rogue.harvest.fetchers.Fetcher`
    (needs :attr:`~Capability.SERP_IMAGE` and :attr:`~Capability.IMAGE_BYTES`).
    Carriers are stored **per attack** so they're browsable:
    ``cache_dir/{primitive_id}/`` holds ``carrier.{ext}`` (the real image, proper
    extension — opens on double-click) + ``meta.json`` (source URL, query, where
    it was fetched from). First fetch hits the backend; every later call is a free
    disk read.

    .. note::
        The class name is kept for caller compatibility. Wave 2 can rename it to
        ``MediaFetcher`` and update callers.
    """

    def __init__(
        self,
        fetcher: "Fetcher",
        cache_dir: Path = DEFAULT_MEDIA_CACHE_DIR,
        *,
        max_candidates: int = 5,
    ) -> None:
        self.fetcher = fetcher
        self.cache_dir = Path(cache_dir)
        self.max_candidates = max_candidates

    def asset_dir(self, primitive_id: str) -> Path:
        """The per-attack folder holding ``carrier.{ext}`` + ``meta.json``."""
        return self.cache_dir / primitive_id

    def cached_path(self, primitive_id: str) -> Optional[Path]:
        """Return the cached ``carrier.*`` path for this attack, or None."""
        d = self.asset_dir(primitive_id)
        if d.is_dir():
            for f in sorted(d.glob("carrier.*")):
                if f.is_file() and f.stat().st_size > 0:
                    return f
        return None

    @staticmethod
    def _ext_for(content_type: str, data: bytes) -> str:
        ct = (content_type or "").split(";")[0].strip().lower()
        if ct in _EXT_BY_CTYPE:
            return _EXT_BY_CTYPE[ct]
        if data.startswith(b"\x89PNG"):
            return "png"
        if data.startswith(b"GIF"):
            return "gif"
        if data.startswith(b"RIFF"):
            return "webp"
        if data.startswith(b"BM"):
            return "bmp"
        return "jpg"

    async def fetch_base_image_path(
        self,
        query: str,
        primitive_id: str,
        *,
        source_url: Optional[str] = None,
        session=None,
    ) -> Optional[Path]:
        """Resolve ``query`` → a per-attack ``carrier.{ext}`` PATH (cache-first).

        Stored under ``cache_dir/{primitive_id}/`` with a ``meta.json`` recording
        ``source_url`` / ``media_query`` / where it was fetched from. The path
        plugs into the renderers' ``base_image`` slot. Returns None (caller falls
        back to the synthetic render) when the query/primitive_id is blank, BD
        credentials are absent, the search returns nothing, or no candidate
        downloads as a valid image. Never raises for the no-result path.
        """
        if not query or not query.strip() or not primitive_id:
            return None

        hit = self.cached_path(primitive_id)
        if hit is not None:
            return hit

        try:
            urls = await self.fetcher.serp_image(query, count=self.max_candidates)
        except Exception as exc:  # noqa: BLE001 — search failure ⇒ degrade, don't crash
            logger.warning("media_fetch: SERP image search failed for %r: %s", query[:60], exc)
            return None

        for url in urls:
            try:
                data, ctype = await self.fetcher.fetch_image_bytes(url)
            except Exception as exc:  # noqa: BLE001 — try the next candidate
                logger.warning("media_fetch: download failed %s: %s", url[:80], exc)
                continue
            if not _looks_like_image(data):
                logger.info("media_fetch: %s is not a valid image, trying next", url[:80])
                continue
            d = self.asset_dir(primitive_id)
            d.mkdir(parents=True, exist_ok=True)
            path = d / f"carrier.{self._ext_for(ctype, data)}"
            path.write_bytes(data)
            (d / "meta.json").write_text(
                json.dumps(
                    {
                        "primitive_id": primitive_id,
                        "media_query": query,
                        "source_url": source_url,
                        "fetched_from": url,
                        "content_type": ctype,
                        "bytes": len(data),
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            logger.info("media_fetch: cached carrier %s (%d bytes) from %s",
                        path, len(data), url[:80])
            return path

        logger.warning("media_fetch: no downloadable image for %s (%r, %d candidates)",
                       primitive_id, query[:60], len(urls))
        return None

    async def fetch_base_image_b64(
        self,
        query: str,
        primitive_id: str,
        *,
        source_url: Optional[str] = None,
        session=None,
    ) -> Optional[str]:
        """Convenience: resolve → base64 of the carrier image (or None)."""
        path = await self.fetch_base_image_path(
            query, primitive_id, source_url=source_url, session=session
        )
        if path is None:
            return None
        return base64.b64encode(path.read_bytes()).decode("ascii")
