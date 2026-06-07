"""Backfill the on-disk attack images into the DB so they render on the deployed site.

The image FILES live under ``data/media_cache/`` (local-only); this copies each
primitive's image BYTES into the ``primitive_images`` table so they can be synced
to Neon and served by the deployed API. Free + idempotent (no LLM/BD).

Usage::

    uv run python scripts/harvest/cache_images_to_db.py            # local DB
    uv run python scripts/harvest/cache_images_to_db.py && uv run python scripts/ops/sync_to_neon.py
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from rogue.db.image_cache import cache_images_to_db  # noqa: E402

DEFAULT_DATABASE_URL = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cache on-disk attack images into the DB.")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        help="Target DB (default: DATABASE_URL or local docker).",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")

    engine = create_engine(args.database_url)
    SessionLocal = sessionmaker(bind=engine)
    try:
        with SessionLocal() as session:
            counts = cache_images_to_db(session)
    finally:
        engine.dispose()
    print(f"cached {counts['cached']} image(s) across {counts['primitives']} primitives")
    return 0


if __name__ == "__main__":  # pragma: no cover — exercised via cache_images_to_db()
    sys.exit(main())
