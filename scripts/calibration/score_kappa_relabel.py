"""Score returned κ-relabel worksheets (P2 multi-labeler shore-up).

Consumes the ``<labeler>_p2_kappa_relabel.json`` files produced by the blind HTML worksheet
(``build_kappa_relabel_html.py``) and computes, per labeler, Cohen's κ against the operator's
by-construction ``human_label`` in each phase:

  κ_text  = agreement(labeler text-only round, operator)   [the original ~0.746 / 0.723 regime]
  κ_trace = agreement(labeler with-trace round, operator)   [the ~0.917 / 0.909 regime]

The P2 evidence-modality finding is robust to the annotator iff EVERY independent labeler shows
κ_trace > κ_text (the within-labeler jump replicates), separating "evidence modality raises κ"
from "one annotator behaved differently." Cohen's κ via the house helper in
``scripts/calibration/kappa_check.py`` (stdlib only).

    uv run python scripts/calibration/score_kappa_relabel.py <labeler1.json> <labeler2.json> ...
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_FIXTURES = [
    "tests/fixtures/labels/unauthorized_action_designed_v1.json",
    "tests/fixtures/labels/fabricated_sensitive_value_designed_v1.json",
]


def _kappa_fn():
    spec = importlib.util.spec_from_file_location("rogue_kappa_check", _HERE / "kappa_check.py")
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m._kappa


def _operator_labels() -> dict[str, str]:
    ref: dict[str, str] = {}
    for fn in _FIXTURES:
        rows = json.loads(Path(fn).read_text())
        rows = rows.get("cases", rows) if isinstance(rows, dict) else rows
        for c in rows:
            if c.get("case_id") and c.get("human_label"):
                ref[c["case_id"]] = str(c["human_label"]).strip().lower()
    return ref


def _kappa_vs_operator(verdicts: dict[str, str], ref: dict[str, str], kfn) -> tuple[float, float, int]:
    a, b = [], []
    for cid, v in verdicts.items():
        if cid in ref:
            a.append(ref[cid])
            b.append(str(v).strip().lower())
    if len(a) < 2:
        return (float("nan"), float("nan"), len(a))
    p_o, kappa = kfn(a, b)
    return (p_o, kappa, len(a))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("labeler_files", nargs="+", help="returned <labeler>_p2_kappa_relabel.json files")
    args = ap.parse_args()

    ref = _operator_labels()
    kfn = _kappa_fn()
    print(f"operator reference labels: {len(ref)} cases\n")
    rows, all_jump_up = [], True
    for fp in args.labeler_files:
        d = json.loads(Path(fp).read_text())
        name = d.get("labeler", Path(fp).stem)
        _, k_text, n_t = _kappa_vs_operator(d.get("phase1_text_only", {}), ref, kfn)
        _, k_trace, n_v = _kappa_vs_operator(d.get("phase2_with_trace", {}), ref, kfn)
        jump = k_trace - k_text
        up = k_trace > k_text
        all_jump_up = all_jump_up and up
        rows.append((name, k_text, k_trace, jump, n_t, n_v))
        print(f"  {name:18s}  κ_text={k_text:.3f}  κ_trace={k_trace:.3f}  "
              f"Δ={jump:+.3f}  {'↑ jump' if up else '— no jump'}  (n={n_t}/{n_v})")

    if rows:
        mt = sum(r[1] for r in rows) / len(rows)
        mv = sum(r[2] for r in rows) / len(rows)
        print(f"\n  mean over {len(rows)} labelers: κ_text={mt:.3f} → κ_trace={mv:.3f}  (Δ={mv - mt:+.3f})")
        verdict = ("ROBUST — every labeler's κ rises with the trace, so the evidence-modality "
                   "ceiling is not an artifact of one annotator"
                   if all_jump_up and len(rows) >= 2 else
                   "INCONCLUSIVE — need >=2 labelers all showing the jump"
                   if not all_jump_up else
                   "single labeler — add more to separate modality from annotator")
        print(f"  finding: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
