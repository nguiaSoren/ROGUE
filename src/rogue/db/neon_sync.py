"""Data-only local → Neon sync (no LLM, no BD — free to run on every pipeline run).

The dashboard reads the **Neon** Postgres (Vercel → Render → Neon), but the
`$`-billed pipeline scripts (`harvest_once`, `reproduce_once`, the re-grade
passes) run against the **local** docker Postgres. So a local re-grade /
reproduce never surfaces on the live site until its rows reach Neon. This module
copies the display-critical tables local → Neon with idempotent upserts and
**zero model calls**, so it's safe to run automatically at the end of every
pipeline run (gated by the `NEON_DATABASE_URL` env var being set).

Idempotent: `INSERT ... ON CONFLICT (pk) DO UPDATE` per table, in FK order, so a
re-graded `breach_results` row overwrites the stale verdict on Neon and a new
primitive lands once. Re-running is a no-op beyond re-touching the same rows.

NOT synced: the image FILES under `data/media_cache/` — those are on the local
disk, not in Postgres. The deployed image route only sees them if they're on the
API host's filesystem (a separate file-hosting concern from this DB sync).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import sessionmaker

from rogue.db.models import (
    AttackPrimitive,
    BanditState,
    BreachResult,
    DeploymentConfig,
    PairRefinementStep,
    PrimitiveImage,
    SourceProvenance,
)

logger = logging.getLogger("rogue.db.neon_sync")

__all__ = ["sync", "maybe_auto_sync", "SYNC_MODELS", "SYNC_TABLE_NAMES"]

# Display-critical tables, in FK-dependency order (parents before children) so
# the per-table upsert never trips a foreign-key violation. Operational tables
# (bright_data_cost_log — known ORM/migration drift; fetch_cache — local skip
# cache) are intentionally excluded.
SYNC_MODELS = (
    DeploymentConfig,     # configs first (breach_results FK)
    AttackPrimitive,      # primitives (sources + breach_results + image FK)
    PrimitiveImage,       # DB-stored image bytes (FK → attack_primitives)
    SourceProvenance,     # provenance (FK → attack_primitives)
    BreachResult,         # the verdicts the matrix reads
    PairRefinementStep,   # §10.7 PAIR iters (FK → breach_results)
    BanditState,          # bandit dashboard
)
SYNC_TABLE_NAMES = tuple(m.__tablename__ for m in SYNC_MODELS)

_DEFAULT_CHUNK = 500


def _normalize_url(url: str) -> str:
    """Strip whitespace + a trailing slash so a source==dest compare is robust."""
    return (url or "").strip().rstrip("/")


# The literal tokens from the .env.example placeholder string — if any survive,
# the user hasn't filled in their real Neon credentials yet.
_PLACEHOLDER_TOKENS = ("@HOST/", "@HOST:", "USER:PASS", "://USER:", ":PASS@")


def looks_like_placeholder(url: str) -> bool:
    """True if ``url`` is the un-edited NEON_DATABASE_URL placeholder."""
    u = (url or "").strip()
    return any(tok in u for tok in _PLACEHOLDER_TOKENS)


def _upsert_table(src_session, dst_session, model, *, chunk: int) -> int:
    """Copy every row of one table source → dest via ON CONFLICT DO UPDATE.

    Returns the number of source rows processed. No-op (0) for an empty table.
    """
    table = model.__table__
    rows = [dict(r._mapping) for r in src_session.execute(select(table)).all()]
    if not rows:
        return 0
    pk_names = [c.name for c in table.primary_key.columns]
    for i in range(0, len(rows), chunk):
        batch = rows[i : i + chunk]
        stmt = pg_insert(table).values(batch)
        update_cols = {
            c.name: stmt.excluded[c.name]
            for c in table.columns
            if c.name not in pk_names
        }
        # A PK-only table (no other columns) → nothing to update; just ignore dups.
        if update_cols:
            stmt = stmt.on_conflict_do_update(index_elements=pk_names, set_=update_cols)
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=pk_names)
        dst_session.execute(stmt)
    return len(rows)


def sync(
    source_url: str,
    dest_url: str,
    *,
    models=SYNC_MODELS,
    dry_run: bool = False,
    refresh_snapshot: bool = True,
    chunk: int = _DEFAULT_CHUNK,
) -> dict[str, Any]:
    """Upsert the display-critical tables from ``source_url`` into ``dest_url``.

    Returns ``{"synced": bool, "reason"?: str, "counts": {table: n}}``. Skips
    (synced=False) when source and dest resolve to the same database — running
    the pipeline directly against Neon needs no sync. ``dry_run`` rolls back
    instead of committing. Best-effort snapshot refresh at the end (the baseline
    matrix uses the live view, so this only matters for the materialized
    day-over-day snapshot).
    """
    if _normalize_url(source_url) == _normalize_url(dest_url):
        return {"synced": False, "reason": "source == dest (already on target DB)", "counts": {}}

    src_engine = create_engine(source_url)
    dst_engine = create_engine(dest_url)
    SrcSession = sessionmaker(bind=src_engine)
    DstSession = sessionmaker(bind=dst_engine)

    counts: dict[str, int] = {}
    try:
        with SrcSession() as src, DstSession() as dst:
            for model in models:
                counts[model.__tablename__] = _upsert_table(src, dst, model, chunk=chunk)
            if dry_run:
                dst.rollback()
            else:
                dst.commit()
                if refresh_snapshot:
                    _refresh_snapshot(dst)
    finally:
        src_engine.dispose()
        dst_engine.dispose()

    logger.info(
        "neon_sync: %s %s rows across %d tables → %s",
        "DRY-RUN" if dry_run else "committed",
        sum(counts.values()),
        len(counts),
        _normalize_url(dest_url).rsplit("@", 1)[-1],  # host only, never log creds
    )
    return {"synced": True, "dry_run": dry_run, "counts": counts}


def _refresh_snapshot(dst_session) -> None:
    """Best-effort refresh of the materialized day-over-day snapshot on dest."""
    from sqlalchemy import text

    try:
        dst_session.execute(
            text("REFRESH MATERIALIZED VIEW CONCURRENTLY breach_matrix_daily_snapshot")
        )
        dst_session.commit()
    except Exception as exc:  # noqa: BLE001 — snapshot is optional; live view is primary
        dst_session.rollback()
        logger.info("neon_sync: snapshot refresh skipped (%s)", type(exc).__name__)


def maybe_auto_sync(local_url: str, *, dry_run: bool = False) -> Optional[dict[str, Any]]:
    """Auto-sync hook for the pipeline scripts (free — no LLM/BD spend).

    Runs ``sync(local_url → $NEON_DATABASE_URL)`` iff ``NEON_DATABASE_URL`` is
    set AND differs from the run's own DB. Returns the sync result, or ``None``
    when no Neon target is configured (the common local-only case → no-op).
    Never raises — a sync failure is logged but must not fail the pipeline run
    that already did the expensive work.
    """
    neon_url = os.environ.get("NEON_DATABASE_URL", "").strip()
    if not neon_url:
        return None
    if looks_like_placeholder(neon_url):
        logger.warning(
            "neon_sync: NEON_DATABASE_URL is still the placeholder (USER:PASS@HOST) "
            "— set your real Neon connection string to enable auto-sync. Skipping.",
        )
        return {"synced": False, "reason": "NEON_DATABASE_URL is a placeholder", "counts": {}}
    if _normalize_url(neon_url) == _normalize_url(local_url):
        return None
    try:
        result = sync(local_url, neon_url, dry_run=dry_run)
        if result.get("synced"):
            logger.info("neon_sync: auto-synced to Neon (counts=%s)", result["counts"])
        return result
    except Exception as exc:  # noqa: BLE001 — never fail the pipeline on a sync error
        logger.warning("neon_sync: auto-sync to Neon failed (%s) — local DB is intact", exc)
        return {"synced": False, "reason": str(exc), "counts": {}}
