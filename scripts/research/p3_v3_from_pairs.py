#!/usr/bin/env python3
"""Recompute P3's calibrated-v3 headline from the released pairs CSV — pure stdlib, NO database.

Reads data/research/p3_v3_rejudge_pairs.csv (per-primitive: claimed_rate, source_type,
and v3 reproduction rates) and reproduces the C1 funnel, the C2 Spearman null, and the
claims-≈100% subset under the calibrated judge. This is the supplement's self-contained
verification path (the companion to reproduce_p3_from_pairs.py, which does the same for
the original-grade reproducibility_gap_pairs.csv).

Run:  python3 scripts/research/p3_v3_from_pairs.py
"""
from __future__ import annotations
import csv
from pathlib import Path

TAU = 0.4
CSV = Path(__file__).resolve().parents[2] / "data" / "research" / "p3_v3_rejudge_pairs.csv"


def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i]); rk = [0.0] * len(xs); i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            rk[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return rk


def _spearman(x, y):
    a, b = _ranks(x), _ranks(y); n = len(a)
    if n < 2:
        return float("nan")
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = sum((a[i] - ma) ** 2 for i in range(n)) ** 0.5
    db = sum((b[i] - mb) ** 2 for i in range(n)) ** 0.5
    return num / (da * db) if da and db else float("nan")


def main() -> int:
    rows = list(csv.DictReader(CSV.open()))
    def frac(sel, col):
        sub = [r for r in sel]
        return sum(float(r[col]) >= TAU for r in sub) / len(sub) if sub else 0.0
    allr = rows
    arx = [r for r in rows if r["source_type"] == "arxiv"]
    grey = [r for r in rows if r["source_type"] == "grey-lit"]
    print("C1 funnel (v3, fraction reproducing at τ=0.4):  any  →  Llama  →  robust")
    for lab, sel in [("ALL", allr), ("arXiv", arx), ("grey-lit", grey)]:
        print(f"  {lab:9s} n={len(sel):3d}  {frac(sel,'v3_any'):.3f}  →  {frac(sel,'v3_llama'):.3f}  →  {frac(sel,'v3_robust'):.3f}")
    claimed = [r for r in rows if r["claimed_rate"] not in ("", None)]
    x = [float(r["claimed_rate"]) for r in claimed]; y = [float(r["v3_pooled"]) for r in claimed]
    print(f"\nC2 Spearman(claimed, v3_pooled) = {_spearman(x, y):+.3f}  (n={len(claimed)})")
    hi = [r for r in claimed if float(r["claimed_rate"]) >= 0.999]
    repro = sum(float(r["v3_any"]) >= TAU for r in hi)
    mean = sum(float(r["v3_pooled"]) for r in hi) / len(hi) if hi else 0.0
    print(f"claims ≈100%: {repro} of {len(hi)} reproduce; mean measured = {mean:.3f}")
    # bucket-boundary robustness (paper Sec. C2): the count is not an artifact of the ~100% cut
    for lo in (0.95, 0.90):
        b = [r for r in claimed if float(r["claimed_rate"]) >= lo]
        rb = sum(float(r["v3_any"]) >= TAU for r in b)
        mb = sum(float(r["v3_pooled"]) for r in b) / len(b) if b else 0.0
        print(f"  bucket >= {lo}: {rb} of {len(b)} reproduce; mean measured = {mb:.3f}")
    print("\nExpected (paper): funnel ALL 0.402/0.090/0.037; C2 -0.068, n=56; 6 of 17, mean 0.135;"
          " bucket >=0.95: 12 of 32 (0.154); >=0.90: 13 of 36 (0.144)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
