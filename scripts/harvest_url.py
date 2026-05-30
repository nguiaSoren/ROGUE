"""Harvest ONE specific URL on demand → extract → dedup → persist (→ Neon).

For grabbing a single post that BD's profile/discovery scrapers won't return —
e.g. an **X status URL** (their discover-by-profile scraper returns empty for X,
but Web Unlocker on the exact status URL works). Fetches the page via Web
Unlocker, pulls its images (X `pbs.twimg.com/media/...` screenshots, or generic
`<img>`), runs the **multimodal** extraction (the jailbreak lives in the
screenshot → Feature A), dedups, persists, and auto-syncs to Neon.

Usage::

    uv run python scripts/harvest_url.py --url "https://x.com/elder_plinius/status/2060085595808936024"
    uv run python scripts/harvest_url.py --url "<any page>" --source-type blog
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make the repo root importable so `from scripts.harvest_once import ...` works
# when this file is run directly (python scripts/harvest_url.py puts scripts/ on
# the path, not the repo root).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from rogue.dedupe.embeddings import Deduplicator  # noqa: E402
from rogue.extract.extraction_agent import ExtractionAgent, ExtractionImage  # noqa: E402
from rogue.harvest.bandit_serp_phase import _infer_source_type  # noqa: E402
from rogue.harvest.bright_data_client import BrightDataClient  # noqa: E402
from rogue.harvest.media_extract import media_urls_for_document  # noqa: E402
from rogue.harvest.media_ingest import MediaIngestor  # noqa: E402
from rogue.harvest.x_status import parse_x_status  # noqa: E402
from rogue.schemas import RawDocument  # noqa: E402

logger = logging.getLogger("rogue.scripts.harvest_url")

DEFAULT_DATABASE_URL = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"


def _is_x(url: str) -> bool:
    return "x.com/" in url or "twitter.com/" in url


def _default_openai_embed_fn(model: str = "text-embedding-3-small"):
    from openai import OpenAI

    client = OpenAI()

    def embed_fn(text: str) -> list[float]:
        return list(client.embeddings.create(model=model, input=text).data[0].embedding)

    return embed_fn


async def harvest_url(url: str, database_url: str, source_type: str | None) -> int:
    bd = BrightDataClient.from_env()
    try:
        logger.info("web_unlock %s", url)
        page = await bd.web_unlock(url, format="html")
        html = page.content or ""
        logger.info("fetched %d bytes (status %s)", len(html), page.status_code)

        if _is_x(url):
            raw_content, media_urls = parse_x_status(html, url)
            content_format = "text"
        else:
            raw_content, content_format = html, "html"
            media_urls = media_urls_for_document(
                media_urls=[], raw_content=html, content_format="html", base_url=url
            )
        logger.info("media images found: %d -> %s", len(media_urls),
                    [u.split("/media/")[-1][:20] for u in media_urls])

        st = source_type or _infer_source_type(url)
        doc = RawDocument(
            url=url,
            source_type=st,  # type: ignore[arg-type]
            bright_data_product="web_unlocker",
            fetched_at=datetime.now(timezone.utc),
            raw_content=raw_content[:2_000_000],
            content_format=content_format,  # type: ignore[arg-type]
            archive_hash=hashlib.sha256(raw_content.encode("utf-8")).hexdigest(),
            http_status=page.status_code,
            metadata={"on_demand": True},
            discovered_via="harvest_url",
            media_urls=media_urls,
        )

        # Download + vision-read the screenshots (Feature A).
        ingestor = MediaIngestor(bd, max_images_per_doc=8)
        ingested = await ingestor.ingest_for_document(doc, limit=8)
        logger.info("ingested %d image(s)", len(ingested))
        images = [
            ExtractionImage(b64=i.b64, media_type=i.media_type, source_url=i.url, path=str(i.path))
            for i in ingested
        ] or None

        extractor = ExtractionAgent()
        primitive = await extractor.extract_from_raw_document(doc, images=images)
    finally:
        await bd.aclose()

    if primitive is None:
        logger.warning("extraction returned None — the page did not yield an attack primitive")
        print("no attack primitive extracted from this URL")
        return 1

    logger.info("extracted primitive: %s (%s / %s)",
                primitive.title, primitive.family.value, primitive.vector.value)

    # Persist with dedup, then cache images + sync to Neon.
    from scripts.harvest_once import _ensure_primitive_has_provenance, _to_orm_primitive

    engine = create_engine(database_url)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with SessionLocal() as session:
            primitive = _ensure_primitive_has_provenance(primitive, doc)
            orm = _to_orm_primitive(primitive)
            Deduplicator(session=session, embed_fn=_default_openai_embed_fn()).assign_cluster(orm)
            session.add(orm)
            session.commit()
            logger.info("persisted primitive_id=%s canonical=%s cluster=%s",
                        orm.primitive_id, orm.canonical, orm.cluster_id)
            pid = orm.primitive_id
    finally:
        engine.dispose()

    from rogue.db.image_cache import maybe_cache_images
    from rogue.db.neon_sync import maybe_auto_sync

    maybe_cache_images(database_url)
    maybe_auto_sync(database_url)

    print(f"\nHARVESTED: {primitive.title}")
    print(f"  family={primitive.family.value}  vector={primitive.vector.value}  primitive_id={pid}")
    print(f"  reproduce it:  uv run python scripts/reproduce_once.py --primitive-ids {pid}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Harvest a single URL on demand (web_unlock + extract).")
    p.add_argument("--url", required=True)
    p.add_argument("--source-type", default=None, help="Override the inferred source_type (e.g. 'x').")
    p.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    return asyncio.run(harvest_url(args.url, args.database_url, args.source_type))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
