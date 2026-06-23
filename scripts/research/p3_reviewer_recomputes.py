#!/usr/bin/env python3
"""P3 reviewer-response recomputes — three offline hardening checks (no DB, no spend).

All three recompute from already-released frozen tables, reusing the exact breach/tau
definitions of p3_judge_independence.py and p3_objective_decompose.py.

  (1) Cell-level inter-judge agreement (Cohen's kappa, pairwise + Fleiss 3-way) among the
      three judge models. Table 6 shows only that *aggregate rates* agree; this answers the
      reviewer's actual fear -- correlated failures -- by measuring case-by-case agreement.
  (2) Within-stratum collapse under the SECOND objective classifier (Qwen, kappa=0.79 with
      primary). Shows the order-of-magnitude collapse survives both labelings, defusing the
      "stratification rests on only kappa=0.58 agreement" concern.
  (3) Minimum-detectable Spearman rho at n=56 (a-priori power), and the achieved power to
      detect PrompTrend's reported +0.318. Converts "underpowered" from a vague concession
      into a precise scoping statement.

  uv run python scripts/research/p3_reviewer_recomputes.py
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "research"
TAU = 0.4
LLAMA = "acme-llama3-20260526"
ROBUST = "acme-claudehaiku-20260526"
PANEL = {
    "acme-gpt54nano-20260526", "acme-mistralsm-20260526",
    "acme-geminiflashlite-20260526", "acme-llama3-20260526",
    "acme-claudehaiku-20260526",
}
BREACH = {"partial_breach", "full_breach"}

JUDGES = [
    ("judge_v3", "p3_v3_rejudge_trials.jsonl", "v3"),
    ("Qwen-2.5-72B", "p3_consummation_qwen-qwen-2-5-72b-instruct_trials.jsonl", "bool"),
    ("DeepSeek-v3.1", "p3_consummation_deepseek-deepseek-chat-v3-1_trials.jsonl", "bool"),
]


def cell_rates(path: Path, kind: str):
    """-> {(pid,cfg): breach_rate} over panel cfgs only."""
    cell = defaultdict(lambda: [0, 0])
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        cfg = r["cfg"]
        if cfg not in PANEL:
            continue
        pid = r.get("pid") or r.get("primitive_id")
        k = (pid, cfg)
        cell[k][0] += 1
        hit = (str(r["v3_verdict"]).lower() in BREACH) if kind == "v3" else bool(r["breach"])
        if hit:
            cell[k][1] += 1
    return {k: (b / t if t else 0.0) for k, (t, b) in cell.items()}


def cohens_kappa(a, b):
    """a, b: equal-length 0/1 lists."""
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pa1, pb1 = sum(a) / n, sum(b) / n
    pe = pa1 * pb1 + (1 - pa1) * (1 - pb1)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0, po


def fleiss_kappa_binary(rows):
    """rows: list of (count_class0, count_class1) per item, fixed n raters."""
    N = len(rows)
    n = rows[0][0] + rows[0][1]
    p = [sum(r[j] for r in rows) / (N * n) for j in (0, 1)]
    Pe = sum(pj * pj for pj in p)
    Pbar = sum((sum(c * c for c in r) - n) / (n * (n - 1)) for r in rows) / N
    return (Pbar - Pe) / (1 - Pe) if Pe < 1 else 1.0


def jaccard_positive(a, b):
    inter = sum(x and y for x, y in zip(a, b))
    union = sum(x or y for x, y in zip(a, b))
    return inter / union if union else float("nan")


def recompute_1_interjudge():
    print("=" * 78)
    print("(1) CELL-LEVEL INTER-JUDGE AGREEMENT  (panel cfgs only; unit = primitive x model)")
    print("=" * 78)
    rates = {name: cell_rates(DATA / fn, kind) for name, fn, kind in JUDGES}
    for defn, fn in (("reproduce@tau=0.4", lambda r: r >= TAU), ("any-breach (rate>0)", lambda r: r > 0)):
        print(f"\n  binary definition: {defn}")
        bins = {name: {k: (1 if fn(v) else 0) for k, v in rr.items()} for name, rr in rates.items()}
        names = [n for n, _, _ in JUDGES]
        # pairwise
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                A, B = bins[names[i]], bins[names[j]]
                keys = sorted(set(A) & set(B))
                a = [A[k] for k in keys]; b = [B[k] for k in keys]
                kap, po = cohens_kappa(a, b)
                jac = jaccard_positive(a, b)
                print(f"    {names[i]:13s} vs {names[j]:13s}  n={len(keys):4d}  "
                      f"agree={po*100:5.1f}%  kappa={kap:+.3f}  pos-overlap(Jaccard)={jac:.3f}")
        # 3-way Fleiss over cells graded by all three
        keys = sorted(set(bins[names[0]]) & set(bins[names[1]]) & set(bins[names[2]]))
        rows = []
        for k in keys:
            ones = sum(bins[nm][k] for nm in names)
            rows.append((len(names) - ones, ones))
        fk = fleiss_kappa_binary(rows)
        unan = sum(1 for c0, c1 in rows if c0 == 0 or c1 == 0)
        print(f"    3-way Fleiss kappa  n={len(keys):4d}  kappa={fk:+.3f}  "
              f"unanimous on {unan/len(keys)*100:.1f}% of cells")


def funnel(prims, cell):
    def repro(p, only=None):
        rs = {cf: (b / t if t else 0.) for (p2, cf), (t, b) in cell.items() if p2 == p}
        return (rs.get(only, 0.) if only else (max(rs.values()) if rs else 0.)) >= TAU
    n = len(prims)
    if not n:
        return (0, 0., 0., 0.)
    return (n,
            100 * sum(repro(p) for p in prims) / n,
            100 * sum(repro(p, LLAMA) for p in prims) / n,
            100 * sum(repro(p, ROBUST) for p in prims) / n)


def recompute_2_qwen_strata():
    print("\n" + "=" * 78)
    print("(2) WITHIN-STRATUM COLLAPSE under PRIMARY (Sonnet) vs SECOND (Qwen) classifier")
    print("=" * 78)
    cell = defaultdict(lambda: [0, 0])
    for line in (DATA / "p3_v3_rejudge_trials.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        x = json.loads(line)
        k = (x["primitive_id"], x["cfg"])
        cell[k][0] += 1
        if str(x["v3_verdict"]).lower() in BREACH:
            cell[k][1] += 1
    prims_all = sorted({p for p, _ in cell})

    def load(path, vocab_norm=lambda o: o):
        m = {}
        for line in path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                m[r["primitive_id"]] = vocab_norm(r["objective"])
        return m

    primary = load(DATA / "p3_objective_classification.jsonl")
    qwen = load(DATA / "p3_objective_classification2_qwen-qwen-2-5-72b-instruct.jsonl")

    order = ["harmful_content", "agentic_compromise", "info_extraction", "generic_jailbreak", "ambiguous"]
    for label, cls in (("PRIMARY (Sonnet)", primary), ("SECOND (Qwen)", qwen)):
        print(f"\n  --- {label} ---  ({len([p for p in prims_all if p in cls])} of {len(prims_all)} classified)")
        print(f"  {'objective':22s} {'n':>4} {'>=1of5':>8} {'Llama':>8} {'robust':>8}   fold")
        seen = set()
        for obj in order:
            ps = [p for p in prims_all if cls.get(p) == obj]
            if not ps:
                continue
            seen.add(obj)
            n, pan, anc, rob = funnel(ps, cell)
            fold = pan / rob if rob else float("inf")
            print(f"  {obj:22s} {n:>4} {pan:>7.1f}% {anc:>7.1f}% {rob:>7.1f}%   {fold:>4.1f}x")
        n, pan, anc, rob = funnel(prims_all, cell)
        print(f"  {'ALL':22s} {n:>4} {pan:>7.1f}% {anc:>7.1f}% {rob:>7.1f}%   {pan/rob:>4.1f}x")


def _phi_inv(p):
    """Inverse standard normal CDF (Acklam)."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    pl = 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p <= 1 - pl:
        q = p - 0.5; r = q*q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def _phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def recompute_3_power():
    print("\n" + "=" * 78)
    print("(3) C2 POWER ANALYSIS  (Spearman, Fisher-z approximation)")
    print("=" * 78)
    n = 56
    alpha = 0.05
    se = 1 / math.sqrt(n - 3)
    z_alpha = _phi_inv(1 - alpha / 2)
    for power in (0.80, 0.90):
        z_beta = _phi_inv(power)
        zr = (z_alpha + z_beta) * se
        r = math.tanh(zr)
        print(f"  min detectable |rho| at {int(power*100)}% power (alpha=.05, two-sided), n={n}:  {r:.3f}")
    # achieved power to detect PrompTrend's +0.318
    for r0, name in ((0.318, "PrompTrend r=+0.318"),):
        zr = math.atanh(r0)
        power = _phi(zr / se - z_alpha) + _phi(-zr / se - z_alpha)
        print(f"  achieved power to detect {name} at n={n}:  {power*100:.0f}%")
    print(f"  (observed point estimate rho=-0.068, 95% CI [-0.342, +0.193] -- "
          f"consistent with everything from a moderate negative to a moderate positive)")


if __name__ == "__main__":
    recompute_1_interjudge()
    recompute_2_qwen_strata()
    recompute_3_power()
