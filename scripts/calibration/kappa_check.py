"""Second-author κ check for a designed-label corpus (ADR-0011 independence step).

The calibration number (e.g. info-disclosure agreement 97.67%) is computed against
labels a single author wrote *by construction*, so it is optimistic until a
*second, independent* person re-labels a blind sample and substantially agrees.
This tool makes that a ~10-minute task:

    # 1) export a blind, stratified sample (NO original labels leaked)
    uv run python scripts/calibration/kappa_check.py export \
        --labels tests/fixtures/labels/infodisc_designed_v1.json \
        --n 20 --out data/calibration/kappa_worksheet.json

    # 2) a SECOND person (not the case author) reads each case + the rubric and
    #    fills "second_label": "breach" | "clean"  in the worksheet.

    # 3) score: Cohen's kappa vs the original labels + the disagreements to adjudicate
    uv run python scripts/calibration/kappa_check.py score \
        --labels tests/fixtures/labels/infodisc_designed_v1.json \
        --worksheet data/calibration/kappa_worksheet.json

Cohen's kappa, binary, stdlib only (no scipy — same minimalism as calibration/bootstrap.py).
Interpretation: κ ≥ 0.80 almost-perfect (labels reliable → the calibration stands);
0.60–0.80 substantial (adjudicate the disagreements, fix genuine ambiguities, re-run);
< 0.60 (the labels are not reliable — the calibration number is suspect, re-author).
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

# Fields the second author is allowed to see — everything they need to apply the
# rubric, and NOTHING that leaks the answer (no human_label / rationale / fp_mode_trap).
_VISIBLE = ("case_id", "rule_text", "protected_target", "probe_payload", "model_response")


def _load_cases(labels_path: str) -> list[dict]:
    raw = json.loads(Path(labels_path).read_text())
    cases = raw["cases"] if isinstance(raw, dict) and "cases" in raw else raw
    return [c for c in cases if isinstance(c, dict) and c.get("case_id")]


def export(args) -> None:
    cases = _load_cases(args.labels)
    # Stratify so both classes AND the FP-mode traps (the load-bearing cases) are
    # represented; shuffle within strata so order leaks nothing.
    rng = random.Random(args.seed)
    strata = {"breach": [], "clean_trap": [], "clean_plain": []}
    for c in cases:
        if c["human_label"] == "breach":
            strata["breach"].append(c)
        elif c.get("fp_mode_trap"):
            strata["clean_trap"].append(c)
        else:
            strata["clean_plain"].append(c)
    for v in strata.values():
        rng.shuffle(v)
    # Proportional allocation to n, with a floor of 1 per non-empty stratum.
    total = sum(len(v) for v in strata.values())
    picks: list[dict] = []
    for v in strata.values():
        if not v:
            continue
        k = max(1, round(args.n * len(v) / total))
        picks.extend(v[:k])
    rng.shuffle(picks)
    picks = picks[: args.n]
    worksheet = [{**{f: c.get(f) for f in _VISIBLE}, "second_label": ""} for c in picks]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(worksheet, indent=2, ensure_ascii=False))
    # Name the correct rubric for THIS breach type (derived from the label set).
    bt = picks[0].get("breach_type") if picks else None
    rubric = "the rubric for this breach type"
    if bt:
        try:
            from rogue.reproduce.rubrics import get_breach_type
            rubric = f"src/rogue/reproduce/prompts/{get_breach_type(bt).rubric_filename}"
        except Exception:
            rubric = f"the {bt} rubric"
    print(f"wrote {len(worksheet)} blind cases → {out}")
    print(f"Now: read the rubric ({rubric}), then for")
    print('each case set "second_label" to "breach" or "clean". Do NOT look at the fixture.')


def _kappa(a: list[str], b: list[str]) -> tuple[float, float]:
    n = len(a)
    p_o = sum(x == y for x, y in zip(a, b)) / n
    classes = {"breach", "clean"}
    p_e = sum((a.count(c) / n) * (b.count(c) / n) for c in classes)
    kappa = 1.0 if p_e == 1.0 else (p_o - p_e) / (1 - p_e)
    return p_o, kappa


def score(args) -> None:
    truth = {c["case_id"]: c for c in _load_cases(args.labels)}
    ws = json.loads(Path(args.worksheet).read_text())
    pairs = []
    for row in ws:
        sl = (row.get("second_label") or "").strip().lower()
        if sl not in ("breach", "clean"):
            print(f"!! {row['case_id']}: second_label not filled in ('{sl}') — fill all rows first.")
            return
        orig = truth.get(row["case_id"])
        if orig is None:
            print(f"!! {row['case_id']} not in the fixture — skipping.")
            continue
        pairs.append((row["case_id"], orig["human_label"], sl, orig))
    a = [orig for _, orig, _, _ in pairs]
    b = [sec for _, _, sec, _ in pairs]
    p_o, kappa = _kappa(a, b)
    verdict = ("RELIABLE — labels confirmed, calibration stands" if kappa >= 0.80
               else "INVESTIGATE — adjudicate the disagreements, fix ambiguities, re-run" if kappa >= 0.60
               else "UNRELIABLE — re-author; the calibration number is suspect")
    print("=" * 64)
    print(f"second-author κ check  (n={len(pairs)})")
    print(f"  raw agreement = {p_o:.1%}")
    print(f"  Cohen's κ     = {kappa:.3f}   →  {verdict}")
    print("=" * 64)
    diffs = [(cid, orig, sec, c) for (cid, orig, sec, c) in pairs if orig != sec]
    if not diffs:
        print("no disagreements — perfect agreement.")
    else:
        print(f"{len(diffs)} disagreement(s) to adjudicate (author-label vs second-label):")
        for cid, orig, sec, c in diffs:
            trap = " [FP-MODE TRAP]" if c.get("fp_mode_trap") else ""
            print(f"\n  • {cid}{trap}: author='{orig}'  second='{sec}'")
            print(f"      rule: {c.get('rule_text')}")
            print(f"      author rationale: {c.get('label_rationale')}")
        print("\nFor each: decide (i) labeler misread rubric → original stands; "
              "(ii) original mislabeled → fix the fixture; (iii) genuine ambiguity → rewrite/drop the case.")
    print("\nWhen κ ≥ 0.80: set the fixture's `kappa_check` to the value + date, and update "
          "docs/research/judge_calibration_paper.md §4 (replace 'preliminary until κ' with the result).")


def main() -> None:
    p = argparse.ArgumentParser(description="Second-author κ check for a designed-label corpus.")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help="write a blind stratified sample worksheet")
    e.add_argument("--labels", required=True)
    e.add_argument("--n", type=int, default=20)
    e.add_argument("--seed", type=int, default=7)
    e.add_argument("--out", default="data/calibration/kappa_worksheet.json")
    e.set_defaults(func=export)
    s = sub.add_parser("score", help="compute Cohen's κ vs the original labels")
    s.add_argument("--labels", required=True)
    s.add_argument("--worksheet", required=True)
    s.set_defaults(func=score)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
