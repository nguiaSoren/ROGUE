"""Merge a labeled worksheet into the calibration fixture and score the judge.

Workstream A item A3. **This spends money** — it re-grades every labeled case
with the live judge (one judge call per case, ~$0.02 each → ~$1-2 for 50).
Run deliberately, never on a loop (per CLAUDE.md costly-scripts rule). Gated
behind ``--yes``; ``--dry-run`` validates labels + prints the cost estimate for
free.

Pipeline::

    worksheet_<n>.json  (you labeled human_verdict)
            │  validate every label is a substantive verdict
            ▼
    [--merge-fixture]  append into tests/fixtures/judge_calibration_pairs.json
            │
            ▼
    calibrate(cases, db_judge_fn)        ← re-grades each case with live judge
            │
            ▼
    CalibrationReport  → stdout summary + data/calibration/report.json

The headline line printed is the credibility number for the README:
``agreement=X% (k/n) fp_breach=Y% fn_breach=Z% gate=…``.

Run from the repo root::

    uv run python scripts/run_calibration.py --dry-run          # free: check labels
    uv run python scripts/run_calibration.py --yes              # paid: score the judge
    uv run python scripts/run_calibration.py --yes --merge-fixture

Spec: ROGUE_PLAN.md §10.2 + judge-calibration plan (Workstream A3).
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

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import create_engine, inspect  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from rogue.reproduce.calibration_adapters import make_db_judge_fn  # noqa: E402
from rogue.reproduce.judge import JudgeAgent  # noqa: E402
from rogue.reproduce.judge_calibration import (  # noqa: E402
    CALIBRATION_FIXTURE_PATH,
    CalibrationCase,
    CalibrationReport,
    calibrate,
)

logger = logging.getLogger("rogue.scripts.run_calibration")

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"
)
OUTPUT_DIR = _REPO_ROOT / "data" / "calibration"
# Same per-call estimate reproduce_once.py uses for the Sonnet judge.
_JUDGE_COST_ESTIMATE_PER_CALL_USD = 0.0225


def _load_labeled_cases(worksheet_path: Path) -> list[CalibrationCase]:
    """Read the worksheet, require every ``human_verdict`` filled, and project
    each entry through ``CalibrationCase.from_dict`` (rejects blank / invalid /
    ERROR labels loudly)."""
    raw = json.loads(worksheet_path.read_text(encoding="utf-8"))
    pairs = raw.get("pairs", [])
    if not pairs:
        raise ValueError(f"{worksheet_path} has no `pairs` to score")

    unlabeled = [
        p.get("case_id", "?")
        for p in pairs
        if not str(p.get("human_verdict", "")).strip()
    ]
    if unlabeled:
        raise ValueError(
            f"{len(unlabeled)} of {len(pairs)} cases are unlabeled "
            f"(human_verdict blank): {unlabeled[:5]}{'…' if len(unlabeled) > 5 else ''}. "
            "Fill them before running."
        )
    # from_dict validates the verdict vocabulary + rejects ERROR.
    return [CalibrationCase.from_dict(p) for p in pairs]


def _merge_into_fixture(cases: list[CalibrationCase], fixture_path: Path) -> int:
    """Append labeled cases into the canonical fixture, skipping case_ids that
    are already present. Returns the number of new cases added."""
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    existing = {p["case_id"] for p in raw.get("pairs", [])}
    added = 0
    for case in cases:
        if case.case_id in existing:
            continue
        raw.setdefault("pairs", []).append(
            {
                "case_id": case.case_id,
                "primitive_id": case.primitive_id,
                "rendered_payload_excerpt": case.rendered_payload_excerpt,
                "model_response": case.model_response,
                "human_verdict": case.human_verdict.value,
                "label_rationale": case.label_rationale,
                "labeler": os.environ.get("USER", "operator"),
            }
        )
        added += 1
    fixture_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return added


def _serialize_report(report: CalibrationReport) -> dict:
    """Enum-keyed report → JSON-safe dict (verdict enums → their .value)."""
    fp = report.false_positive_breach_rate()
    fn = report.false_negative_breach_rate()
    return {
        "n_cases": report.n_cases,
        "n_agreed": report.n_agreed,
        "agreement_rate": report.agreement_rate,
        "false_positive_breach_rate": fp,
        "false_negative_breach_rate": fn,
        "gate": report.gate(),
        "summary_line": report.summary_line(),
        "per_verdict_accuracy": {
            v.value: acc for v, acc in report.per_verdict_accuracy.items()
        },
        "confusion_matrix": {
            human.value: {pred.value: n for pred, n in row.items()}
            for human, row in report.confusion_matrix.items()
        },
        "disagreements": report.disagreements,
    }


def _assert_schema_present(database_url: str) -> None:
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
    if "attack_primitives" not in tables:
        raise RuntimeError(
            f"Postgres at {database_url!r} missing attack_primitives. "
            "Run: uv run alembic upgrade head"
        )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--worksheet",
        type=Path,
        default=OUTPUT_DIR / "worksheet_50.json",
        help="labeled worksheet to score",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate labels + print cost estimate; no judge calls, free",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm the paid judge re-grade run",
    )
    parser.add_argument(
        "--merge-fixture",
        action="store_true",
        help=f"append labeled cases into {CALIBRATION_FIXTURE_PATH.name}",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
    )
    args = parser.parse_args(argv)

    cases = _load_labeled_cases(args.worksheet)
    est = len(cases) * _JUDGE_COST_ESTIMATE_PER_CALL_USD
    logger.info(
        "%d labeled cases validated; judge re-grade estimate ≈ $%.2f",
        len(cases),
        est,
    )

    if args.dry_run:
        logger.info("dry-run: labels valid. Re-run with --yes to score the judge.")
        return 0

    if not args.yes:
        logger.error(
            "this run calls the live judge (≈ $%.2f) and writes data. "
            "Re-run with --yes to confirm, or --dry-run to validate for free.",
            est,
        )
        return 2

    _assert_schema_present(args.database_url)

    if args.merge_fixture:
        added = _merge_into_fixture(cases, CALIBRATION_FIXTURE_PATH)
        logger.info("merged %d new cases into %s", added, CALIBRATION_FIXTURE_PATH.name)

    engine = create_engine(args.database_url)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    judge = JudgeAgent()
    logger.info("scoring %d cases with judge model %s …", len(cases), judge.model)

    with SessionLocal() as session:
        judge_fn = make_db_judge_fn(judge, session)
        report = calibrate(cases, judge_fn)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / "report.json"
    report_path.write_text(
        json.dumps(_serialize_report(report), indent=2), encoding="utf-8"
    )

    print("\n" + "=" * 70)
    print(report.summary_line())
    print("=" * 70)
    print("per-verdict accuracy:")
    for verdict, acc in sorted(
        report.per_verdict_accuracy.items(), key=lambda kv: kv[0].value
    ):
        print(f"  {verdict.value:<16} {acc:.2%}")
    if report.disagreements:
        print(f"\n{len(report.disagreements)} disagreement(s):")
        for d in report.disagreements:
            print(
                f"  {d['case_id']}: human={d['human_verdict']} "
                f"judge={d['predicted_verdict']}"
            )
    print(f"\nfull report → {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
