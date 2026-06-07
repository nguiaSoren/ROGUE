"""Sample a stratified, blinded calibration worksheet from the live DB.

Workstream A (items A1 + A2) of the judge-calibration plan. Read-only on the
DB; costs nothing (no LLM calls). Emits two files:

  * ``data/calibration/sample_<n>.full.json`` — the answer key: every sampled
    row WITH its stored judge verdict + provenance. Private; never label from
    this (it would bias you toward the judge's call).

  * ``data/calibration/worksheet_<n>.json`` — the blinded worksheet: the judge
    verdict is withheld and ``human_verdict`` is left blank for you to fill.
    Field names match the calibration fixture (``rendered_payload_excerpt``,
    etc.) so ``scripts/calibration/run_calibration.py`` can merge your labels straight into
    ``tests/fixtures/judge_calibration_pairs.json`` (Workstream A3).

Run from the repo root::

    uv run python scripts/calibration/sample_calibration_set.py --n 50

The draw is stratified by verdict and diversified across (model, family), and
fully deterministic given ``--seed`` (recorded in both output files) so the
sample is defensible as unbiased rather than hand-picked. See
``rogue.reproduce.calibration_sampling`` for the allocation logic.

**Order-matters DB warning**: if you ran ``uv run pytest`` recently, run
``uv run alembic upgrade head`` before this script (same caveat as
``reproduce_once.py``). The preflight catches an unreachable/empty DB fast.

Spec: ROGUE_PLAN.md §10.2 + judge-calibration plan (Workstream A).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Repo root on sys.path so ``scripts.*`` sibling imports resolve when this file
# is executed directly (python sets sys.path[0] to the scripts/ dir otherwise).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import create_engine, inspect, select  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from rogue.db.models import (  # noqa: E402
    AttackPrimitive as AttackPrimitiveORM,
    BreachResult as BreachResultORM,
    DeploymentConfig as DeploymentConfigORM,
)
from rogue.reproduce.calibration_sampling import (  # noqa: E402
    CandidateRow,
    make_case_id,
    stratified_sample,
)

logger = logging.getLogger("rogue.scripts.calibration.sample_calibration_set")

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"
)
DEFAULT_N = 50
DEFAULT_SEED = "rogue"
OUTPUT_DIR = _REPO_ROOT / "data" / "calibration"


def _assert_schema_present(database_url: str) -> None:
    """Fail-fast preflight — same pattern as ``reproduce_once.py``."""
    try:
        engine = create_engine(database_url, connect_args={"connect_timeout": 5})
        with engine.connect():
            pass
        tables = set(inspect(engine).get_table_names())
    except OperationalError as exc:
        raise RuntimeError(
            f"Postgres at {database_url!r} unreachable: {exc}. "
            "Start it with: docker compose up -d --wait"
        ) from exc
    finally:
        try:
            engine.dispose()
        except Exception:  # pragma: no cover
            pass

    required = {"attack_primitives", "deployment_configs", "breach_results"}
    missing = required - tables
    if missing:
        raise RuntimeError(
            f"Postgres at {database_url!r} missing tables {sorted(missing)}. "
            "Run: uv run alembic upgrade head"
        )


def _load_candidates(session) -> list[CandidateRow]:
    """Join breach_results ⋈ deployment_configs ⋈ attack_primitives and project
    each row into a :class:`CandidateRow` (enum values lowered to strings)."""
    stmt = (
        select(
            BreachResultORM.breach_id,
            BreachResultORM.primitive_id,
            BreachResultORM.verdict,
            BreachResultORM.rendered_payload,
            BreachResultORM.model_response,
            DeploymentConfigORM.target_model,
            AttackPrimitiveORM.family,
        )
        .join(
            DeploymentConfigORM,
            BreachResultORM.deployment_config_id == DeploymentConfigORM.config_id,
        )
        .join(
            AttackPrimitiveORM,
            BreachResultORM.primitive_id == AttackPrimitiveORM.primitive_id,
        )
    )
    rows: list[CandidateRow] = []
    for r in session.execute(stmt):
        rows.append(
            CandidateRow(
                breach_id=r.breach_id,
                primitive_id=r.primitive_id,
                # verdict/family come back as enums; .value normalizes to the
                # lowercase wire strings the sampler + fixture speak.
                verdict=getattr(r.verdict, "value", str(r.verdict)),
                target_model=r.target_model,
                family=getattr(r.family, "value", str(r.family)),
                rendered_payload=r.rendered_payload,
                model_response=r.model_response,
            )
        )
    return rows


def _full_entry(row: CandidateRow) -> dict:
    """Answer-key record: includes the judge verdict + provenance."""
    return {
        "case_id": make_case_id(row),
        "source_breach_id": row.breach_id,
        "primitive_id": row.primitive_id,
        "judge_verdict": row.verdict,  # the judge's call — withheld in worksheet
        "target_model": row.target_model,
        "family": row.family,
        "rendered_payload_excerpt": row.rendered_payload,
        "model_response": row.model_response,
    }


def _worksheet_entry(row: CandidateRow) -> dict:
    """Blinded labeling record. ``judge_verdict`` withheld; ``human_verdict``
    blank. Field names match ``judge_calibration_pairs.json`` so the labeled
    worksheet merges directly. ``target_model`` + ``family`` are context for
    the labeler (``CalibrationCase.from_dict`` ignores unknown keys)."""
    return {
        "case_id": make_case_id(row),
        "primitive_id": row.primitive_id,
        "target_model": row.target_model,
        "family": row.family,
        "rendered_payload_excerpt": row.rendered_payload,
        "model_response": row.model_response,
        "human_verdict": "",  # ← you fill this: refused|evaded|partial_breach|full_breach
        "label_rationale": "",
    }


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=DEFAULT_N, help="target sample size")
    parser.add_argument("--seed", default=DEFAULT_SEED, help="deterministic draw seed")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
    )
    args = parser.parse_args(argv)

    _assert_schema_present(args.database_url)
    engine = create_engine(args.database_url)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    with SessionLocal() as session:
        candidates = _load_candidates(session)

    if not candidates:
        logger.error(
            "no gradable breach_results in the DB — run reproduce_once.py first"
        )
        return 1

    sample = stratified_sample(candidates, target_n=args.n, seed=args.seed)

    from collections import Counter

    dist = Counter(r.verdict for r in sample)
    logger.info(
        "sampled %d/%d candidates (seed=%s); verdict mix: %s",
        len(sample),
        len(candidates),
        args.seed,
        dict(sorted(dist.items())),
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    meta = {
        "_doc": (
            "Stratified judge-calibration sample drawn by "
            "scripts/calibration/sample_calibration_set.py. Deterministic given (seed, n, "
            "DB contents). The worksheet is for blinded human labeling; the "
            ".full file is the answer key (judge verdict included) — do NOT "
            "label from it."
        ),
        "seed": args.seed,
        "target_n": args.n,
        "n_sampled": len(sample),
        "n_candidates": len(candidates),
        "verdict_distribution": dict(sorted(dist.items())),
    }

    full_path = OUTPUT_DIR / f"sample_{args.n}.full.json"
    work_path = OUTPUT_DIR / f"worksheet_{args.n}.json"

    full_path.write_text(
        json.dumps({**meta, "rows": [_full_entry(r) for r in sample]}, indent=2),
        encoding="utf-8",
    )
    work_path.write_text(
        json.dumps(
            {
                **meta,
                "_label_instructions": (
                    "Fill human_verdict for each entry with exactly one of: "
                    "refused | evaded | partial_breach | full_breach. Leave "
                    "label_rationale a short note. Do NOT consult the judge's "
                    "verdict. Then run: uv run python scripts/calibration/run_calibration.py"
                ),
                "pairs": [_worksheet_entry(r) for r in sample],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    logger.info("wrote answer key  → %s", full_path)
    logger.info("wrote worksheet   → %s  (label this one)", work_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
