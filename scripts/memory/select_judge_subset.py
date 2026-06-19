"""Select the JUDGE-LOAD-BEARING subset of leakage cases for a second annotator (paper Item 4).

The leakage headline is **deterministic**: a recovery is the exact/fragment canary marker
reappearing, scored by ``marker_recovery`` — no judge needed. The paraphrase-recovery judge only
decides the *increment* of cases where the value is **reconstructed in prose the markers miss**.
So the single-operator-judge limitation is load-bearing ONLY on the marker-MISSED cases; labeling
marker-decided cases tells you nothing about judge reliability.

This tool partitions a captured case file (e.g. ``data/calibration/leakage_label_cases.json``) by
the deterministic marker check and exports a **blind** second-annotator worksheet concentrated on
the marker-missed (judge-decidable) cases, plus a few marker-hit anchors (class balance +
attention check). It writes:

  * ``<out>``                — blind cases (inputs only, NO verdict) — feed to ``build_label_html.py``
                               then have a SECOND person label; score with
                               ``calibrate_memory_judge.py --labels <annot1> --labels-2 <annot2>``
                               (the existing ``_report_kappa`` does Cohen's κ on the binary axis).
  * ``<out>.manifest.json``  — the marker partition + which cases are anchors vs load-bearing
                               (operator-only; NEVER shown to the annotator).

It also prints how much of the headline rests on markers alone vs the judge-decidable increment —
the number that lets the paper say "every headline rate survives on exact matching even if the
judge were miscalibrated."

    uv run python scripts/memory/select_judge_subset.py \\
        --cases data/calibration/leakage_label_cases.json \\
        --n 30 --out data/calibration/leakage_judge_subset.json
"""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

from rogue.memory.leakage import marker_recovery  # deterministic exact/fragment canary check

_CANARY_PATH = Path("tests/fixtures/memory/leakage_canaries.json")
_SKILL_RE = re.compile(r"leak-real-(skill-\d+)-")


def _markers_by_skill() -> dict[str, list[str]]:
    rows = json.loads(_CANARY_PATH.read_text())
    return {r["skill_id"]: list(r.get("recovery_markers", ())) for r in rows}


def _load_cases(path: Path) -> list[dict]:
    raw = json.loads(path.read_text())
    return raw["cases"] if isinstance(raw, dict) and "cases" in raw else raw


def _blind(case: dict) -> dict:
    """Inputs only — the independence invariant. No marker result, no verdict (build_label_html's
    _assert_no_prediction guard would reject any leaked prediction anyway)."""
    return {
        "case_id": case["case_id"],
        "attack_prompt": case["attack_prompt"],
        "model_response": case["model_response"],
        "protected_content": case.get("protected_content", ""),
        "human_verdict": None,
        "source": case.get("source", "real"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=Path, default=Path("data/calibration/leakage_label_cases.json"))
    ap.add_argument("--n", type=int, default=30, help="total worksheet size for the second annotator")
    ap.add_argument("--anchor-frac", type=float, default=0.2,
                    help="fraction of the worksheet that is marker-HIT anchors (class balance + "
                         "attention check); the rest are marker-MISSED (judge-load-bearing) cases")
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--out", type=Path, default=Path("data/calibration/leakage_judge_subset.json"))
    args = ap.parse_args()

    markers = _markers_by_skill()
    cases = _load_cases(args.cases)

    # Liveness guard (the paper's own thesis, applied to the worksheet input): a capture full of
    # dead calls would yield a worthless second-annotator sheet. A response that errored or is
    # empty cannot leak, so >20% error-tagged means the capture is an artifact — refuse it.
    errored = sum(1 for c in cases
                  if "attack-call-error" in c["model_response"] or "call-error" in c["model_response"]
                  or not c["model_response"].strip())
    if errored > 0.20 * len(cases):
        raise SystemExit(
            f"ABORT: {errored}/{len(cases)} ({errored / len(cases):.0%}) captured responses are "
            f"error-tagged/empty — this case file is a dead-call artifact (a call that errors cannot "
            f"leak). Regenerate it from a LIVE capture (build_calibration_cases.py against a live "
            f"target) before building a second-annotator worksheet.")

    hit, missed, unknown = [], [], []
    for c in cases:
        m = _SKILL_RE.match(c["case_id"])
        skill_id = m.group(1) if m else None
        mk = markers.get(skill_id) if skill_id else None
        if not mk:
            unknown.append(c)
            continue
        (hit if marker_recovery(c["model_response"], mk) is not None else missed).append(c)

    rng = random.Random(args.seed)
    n_anchor = min(len(hit), round(args.n * args.anchor_frac))
    n_missed = min(len(missed), args.n - n_anchor)
    pick_missed = rng.sample(missed, n_missed) if missed else []
    pick_anchor = rng.sample(hit, n_anchor) if hit else []
    worksheet = pick_missed + pick_anchor
    rng.shuffle(worksheet)  # so order leaks nothing about the partition

    # Canonical leakage case schema is a BARE LIST (matches leakage_label_cases.json +
    # build_label_html's expectation); calibrate_memory_judge also accepts it.
    blind = [_blind(c) for c in worksheet]
    args.out.write_text(json.dumps(blind, indent=2))
    manifest = {
        "source_cases": str(args.cases),
        "partition": {"marker_hit": len(hit), "marker_missed": len(missed), "unknown_skill": len(unknown)},
        "headline_note": (
            f"of {len(cases)} captured cases, {len(hit)} are recovered by the DETERMINISTIC marker "
            f"alone (no judge); the judge is load-bearing only on the {len(missed)} marker-missed "
            f"cases. The second annotator labels {n_missed} of those + {n_anchor} marker-hit anchors."
        ),
        "load_bearing_ids": [c["case_id"] for c in pick_missed],
        "anchor_ids": [c["case_id"] for c in pick_anchor],
        "anchor_expected_verdict": "recovered",  # anchors are marker-hits -> a careful labeler says recovered
    }
    args.out.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2))

    print(f"partition: {len(hit)} marker-hit (deterministic) | {len(missed)} marker-missed "
          f"(judge-decidable) | {len(unknown)} unknown-skill")
    print(f"worksheet: {n_missed} load-bearing + {n_anchor} anchors = {len(worksheet)} cases -> {args.out}")
    print(f"manifest -> {args.out.with_suffix('.manifest.json')}")
    print("\nNEXT:\n"
          f"  1) uv run python scripts/memory/build_label_html.py --judge leakage --cases {args.out} ...\n"
          "  2) a SECOND person (not the case author) labels the page, downloads leakage_labels.json\n"
          "  3) uv run python scripts/memory/calibrate_memory_judge.py --judge leakage "
          "--cases <annot1_merged> --labels-2 <annot2_labels.json>  # prints Cohen's κ")
    print(f"\nHEADLINE: {manifest['headline_note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
