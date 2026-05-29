"""Bright Data media fetcher (§11.8) — real-image carriers for multimodal attacks.

When a harvested multimodal attack describes the *kind* of carrier it needs
(``payload_slots["media_query"]`` — e.g. "bank login screenshot", "tax form
scan", "meme template"), this fetches a matching REAL image from the open web via
Bright Data: **SERP image search** (``serp_image_search``) to find a candidate,
then **Web Unlocker** (``fetch_image_bytes``) to download the bytes. The image is
then composited under the attack overlay via the renderers' existing
``base_image`` slot — turning synthetic Pillow canvases into real-world carriers.

**Disk cache (why):** the renderers are deterministic by contract (§10.3); a live
web image is not. Caching the first fetch (keyed by the query) freezes the carrier
so every replay composites onto the SAME bytes — deterministic again — and we
never re-spend Bright Data credit on a repeat. This mirrors the §11.7 fetch-cache
idea, applied to media assets.

**Pipeline position:** extraction sets ``media_query`` → a *gated* resolve step
(this module — costs BD credit) fetches once + caches + stamps
``payload_slots["base_image"]`` → the offline ``render()`` composites onto it. The
network call lives HERE (harvest layer), never inside ``render()``.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover
    from rogue.harvest.bright_data_client import BrightDataClient

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


class BrightDataMediaFetcher:
    """Fetch + cache a real carrier image for a text description, via Bright Data.

    ``client`` is a ``BrightDataClient`` (the SERP + Web Unlocker products).
    Pass an explicit ``cache_dir`` for tests. All fetches are cached as base64
    text under ``cache_dir/{sha256(query)[:16]}.b64`` — first call spends BD
    credit, every later call (any run) is a free disk read.
    """

    def __init__(
        self,
        client: "BrightDataClient",
        cache_dir: Path = DEFAULT_MEDIA_CACHE_DIR,
        *,
        max_candidates: int = 5,
    ) -> None:
        self.client = client
        self.cache_dir = Path(cache_dir)
        self.max_candidates = max_candidates

    def cache_path(self, query: str) -> Path:
        """Deterministic on-disk path for ``query``'s cached RAW image bytes."""
        digest = hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / f"{digest}.img"

    def cached_path(self, query: str) -> Optional[Path]:
        """Return the cached raw-image path for ``query`` if present (no BD call)."""
        path = self.cache_path(query)
        return path if path.exists() and path.stat().st_size > 0 else None

    async def fetch_base_image_path(
        self,
        query: str,
        *,
        session=None,
    ) -> Optional[Path]:
        """Resolve ``query`` → a cached RAW-image file PATH (cache-first).

        The path plugs straight into the renderers' ``base_image`` slot (which
        reads a file as raw bytes). Returns None (caller falls back to the
        synthetic render) when: the query is blank, BD credentials are absent,
        the search returns nothing, or no candidate downloads as a valid image.
        Never raises for the no-result path — a missing carrier is a degraded
        render, not a pipeline error.
        """
        if not query or not query.strip():
            return None

        hit = self.cached_path(query)
        if hit is not None:
            return hit

        # No credentials → don't attempt a network call; degrade to synthetic.
        if not getattr(self.client, "api_key", ""):
            logger.info("media_fetch: no BD api_key — skipping fetch for %r", query[:60])
            return None

        try:
            urls = await self.client.serp_image_search(
                query, count=self.max_candidates, session=session
            )
        except Exception as exc:  # noqa: BLE001 — search failure ⇒ degrade, don't crash
            logger.warning("media_fetch: SERP image search failed for %r: %s", query[:60], exc)
            return None

        for url in urls:
            try:
                data, _ctype = await self.client.fetch_image_bytes(url, session=session)
            except Exception as exc:  # noqa: BLE001 — try the next candidate
                logger.warning("media_fetch: download failed %s: %s", url[:80], exc)
                continue
            if not _looks_like_image(data):
                logger.info("media_fetch: %s is not a valid image, trying next", url[:80])
                continue
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path = self.cache_path(query)
            path.write_bytes(data)
            logger.info("media_fetch: cached carrier for %r (%d bytes) from %s",
                        query[:60], len(data), url[:80])
            return path

        logger.warning("media_fetch: no downloadable image for %r (%d candidates)",
                       query[:60], len(urls))
        return None

    async def fetch_base_image_b64(
        self,
        query: str,
        *,
        session=None,
    ) -> Optional[str]:
        """Convenience: resolve ``query`` → base64 of the carrier image (or None).

        Wraps :meth:`fetch_base_image_path` for callers that want bytes inline
        rather than a ``base_image`` file path.
        """
        path = await self.fetch_base_image_path(query, session=session)
        if path is None:
            return None
        return base64.b64encode(path.read_bytes()).decode("ascii")
