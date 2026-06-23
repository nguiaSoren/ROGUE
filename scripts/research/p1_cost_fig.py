#!/usr/bin/env python3
"""Regenerate the scheduler paper's cost-per-graduation figure HONESTLY — from the released
scheduler_results.json (no DB, no metrics.json needed), so it stays reproducible.

The point of this version (vs the old f4_cost_per_grad in paper_figs.py): the three
sweeps do NOT share a cost basis (K=3,5 spend-capped; K=20 uncapped), so plotting them
as a solid connected curve over-reads. Here they are discrete points with distinct
capped/uncapped markers and a DASHED directional connector (explicitly "not fitted"),
matching the paper's claim-reduction: the direction is structural, the magnitudes are
illustrative.

Usage:  uv run python scripts/research/p1_cost_fig.py
Writes: docs/research/publishing/p1_scheduler/fig-cost-per-grad.png
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams.update({"font.family": "serif", "font.serif": ["STIXGeneral", "DejaVu Serif"],
                     "mathtext.fontset": "stix"})
C_GROWTH, C_GREY, C_VERM = "#0072B2", "#999999", "#D55E00"

ROOT = Path(__file__).resolve().parents[2]
by_K = json.loads((ROOT / "data/research/scheduler_results.json").read_text())["cost_per_graduation_usd"]["by_K"]
by_K = sorted(by_K, key=lambda r: r["K"])
K = [r["K"] for r in by_K]
cpg = [r["cost_per_graduation_usd"] for r in by_K]
capped = [k <= 5 for k in K]   # K=3,5 spend-capped; K=20 uncapped

fig, ax = plt.subplots(figsize=(6.6, 4.2), constrained_layout=True)
# directional connector — DASHED + grey, explicitly not a fitted curve
ax.plot(K, cpg, "--", color=C_GREY, lw=1.3, zorder=2, label="directional trend (not fitted)")
ax.scatter([k for k, c in zip(K, capped) if c], [v for v, c in zip(cpg, capped) if c],
           s=85, color=C_GROWTH, marker="o", zorder=4, label="spend-capped sweep (K=3,5)")
ax.scatter([k for k, c in zip(K, capped) if not c], [v for v, c in zip(cpg, capped) if not c],
           s=115, color=C_VERM, marker="D", zorder=4, label="uncapped sweep (K=20)")
for k, v in zip(K, cpg):
    ax.annotate(f"${v:.2f}", (k, v), textcoords="offset points", xytext=(0, 12),
                ha="center", fontsize=9, color="#333", zorder=5)
blo, bhi = K[-1], K[-1] + 3
ax.axvspan(blo, bhi, color=C_GREY, alpha=0.12, zorder=0)
ax.plot([blo, bhi], [cpg[-1], cpg[-1] * 1.4], ":", color=C_GREY, lw=1.2, zorder=2)
ax.annotate("saturation\nunmeasured\n(past K=20)", (blo + 1.5, max(cpg) * 0.52),
            ha="center", va="center", fontsize=8, color="#666")
ax.set_xlabel("K  (candidates evaluated per growth sweep)")
ax.set_ylabel("cost per graduation  ($)")
ax.set_xticks(K); ax.set_xlim(K[0] - 0.5, bhi + 0.3); ax.set_ylim(0, max(cpg) * 1.25)
ax.legend(loc="upper right", frameon=False, fontsize=7.5, labelspacing=1.2, handletextpad=0.7, borderpad=0.6)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
fig.text(0.5, -0.02, "Three measured points on a NON-common cost basis; trend is directional, not a fitted curve.",
         ha="center", fontsize=7, color="#777")
out = ROOT / "docs/research/publishing/p1_scheduler/fig-cost-per-grad.png"
out.parent.mkdir(parents=True, exist_ok=True)  # the offline supplement tree lacks this dir
fig.savefig(out, dpi=200, bbox_inches="tight")
print(f"wrote {out.relative_to(ROOT)}  (K={K}, cpg={cpg})")
