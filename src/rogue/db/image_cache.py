"""Read on-disk attack images into the DB so they render on the deployed site.

The image FILES live under ``data/media_cache/`` (§11.8 ``{id}/carrier.*``
carriers + Feature-A ``ingested/`` payloads) — but that disk is local-only, so
the deployed Render API can't serve them. This module copies each primitive's
image BYTES into the ``primitive_images`` table; ``rogue.db.neon_sync`` then
ships that table to Neon, and the image route serves the bytes anywhere.

Free + idempotent (no LLM/BD). Auto-runs at the end of ``reproduce_once`` /
``harvest_once`` (just before the Neon sync) so freshly-fetched carriers get a
DB row; also a standalone backfill via ``scripts/cache_images_to_db.py``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from rogue.db.models import AttackPrimitive, PrimitiveImage

logger = logging.getLogger("rogue.db.image_cache")

__all__ = [
    "MEDIA_CACHE_DIR",
    "resolve_image_on_disk",
    "media_type_for",
    "cache_images_to_db",
    "maybe_cache_images",
]

MEDIA_CACHE_DIR = Path("data/media_cache")

_MEDIA_TYPE_BY_EXT = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
    ".tiff": "image/tiff", ".tif": "image/tiff",
}


def media_type_for(path: Path) -> str:
    """IANA media type from a file extension (octet-stream fallback)."""
    return _MEDIA_TYPE_BY_EXT.get(path.suffix.lower(), "application/octet-stream")


def resolve_image_on_disk(
    primitive_id: str,
    payload_slots: Any,
    *,
    media_cache_dir: Path = MEDIA_CACHE_DIR,
) -> Optional[Path]:
    """Locate a primitive's real image file on disk, or None.

    Two layouts, both confined to ``media_cache_dir`` (no arbitrary-path read):
      1. ``payload_slots['base_image']`` — the Feature-A verbatim-ingested image
         (or any explicitly-stamped carrier path);
      2. ``{media_cache_dir}/{primitive_id}/carrier.*`` — the §11.8 per-attack
         carrier written by ``BrightDataMediaFetcher`` (path not persisted, so
         it's re-derived by primitive id).
    """
    root = media_cache_dir.resolve()
    slots = payload_slots if isinstance(payload_slots, dict) else {}
    base_image = slots.get("base_image")
    if base_image:
        try:
            resolved = Path(base_image).resolve()
            if str(resolved).startswith(str(root)) and resolved.is_file():
                return resolved
        except (OSError, ValueError):
            pass
    asset_dir = root / primitive_id
    if asset_dir.is_dir():
        for f in sorted(asset_dir.glob("carrier.*")):
            if f.is_file() and f.stat().st_size > 0:
                return f
    return None


def _source_label(path: Path, media_cache_dir: Path) -> str:
    return "ingested" if (media_cache_dir.resolve() / "ingested") in path.parents else "carrier"


def cache_images_to_db(
    session: Session,
    *,
    media_cache_dir: Path = MEDIA_CACHE_DIR,
) -> dict[str, int]:
    """Upsert every on-disk primitive image into ``primitive_images``.

    Walks all primitives, resolves each one's image file (if any), reads the
    bytes, and upserts a ``primitive_images`` row. Idempotent — re-running
    overwrites with the current bytes. Returns ``{"primitives": N, "cached": M}``.
    """
    primitives = session.execute(select(AttackPrimitive)).scalars().all()
    cached = 0
    for prim in primitives:
        path = resolve_image_on_disk(prim.primitive_id, prim.payload_slots, media_cache_dir=media_cache_dir)
        if path is None:
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            logger.warning("image_cache: read failed for %s: %s", prim.primitive_id, exc)
            continue
        if not data:
            continue
        session.merge(
            PrimitiveImage(
                primitive_id=prim.primitive_id,
                media_type=media_type_for(path),
                image_bytes=data,
                byte_size=len(data),
                source=_source_label(path, media_cache_dir),
            )
        )
        cached += 1
    session.commit()
    logger.info("image_cache: cached %d/%d primitive images into the DB", cached, len(primitives))
    return {"primitives": len(primitives), "cached": cached}


def maybe_cache_images(database_url: str) -> Optional[dict[str, int]]:
    """Auto-hook: cache on-disk images into ``database_url`` (best-effort).

    Called by the pipeline scripts before the Neon sync so freshly-fetched
    carriers get a DB row that then syncs. Never raises — a failure here must
    not fail the run that already did the expensive work. Returns counts, or
    None on error / when the media cache is absent.
    """
    if not MEDIA_CACHE_DIR.is_dir():
        return None
    engine = create_engine(database_url)
    SessionLocal = sessionmaker(bind=engine)
    try:
        with SessionLocal() as session:
            return cache_images_to_db(session)
    except Exception as exc:  # noqa: BLE001 — image caching must not fail the pipeline
        logger.warning("image_cache: caching skipped (%s)", exc)
        return None
    finally:
        engine.dispose()
