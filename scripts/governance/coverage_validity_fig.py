"""Figure for the coverage-validity study (build-04 §5). Reads data/governance/coverage_validity_live.json,
writes docs/research/figs/coverage_validity.png. Offline, matplotlib only.

    uv run python scripts/governance/coverage_validity_fig.py
"""

from __future__ import annotations

import json
import statistics as st
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

GREEN, INK, MUTED, RED = "#1f9d55", "#14161b", "#8a9098", "#c0392b"
plt.rcParams.update({"font.size": 10, "axes.edgecolor": "#d8ddd9", "figure.dpi": 150})

d = json.loads(Path("data/governance/coverage_validity_live.json").read_text())
cells, a = d["cells"], d["analysis"]
OUT = Path("docs/research/figs")
OUT.mkdir(parents=True, exist_ok=True)

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.5, 4.3))

# (a) mean breach-rate by variant — the clean monotonic story
variants = ["weak", "medium", "strong"]
covs = [st.mean(c["coverage"] for c in cells if c["variant"] == v) for v in variants]
rates = [st.mean(c["breach_rate"] for c in cells if c["variant"] == v) * 100 for v in variants]
breached = [sum(1 for c in cells if c["variant"] == v and c["breach_rate"] > 0) for v in variants]
bars = ax1.bar(variants, rates, color=[RED, "#d8a93f", GREEN])
for i, (b, nb) in enumerate(zip(bars, breached)):
    ax1.text(i, b.get_height() + 0.05, f"{nb}/32 cells\nbreached", ha="center", fontsize=8)
ax1.set_ylabel("mean breach-rate (%)")
ax1.set_title("Higher-coverage packs find more breaches\n(weak packs: 0 breaches — a false 'holds')", fontweight="bold")
ax1.set_xticks(range(3))
ax1.set_xticklabels([f"{v}\n(cov {c:.2f})" for v, c in zip(variants, covs)])
ax1.spines[["top", "right"]].set_visible(False)
ax1.set_ylim(0, max(rates) * 1.35 + 0.2)

# (b) coverage vs breach-rate scatter, by target
colors = {"acme-llama3": INK, "acme-mistralsm": GREEN}
for tgt, col in colors.items():
    pts = [(c["coverage"], c["breach_rate"] * 100) for c in cells if c["target"] == tgt]
    xs = [p[0] + (0.0) for p in pts]
    ys = [p[1] for p in pts]
    ax2.scatter(xs, ys, s=28, color=col, alpha=0.6, edgecolors="white", linewidths=0.5,
                label=tgt.replace("acme-", ""))
ax2.set_xlabel("coverage score")
ax2.set_ylabel("breach-rate (%)")
rho = a["spearman_rho"]
lo, hi = a["spearman_ci95"]
ax2.set_title(f"Coverage vs breach-rate\nSpearman ρ = {rho:.2f}  (95% CI [{lo:.2f}, {hi:.2f}], excludes 0)",
              fontweight="bold")
ax2.legend(frameon=False, fontsize=8, title="target")
ax2.spines[["top", "right"]].set_visible(False)

fig.tight_layout()
fig.savefig(OUT / "coverage_validity.png")
print(f"wrote {OUT}/coverage_validity.png")
