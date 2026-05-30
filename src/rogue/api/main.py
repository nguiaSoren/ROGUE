"""ROGUE dashboard API — FastAPI backend for the Day-3 Next.js dashboard.

Seven endpoints per ROGUE_PLAN.md §11.1:

  * GET  /api/attacks?since_days=7&family=...        — list AttackPrimitives
  * GET  /api/attacks/{id}                            — full primitive + breach rollup
  * GET  /api/attacks/{id}/image                      — the primitive's real carrier/payload image
  * GET  /api/breaches/matrix?date=YYYY-MM-DD         — breach matrix + CI per cell
  * GET  /api/breaches/cell?family=&config=&date=     — every breaching primitive in one cell
  * GET  /api/brief?date=YYYY-MM-DD&format=...        — threat brief md/json
  * GET  /api/sse/feed                                — Server-Sent Events stream of newest primitives
  * GET  /api/bandit/stats                            — top-3/bottom-3 bandit arms
  * GET  /api/health                                  — liveness check

Design notes:
  * CORS wide-open (`allow_origins=["*"]`) — per §11.1 "no auth"; this is a
    single-tenant demo, the dashboard runs on a different localhost port
    than the backend.
  * Read-only — no POST/PUT/DELETE. The dashboard is a view over the
    harvest+reproduce pipeline's outputs.
  * Engine + session-maker are lazy-built on first request via the
    ``get_session`` dependency so importing this module is zero-IO (matches
    the MCP server pattern).
  * Enum stringification handled by `_enum_str` so the JSON payload is
    always plain strings, not Python enum members.

Run: ``uv run uvicorn rogue.api.main:app --reload --port 8000``
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, FastAPI, HTTPException, Query  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, Response, StreamingResponse  # noqa: E402
from sqlalchemy import create_engine, select, text  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from rogue.db.models import (  # noqa: E402
    AttackPrimitive as AttackPrimitiveORM,
    BreachResult as BreachResultORM,
    DeploymentConfig as DeploymentConfigORM,
    PrimitiveImage as PrimitiveImageORM,
)
from rogue.db.image_cache import (  # noqa: E402
    media_type_for,
    resolve_image_on_disk,
)

logger = logging.getLogger("rogue.api")


DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"
)
THREAT_BRIEFS_DIR = Path("data/threat_briefs")
BANDIT_STATE_PATH = Path("data/discovery_bandit.json")


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


_engine = None
_SessionLocal = None


def get_session() -> Iterator[Session]:
    """FastAPI dependency that yields a Session for the request lifetime.

    Engine + session-maker are lazy-init on first request so importing this
    module remains zero-IO (FastAPI test clients can import without Postgres).
    """
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_engine(_database_url())
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# App + middleware
# --------------------------------------------------------------------------- #


app = FastAPI(
    title="ROGUE Dashboard API",
    description=(
        "Read-only API behind the ROGUE dashboard. Surfaces the harvest + "
        "reproduce pipeline's outputs: attack primitives, breach matrix, "
        "daily threat brief, and bandit telemetry."
    ),
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _enum_str(v: Any) -> Any:
    """Stringify enum members for JSON. Same helper pattern as mcp_server."""
    if v is None:
        return None
    if hasattr(v, "value"):
        return v.value
    return v


def _primitive_to_dict(
    primitive: AttackPrimitiveORM,
    *,
    include_payload: bool = False,
    truncate_payload: bool = True,
) -> dict[str, Any]:
    payload = primitive.payload_template or ""
    if truncate_payload and len(payload) > 500:
        payload = payload[:500] + "...[truncated]"

    # Image availability for the drawer/cell view. DB-stored bytes
    # (primitive_images, synced to Neon) work on the deployed site; the on-disk
    # media-cache file is the local-dev fallback. Served by
    # GET /api/attacks/{id}/image.
    has_image = primitive.image is not None or (
        resolve_image_on_disk(primitive.primitive_id, primitive.payload_slots) is not None
    )

    return {
        "primitive_id": primitive.primitive_id,
        "title": primitive.title,
        "family": _enum_str(primitive.family),
        "vector": _enum_str(primitive.vector),
        "base_severity": _enum_str(primitive.base_severity),
        "short_description": primitive.short_description,
        "payload_template": payload if include_payload else None,
        "requires_multimodal": bool(primitive.requires_multimodal),
        "has_image": has_image,
        "reproducibility_score": primitive.reproducibility_score,
        "canonical": primitive.canonical,
        "cluster_id": primitive.cluster_id,
        "discovered_at": primitive.discovered_at.isoformat() if primitive.discovered_at else None,
        "secondary_families": [_enum_str(f) for f in (primitive.secondary_families or [])],
        "requires_multi_turn": primitive.requires_multi_turn,
        "requires_system_prompt_access": primitive.requires_system_prompt_access,
        "requires_tools": list(primitive.requires_tools or []),
        "sources": [
            {
                "url": s.url,
                "source_type": _enum_str(s.source_type),
                "bright_data_product": _enum_str(s.bright_data_product),
                "author": s.author,
                "fetched_at": s.fetched_at.isoformat() if s.fetched_at else None,
            }
            for s in (primitive.sources or [])
        ],
    }


def _parse_date(s: str | None) -> date:
    if not s or s == "today":
        return datetime.now(timezone.utc).date()
    return date.fromisoformat(s)


# When /matrix or /brief is requested without a ?date=, which day to default to:
#   "most-data"     → the day with the most breach cells (best for a demo / data gap)
#   "most-recent"   → the latest day with data (the right default once daily runs flow)
#   "YYYY-MM-DD"    → pin a specific run day (e.g. 2026-05-30, the fresh-breach day)
# Set the REPORT_DEFAULT_DATE env var to switch with no code change.
REPORT_DEFAULT_DATE = os.getenv("REPORT_DEFAULT_DATE", "most-data")


def _default_report_date(db: Session) -> date | None:
    """The day used by /matrix and /brief when no explicit ?date= is given.

    ``REPORT_DEFAULT_DATE`` may be ``most-recent``, ``most-data`` (default), or a
    literal ``YYYY-MM-DD`` to pin a specific run day.
    """
    if REPORT_DEFAULT_DATE == "most-recent":
        return db.execute(text("SELECT max(run_date) FROM breach_matrix")).scalar()
    if REPORT_DEFAULT_DATE not in ("most-data", ""):
        # Literal pinned date (e.g. "2026-05-30"); fall through on a bad value.
        try:
            return date.fromisoformat(REPORT_DEFAULT_DATE)
        except ValueError:
            logger.warning(
                "REPORT_DEFAULT_DATE=%r is not most-recent/most-data/YYYY-MM-DD; "
                "falling back to most-data", REPORT_DEFAULT_DATE,
            )
    return db.execute(
        text(
            "SELECT run_date FROM breach_matrix GROUP BY run_date "
            "ORDER BY COUNT(*) DESC, run_date DESC LIMIT 1"
        )
    ).scalar()


# --------------------------------------------------------------------------- #
# 1. GET /api/health
# --------------------------------------------------------------------------- #


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Liveness check. Returns counts so the dashboard can show a freshness banner."""
    try:
        # Pull the session manually here so health doesn't error when DB
        # is briefly down — return `db: down` instead of 500.
        for db in get_session():
            n_primitives = db.execute(
                select(text("COUNT(*)")).select_from(AttackPrimitiveORM)
            ).scalar() or 0
            n_breaches = db.execute(
                select(text("COUNT(*)")).select_from(BreachResultORM)
            ).scalar() or 0
            n_configs = db.execute(
                select(text("COUNT(*)")).select_from(DeploymentConfigORM)
            ).scalar() or 0
            return {
                "status": "ok",
                "db": "up",
                "n_primitives": int(n_primitives),
                "n_breaches": int(n_breaches),
                "n_configs": int(n_configs),
                "now": datetime.now(timezone.utc).isoformat(),
            }
    except Exception as exc:  # noqa: BLE001 - health endpoint must never 500
        return {
            "status": "ok",
            "db": "down",
            "error": f"{type(exc).__name__}: {exc}",
            "now": datetime.now(timezone.utc).isoformat(),
        }
    return {"status": "ok", "db": "unknown"}  # unreachable but typing-safe


# --------------------------------------------------------------------------- #
# 2. GET /api/attacks
# --------------------------------------------------------------------------- #


@app.get("/api/attacks")
def list_attacks(
    since_days: int = Query(7, ge=1, le=999),
    family: str | None = Query(None),
    vector: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """List attacks newest-first, optionally filtered by family/vector/recency.

    Graceful fallback: when nothing was discovered inside the ``since_days``
    window (e.g. the harvester hasn't run in 48h), return the newest ``limit``
    attacks regardless of recency and set ``stale=True`` so the UI can relabel
    the panel ("most recent harvest") instead of rendering empty.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    base = select(AttackPrimitiveORM)
    if family:
        base = base.where(AttackPrimitiveORM.family == family)
    if vector:
        base = base.where(AttackPrimitiveORM.vector == vector)

    windowed = (
        base.where(AttackPrimitiveORM.discovered_at >= cutoff)
        .order_by(AttackPrimitiveORM.discovered_at.desc())
        .limit(limit)
    )
    rows = db.execute(windowed).scalars().all()

    stale = False
    if not rows:
        # Nothing in-window — fall back to the newest *harvested* rows regardless
        # of date. Excludes synthesized (escalation/mutation) children so the
        # "captured from the open web" framing stays honest.
        fallback = (
            base.where(AttackPrimitiveORM.synthesized.is_(False))
            .order_by(AttackPrimitiveORM.discovered_at.desc())
            .limit(limit)
        )
        rows = db.execute(fallback).scalars().all()
        stale = bool(rows)  # only "stale" if we actually surfaced older rows

    return {
        "since_days": since_days,
        "family": family,
        "vector": vector,
        "limit": limit,
        "stale": stale,
        "count": len(rows),
        "attacks": [_primitive_to_dict(p, include_payload=True) for p in rows],
    }


# --------------------------------------------------------------------------- #
# 3. GET /api/attacks/{id}
# --------------------------------------------------------------------------- #


@app.get("/api/attacks/{primitive_id}")
def attack_detail(
    primitive_id: str,
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """Full primitive + per-config breach rollup."""
    primitive = db.get(AttackPrimitiveORM, primitive_id)
    if primitive is None:
        raise HTTPException(status_code=404, detail=f"primitive not found: {primitive_id!r}")

    rollup = db.execute(
        text(
            """
            SELECT
                br.deployment_config_id,
                dc.name AS config_name,
                dc.target_model,
                COUNT(*) AS n_trials,
                COUNT(*) FILTER (WHERE br.verdict = 'full_breach') AS n_full,
                COUNT(*) FILTER (WHERE br.verdict = 'partial_breach') AS n_partial,
                COUNT(*) FILTER (WHERE br.verdict = 'refused') AS n_refused,
                COUNT(*) FILTER (WHERE br.verdict = 'evaded') AS n_evaded,
                COUNT(*) FILTER (WHERE br.verdict = 'error') AS n_error,
                AVG(br.judge_confidence) FILTER (WHERE br.verdict != 'error') AS avg_confidence,
                MAX(br.ran_at) AS last_ran_at
            FROM breach_results br
            JOIN deployment_configs dc ON dc.config_id = br.deployment_config_id
            WHERE br.primitive_id = :pid
            GROUP BY br.deployment_config_id, dc.name, dc.target_model
            ORDER BY br.deployment_config_id
            """
        ),
        {"pid": primitive_id},
    ).all()

    return {
        "primitive": _primitive_to_dict(primitive, include_payload=True, truncate_payload=False),
        "breaches": [
            {
                "deployment_config_id": row.deployment_config_id,
                "config_name": row.config_name,
                "target_model": row.target_model,
                "n_trials": int(row.n_trials),
                "n_full_breach": int(row.n_full),
                "n_partial_breach": int(row.n_partial),
                "n_refused": int(row.n_refused),
                "n_evaded": int(row.n_evaded),
                "n_error": int(row.n_error),
                "avg_confidence": float(row.avg_confidence) if row.avg_confidence is not None else None,
                "last_ran_at": row.last_ran_at.isoformat() if row.last_ran_at else None,
            }
            for row in rollup
        ],
    }


# --------------------------------------------------------------------------- #
# 3b. GET /api/attacks/{id}/image  — serve the primitive's real carrier/payload image
# --------------------------------------------------------------------------- #

@app.get("/api/attacks/{primitive_id}/image")
def attack_image(
    primitive_id: str,
    db: Session = Depends(get_session),
):
    """Serve the primitive's real image — the §11.8 fetched carrier OR the
    Feature-A verbatim-ingested payload image.

    DB-FIRST: serves the bytes stored in ``primitive_images`` (synced to Neon →
    works on the deployed site). Falls back to the local ``data/media_cache``
    file (local dev). 404 only when neither has it."""
    row = db.get(PrimitiveImageORM, primitive_id)
    if row is not None and row.image_bytes:
        return Response(content=row.image_bytes, media_type=row.media_type)
    primitive = db.get(AttackPrimitiveORM, primitive_id)
    if primitive is not None:
        resolved = resolve_image_on_disk(primitive_id, primitive.payload_slots or {})
        if resolved is not None:
            return FileResponse(resolved, media_type=media_type_for(resolved))
    raise HTTPException(status_code=404, detail="no image for this primitive")


# --------------------------------------------------------------------------- #
# 4. GET /api/breaches/matrix
# --------------------------------------------------------------------------- #


def _matrix_worst_rows(db: Session, *, date: Any = None, baseline_only: bool = False) -> list[Any]:
    """Worst-case (primitive × config) breach rows aggregated from raw trials.

    The grid takes MAX(any_breach_rate) over techniques per cell. Two optional
    filters drive the SCOPE × ATTACKER 2×2:

    * ``date`` set → SCOPE=this-run (only trials whose ``ran_at`` falls on that day).
      ``None`` → SCOPE=all-time (every run day merged, worst kept).
    * ``baseline_only`` → ATTACKER=baseline (only raw single-shot trials: no
      persona-wrap, no PAIR). ``False`` → ATTACKER=augmented (all techniques,
      worst kept = baseline / persona / PAIR).
    """
    filters: list[str] = []
    params: dict[str, Any] = {}
    if date is not None:
        filters.append("br.ran_at::date = :target_date")
        params["target_date"] = date
    if baseline_only:
        filters.append("br.persona_used IS NULL AND br.pair_attacker_total_cost_usd IS NULL")
    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    return db.execute(
        text(
            f"""
            WITH per_tech AS (
                SELECT
                    br.primitive_id,
                    br.deployment_config_id,
                    CASE
                        WHEN br.pair_attacker_total_cost_usd IS NOT NULL THEN 'pair'
                        WHEN br.persona_used IS NOT NULL THEN 'persona'
                        ELSE 'baseline'
                    END AS technique,
                    COUNT(*) FILTER (WHERE br.verdict != 'error') AS n_judged,
                    COUNT(*) FILTER (WHERE br.verdict IN ('partial_breach','full_breach')) AS n_breach,
                    COUNT(*) FILTER (WHERE br.verdict = 'full_breach') AS n_full,
                    AVG(br.judge_confidence) FILTER (WHERE br.verdict != 'error') AS avg_conf
                FROM breach_results br
                {where}
                GROUP BY 1, 2, 3
            ),
            ranked AS (
                SELECT
                    primitive_id, deployment_config_id, n_judged,
                    n_breach::float / NULLIF(n_judged, 0) AS any_rate,
                    n_full::float / NULLIF(n_judged, 0) AS full_rate,
                    avg_conf
                FROM per_tech WHERE n_judged > 0
            ),
            worst AS (
                SELECT DISTINCT ON (primitive_id, deployment_config_id)
                    primitive_id, deployment_config_id, n_judged, any_rate, full_rate, avg_conf
                FROM ranked
                ORDER BY primitive_id, deployment_config_id, any_rate DESC
            )
            SELECT
                w.primitive_id,
                w.deployment_config_id,
                w.n_judged AS n_trials,
                w.any_rate AS any_breach_rate,
                w.full_rate AS full_breach_rate,
                w.avg_conf AS avg_confidence,
                ap.title, ap.family, ap.vector,
                dc.name AS config_name, dc.target_model
            FROM worst w
            JOIN attack_primitives ap ON ap.primitive_id = w.primitive_id
            JOIN deployment_configs dc ON dc.config_id = w.deployment_config_id
            """
        ),
        params,
    ).all()


@app.get("/api/breaches/matrix")
def breach_matrix(
    date_str: str | None = Query(None, alias="date"),
    include: str = Query("baseline", alias="include"),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """Breach matrix heatmap — drives the SCOPE × ATTACKER 2×2 toggle.

    Four ``include`` modes, one per quadrant:

    * ``baseline`` (default) → SCOPE=this-run × ATTACKER=baseline. Single-shot
      breaches for one day (the clean per-day grid, served from the
      ``breach_matrix`` view, which carries the JUDGE_REFUSED flag).
    * ``thisrun_augmented`` → this-run × augmented. That day's worst-case per cell
      across baseline / persona / PAIR.
    * ``alltime_baseline`` → all-time × baseline. Every run day's raw single-shot
      breaches merged, worst kept per (primitive × config) — no augmentation mixed in.
    * ``augmented`` → all-time × augmented. The highest breach rate any technique
      reached, all days merged. "How bad it gets once the attacker adapts."

    All-time modes merge days because the augmentation sweep ran on a different
    day than the baseline bulk — a per-day augmented view would be empty on the
    default day.
    """
    from rogue.diff.bootstrap import bootstrap_ci

    if date_str and date_str != "today":
        target = _parse_date(date_str)
    else:
        target = _default_report_date(db) or _parse_date(date_str)

    if include == "augmented":
        rows = _matrix_worst_rows(db)
    elif include == "alltime_baseline":
        rows = _matrix_worst_rows(db, baseline_only=True)
    elif include == "thisrun_augmented":
        rows = _matrix_worst_rows(db, date=target)
    else:
        rows = db.execute(
            text(
                """
                SELECT
                    bm.primitive_id,
                    bm.deployment_config_id,
                    bm.n_trials,
                    bm.any_breach_rate,
                    bm.full_breach_rate,
                    bm.avg_confidence,
                    ap.title,
                    ap.family,
                    ap.vector,
                    dc.name AS config_name,
                    dc.target_model,
                    COALESCE(jr.refused, false) AS refused
                FROM breach_matrix bm
                JOIN attack_primitives ap ON ap.primitive_id = bm.primitive_id
                JOIN deployment_configs dc ON dc.config_id = bm.deployment_config_id
                -- did any trial in this cell get graded by the secondary judge
                -- because the primary (Sonnet) refused? (the [JUDGE_REFUSED→…] flag)
                LEFT JOIN (
                    SELECT primitive_id, deployment_config_id, ran_at::date AS rd,
                           bool_or(judge_rationale LIKE '[JUDGE_REFUSED%') AS refused
                    FROM breach_results GROUP BY 1, 2, 3
                ) jr
                  ON jr.primitive_id = bm.primitive_id
                 AND jr.deployment_config_id = bm.deployment_config_id
                 AND jr.rd = bm.run_date
                WHERE bm.run_date = :target_date
                """
            ),
            {"target_date": target},
        ).all()

    cells: list[dict[str, Any]] = []
    families: dict[str, int] = {}
    configs: dict[str, str] = {}
    for r in rows:
        n_trials = int(r.n_trials or 0)
        rate = float(r.any_breach_rate or 0.0)
        n_succ = int(round(rate * n_trials))
        trials = [True] * n_succ + [False] * (n_trials - n_succ)
        ci_lo, ci_hi = bootstrap_ci(trials)

        family_str = _enum_str(r.family) or ""
        families[family_str] = families.get(family_str, 0) + 1
        configs[r.deployment_config_id] = r.config_name

        cells.append(
            {
                "primitive_id": r.primitive_id,
                "title": r.title,
                "family": family_str,
                "vector": _enum_str(r.vector),
                "deployment_config_id": r.deployment_config_id,
                "config_name": r.config_name,
                "target_model": r.target_model,
                "n_trials": n_trials,
                "any_breach_rate": rate,
                "any_breach_ci_lo": ci_lo,
                "any_breach_ci_hi": ci_hi,
                "full_breach_rate": float(r.full_breach_rate or 0.0),
                "avg_confidence": float(r.avg_confidence) if r.avg_confidence is not None else None,
                # True iff the primary (Sonnet) judge refused some trial in this
                # cell and it was graded by the secondary judge. Augmented branch
                # has no such column → defaults to False.
                "refused": bool(r._mapping.get("refused") or False),
            }
        )

    return {
        "target_date": target.isoformat(),
        "n_cells": len(cells),
        "n_primitives": len({c["primitive_id"] for c in cells}),
        "families": sorted(families.keys()),
        "configs": [{"config_id": cid, "config_name": name} for cid, name in sorted(configs.items())],
        "cells": cells,
    }


# --------------------------------------------------------------------------- #
# 4b. GET /api/breaches/cell — EVERY breaching primitive in one (family × config)
# --------------------------------------------------------------------------- #


@app.get("/api/breaches/cell")
def breach_cell(
    family: str = Query(...),
    config_id: str = Query(..., alias="config"),
    date_str: str | None = Query(None, alias="date"),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """All primitives with any-breach > 0 in one (family × config) cell.

    The matrix grid collapses a cell to its single worst-offending primitive;
    this returns the FULL list (sorted worst-first) with the same per-primitive
    detail the drawer shows — payload, provenance, image flag, CI, and the
    verdict histogram — so the dashboard can render a dedicated cell page.
    """
    from rogue.diff.bootstrap import bootstrap_ci

    if date_str and date_str != "today":
        target = _parse_date(date_str)
    else:
        target = _default_report_date(db) or _parse_date(date_str)

    rows = db.execute(
        text(
            """
            SELECT bm.primitive_id, bm.n_trials, bm.any_breach_rate,
                   bm.full_breach_rate, bm.avg_confidence,
                   COALESCE(jr.refused, false) AS refused
            FROM breach_matrix bm
            JOIN attack_primitives ap ON ap.primitive_id = bm.primitive_id
            LEFT JOIN (
                SELECT primitive_id, deployment_config_id, ran_at::date AS rd,
                       bool_or(judge_rationale LIKE '[JUDGE_REFUSED%') AS refused
                FROM breach_results GROUP BY 1, 2, 3
            ) jr
              ON jr.primitive_id = bm.primitive_id
             AND jr.deployment_config_id = bm.deployment_config_id
             AND jr.rd = bm.run_date
            WHERE bm.run_date = :d
              AND ap.family = :fam
              AND bm.deployment_config_id = :cfg
              AND bm.any_breach_rate > 0
            ORDER BY bm.any_breach_rate DESC, bm.full_breach_rate DESC
            """
        ),
        {"d": target, "fam": family, "cfg": config_id},
    ).all()

    # Per-primitive verdict histogram for this config on this day (one query).
    hist_rows = db.execute(
        text(
            """
            SELECT primitive_id,
                   COUNT(*) FILTER (WHERE verdict = 'full_breach')    AS n_full,
                   COUNT(*) FILTER (WHERE verdict = 'partial_breach') AS n_partial,
                   COUNT(*) FILTER (WHERE verdict = 'evaded')         AS n_evaded,
                   COUNT(*) FILTER (WHERE verdict = 'refused')        AS n_refused,
                   COUNT(*) FILTER (WHERE verdict = 'error')          AS n_error,
                   MAX(ran_at) AS last_ran_at
            FROM breach_results
            WHERE deployment_config_id = :cfg AND ran_at::date = :d
            GROUP BY primitive_id
            """
        ),
        {"d": target, "cfg": config_id},
    ).all()
    hist = {r.primitive_id: r for r in hist_rows}

    config = db.get(DeploymentConfigORM, config_id)

    primitives: list[dict[str, Any]] = []
    for r in rows:
        prim = db.get(AttackPrimitiveORM, r.primitive_id)
        if prim is None:
            continue
        detail = _primitive_to_dict(prim, include_payload=True, truncate_payload=False)
        n_trials = int(r.n_trials or 0)
        rate = float(r.any_breach_rate or 0.0)
        n_succ = int(round(rate * n_trials))
        ci_lo, ci_hi = bootstrap_ci([True] * n_succ + [False] * (n_trials - n_succ))
        h = hist.get(r.primitive_id)
        primitives.append(
            {
                **detail,
                "n_trials": n_trials,
                "any_breach_rate": rate,
                "any_breach_ci_lo": ci_lo,
                "any_breach_ci_hi": ci_hi,
                "full_breach_rate": float(r.full_breach_rate or 0.0),
                "avg_confidence": float(r.avg_confidence) if r.avg_confidence is not None else None,
                "refused": bool(r.refused),
                "histogram": {
                    "full_breach": int(h.n_full) if h else 0,
                    "partial_breach": int(h.n_partial) if h else 0,
                    "evaded": int(h.n_evaded) if h else 0,
                    "refused": int(h.n_refused) if h else 0,
                    "error": int(h.n_error) if h else 0,
                },
                "last_ran_at": h.last_ran_at.isoformat() if h and h.last_ran_at else None,
            }
        )

    return {
        "target_date": target.isoformat(),
        "family": family,
        "config_id": config_id,
        "config_name": config.name if config else config_id,
        "target_model": config.target_model if config else None,
        "n_primitives": len(primitives),
        "primitives": primitives,
    }


# --------------------------------------------------------------------------- #
# 5. GET /api/brief
# --------------------------------------------------------------------------- #


@app.get("/api/brief")
def brief(
    date_str: str | None = Query(None, alias="date"),
    format: str = Query("markdown"),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """Threat brief in markdown OR json. Reads disk artifact, falls back to live render."""
    fmt = format.lower()
    if fmt not in ("markdown", "json"):
        raise HTTPException(status_code=400, detail="format must be 'markdown' or 'json'")
    if date_str and date_str != "today":
        target = _parse_date(date_str)
    else:
        target = _default_report_date(db) or _parse_date(date_str)

    ext = "md" if fmt == "markdown" else "json"
    brief_path = THREAT_BRIEFS_DIR / f"{target.isoformat()}.{ext}"

    if brief_path.exists():
        content = brief_path.read_text(encoding="utf-8")
        if fmt == "markdown":
            return {"target_date": target.isoformat(), "format": fmt, "markdown": content, "from_disk": True}
        return {"target_date": target.isoformat(), "format": fmt, "json": json.loads(content), "from_disk": True}

    # Live render fallback.
    from rogue.diff.threat_brief import ThreatBriefBuilder

    builder = ThreatBriefBuilder(session=db)
    diff = builder.build_diff(customer_id="acme", target_date=target)
    if fmt == "markdown":
        return {"target_date": target.isoformat(), "format": fmt, "markdown": builder.render_markdown(diff), "from_disk": False}
    return {"target_date": target.isoformat(), "format": fmt, "json": builder.render_json(diff), "from_disk": False}


# --------------------------------------------------------------------------- #
# 6. GET /api/sse/feed — Server-Sent Events stream of newest primitives
# --------------------------------------------------------------------------- #


@app.get("/api/sse/feed")
async def sse_feed(
    since_days: int = Query(1, ge=1, le=30),
):
    """Server-Sent Events stream. Sends one initial snapshot + heartbeats every 15s.

    For the demo we don't run a true subscription on the DB — the dashboard
    polls this endpoint and gets a fresh snapshot of the last `since_days`
    primitives on each connection. Heartbeats keep the connection alive so
    the frontend's reconnect logic doesn't churn.
    """
    import asyncio as _aio

    async def gen():
        # Initial snapshot.
        for db in get_session():
            cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
            stmt = (
                select(AttackPrimitiveORM)
                .where(AttackPrimitiveORM.discovered_at >= cutoff)
                .order_by(AttackPrimitiveORM.discovered_at.desc())
                .limit(50)
            )
            rows = db.execute(stmt).scalars().all()
            payload = {
                "type": "snapshot",
                "count": len(rows),
                "primitives": [_primitive_to_dict(p) for p in rows],
                "now": datetime.now(timezone.utc).isoformat(),
            }
            yield f"event: snapshot\ndata: {json.dumps(payload)}\n\n"
            break

        # Keepalive heartbeats. The frontend reconnects on disconnect, so each
        # connection lives 15-60s; this loop just keeps it open until the
        # client closes.
        while True:
            await _aio.sleep(15)
            yield f": heartbeat {datetime.now(timezone.utc).isoformat()}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# --------------------------------------------------------------------------- #
# 7. GET /api/persona/stats — §10.7 persona augmentation A/B
# --------------------------------------------------------------------------- #


@app.get("/api/persona/stats")
def persona_stats(
    min_trials: int = Query(
        5,
        ge=1,
        le=100,
        description=(
            "Suppress (config, persona) cells with fewer than this many "
            "wrapped trials — small samples produce misleading deltas."
        ),
    ),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """§10.7 persona susceptibility per (deployment_config × PAP technique).

    Compares wrapped (``persona_used IS NOT NULL``) breach rate to the
    unwrapped baseline (``persona_used IS NULL``) for the same config, over
    BREACH verdicts (partial_breach OR full_breach), excluding ERROR rows.

    ``delta`` is the headline metric: positive means the persona wrap raised
    breach rate vs baseline (the deck claim — "configs vulnerable to social
    engineering layers"); negative means the wrap actually *protected* the
    target (rarer but real for techniques the target was fine-tuned against).

    Refusal-suffix variants (``"X__refused"``) are reported under their own
    row so the dashboard can distinguish "persona was applied + target
    breached" from "wrapper refused + fell back to original + target's
    response is the unwrapped baseline result".

    Read-only. Returns empty arrays + ``baseline_n_trials=0`` when no
    persona-wrapped runs have been persisted yet (fresh DB / pre-§10.7
    state).
    """
    # Unwrapped baseline per config — denominator of the comparison.
    baseline_rows = db.execute(
        text(
            """
            SELECT
                br.deployment_config_id,
                dc.name AS config_name,
                dc.target_model,
                COUNT(*) FILTER (WHERE br.verdict != 'error') AS n_judged,
                COUNT(*) FILTER (WHERE br.verdict IN ('partial_breach', 'full_breach')) AS n_breach
            FROM breach_results br
            JOIN deployment_configs dc ON dc.config_id = br.deployment_config_id
            WHERE br.persona_used IS NULL
              AND br.pair_attacker_total_cost_usd IS NULL
            GROUP BY br.deployment_config_id, dc.name, dc.target_model
            """
        ),
    ).all()

    baselines: dict[str, dict[str, Any]] = {}
    for r in baseline_rows:
        n_judged = int(r.n_judged or 0)
        n_breach = int(r.n_breach or 0)
        baselines[r.deployment_config_id] = {
            "config_id": r.deployment_config_id,
            "config_name": r.config_name,
            "target_model": r.target_model,
            "baseline_n_trials": n_judged,
            "baseline_breach_rate": (n_breach / n_judged) if n_judged else 0.0,
        }

    # Wrapped breakdown per (config, persona).
    wrapped_rows = db.execute(
        text(
            """
            SELECT
                br.deployment_config_id,
                dc.name AS config_name,
                dc.target_model,
                br.persona_used,
                COUNT(*) FILTER (WHERE br.verdict != 'error') AS n_judged,
                COUNT(*) FILTER (WHERE br.verdict IN ('partial_breach', 'full_breach')) AS n_breach,
                COUNT(*) FILTER (WHERE br.verdict = 'full_breach') AS n_full_breach
            FROM breach_results br
            JOIN deployment_configs dc ON dc.config_id = br.deployment_config_id
            WHERE br.persona_used IS NOT NULL
              AND br.pair_attacker_total_cost_usd IS NULL
            GROUP BY br.deployment_config_id, dc.name, dc.target_model, br.persona_used
            ORDER BY br.deployment_config_id, br.persona_used
            """
        ),
    ).all()

    cells: list[dict[str, Any]] = []
    per_config_max_delta: dict[str, float] = {}
    for r in wrapped_rows:
        n_judged = int(r.n_judged or 0)
        if n_judged < min_trials:
            continue
        n_breach = int(r.n_breach or 0)
        wrapped_rate = (n_breach / n_judged) if n_judged else 0.0
        baseline = baselines.get(r.deployment_config_id)
        baseline_rate = (
            baseline["baseline_breach_rate"] if baseline else 0.0
        )
        delta = wrapped_rate - baseline_rate
        cells.append(
            {
                "config_id": r.deployment_config_id,
                "config_name": r.config_name,
                "target_model": r.target_model,
                "persona_used": r.persona_used,
                "is_refusal_fallback": r.persona_used.endswith("__refused"),
                "n_wrapped_trials": n_judged,
                "n_wrapped_breach": n_breach,
                "n_wrapped_full_breach": int(r.n_full_breach or 0),
                "wrapped_breach_rate": wrapped_rate,
                "baseline_breach_rate": baseline_rate,
                "delta": delta,
            }
        )
        prev = per_config_max_delta.get(r.deployment_config_id, float("-inf"))
        if delta > prev:
            per_config_max_delta[r.deployment_config_id] = delta

    # Per-config rollup: max delta across all techniques = headline
    # persona-susceptibility score for that deployment.
    rollup = []
    for cid, baseline in baselines.items():
        rollup.append(
            {
                **baseline,
                "max_delta": (
                    per_config_max_delta[cid]
                    if cid in per_config_max_delta
                    else None
                ),
                "n_techniques_tried": sum(
                    1 for c in cells if c["config_id"] == cid
                ),
            },
        )
    rollup.sort(
        key=lambda r: (
            r.get("max_delta") if r.get("max_delta") is not None else float("-inf")
        ),
        reverse=True,
    )

    cells.sort(key=lambda c: c["delta"], reverse=True)

    return {
        "min_trials": min_trials,
        "n_configs_with_baseline": len(baselines),
        "n_cells": len(cells),
        "per_config": rollup,
        "cells": cells,
    }


# --------------------------------------------------------------------------- #
# 8. GET /api/escalation/stats — §10.7 multi-turn escalation A/B
# --------------------------------------------------------------------------- #


@app.get("/api/escalation/stats")
def escalation_stats(
    min_trials: int = Query(
        5,
        ge=1,
        le=100,
        description=(
            "Suppress (config, synthesized) cells with fewer than this many "
            "trials — small samples produce misleading deltas."
        ),
    ),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """§10.7 escalation-vulnerability per deployment_config.

    Compares synthesized (multi-turn escalation) breach rate to the
    harvested (single-turn parent) baseline for the same config. Only
    counts breach rows whose primitive has ``derived_from_primitive_id``
    populated AND whose parent itself has at least one breach row in the
    matrix — so the A/B is anchored on the same set of (parent → escalation)
    pairs.

    Per-config rollup:
      - ``baseline_breach_rate``: mean any-breach rate across the parent
        primitives this config was tested on.
      - ``escalated_breach_rate``: mean any-breach rate across the
        synthesized children of those parents.
      - ``delta``: escalated − baseline; positive = the escalation helped
        the attacker, which is the deck claim ("watch this single-turn
        primitive fail at turn 1, escalated 3-turn version breach at
        turn 3").

    Read-only. Returns empty arrays when no synthesized primitives have
    been planned yet.
    """
    rows = db.execute(
        text(
            """
            WITH escalation_pairs AS (
                SELECT
                    child.primitive_id AS child_id,
                    child.derived_from_primitive_id AS parent_id
                FROM attack_primitives child
                WHERE child.synthesized = true
                  AND child.derived_from_primitive_id IS NOT NULL
            ),
            child_rates AS (
                SELECT
                    ep.parent_id,
                    br.deployment_config_id,
                    COUNT(*) FILTER (WHERE br.verdict != 'error') AS n_judged,
                    COUNT(*) FILTER (WHERE br.verdict IN ('partial_breach','full_breach')) AS n_breach
                FROM escalation_pairs ep
                JOIN breach_results br ON br.primitive_id = ep.child_id
                GROUP BY ep.parent_id, br.deployment_config_id
            ),
            parent_rates AS (
                SELECT
                    ep.parent_id,
                    br.deployment_config_id,
                    COUNT(*) FILTER (WHERE br.verdict != 'error') AS n_judged,
                    COUNT(*) FILTER (WHERE br.verdict IN ('partial_breach','full_breach')) AS n_breach
                FROM escalation_pairs ep
                JOIN breach_results br ON br.primitive_id = ep.parent_id
                GROUP BY ep.parent_id, br.deployment_config_id
            )
            SELECT
                dc.config_id,
                dc.name AS config_name,
                dc.target_model,
                SUM(p.n_judged) AS parent_n_judged,
                SUM(p.n_breach) AS parent_n_breach,
                SUM(c.n_judged) AS child_n_judged,
                SUM(c.n_breach) AS child_n_breach
            FROM child_rates c
            JOIN parent_rates p
              ON p.parent_id = c.parent_id
             AND p.deployment_config_id = c.deployment_config_id
            JOIN deployment_configs dc ON dc.config_id = c.deployment_config_id
            GROUP BY dc.config_id, dc.name, dc.target_model
            ORDER BY dc.config_id
            """
        ),
    ).all()

    per_config: list[dict[str, Any]] = []
    for r in rows:
        child_n = int(r.child_n_judged or 0)
        parent_n = int(r.parent_n_judged or 0)
        if child_n < min_trials or parent_n < min_trials:
            continue
        child_breach = int(r.child_n_breach or 0)
        parent_breach = int(r.parent_n_breach or 0)
        baseline_rate = parent_breach / parent_n if parent_n else 0.0
        escalated_rate = child_breach / child_n if child_n else 0.0
        per_config.append(
            {
                "config_id": r.config_id,
                "config_name": r.config_name,
                "target_model": r.target_model,
                "parent_n_trials": parent_n,
                "child_n_trials": child_n,
                "baseline_breach_rate": baseline_rate,
                "escalated_breach_rate": escalated_rate,
                "delta": escalated_rate - baseline_rate,
            },
        )

    per_config.sort(key=lambda r: r["delta"], reverse=True)

    # Total synthesized count for the dashboard header.
    n_synthesized = db.execute(
        text(
            "SELECT COUNT(*) FROM attack_primitives WHERE synthesized = true"
        ),
    ).scalar() or 0
    n_with_parents = db.execute(
        text(
            "SELECT COUNT(DISTINCT derived_from_primitive_id) "
            "FROM attack_primitives "
            "WHERE synthesized = true AND derived_from_primitive_id IS NOT NULL"
        ),
    ).scalar() or 0

    return {
        "min_trials": min_trials,
        "n_synthesized_primitives": int(n_synthesized),
        "n_parents_escalated": int(n_with_parents),
        "n_configs_with_pairs": len(per_config),
        "per_config": per_config,
    }


# --------------------------------------------------------------------------- #
# 9. GET /api/mutation/stats — §10.7 surface-pattern-matching A/B
# --------------------------------------------------------------------------- #


@app.get("/api/mutation/stats")
def mutation_stats(
    min_trials: int = Query(
        5,
        ge=1,
        le=100,
        description=(
            "Suppress (config, parent) cells with fewer than this many trials."
        ),
    ),
    evade_threshold: float = Query(
        0.4,
        ge=0.0,
        le=1.0,
        description=(
            "A config 'defended' the parent if its any_breach_rate is BELOW "
            "this threshold. Default 0.4 matches §10.7 EVADE-band."
        ),
    ),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """§10.7 surface-pattern-matching score per deployment_config.

    For each (parent → mutation child) pair, look at every config that
    DEFENDED the parent (parent any_breach_rate < ``evade_threshold``). If
    that same config FAILS on the mutated child (child any_breach_rate >=
    threshold), the config was pattern-matching the specific wording of the
    parent rather than understanding the underlying technique. The
    per-config "pattern-matching score" is the fraction of
    parent-defended cells where a mutation slipped through.

    Mutation rows are identified by ``synthesized=true AND
    requires_multi_turn=false AND derived_from_primitive_id IS NOT NULL``
    (escalation children are multi-turn and excluded from this query so the
    two augmentations don't pollute each other's metrics).

    Read-only. Returns ``per_config = []`` when no mutation rows exist yet.
    """
    rows = db.execute(
        text(
            """
            WITH mutation_pairs AS (
                SELECT
                    child.primitive_id AS child_id,
                    child.derived_from_primitive_id AS parent_id
                FROM attack_primitives child
                WHERE child.synthesized = true
                  AND child.requires_multi_turn = false
                  AND child.derived_from_primitive_id IS NOT NULL
            ),
            cell_rates AS (
                SELECT
                    primitive_id,
                    deployment_config_id,
                    COUNT(*) FILTER (WHERE verdict != 'error') AS n_judged,
                    COUNT(*) FILTER (WHERE verdict IN ('partial_breach','full_breach')) AS n_breach
                FROM breach_results
                GROUP BY primitive_id, deployment_config_id
            )
            SELECT
                dc.config_id,
                dc.name AS config_name,
                dc.target_model,
                mp.parent_id,
                mp.child_id,
                parent.n_judged AS parent_n_judged,
                parent.n_breach AS parent_n_breach,
                child.n_judged AS child_n_judged,
                child.n_breach AS child_n_breach
            FROM mutation_pairs mp
            JOIN cell_rates child ON child.primitive_id = mp.child_id
            JOIN cell_rates parent
              ON parent.primitive_id = mp.parent_id
             AND parent.deployment_config_id = child.deployment_config_id
            JOIN deployment_configs dc ON dc.config_id = child.deployment_config_id
            """
        ),
    ).all()

    # Aggregate by config: count parent-defended cells and how many "leaked"
    # (mutation breached where parent did not).
    per_config_agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        parent_n = int(r.parent_n_judged or 0)
        child_n = int(r.child_n_judged or 0)
        if parent_n < min_trials or child_n < min_trials:
            continue
        parent_rate = (int(r.parent_n_breach or 0) / parent_n) if parent_n else 0.0
        child_rate = (int(r.child_n_breach or 0) / child_n) if child_n else 0.0
        parent_defended = parent_rate < evade_threshold
        child_breached = child_rate >= evade_threshold

        agg = per_config_agg.setdefault(
            r.config_id,
            {
                "config_id": r.config_id,
                "config_name": r.config_name,
                "target_model": r.target_model,
                "n_pairs": 0,
                "n_parent_defended": 0,
                "n_parent_defended_child_breached": 0,
            },
        )
        agg["n_pairs"] += 1
        if parent_defended:
            agg["n_parent_defended"] += 1
            if child_breached:
                agg["n_parent_defended_child_breached"] += 1

    per_config = []
    for agg in per_config_agg.values():
        denom = agg["n_parent_defended"]
        score = (
            agg["n_parent_defended_child_breached"] / denom if denom else None
        )
        per_config.append(
            {
                **agg,
                # Higher = more pattern-matching, less robust defense. None
                # when no parent-defended cells exist for this config.
                "pattern_matching_score": score,
            },
        )

    per_config.sort(
        key=lambda r: (
            r.get("pattern_matching_score")
            if r.get("pattern_matching_score") is not None
            else -1.0
        ),
        reverse=True,
    )

    # Total mutation counts for the dashboard header.
    n_mutations = db.execute(
        text(
            """
            SELECT COUNT(*) FROM attack_primitives
             WHERE synthesized = true
               AND requires_multi_turn = false
               AND derived_from_primitive_id IS NOT NULL
            """
        ),
    ).scalar() or 0
    n_parents_mutated = db.execute(
        text(
            """
            SELECT COUNT(DISTINCT derived_from_primitive_id)
            FROM attack_primitives
             WHERE synthesized = true
               AND requires_multi_turn = false
               AND derived_from_primitive_id IS NOT NULL
            """
        ),
    ).scalar() or 0

    return {
        "min_trials": min_trials,
        "evade_threshold": evade_threshold,
        "n_mutation_primitives": int(n_mutations),
        "n_parents_mutated": int(n_parents_mutated),
        "n_configs_with_pairs": len(per_config),
        "per_config": per_config,
    }


# --------------------------------------------------------------------------- #
# 10. GET /api/stubbornness/stats — §10.7 PAIR per-config stubbornness
# --------------------------------------------------------------------------- #


@app.get("/api/stubbornness/stats")
def stubbornness_stats(
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """§10.7 full PAIR build: per-config "stubbornness" = mean iters-to-breach.

    Reads ``breach_results.pair_iters_to_breach`` (set by PAIR runs only;
    NULL elsewhere). For each config, computes:
      - n_pair_cells: cells that went through PAIR
      - n_breached: of those, how many actually breached (pair_iters_to_breach
                    IS NOT NULL means PAIR ran AND breached)
      - avg_iters_to_breach: among breached cells, average iter index of
                              first breach (lower = vulnerable, higher = robust)
      - never_breach_rate: fraction of PAIR cells PAIR couldn't crack
      - total_attacker_cost_usd: sum across cells

    Refinement-type distribution: top-3 refinement strategies seen across
    all RefinementSteps, for the chart's tag-cloud display.

    Read-only. Returns empty arrays when no PAIR rows have been persisted.
    """
    config_rows = db.execute(
        text(
            """
            SELECT
                br.deployment_config_id,
                dc.name AS config_name,
                dc.target_model,
                COUNT(*) FILTER (WHERE br.pair_attacker_total_cost_usd IS NOT NULL) AS n_pair_cells,
                COUNT(*) FILTER (WHERE br.pair_iters_to_breach IS NOT NULL) AS n_breached,
                AVG(br.pair_iters_to_breach) FILTER (
                    WHERE br.pair_iters_to_breach IS NOT NULL
                ) AS avg_iters_to_breach,
                SUM(COALESCE(br.pair_attacker_total_cost_usd, 0.0)) FILTER (
                    WHERE br.pair_attacker_total_cost_usd IS NOT NULL
                ) AS total_attacker_cost_usd
            FROM breach_results br
            JOIN deployment_configs dc ON dc.config_id = br.deployment_config_id
            WHERE br.pair_attacker_total_cost_usd IS NOT NULL
            GROUP BY br.deployment_config_id, dc.name, dc.target_model
            ORDER BY avg_iters_to_breach NULLS LAST, dc.name
            """
        ),
    ).all()

    per_config = []
    for r in config_rows:
        n_pair = int(r.n_pair_cells or 0)
        n_breached = int(r.n_breached or 0)
        per_config.append(
            {
                "config_id": r.deployment_config_id,
                "config_name": r.config_name,
                "target_model": r.target_model,
                "n_pair_cells": n_pair,
                "n_breached": n_breached,
                "avg_iters_to_breach": (
                    float(r.avg_iters_to_breach)
                    if r.avg_iters_to_breach is not None
                    else None
                ),
                "never_breach_rate": (
                    (n_pair - n_breached) / n_pair if n_pair else None
                ),
                "total_attacker_cost_usd": float(r.total_attacker_cost_usd or 0.0),
            },
        )

    # Refinement-type distribution across all PAIR steps.
    type_rows = db.execute(
        text(
            """
            SELECT refinement_type, COUNT(*) AS n_steps
            FROM pair_refinement_steps
            GROUP BY refinement_type
            ORDER BY n_steps DESC
            """
        ),
    ).all()
    refinement_type_distribution = [
        {"refinement_type": r.refinement_type, "n_steps": int(r.n_steps)}
        for r in type_rows
    ]

    total_pair_cells = sum(c["n_pair_cells"] for c in per_config)
    total_breached = sum(c["n_breached"] for c in per_config)
    total_steps = db.execute(
        text("SELECT COUNT(*) FROM pair_refinement_steps"),
    ).scalar() or 0

    return {
        "n_pair_cells": total_pair_cells,
        "n_breached": total_breached,
        "n_refinement_steps": int(total_steps),
        "per_config": per_config,
        "refinement_type_distribution": refinement_type_distribution,
    }


# --------------------------------------------------------------------------- #
# 11. GET /api/bandit/stats
# --------------------------------------------------------------------------- #


@app.get("/api/bandit/stats")
def bandit_stats(db: Session = Depends(get_session)) -> dict[str, Any]:
    """Top-3 / bottom-3 bandit arms by yield-per-dollar + last-updated timestamp.

    Live from the DB: reads the ``bandit_state`` row (upserted by each harvest),
    so the widget updates without a redeploy. Falls back to the on-disk
    ``data/discovery_bandit.json`` if the DB row isn't present yet, and returns
    empty arm lists rather than 500 when neither exists.
    """
    from rogue.db.bandit_state import load_bandit_state

    state = load_bandit_state(db)
    if not state:
        if not BANDIT_STATE_PATH.exists():
            return {
                "updated_at": None,
                "n_arms": 0,
                "top_arms": [],
                "bottom_arms": [],
                "note": "bandit state not found — run scripts/harvest_once.py to seed it",
            }
        try:
            state = json.loads(BANDIT_STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail=f"bandit state unreadable: {exc}")

    arms = state.get("arms", [])
    warm = [a for a in arms if a.get("pulls", 0) > 0]
    warm.sort(key=lambda a: a.get("mean_yield", 0.0), reverse=True)

    return {
        "updated_at": state.get("updated_at"),
        "seeded_from_corpus_at": state.get("seeded_from_corpus_at"),
        "last_live_pulled_at": state.get("last_live_pulled_at"),
        "epsilon": state.get("epsilon"),
        "n_arms": len(arms),
        "n_warm_arms": len(warm),
        "top_arms": warm[:3],
        "bottom_arms": warm[-3:] if len(warm) >= 3 else [],
    }
