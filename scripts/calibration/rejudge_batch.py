"""Re-grade breach_results via the Anthropic Batch API (50% off + prompt cache).

The cheap, latency-tolerant way to (re-)grade a lot of cells: submit one batch,
poll, collect, fall back to the secondary judge on refusals, write the verdicts
back. Use for bulk backfills / re-grades during a long harvest — flat 50% off
vs the inline judge, and the rubric is prompt-cached on top.

Run from the repo root::

    # everything for a run_date (or --error-only for just the ERROR cells):
    uv run python scripts/calibration/rejudge_batch.py --date 2026-05-26 --dry-run
    uv run python scripts/calibration/rejudge_batch.py --date 2026-05-26 --yes
    uv run python scripts/calibration/rejudge_batch.py --error-only --yes        # all ERROR rows

**Spends money** (batched, so ~half the inline cost). Gated behind ``--yes``;
``--dry-run`` shows the row count + estimate for free. The batch can take
minutes–24h to finish — that's the trade for 50% off.

Spec: ROGUE_PLAN.md §10.2 + the judge cost-ladder note.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import create_engine, select, text as sqltext  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from rogue.db.models import (  # noqa: E402
    AttackPrimitive as AttackPrimitiveORM,
    BreachResult as BreachResultORM,
)
from rogue.reproduce.instantiator import RenderedAttack  # noqa: E402
from rogue.reproduce.judge import JudgeAgent  # noqa: E402
from rogue.reproduce.judge_batch import BatchGradeItem, JudgeBatch  # noqa: E402
from rogue.schemas import JudgeVerdict  # noqa: E402

logger = logging.getLogger("rogue.scripts.calibration.rejudge_batch")

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"
)
# Batched Sonnet ≈ half the inline cached cost (~$0.0064 → ~$0.0032/cell).
_BATCH_COST_ESTIMATE_PER_CELL_USD = 0.0032
_KEEPALIVE = dict(
    keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5
)


def _engine(url: str):
    return create_engine(
        url, pool_pre_ping=True, pool_recycle=180, connect_args=_KEEPALIVE
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=None, help="run_date (YYYY-MM-DD) to re-grade")
    parser.add_argument(
        "--error-only", action="store_true", help="only re-grade verdict='error' rows"
    )
    parser.add_argument(
        "--breaches-only",
        action="store_true",
        help="only re-grade current breach cells (full_breach + partial_breach) — the targeted v3 re-judge",
    )
    parser.add_argument(
        "--changeable-only",
        action="store_true",
        help="re-grade every cell whose verdict v3 can change: full_breach + partial_breach + error "
        "(skips refused/evaded, which v3 never upgrades) — one combined batch",
    )
    parser.add_argument("--dry-run", action="store_true", help="count + estimate, free")
    parser.add_argument("--yes", action="store_true", help="confirm the paid batch run")
    parser.add_argument(
        "--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    )
    args = parser.parse_args(argv)

    eng = _engine(args.database_url)
    S = sessionmaker(bind=eng)
    sys.path.insert(0, str(_REPO_ROOT))
    from scripts.reproduce.reproduce_once import _orm_to_pydantic_primitive  # noqa: PLC0415

    # 1) load rows + primitives into memory
    with S() as s:
        stmt = select(BreachResultORM)
        if args.date:
            stmt = stmt.where(sqltext("breach_results.ran_at::date = :d")).params(d=args.date)
        if args.error_only:
            stmt = stmt.where(BreachResultORM.verdict == JudgeVerdict.ERROR)
        if args.breaches_only:
            stmt = stmt.where(
                BreachResultORM.verdict.in_(
                    [JudgeVerdict.FULL_BREACH, JudgeVerdict.PARTIAL_BREACH]
                )
            )
        if args.changeable_only:
            stmt = stmt.where(
                BreachResultORM.verdict.in_(
                    [
                        JudgeVerdict.FULL_BREACH,
                        JudgeVerdict.PARTIAL_BREACH,
                        JudgeVerdict.ERROR,
                    ]
                )
            )
        rows = list(s.execute(stmt).scalars())
        data = [
            (r.breach_id, r.primitive_id, r.rendered_payload, r.model_response)
            for r in rows
        ]
        # Bulk-load primitives in ONE query (not N+1 s.get) — the per-pid loop
        # held a transaction open long enough for Neon's idle-in-transaction
        # timeout to kill the connection over the high-latency link.
        pids = {d[1] for d in data}
        prim_orms = (
            s.execute(
                select(AttackPrimitiveORM).where(
                    AttackPrimitiveORM.primitive_id.in_(pids)
                )
            )
            .scalars()
            .all()
        )
        prims = {p.primitive_id: _orm_to_pydantic_primitive(p) for p in prim_orms}

    if not data:
        logger.error("no breach_results matched the filter")
        return 1
    est = len(data) * _BATCH_COST_ESTIMATE_PER_CELL_USD
    logger.info("%d cells to re-grade via Batch API; estimate ≈ $%.2f", len(data), est)
    if args.dry_run:
        logger.info("dry-run: re-run with --yes to submit the batch.")
        return 0
    if not args.yes:
        logger.error("re-run with --yes to submit the paid batch (or --dry-run).")
        return 2

    # 2) build items + grade via batch (50% off + cached rubric)
    items = [
        BatchGradeItem(
            custom_id=bid,
            rendered=RenderedAttack(
                messages=[{"role": "user", "content": payload}],
                is_multi_turn=False,
                resolved_slots={},
                primitive_id=pid,
                deployment_config_id="rejudge",
            ),
            model_response=resp,
            primitive=prims[pid],
        )
        for (bid, pid, payload, resp) in data
    ]
    jb = JudgeBatch(JudgeAgent())
    logger.info("submitting batch (judge=%s, fallback=%s) …", jb.judge.model, jb.judge.fallback_model)
    verdicts = asyncio.run(jb.grade(items))
    logger.info("collected %d/%d verdicts", len(verdicts), len(items))

    # 3) write back in small batches (robust to Neon drops)
    pairs = [(bid, v) for bid, v in verdicts.items()]
    upd = 0
    for i in range(0, len(pairs), 25):
        chunk = pairs[i : i + 25]
        with eng.begin() as c:
            for bid, v in chunk:
                c.execute(
                    sqltext(
                        "UPDATE breach_results SET verdict=:vd, judge_rationale=:r, "
                        "judge_confidence=:cf WHERE breach_id=:b"
                    ),
                    {"vd": v.verdict.value, "r": v.rationale[:2000], "cf": v.confidence, "b": bid},
                )
        upd += len(chunk)
    logger.info("updated %d rows.", upd)

    # Auto-push the re-graded verdicts to Neon (data-only, no spend) when
    # NEON_DATABASE_URL is set — so the live matrix reflects the re-grade with
    # no manual step. No-op when unset or already running against Neon.
    from rogue.db.neon_sync import maybe_auto_sync

    maybe_auto_sync(args.database_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
