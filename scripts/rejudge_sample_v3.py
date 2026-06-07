"""Re-judge a calibration sample under the current (v3) judge rubric, in memory.

Why: ``scripts/second_grader_pass.py`` (StrongREJECT) reads each row's stored
``judge_verdict`` — which on the existing ``sample_*.full.json`` is the v1/v2
verdict. To compute the StrongREJECT inflation delta *under v3*, we need v3
ROGUE verdicts on the same rows. This re-judges those rows with the current
``JudgeAgent`` (default rubric = v3) and writes a new ``sample_*_v3.full.json``.

Read-only on the DB: it SELECTs the full ``rendered_payload`` + primitive for
each row's ``source_breach_id`` (the sample only stores a truncated excerpt) and
**never writes back** — it does NOT touch the live breach matrix (that's the
deferred corpus re-judge). It only writes the new local sample file and makes
judge LLM calls (~$0.5-1 for 50 rows).

    uv run python scripts/rejudge_sample_v3.py --sample data/calibration/sample_50.full.json --dry-run
    uv run python scripts/rejudge_sample_v3.py --sample data/calibration/sample_50.full.json --limit 3 --yes
    uv run python scripts/rejudge_sample_v3.py --sample data/calibration/sample_50.full.json --yes
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from rogue.db.models import AttackPrimitive as AttackPrimitiveORM  # noqa: E402
from rogue.db.models import BreachResult as BreachResultORM  # noqa: E402
from rogue.reproduce.judge import JudgeAgent, RenderedAttack  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("rogue.scripts.rejudge_sample_v3")


def main(argv: list[str] | None = None) -> int:
    import os

    p = argparse.ArgumentParser()
    p.add_argument("--sample", type=Path, default=Path("data/calibration/sample_50.full.json"))
    p.add_argument("--limit", type=int, default=None, help="re-judge only the first N rows (test)")
    p.add_argument("--dry-run", action="store_true", help="count + estimate, free")
    p.add_argument("--yes", action="store_true", help="confirm the paid re-judge")
    args = p.parse_args(argv)

    raw = json.loads(args.sample.read_text())
    rows = raw.get("rows", [])
    if args.limit:
        rows = rows[: args.limit]
    ids = [r["source_breach_id"] for r in rows if r.get("source_breach_id")]
    est = len(ids) * 0.012  # inline cached judge ≈ $0.011-0.0064/call
    logger.info("%d rows to re-judge under v3; estimate ≈ $%.2f", len(ids), est)
    if args.dry_run:
        logger.info("dry-run: re-run with --yes to re-judge.")
        return 0
    if not args.yes:
        logger.error("re-run with --yes (or --dry-run).")
        return 2

    url = os.environ["DATABASE_URL"]
    eng = create_engine(url)
    S = sessionmaker(bind=eng)
    from scripts.reproduce_once import _orm_to_pydantic_primitive  # noqa: PLC0415

    # Read-only: fetch full payload + primitive for each breach_id. No writes.
    with S() as s:
        brows = list(
            s.execute(select(BreachResultORM).where(BreachResultORM.breach_id.in_(ids))).scalars()
        )
        by_id = {b.breach_id: b for b in brows}
        prims = {
            pid: _orm_to_pydantic_primitive(s.get(AttackPrimitiveORM, pid))
            for pid in {b.primitive_id for b in brows}
        }

    judge = JudgeAgent()  # default rubric = v3
    logger.info("judge rubric version: %s | model: %s", judge.prompt_version, judge.model)

    out_rows = []
    missing = 0
    for r in rows:
        bid = r.get("source_breach_id")
        b = by_id.get(bid)
        if b is None:
            missing += 1
            out_rows.append(r)  # keep original verdict if we can't fetch
            continue
        rendered = RenderedAttack(
            messages=[{"role": "user", "content": b.rendered_payload}],
            is_multi_turn=False,
            resolved_slots={},
            primitive_id=b.primitive_id,
            deployment_config_id="rejudge_sample_v3",
        )
        result = judge.judge_sync(rendered, b.model_response, prims[b.primitive_id])
        nr = dict(r)
        nr["judge_verdict"] = result.verdict.value
        nr["_v1_verdict"] = r.get("judge_verdict")  # keep the old one for diffing
        out_rows.append(nr)

    out = dict(raw)
    out["rows"] = out_rows
    out["rejudged_under"] = judge.prompt_version
    out_path = args.sample.with_name(args.sample.stem.replace(".full", "") + "_v3.full.json")
    out_path.write_text(json.dumps(out, indent=2))

    # quick verdict diff summary
    changed = sum(1 for r in out_rows if r.get("_v1_verdict") and r["_v1_verdict"] != r["judge_verdict"])
    logger.info("re-judged %d rows (%d missing in DB); %d verdicts changed vs v1", len(out_rows), missing, changed)
    logger.info("wrote %s", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
