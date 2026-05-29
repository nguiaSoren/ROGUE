"""§11.8 — fetch REAL carrier images for multimodal attacks via Bright Data.

Pipeline step between extraction and reproduction: for each multimodal-image
primitive, take its described carrier (``payload_slots["media_query"]``, e.g.
"bank login screenshot"; falls back to a cleaned title) and use Bright Data
(SERP image search → Web Unlocker download) to fetch a matching REAL image,
cache it to ``data/media_cache/``, and stamp ``payload_slots["base_image"]`` so
the reproduction layer composites the attack overlay onto a real-world carrier
instead of a synthetic Pillow canvas.

COSTLY — spends Bright Data credit (1 SERP search + ≥1 Web Unlocker fetch per
primitive). Cached, so re-runs are free. Run deliberately (never on a timer).

    uv run python scripts/fetch_media_assets.py            # all multimodal-image primitives
    uv run python scripts/fetch_media_assets.py --limit 3  # just a few (demo)
    uv run python scripts/fetch_media_assets.py --primitive-id <id> --query "tax form scan"

Spec: ROGUE_PLAN.md §11.8. Position: harvest → extract → **fetch-media** → reproduce.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.orm.attributes import flag_modified  # noqa: E402

from rogue.db.models import (  # noqa: E402
    AttackPrimitive as AttackPrimitiveORM,
    SourceProvenance as SourceProvenanceORM,
)
from rogue.harvest.bright_data_client import BrightDataClient  # noqa: E402
from rogue.harvest.media_fetch import BrightDataMediaFetcher  # noqa: E402

logger = logging.getLogger("rogue.scripts.fetch_media_assets")

DEFAULT_DATABASE_URL = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"
_MM_IMAGE = "multimodal_image"


def _derive_query(orm: AttackPrimitiveORM) -> str:
    """Carrier query for a primitive with no explicit media_query.

    Heuristic fallback: strip the attack-mechanism tail ("via …", "with …") off
    the title and append "screenshot" so the SERP image search returns a
    plausible real-world carrier. An explicit ``media_query`` always wins.
    """
    title = (orm.title or "").strip()
    base = re.split(r"\b(via|with|using|for)\b", title, maxsplit=1)[0].strip()
    base = base.rstrip(":").strip() or title or "user interface"
    return f"{base} screenshot"


async def run(*, database_url: str, limit: int | None, primitive_id: str | None,
              query_override: str | None) -> int:
    client = BrightDataClient.from_env()
    if not client.api_key:
        logger.error("no BRIGHTDATA_API_KEY — cannot fetch media. Aborting.")
        return 1
    fetcher = BrightDataMediaFetcher(client)

    engine = create_engine(database_url)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    fetched = skipped = failed = 0
    try:
        with SessionLocal() as session:
            stmt = select(AttackPrimitiveORM).where(
                AttackPrimitiveORM.canonical.is_(True),
                AttackPrimitiveORM.vector == _MM_IMAGE,
            )
            if primitive_id is not None:
                stmt = select(AttackPrimitiveORM).where(
                    AttackPrimitiveORM.primitive_id == primitive_id
                )
            if limit is not None:
                stmt = stmt.limit(limit)
            orms = list(session.execute(stmt).scalars())
            logger.info("resolving carriers for %d multimodal-image primitive(s)", len(orms))

            for orm in orms:
                slots = dict(orm.payload_slots or {})
                if slots.get("base_image") and not query_override:
                    skipped += 1
                    continue
                query = query_override or slots.get("media_query") or _derive_query(orm)
                src_url = session.execute(
                    select(SourceProvenanceORM.url)
                    .where(SourceProvenanceORM.primitive_id == orm.primitive_id)
                    .limit(1)
                ).scalar()
                logger.info("primitive=%s query=%r", orm.primitive_id, query)
                path = await fetcher.fetch_base_image_path(
                    query, orm.primitive_id, source_url=src_url, session=session
                )
                if path is None:
                    failed += 1
                    continue
                slots["base_image"] = str(path)
                slots.setdefault("media_query", query)
                orm.payload_slots = slots
                flag_modified(orm, "payload_slots")
                session.commit()
                fetched += 1
    finally:
        await client.aclose()
        engine.dispose()

    logger.info("done: fetched=%d skipped(existing)=%d failed=%d", fetched, skipped, failed)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="§11.8 BD media-carrier fetch.")
    p.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--primitive-id", default=None)
    p.add_argument("--query", default=None, help="override the carrier search query (one primitive)")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    return asyncio.run(run(
        database_url=args.database_url, limit=args.limit,
        primitive_id=args.primitive_id, query_override=args.query,
    ))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
