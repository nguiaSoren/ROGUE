"""Judge-shrink A/B — decide, for $0, whether a cheaper judge can replace Sonnet (Q1).

Re-aggregates the ALREADY-PAID per-item JBB judge_comparison verdicts frozen in
``data/calibration/jbb_judge_items_*.jsonl`` (Sonnet baseline = ``jbb_judge_items.jsonl``;
each candidate = ``jbb_judge_items_<model>.jsonl``) into the honest decision metric —
Cohen's κ + false-positive-breach rate + bootstrap CI — and prints a ship/HOLD verdict per
candidate vs the Sonnet baseline. NO model calls, NO DB writes, NO spend: ``eval_jbb_judge.py``
freezes those items precisely so re-aggregation is free.

Grounding + gate rationale: ``docs/research/judge_shrink_ab.md``. Short version — raw
agreement inflates under the 110/300 class balance, so we report κ; and small judges over-call
breaches (Thakur 2406.12624), so the gate also caps the FP-breach rate, not just κ.

Run from the repo root::

    uv run python scripts/calibration/judge_shrink_ab.py            # $0 decision table + JSON report
    uv run python scripts/calibration/judge_shrink_ab.py --all      # include .repro/.anchor/_strict variants

To measure whether Krumdick's reference lever CLOSES a candidate's gap (the one paid arm),
re-grade with the lever on — this reuses the existing paid path, no new script::

    ROGUE_JUDGE_REFERENCE_K=4 JUDGE_MODEL=openrouter/qwen/qwen3-32b \
        uv run python scripts/calibration/eval_jbb_judge.py --yes    # ~$6.75, gated

then re-run this script to compare the new items file against Sonnet.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from rogue.reproduce.calibration.judge_ab import (  # noqa: E402
    JudgeShrinkVerdict,
    judge_ab_from_cells,
    reaggregate_jbb_items,
)

CALIB_DIR = _REPO_ROOT / "data" / "calibration"
BASELINE_FILE = CALIB_DIR / "jbb_judge_items.jsonl"
OUTPUT_JSON = CALIB_DIR / "judge_shrink_ab_report.json"

# The Sonnet per-call judge cost from eval_jbb_judge.py (used only to frame the saving; the
# candidate open models run at a fraction of it — we report the decision, not invented per-model
# prices).
_SONNET_COST_PER_CALL_USD = 0.0225

_VARIANT_MARKERS = (".repro", ".anchor", ".bak", "_strict", ".matched", ".transfer")


def _model_from_path(p: Path) -> str:
    """``jbb_judge_items_qwen3-32b.jsonl`` -> ``qwen3-32b``."""
    return p.name.removeprefix("jbb_judge_items_").removesuffix(".jsonl")


def _candidate_files(include_variants: bool) -> list[Path]:
    files = [
        Path(f)
        for f in sorted(glob.glob(str(CALIB_DIR / "jbb_judge_items_*.jsonl")))
    ]
    if include_variants:
        return files
    return [f for f in files if not any(m in f.name for m in _VARIANT_MARKERS)]


def _verdict_to_dict(v: JudgeShrinkVerdict) -> dict:
    k_lo, k_hi = v.cand_kappa_ci
    return {
        "candidate": v.candidate,
        "n": v.n,
        "ship": v.ship,
        "agreement": v.cand_agreement,
        "kappa": v.cand_kappa,
        "kappa_ci": [k_lo, k_hi],
        "kappa_delta_vs_sonnet": v.kappa_delta,
        "fpr_breach": v.cand_fpr,
        "fpr_delta_vs_sonnet": v.fpr_delta,
        "reasons": list(v.reasons),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--all",
        action="store_true",
        help="include .repro/.anchor/_strict robustness variants (default: canonical only)",
    )
    args = ap.parse_args()

    if not BASELINE_FILE.exists():
        print(f"ERROR: Sonnet baseline items not found at {BASELINE_FILE}", file=sys.stderr)
        return 1

    baseline = reaggregate_jbb_items(BASELINE_FILE)
    print(
        f"Sonnet baseline (jbb_judge_items.jsonl): {baseline.summary_line()} "
        f"fpr_breach={baseline.false_positive_rate:.1%}\n"
    )

    verdicts: list[JudgeShrinkVerdict] = []
    for f in _candidate_files(args.all):
        model = _model_from_path(f)
        cand = reaggregate_jbb_items(f)
        v = judge_ab_from_cells(
            cand,
            baseline,
            candidate_name=model,
            baseline_name="sonnet",
            base_cost_per_1k=_SONNET_COST_PER_CALL_USD * 1000,
        )
        verdicts.append(v)

    # Rank by κ descending (None last).
    verdicts.sort(key=lambda v: (v.cand_kappa is not None, v.cand_kappa or 0.0), reverse=True)

    print(f"{'candidate':40} {'agree':>6} {'κ':>7} {'κ CI':>16} {'fpr':>6} {'Δfpr':>7}  decision")
    print("-" * 100)
    for v in verdicts:
        k_lo, k_hi = v.cand_kappa_ci
        ci = f"[{k_lo:.3f},{k_hi:.3f}]" if v.cand_kappa is not None else "n/a"
        agree = f"{v.cand_agreement:.1%}" if v.cand_agreement is not None else "n/a"
        kappa = f"{v.cand_kappa:.3f}" if v.cand_kappa is not None else "n/a"
        fpr = f"{v.cand_fpr:.1%}" if v.cand_fpr is not None else "n/a"
        dfpr = f"{v.fpr_delta:+.1%}" if v.fpr_delta is not None else "n/a"
        decision = "SHIP" if v.ship else "hold"
        print(f"{v.candidate:40} {agree:>6} {kappa:>7} {ci:>16} {fpr:>6} {dfpr:>7}  {decision}")
    print("-" * 100)
    shipped = [v.candidate for v in verdicts if v.ship]
    print(
        f"\nSHIP candidates (κ within tol of Sonnet AND FP-breach not materially worse): "
        f"{shipped or 'none'}"
    )
    for v in verdicts:
        if not v.ship:
            print(f"  hold {v.candidate}: {'; '.join(v.reasons)}")

    report = {
        "dataset": "JailbreakBench/JBB-Behaviors:judge_comparison/test",
        "axis": "breach (jailbroken) vs human_majority",
        "n": baseline.n,
        "cost": "$0 (re-aggregation of frozen per-item verdicts)",
        "baseline": {
            "name": "sonnet",
            "agreement": baseline.agreement_rate,
            "kappa": baseline.cohen_kappa,
            "fpr_breach": baseline.false_positive_rate,
            "cells": {"tp": baseline.tp, "fp": baseline.fp, "fn": baseline.fn, "tn": baseline.tn},
        },
        "candidates": [_verdict_to_dict(v) for v in verdicts],
        "ship": shipped,
        "note": (
            "Candidates graded WITHOUT the reference lever (logged pre-lever). Whether "
            "ROGUE_JUDGE_REFERENCE_K>0 closes a hold candidate's gap is a separate paid arm."
        ),
    }
    OUTPUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nwrote {OUTPUT_JSON.relative_to(_REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
