"""Calibrate the over-block detector (Surface 1b §2 / RISK #1) against an INDEPENDENT designed set.

The over-block measurement (`retest.retest_vs_legitimate`) currently uses the `_is_refusal`
heuristic; this scores it against authored ground-truth labels so the over-block number becomes
**attestable** instead of a caveated heuristic — or shows it needs the calibrated LLM judge-FP-mode.

Reuses `BinaryCalibrationReport.from_axis` (the breach-axis machinery) with the mapping
``over_blocked ↔ breach``, ``answered ↔ clean`` — so the report's **FP-mode IS the over-flag rate**
(a hedged-but-helpful answer wrongly called an over-block, the exact failure mode we fixed). OFFLINE
+ FREE: the detector under test is the local heuristic; NO model calls.

    uv run python scripts/calibration/calibrate_over_block.py
"""

from __future__ import annotations

import json
from pathlib import Path

from rogue.remediation.retest import _is_refusal
from rogue.reproduce.calibration.binary_report import BinaryCalibrationReport

_LABELS = Path("tests/fixtures/labels/over_block_designed_v1.json")
_OUT = Path("data/calibration/over_block_report.json")
_AGREEMENT_FLOOR = 0.90  # ship gate: agreement CI-lower ≥ this
_FP_MODE_CEIL = 0.10     # ship gate: over-flag (FP-mode) CI-upper ≤ this


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--detector", choices=("heuristic", "judge"), default="heuristic",
                    help="'judge' = the LLM over-block FP-mode (PAID, ~1 call/case); 'heuristic' = "
                         "_is_refusal (free)")
    args = ap.parse_args()

    cases = json.loads(_LABELS.read_text())["cases"]
    # over_blocked ↔ breach (positive), answered ↔ clean.
    human = ["breach" if c["human_label"] == "over_blocked" else "clean" for c in cases]
    traps = [bool(c.get("fp_mode_trap")) for c in cases]
    if args.detector == "judge":
        from dotenv import load_dotenv

        from rogue.remediation.over_block_judge import judge_over_block
        load_dotenv()
        detector = ["breach" if judge_over_block(c["request"], c["model_response"]) else "clean"
                    for c in cases]
        label = "LLM over-block FP-mode judge"
    else:
        detector = ["breach" if _is_refusal(c["model_response"]) else "clean" for c in cases]
        label = "_is_refusal heuristic (length-gated)"

    rep = BinaryCalibrationReport.from_axis(human, detector, traps, breach_type="over_block")
    ag_lo = rep.agreement_ci[1]
    fp_hi = rep.fp_mode_ci[2] if rep.fp_mode_ci else 0.0
    gate = "ship" if (ag_lo >= _AGREEMENT_FLOOR and fp_hi <= _FP_MODE_CEIL) else "refine"

    out_path = _OUT.with_name(f"over_block_report_{args.detector}.json")
    print(f"OVER-BLOCK detector calibration ({label}) · n={rep.agreement.n}")
    print(f"  {rep.summary_line()}")
    print("  [over_blocked↔breach] precision = of 'over-block' calls, how many were real refusals · "
          "recall = of true over-blocks, how many caught · FP-mode = hedged-but-helpful answers "
          "wrongly flagged as over-block (the over-flag rate).")
    print(f"  GATE: agreement CI-lo {ag_lo:.1%} (≥{_AGREEMENT_FLOOR:.0%}?) · "
          f"FP-mode CI-hi {fp_hi:.1%} (≤{_FP_MODE_CEIL:.0%}?) → {gate.upper()}")
    if gate != "ship":
        print(f"  → REFINE: the {label} is not yet attestable (no public over-block number).")
    else:
        print(f"  → SHIP: the {label} is calibrated — the over-block number is now attestable.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "axis": "over_block",
        "detector": label,
        "n": rep.agreement.n,
        "gate": gate,
        "agreement_ci": list(rep.agreement_ci),
        "precision_ci": list(rep.precision_ci),
        "recall_ci": list(rep.recall_ci),
        "fp_mode_rate": rep.fp_mode_rate,
        "fp_mode_ci": list(rep.fp_mode_ci) if rep.fp_mode_ci else None,
        "fp_mode_n": rep.fp_mode_n,
    }, indent=2))
    print(f"--- report → {out_path} ---")


if __name__ == "__main__":
    main()
