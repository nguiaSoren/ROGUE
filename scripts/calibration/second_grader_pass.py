"""Run StrongREJECT as an independent second grader over ROGUE's reproduce rows.

Workstream C of the judge-calibration plan. Reads the SAME rows the ROGUE judge
already scored (the ``sample_*.full.json`` produced by
``scripts/calibration/sample_calibration_set.py``, so both graders see identical inputs),
grades each with the StrongREJECT rubric, and reports inter-judge agreement +
the **inflation delta** (rogue_breach_rate − strongreject_breach_rate) overall
and per target model.

The point: StrongREJECT's published finding is that automated graders overstate
jailbreak success. If it scores ROGUE's rows materially lower than the ROGUE
judge — especially on the high-breach models — part of the headline spread is
judge over-eagerness, not real model weakness. Better found here than by an
interviewer.

**This spends money** — one grader LLM call per row (~$0.02 each; 50 rows ≈
$1-2). Gated behind ``--yes``; ``--dry-run`` loads + estimates for free.

Run from the repo root::

    uv run python scripts/calibration/second_grader_pass.py --dry-run
    uv run python scripts/calibration/second_grader_pass.py --yes --sample data/calibration/sample_50.full.json

Output: stdout summary + ``data/calibration/strongreject_report.json``.

Spec: ROGUE_PLAN.md §10.2 + judge-calibration plan (Workstream C).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from rogue.reproduce.llm_cost_log import log_anthropic_response  # noqa: E402
from rogue.reproduce.strongreject_grader import (  # noqa: E402
    DEFAULT_BREACH_THRESHOLD,
    STRONGREJECT_SYSTEM,
    ScoredGrade,
    build_strongreject_prompt,
    combined_score,
    compare_graders,
    flag_disagreements,
    grades_to_rows,
    parse_grader_response,
    threshold_sweep,
)
from rogue.reproduce.verdict_projection import to_breach_binary  # noqa: E402
from rogue.schemas import JudgeVerdict  # noqa: E402

logger = logging.getLogger("rogue.scripts.calibration.second_grader_pass")

OUTPUT_DIR = _REPO_ROOT / "data" / "calibration"
DEFAULT_SAMPLE = OUTPUT_DIR / "sample_50.full.json"
DEFAULT_GRADER_MODEL = os.environ.get(
    "STRONGREJECT_GRADER_MODEL", "claude-sonnet-4-6"
)
DEFAULT_CONCURRENCY = 5
_GRADER_MAX_TOKENS = 512
_GRADER_COST_ESTIMATE_PER_CALL_USD = 0.0225


def _load_sample_rows(sample_path: Path) -> list[dict]:
    """Load the full sample, dropping rows the ROGUE judge marked ERROR (no
    breach-truth to compare against)."""
    raw = json.loads(sample_path.read_text(encoding="utf-8"))
    rows = [r for r in raw.get("rows", []) if r.get("judge_verdict") != "error"]
    if not rows:
        raise ValueError(
            f"{sample_path} has no gradable rows. Run "
            "scripts/calibration/sample_calibration_set.py first."
        )
    return rows


async def _grade_one(client, model: str, forbidden: str, response: str) -> float | None:
    """One StrongREJECT grade → 0-1 score, or None on API/parse failure."""
    from anthropic import APIStatusError, BadRequestError  # noqa: PLC0415

    prompt = build_strongreject_prompt(forbidden, response)
    try:
        reply = await client.messages.create(
            model=model,
            max_tokens=_GRADER_MAX_TOKENS,
            temperature=0.0,
            system=STRONGREJECT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
    except (BadRequestError, APIStatusError) as exc:
        logger.warning("strongreject grade API error: %s", exc)
        return None

    parts = [
        getattr(b, "text", "")
        for b in getattr(reply, "content", []) or []
        if getattr(b, "type", None) == "text"
    ]
    log_anthropic_response(
        reply,
        module="strongreject",
        operation="grade",
        model=model,
        subject_id="rubric",
        refused=False,
        notes=f"forbidden_len={len(forbidden)}",
    )
    scores = parse_grader_response("".join(parts))
    return combined_score(scores) if scores is not None else None


async def _grade_all(
    rows: list[dict], model: str, concurrency: int
) -> tuple[list[dict], int]:
    """Grade every row with StrongREJECT, capturing the RAW 0-1 score (so the
    threshold sweep is free later). Returns ``(per_item_records, n_errors)``."""
    from anthropic import AsyncAnthropic  # noqa: PLC0415

    client = AsyncAnthropic()
    sem = asyncio.Semaphore(concurrency)
    records: list[dict] = []
    errors = 0

    async def _one(row: dict) -> None:
        nonlocal errors
        async with sem:
            score = await _grade_one(
                client,
                model,
                row.get("rendered_payload_excerpt", ""),
                row.get("model_response", ""),
            )
        if score is None:
            errors += 1
            return
        verdict = JudgeVerdict(row["judge_verdict"])
        records.append(
            {
                "breach_id": row.get("source_breach_id", ""),
                "family": row.get("family", ""),
                "target_model": row.get("target_model", "unknown"),
                "rogue_verdict": verdict.value,
                "rogue_breach": to_breach_binary(verdict),
                "strongreject_score": score,
            }
        )

    await asyncio.gather(*(_one(r) for r in rows))
    return records, errors


def _comp(c) -> dict:
    return {
        "n": c.n,
        "n_agreed": c.n_agreed,
        "agreement_rate": c.agreement_rate,
        "rogue_breach_rate": c.rogue_breach_rate,
        "strongreject_breach_rate": c.strongreject_breach_rate,
        "inflation_delta": c.inflation_delta,
    }


def _serialize(
    report, sweep, flagged, *, model: str, threshold: float, n_errors: int
) -> dict:
    return {
        "grader": "strongreject_rubric",
        "grader_model": model,
        "breach_threshold": threshold,
        "n_grader_errors": n_errors,
        "overall": _comp(report.overall),
        "per_model": {m: _comp(c) for m, c in report.per_model.items()},
        "threshold_sweep": [
            {"threshold": pt.threshold, **_comp(pt.report.overall)} for pt in sweep
        ],
        "disagreement_flagger": {
            "scope": "harmful_content_families",
            "threshold": threshold,
            "n_flagged": len(flagged),
        },
    }


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--grader-model", default=DEFAULT_GRADER_MODEL)
    parser.add_argument("--threshold", type=float, default=DEFAULT_BREACH_THRESHOLD)
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--dry-run", action="store_true", help="load + estimate, free")
    parser.add_argument("--yes", action="store_true", help="confirm the paid run")
    args = parser.parse_args(argv)

    try:
        rows = _load_sample_rows(args.sample)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return 1

    est = len(rows) * _GRADER_COST_ESTIMATE_PER_CALL_USD
    logger.info(
        "%d gradable rows from %s; StrongREJECT estimate ≈ $%.2f (model=%s, threshold=%.2f)",
        len(rows),
        args.sample.name,
        est,
        args.grader_model,
        args.threshold,
    )

    if args.dry_run:
        logger.info("dry-run: sample loads. Re-run with --yes to grade.")
        return 0

    if not args.yes:
        logger.error(
            "this run calls the StrongREJECT grader (≈ $%.2f). Re-run with "
            "--yes to confirm, or --dry-run to estimate for free.",
            est,
        )
        return 2

    records, n_errors = asyncio.run(
        _grade_all(rows, args.grader_model, args.concurrency)
    )
    if n_errors:
        logger.warning("%d row(s) failed to grade (excluded)", n_errors)

    grades = [
        ScoredGrade(
            target_model=r["target_model"],
            rogue_breach=r["rogue_breach"],
            strongreject_score=r["strongreject_score"],
            family=r["family"],
            breach_id=r["breach_id"],
        )
        for r in records
    ]
    report = compare_graders(grades_to_rows(grades, args.threshold))
    sweep = threshold_sweep(grades)  # default thresholds, offline
    flagged = flag_disagreements(grades, args.threshold)  # harmful-content scope

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "strongreject_report.json"
    out_path.write_text(
        json.dumps(
            _serialize(
                report, sweep, flagged, model=args.grader_model,
                threshold=args.threshold, n_errors=n_errors,
            ),
            indent=2,
        ),
        encoding="utf-8",
    )

    # Per-item JSONL (raw scores) → any future re-threshold is free.
    items_path = OUTPUT_DIR / "strongreject_items.jsonl"
    with items_path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")

    # Scoped disagreement flagger → cells for human spot-check (harmful-content
    # families only, where StrongREJECT's rubric is a clean fit).
    flagged_path = OUTPUT_DIR / "strongreject_flagged.jsonl"
    with flagged_path.open("w", encoding="utf-8") as fh:
        for cell in flagged:
            fh.write(
                json.dumps(
                    {
                        "breach_id": cell.breach_id,
                        "family": cell.family,
                        "target_model": cell.target_model,
                        "rogue_breach": cell.rogue_breach,
                        "strongreject_breach": cell.strongreject_breach,
                        "strongreject_score": cell.strongreject_score,
                    }
                )
                + "\n"
            )

    print("\n" + "=" * 70)
    for line in report.summary_lines():
        print(line)
    print("-" * 70)
    print("threshold sweep (overall rogue_breach vs strongreject_breach → delta):")
    for pt in sweep:
        c = pt.report.overall
        print(
            f"  t={pt.threshold:<5} agree={c.agreement_rate:.0%} "
            f"rogue={c.rogue_breach_rate:.0%} sr={c.strongreject_breach_rate:.0%} "
            f"delta={c.inflation_delta:+.0%}"
        )
    print("-" * 70)
    print(
        f"disagreement flagger (harmful-content families, t={args.threshold}): "
        f"{len(flagged)} cell(s) for review"
    )
    for cell in flagged:
        print(
            f"  {cell.breach_id} [{cell.family} · {cell.target_model}] "
            f"rogue_breach={cell.rogue_breach} sr_breach={cell.strongreject_breach} "
            f"(score={cell.strongreject_score:.3f})"
        )
    print("=" * 70)
    print(f"report   → {out_path}")
    print(f"per-item → {items_path}")
    print(f"flagged  → {flagged_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
