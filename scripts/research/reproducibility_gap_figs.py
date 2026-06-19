"""Render the reproducibility-gap figures from the harness results JSON.

Reads data/research/reproducibility_gap_results.json (written by
reproducibility_gap.py) and writes PNGs to docs/research/figs/ (gitignored-local,
per the docs/research/README figure convention).

  F1  reproduction funnel — arxiv vs grey-lit, any-model -> Llama anchor -> robust
  F2  carrier reproduction by family (bars) with mean-claimed overlay
  F3  C2 scatter — claimed_success_rate vs measured pooled rate, by source stratum

All numbers are read from the FROZEN snapshot only:
  - F1/F2 + every summary stat (rho, n, inset) come from
    data/research/reproducibility_gap_results.json (the 2026-06-13 snapshot).
  - F3's 56 per-primitive scatter points are PINNED below as frozen constants.
    The live Neon DB has drifted since the snapshot (extra reproduce rows shift
    per-primitive y-values: e.g. reproduce>0 of the ~100%-claimers moved 7 -> 8
    and pooled rho moved -0.098 -> -0.082), so this script must NEVER re-query it.
    The pinned set was captured with `b.ran_at < '2026-06-12'`, which exactly
    reproduces the frozen pooled rho = -0.0979 and the 7/13% inset.

Run:  uv run --with matplotlib python scripts/research/reproducibility_gap_figs.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
FIGS = ROOT / "docs" / "research" / "figs"
FIGS.mkdir(parents=True, exist_ok=True)
RES = json.loads((ROOT / "data" / "research" / "reproducibility_gap_results.json").read_text())

# Okabe-Ito colorblind-safe palette (shared across the publishing batch).
INK = "#16181d"; GREY = "#999999"; ARXIV = "#0072B2"; GREYLIT = "#E69F00"; ROBUST = "#c2354d"
plt.rcParams.update({"font.size": 11, "axes.edgecolor": "#444444",
                     "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": "#bbbbbb",
                     "grid.linewidth": 0.6, "grid.alpha": 0.25,
                     "axes.axisbelow": True, "figure.facecolor": "white",
                     "axes.facecolor": "white", "savefig.facecolor": "white",
                     "figure.dpi": 150, "savefig.dpi": 200, "savefig.bbox": "tight",
                     "font.family": "serif", "font.serif": ["STIXGeneral", "DejaVu Serif"],
                     "mathtext.fontset": "stix"})

# ---------------------------------------------------------------- F1 funnel
f = RES["C1_funnel"]
stages = ["≥1 of 5\nmodels", "frozen\nLlama-8B", "robust\nClaude-Haiku"]
x = range(len(stages))
fig, ax = plt.subplots(figsize=(7, 4.4), constrained_layout=True)
ax.grid(axis="x", visible=False)
for label, color in [("arxiv", ARXIV), ("grey-lit", GREYLIT)]:
    d = f[label]
    ys = [d["any"]["rate"], d["llama"]["rate"], d["robust"]["rate"]]
    los = [d[k]["ci"][0] for k in ("any", "llama", "robust")]
    his = [d[k]["ci"][1] for k in ("any", "llama", "robust")]
    err = [[y - lo for y, lo in zip(ys, los)], [hi - y for y, hi in zip(ys, his)]]
    ax.errorbar(x, ys, yerr=err, marker="o", ms=8, lw=2.5, capsize=4,
                color=color, ecolor=color, elinewidth=1.4, zorder=3,
                label={"arxiv": "arXiv", "grey-lit": "grey literature"}[label])
    # offsets keep the % labels off the line/CI bars and off the other series
    voff = 9 if label == "arxiv" else -18
    hoff = 11 if label == "arxiv" else 13
    for xi, yi in zip(x, ys):
        ax.annotate(f"{yi:.0%}", (xi, yi), textcoords="offset points", xytext=(hoff, voff),
                    fontsize=10, color=color, weight="bold", zorder=4)
ax.set_xticks(list(x)); ax.set_xticklabels(stages)
ax.set_xlim(-0.3, 2.45)
ax.set_ylabel("carrier reproduction rate (τ = 0.4)")
ax.set_ylim(0, 0.68)
ax.legend(frameon=False, loc="upper right", handlelength=1.6)
ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
fig.savefig(FIGS / "repro_gap_F1_funnel.png"); plt.close(fig)

# ---------------------------------------------------------------- F2 by family
fams = [r for r in RES["C3_families"] if r["n"] >= 3]   # drop singletons for legibility
fams.sort(key=lambda r: r["repro"])
names = [r["family"].replace("_", " ") for r in fams]
repro = [r["repro"] for r in fams]
claim = [r["mean_claim"] for r in fams]
y = range(len(fams))
fig, ax = plt.subplots(figsize=(8, 5.2))
ax.barh(list(y), repro, color=ARXIV, alpha=0.85, label="measured reproduction (τ=0.4)")
for yi, r in zip(y, fams):
    if r["mean_claim"] is not None:
        ax.plot(r["mean_claim"], yi, marker="D", ms=8, color=ROBUST, ls="none", zorder=4)
    ax.annotate(f"n={r['n']}", (0.005, yi), va="center", fontsize=8, color="white", weight="bold")
ax.set_yticks(list(y)); ax.set_yticklabels(names, fontsize=9)
ax.set_xlim(0, 1.05); ax.set_xlabel("rate")
ax.plot([], [], marker="D", color=ROBUST, ls="none", label="mean claimed success (source)")
# legend below the axes, clear of the bars and diamonds
ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.09), ncol=2, fontsize=9)
fig.savefig(FIGS / "repro_gap_F2_by_family.png"); plt.close(fig)

# ---------------------------------------------------------------- F3 scatter
# frozen 2026-06-13 snapshot — do not re-query live DB.
# Each point is [claimed_success_rate, measured_pooled_breach_rate, is_arxiv].
# Captured with `b.ran_at < '2026-06-12'`, which exactly reproduces the frozen
# pooled Spearman rho = -0.0979 (n=56) and the 7-reproduce / 13%-mean inset.
SCATTER_POINTS = [
    [1.0, 0.0, False], [1.0, 0.104762, False], [0.5, 0.507692, False], [1.0, 0.2, False],
    [1.0, 0.0, False], [1.0, 0.5, False], [0.9365, 0.0, False], [1.0, 0.0, False],
    [0.95, 0.0, True], [0.9952, 0.12, True], [1.0, 0.740741, False], [0.3, 0.72, False],
    [1.0, 0.0, False], [0.97, 0.16, True], [0.991, 0.4, True], [0.68, 0.08, True],
    [0.9952, 0.0, True], [0.8, 0.0, True], [0.95, 0.0, True], [0.6, 0.0, False],
    [1.0, 0.16, False], [1.0, 0.0, False], [1.0, 0.0, False], [0.99, 0.0, True],
    [0.991, 0.96, True], [0.68, 0.08, True], [0.9952, 0.12, True], [0.8, 0.0, True],
    [0.12, 0.08, True], [0.35, 0.12, True], [1.0, 0.0, False], [0.95, 0.28, True],
    [0.991, 0.48, True], [0.68, 0.56, True], [0.96, 0.0, True], [1.0, 0.4, False],
    [1.0, 0.0, False], [0.95, 0.0, True], [0.65, 0.36, True], [0.85, 0.036697, False],
    [1.0, 0.16, False], [1.0, 0.0, False], [0.9375, 0.0, False], [0.93, 0.24, True],
    [0.65, 0.0, True], [0.56, 0.08, True], [0.65, 0.2, True], [0.967, 0.0, True],
    [0.72, 0.04, True], [0.36, 0.04, True], [0.859, 0.166667, True], [0.98, 0.12, True],
    [0.944, 0.0, True], [0.68, 0.0, True], [0.34, 0.0, True], [1.0, 0.0, False],
]
assert len(SCATTER_POINTS) == RES["C2"]["n"] == 56, "frozen scatter point count must be 56"
xs = [p[0] for p in SCATTER_POINTS]
ys = [p[1] for p in SCATTER_POINTS]
cols = [ARXIV if p[2] else GREYLIT for p in SCATTER_POINTS]
rho = RES["C2"]["pooled"]["rho"]; lo, hi = RES["C2"]["pooled"]["ci"]
fig, ax = plt.subplots(figsize=(7, 5), constrained_layout=True)
ax.plot([0, 1], [0, 1], ls="--", lw=1.2, color=GREY, zorder=1, label="claim = measured")
ax.scatter([x for x, c in zip(xs, cols) if c == ARXIV],
           [y for y, c in zip(ys, cols) if c == ARXIV],
           c=ARXIV, s=48, alpha=0.85, edgecolor="white", lw=0.6, zorder=3, label="arXiv")
ax.scatter([x for x, c in zip(xs, cols) if c == GREYLIT],
           [y for y, c in zip(ys, cols) if c == GREYLIT],
           c=GREYLIT, s=48, alpha=0.85, edgecolor="white", lw=0.6, zorder=3, label="grey literature")
ax.set_xlabel("claimed success rate (source)")
ax.set_ylabel("measured pooled breach rate (ROGUE)")
ax.set_xlim(-0.02, 1.05); ax.set_ylim(-0.02, 1.05)
# inset note parked in the empty upper-centre band, clear of the data cloud
n100 = RES["C2"].get("claims_100pct", {})
ax.annotate(f"{n100.get('n','?')} sources claim ≈100%;\nmean measured = {n100.get('mean_measured', 0):.0%}",
            (0.50, 0.86), ha="center", va="center", fontsize=9, color=INK,
            bbox=dict(boxstyle="round,pad=0.35", fc="#fbf3e7", ec=GREYLIT, lw=1.0))
# stat annotation in the empty lower-left wedge, below the diagonal
ax.annotate(f"Spearman ρ = {rho:+.2f}\n95% CI [{lo:+.2f}, {hi:+.2f}],  n = {RES['C2']['n']}",
            (0.04, 0.50), ha="left", va="center", fontsize=9.5, color=INK)
ax.legend(frameon=False, loc="upper left", handletextpad=0.5)
fig.savefig(FIGS / "repro_gap_F3_scatter.png"); plt.close(fig)

print("wrote:")
for p in ["repro_gap_F1_funnel.png", "repro_gap_F2_by_family.png", "repro_gap_F3_scatter.png"]:
    print(" ", FIGS / p)
