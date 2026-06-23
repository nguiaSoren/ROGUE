#!/usr/bin/env python3
"""Standalone, DB-free recompute of P3's headline numbers from the released
per-primitive pairs CSV. PURE STDLIB — no database, no project package, no pip
installs. This is the supplement's reproduce path; `reproducibility_gap.py`
regenerates the CSV from the database (needs the repo + DATABASE_URL) and is
NOT runnable from the supplement alone.

    python3 reproduce_p3_from_pairs.py [data/research/reproducibility_gap_pairs.csv]
"""
import csv
import math
import sys

PAIRS = sys.argv[1] if len(sys.argv) > 1 else "data/research/reproducibility_gap_pairs.csv"
TAU = 0.4
rows = list(csv.DictReader(open(PAIRS)))


def frac_ge(col, tau=TAU):
    v = [float(r[col]) for r in rows if r[col] != ""]
    return len(v), 100.0 * sum(x >= tau for x in v) / len(v)


def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(x, y):
    rx, ry = _ranks(x), _ranks(y)
    n = len(x)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else 0.0


print(f"C1 reproduction funnel (fraction reproducing at >= tau={TAU}, as the target hardens):")
for col, lab, paper in [("measured_any", "any model", "40.5"),
                        ("measured_llama", "Llama anchor", "9.0"),
                        ("measured_robust", "robust anchor", "3.7")]:
    n, f = frac_ge(col)
    print(f"  {lab:13s} {f:5.1f}%  (n={n})   paper: {paper}%")

cl = [(float(r["claimed_rate"]), float(r["measured_pooled"])) for r in rows if r["claimed_rate"] != ""]
rho = spearman([a for a, _ in cl], [b for _, b in cl])
print(f"\nC2 claimed-vs-measured Spearman: rho={rho:.3f}  n={len(cl)}   paper: -0.10, n=56")
