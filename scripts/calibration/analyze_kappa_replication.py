"""P2 multi-labeler replication analysis -- honest (post-hoc) reporting.

The single-annotator evidence-modality result (second-labeler kappa 0.746->0.917 on actions,
0.723->0.909 on fabrications, Delta-kappa +0.171) is tested against an independent six-labeler
panel. Each labeler graded the SAME cases text-only (round 1) then with the captured trace
(round 2); kappa is each labeler vs the operator's by-construction label, per round.

HEADLINE (raw, no correction): the single-annotator jump does NOT replicate. The raw mean
with-trace effect across the six labelers is Delta-kappa = +0.011.

WHY A "CORRECTION" IS NOT NEUTRAL HERE. In the with-trace round the panel diverges from the
operator's by-construction labels in BOTH directions: breach-on-clean (a labeler stricter than
the operator) and clean-on-breach (a labeler more lenient). A trace-comprehension exclusion
that flips trace-induced breach-on-clean verdicts back to clean recovers Delta-kappa = +0.147.
But this is a POST-HOC analysis and it must be read as one:

  1. The exclusion rule was selected by the output it produced. A looser first version (flag any
     breach-on-clean) gave a flattering +0.244 and was rejected; the operative rule was tightened
     until it gave +0.147. Choosing the threshold by the number it yields is selection on outcome.
  2. The rule touches ONLY the breach-on-clean-and-trace-induced subset -- exactly the divergences
     whose correction RAISES kappa -- and passes over every divergence that would lower it,
     including the clean-on-breach cases where labelers judged the operator's ground truth too
     strict. Correcting only the divergences that help the statistic is selection on outcome one
     level up from (1).

We therefore report +0.011 as the result and +0.147 only as a disclosed artifact, and we emit
EVERY divergence in both directions (not just the kappa-raising subset) so the reader adjudicates
each case against the released worksheet rather than against any rule of ours. Cohen's kappa via
the house helper in scripts/calibration/kappa_check.py (stdlib only).

    uv run python scripts/calibration/analyze_kappa_replication.py
"""
import glob
import importlib.util
import json
import math
import re
from collections import Counter
from pathlib import Path

_H = Path("scripts/calibration")
_FIX = ["tests/fixtures/labels/unauthorized_action_designed_v1.json",
        "tests/fixtures/labels/fabricated_sensitive_value_designed_v1.json"]
_WS = ["data/calibration/kappa_worksheet_unauth_v3.json",
       "data/calibration/kappa_worksheet_fabricated_v2.json"]
_TRACE_RE = re.compile(r"\n+\[(?:TOOL TRACE|RETRIEVAL)\]", re.IGNORECASE)


def _kappa():
    s = importlib.util.spec_from_file_location("kc", _H / "kappa_check.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m._kappa


def _load(fn):
    d = json.loads(Path(fn).read_text())
    return d.get("cases", d) if isinstance(d, dict) else d


def _trace_excerpt(resp: str) -> str:
    """The verbatim trace/retrieval block the labeler saw -- no interpretation."""
    if not _TRACE_RE.search(resp):
        return ""
    tail = resp[len(_TRACE_RE.split(resp, 1)[0]):]
    return " ".join(tail.split())[:140]


def main() -> int:
    kappa = _kappa()
    # The original per-case human-label fixtures (_FIX) this re-derivation reads carry
    # annotator identity and are withheld from the anonymous supplement. When the script
    # is run from the released supplement (fixtures absent) rather than the full repo,
    # point the reviewer at the frozen artifact instead of failing with a traceback.
    if not all(Path(fn).exists() for fn in _FIX):
        print("Note: the per-case human-label fixtures this script re-derives kappa from are")
        print("withheld from the anonymous supplement because they carry annotator identity.")
        print("The kappa result is frozen in data/calibration/kappa_audit_table.md")
        print("(delta-kappa = +0.011, 0.684 -> 0.695; sign-test p = 0.38), and the per-labeler")
        print("relabel worksheets in data/calibration/kappa_relabels/ let you audit each of the")
        print("45 divergences case by case. This script ships as inspection source for the")
        print("methodology; run it inside the full repository to recompute from scratch.")
        return 0
    op = {}
    for fn in _FIX:
        for c in _load(fn):
            if isinstance(c, dict) and c.get("case_id"):
                op[c["case_id"]] = (c.get("human_label") or "").lower()
    ws = {}
    for fn in _WS:
        for c in _load(fn):
            ws[c["case_id"]] = c["model_response"]

    labs = {}
    for f in sorted(glob.glob("data/calibration/p2_kappa_relabels/*.json")):
        d = json.loads(Path(f).read_text())
        labs[d["labeler"]] = {"t": d["phase1_text_only"], "v": d["phase2_with_trace"]}

    def kv(verds):
        a, b = [], []
        for cid, v in verds.items():
            if cid in op:
                a.append(op[cid])
                b.append(v)
        return kappa(a, b)[1] if len(a) >= 2 else float("nan")

    # --- every with-trace divergence from the operator, BOTH directions ---
    diverg = []  # (labeler, cid, op_label, lab_label, direction, trace_induced)
    for n, d in labs.items():
        for cid, v in d["v"].items():
            o = op.get(cid)
            if o is None or v == o:
                continue
            direction = "breach-on-clean" if (o == "clean" and v == "breach") else \
                        "clean-on-breach" if (o == "breach" and v == "clean") else "other"
            trace_induced = d["t"].get(cid) == "clean" and v == "breach" and o == "clean"
            diverg.append((n, cid, o, v, direction, trace_induced))

    boc = [r for r in diverg if r[4] == "breach-on-clean"]
    cob = [r for r in diverg if r[4] == "clean-on-breach"]
    flagged = [r for r in diverg if r[5]]  # the 21 the post-hoc rule would touch

    # --- corrected (post-hoc, disclosed) Delta-kappa: flip only the flagged subset to clean ---
    rows = []
    for n, d in labs.items():
        vc = dict(d["v"])
        for (_, cid, *_rest) in [r for r in flagged if r[0] == n]:
            vc[cid] = "clean"
        rows.append((n, kv(d["t"]), kv(d["v"]), kv(vc),
                     sum(1 for r in flagged if r[0] == n)))

    mt = sum(r[1] for r in rows) / len(rows)
    mr = sum(r[2] for r in rows) / len(rows)
    mc = sum(r[3] for r in rows) / len(rows)
    print("=== per labeler (kappa vs operator) ===")
    for n, kt, kr, kc, nf in rows:
        print(f"  {n:13s} text={kt:.3f}  trace_raw={kr:.3f}  trace_posthoc={kc:.3f}  flagged={nf}")
    print(f"\n  RAW (headline)         mean Delta-kappa = {mr - mt:+.3f}   (text {mt:.3f} -> trace {mr:.3f})")
    print(f"  POST-HOC (disclosed)   mean Delta-kappa = {mc - mt:+.3f}   (text {mt:.3f} -> trace {mc:.3f})")
    print("  single-annotator (paper)              = +0.171   (0.746 -> 0.917)")
    print("\n=== leave-one-out (raw Delta-kappa over the remaining 5) ===")
    for i, (n, *_) in enumerate(rows):
        rest = [r for j, r in enumerate(rows) if j != i]
        print(f"  drop {n:13s} -> {sum(r[2] - r[1] for r in rest) / len(rest):+.3f}")

    # --- sign test on the per-labeler Delta-kappa (non-parametric, stdlib) ---
    # Uses only the SIGN of each labeler's trace effect, so the one outlier
    # (Labeler 6, -0.310) cannot drive it. AUTO-SCALES with the panel: drop more
    # labeler files into p2_kappa_relabels/ and this p-value re-powers, which is
    # the cheapest way to turn the underpowered null into a decidable one.
    deltas = [r[2] - r[1] for r in rows]
    pos = sum(d > 0 for d in deltas)
    neg = sum(d < 0 for d in deltas)
    nz = pos + neg
    kmin = min(pos, neg)
    tail = sum(math.comb(nz, i) for i in range(kmin + 1)) / (2 ** nz) if nz else 1.0
    p_sign = min(1.0, 2 * tail)
    print("\n=== sign test on per-labeler Delta-kappa (H0: median = 0) ===")
    print(f"  n={len(deltas)} labelers: {pos} positive, {neg} negative, "
          f"{len(deltas) - nz} zero  ->  two-sided exact sign-test p = {p_sign:.3f} "
          f"({'REJECTS' if p_sign < 0.05 else 'does NOT reject'} zero at alpha=0.05)")

    print("\n=== divergence accounting (the selection asymmetry) ===")
    print(f"  total with-trace divergences from operator : {len(diverg)}")
    print(f"    breach-on-clean (labeler stricter)       : {len(boc)}")
    print(f"      of which trace-induced (the post-hoc subset): {len(flagged)}")
    print(f"    clean-on-breach (labeler more lenient)   : {len(cob)}")
    print(f"  the post-hoc 'correction' touches {len(flagged)} of {len(diverg)} divergences "
          f"-- only those that RAISE kappa; it passes over the other {len(diverg) - len(flagged)}, "
          f"including the {len(cob)} clean-on-breach.")

    # --- panel-MAJORITY vs operator (non-self idiosyncrasy anchor) ---
    # Complementary to the per-labeler kappa null above: the kappa null says
    # individual second-labeler agreement does not jump with the trace; this
    # asks whether the six-labeler CONSENSUS ever forms AGAINST the operator's
    # by-construction label on these boundary cases. A "clear majority" is >=4
    # of 6; a 3-3 split is no majority either way. This does NOT bear on the
    # evidence-modality effect -- it bounds how idiosyncratic the labels are.
    cases_v = sorted({cid for d in labs.values() for cid in d["v"] if cid in op})

    def klass(c):
        if c.startswith("unauth"):
            return "unauthorized-action"
        return "fabricated-value" if c.startswith("fsv") else "other"

    print("\n=== panel-MAJORITY vs operator (with trace; non-self idiosyncrasy anchor) ===")
    tot_agree = tot_against = tot_tie = 0
    for kn in ("unauthorized-action", "fabricated-value"):
        cs = [c for c in cases_v if klass(c) == kn]
        agree = against = tie = 0
        for c in cs:
            top, k = Counter(labs[n]["v"][c] for n in labs).most_common(1)[0]
            if k < 4:
                tie += 1
            elif top == op[c]:
                agree += 1
            else:
                against += 1
        rates = [sum(labs[n]["v"][c] == op[c] for c in cs) / len(cs) for n in labs]
        tot_agree += agree
        tot_against += against
        tot_tie += tie
        print(f"  {kn:20s} clear-majority(>=4) agrees-with-operator {agree}/{len(cs)}  "
              f"against={against}  3-3 ties={tie}  | per-labeler raw "
              f"mean={sum(rates)/len(rates):.1%} [{min(rates):.0%}-{max(rates):.0%}]")
    nm = tot_agree + tot_against
    print(f"  BOTH (2 of 3 designed classes; info-disclosure NOT in this panel): "
          f"of {nm} cases with a clear majority, {tot_agree} agree with the operator and "
          f"{tot_against} go against; the remaining {tot_tie} are 3-3 deadlocks (no majority).")

    # --- audit table: EVERY divergence, both directions, no 'rule violated' verdict ---
    md = ["# P2 six-labeler panel: every divergence from operator ground truth (both directions)\n",
          f"Raw with-trace effect (headline): Delta-kappa = **{mr - mt:+.3f}** "
          f"(text {mt:.3f} -> trace {mr:.3f}); the single-annotator jump (+0.171) does not replicate.\n",
          f"Divergences total: **{len(diverg)}** = {len(boc)} breach-on-clean "
          f"(of which {len(flagged)} trace-induced) + {len(cob)} clean-on-breach. "
          f"A post-hoc exclusion of the {len(flagged)} trace-induced breach-on-clean verdicts "
          f"recovers Delta-kappa +{mc - mt:.3f}, but it touches only the {len(flagged)} of {len(diverg)} "
          f"divergences that raise kappa and ignores the other {len(diverg) - len(flagged)} "
          f"(including the {len(cob)} where labelers found the ground truth too strict); "
          f"the rule was also tuned to its output, so it is not a neutral correction. "
          f"Read each case against the released worksheet and decide for yourself.\n",
          "| labeler | case | operator | labeler | direction | trace-induced | trace the labeler saw |",
          "|---|---|---|---|---|---|---|"]
    for n, cid, o, v, direction, ti in sorted(diverg, key=lambda r: (r[4], r[1], r[0])):
        md.append(f"| {n} | `{cid}` | {o} | {v} | {direction} | {'yes' if ti else 'no'} | "
                  f"`{_trace_excerpt(ws.get(cid, '')) or '(no trace block)'}` |")
    Path("data/calibration/p2_kappa_audit_table.md").write_text("\n".join(md))
    print(f"\n  wrote audit table ({len(diverg)} divergences, both directions) "
          f"-> data/calibration/p2_kappa_audit_table.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
