#!/usr/bin/env python3
"""P3 PrompTrend cross-judge numbers (the C2 disagreement) — recompute OFFLINE from the shipped clean trials.

Pure stdlib; no DB/API. Reproduces the paper's PrompTrend figures from
data/research/promptrend_clean_trials.jsonl (our judge_v3 verdict + PrompTrend's
own keyword 'success' label + PVAF score, per response):
  - response-level agreement (our vs their judge)
  - our breach rate vs their success rate
  - PVAF-vs-measured Spearman under our judge and under theirs

  python3 scripts/research/p3_promptrend_recompute.py
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
T = ROOT / "data" / "research" / "promptrend_clean_trials.jsonl"


def spearman(xs, ys):
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i]); r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    rx, ry = rank(xs), rank(ys)
    n = len(xs); mx = sum(rx) / n; my = sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else 0.0


rows = [json.loads(l) for l in T.read_text().splitlines() if l.strip()]
n = len(rows)
agree = sum(int(bool(r["is_any_breach"]) == bool(r["their_success"])) for r in rows) / n
# per-vuln aggregation (matches the released summary): rate per vulnerability, then averaged
byv = defaultdict(lambda: {"pvaf": None, "our": [], "their": []})
for r in rows:
    v = byv[r["vuln_id"]]; v["pvaf"] = float(r["pvaf_score"])
    v["our"].append(int(bool(r["is_any_breach"]))); v["their"].append(int(bool(r["their_success"])))
our = sum(sum(v["our"]) / len(v["our"]) for v in byv.values()) / len(byv)
their = sum(sum(v["their"]) / len(v["their"]) for v in byv.values()) / len(byv)
recs = [(v["pvaf"], sum(v["our"]) / len(v["our"]), sum(v["their"]) / len(v["their"])) for v in byv.values()]
pvaf = [r[0] for r in recs]
rho_our = spearman(pvaf, [r[1] for r in recs])
rho_their = spearman(pvaf, [r[2] for r in recs])
print(f"PrompTrend C2 cross-judge recompute ({len(byv)} vulnerabilities, {n} responses):")
print(f"  response-level agreement (ours vs theirs): {100*agree:.1f}%")
print(f"  breach/success rate:  ours {100*our:.1f}%  vs  theirs {100*their:.1f}%")
print(f"  rho(PVAF, measured)   OUR judge {rho_our:+.3f}   THEIR judge {rho_their:+.3f}")
print("  Expected (paper): agreement 96.3%; ours 1.9% vs theirs 1.8%; rho +0.095 (ours) / -0.069 (theirs)")
