"""Reproducible figures for the judge-calibration paper (docs/research/judge_calibration_paper.md).

Reads the measured calibration reports from `data/calibration/*.json` (+ a few
frozen historical constants no longer in the live JSONs: the harm/v3 JBB result
and the unauthorized-action v1/v2 pre-tool-trace results) and writes three clean
PNGs to `docs/research/figs/`:

    judge_F1_generalization.png   — one gate template across FOUR breach classes (agreement / recall / FP-mode)
    judge_F2_refine_to_ship.png   — the unauthorized-action FP-mode descent: v1 (REFINE) → v2 (SHIP) → v3 (tool-trace)
    judge_F3_type_dependent.png   — the tool-trace resolution: content vs action FP-mode, text-only proxy → tool-trace

    uv run python scripts/calibration/judge_figs.py

Offline, no network, no paid call. matplotlib only. Re-run after any new sweep.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
_CAL = _ROOT / "data" / "calibration"
_OUT = _ROOT / "docs" / "research" / "figs"

# Okabe–Ito colorblind-safe palette. Recurring series are fixed across all three figs:
#   agreement = green, recall = blue, false-positive-mode = vermillion.
GREEN = "#009E73"   # agreement
BLUE = "#0072B2"    # recall
RED = "#D55E00"     # false-positive mode (lower is better)
ORANGE = "#E69F00"  # extra
SKY = "#56B4E9"     # extra
GREY = "#999999"    # reference lines / muted annotation
INK = "#14161b"     # text

plt.rcParams.update({
    "font.size": 10,
    "font.family": "serif",
    "font.serif": ["STIXGeneral", "DejaVu Serif"],
    "mathtext.fontset": "stix",
    "figure.dpi": 150,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "axes.edgecolor": "#444444",
    "axes.linewidth": 0.8,
    "axes.axisbelow": True,
})


def _style(ax) -> None:
    """Shared clean style: hide top/right spines, light horizontal gridlines behind data."""
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(length=3, color="#444444")
    ax.yaxis.grid(True, color="#999999", alpha=0.25, lw=0.6, zorder=0)
    ax.xaxis.grid(False)
    ax.set_axisbelow(True)


def _load(name: str) -> dict:
    return json.loads((_CAL / f"{name}_report.json").read_text())


def _pct(x: float) -> float:
    return round(100 * x, 2)


def main() -> None:
    _OUT.mkdir(parents=True, exist_ok=True)
    infodisc = _load("information_disclosure")   # v2
    unauth = _load("unauthorized_action")        # v3 (tool-trace)
    fabricated = _load("fabricated_sensitive_value")

    # Frozen historical constants (recorded in the paper; not in the live JSONs):
    HARM = {"label": "Harm\n(content)", "agreement": 89.3, "recall": 95.5, "fp_mode": None}
    UNAUTH_V1 = {"agreement": 96.67, "fp_mode": 9.38}  # pre-refinement, REFINE
    UNAUTH_V2 = {"agreement": 97.78, "fp_mode": 6.25}  # rubric refinement, SHIP

    # ---- F1: one gate template across FOUR breach classes --------------------
    cls = [
        HARM,
        {"label": "Info-disclosure\n(content, v2)", "agreement": _pct(infodisc["agreement_ci"][0]),
         "recall": _pct(infodisc["recall_ci"][0]), "fp_mode": _pct(infodisc["fp_mode_rate"])},
        {"label": "Unauth-action\n(action, v3)", "agreement": _pct(unauth["agreement_ci"][0]),
         "recall": _pct(unauth["recall_ci"][0]), "fp_mode": _pct(unauth["fp_mode_rate"])},
        {"label": "Fabricated-value\n(fabrication)", "agreement": _pct(fabricated["agreement_ci"][0]),
         "recall": _pct(fabricated["recall_ci"][0]), "fp_mode": _pct(fabricated["fp_mode_rate"])},
    ]
    fig, ax = plt.subplots(figsize=(8.2, 4.6), constrained_layout=True)
    x = range(len(cls))
    w = 0.26
    ax.bar([i - w for i in x], [c["agreement"] for c in cls], w, label="Agreement", color=GREEN, zorder=3)
    ax.bar(list(x), [c["recall"] for c in cls], w, label="Recall", color=BLUE, zorder=3)
    ax.bar([i + w for i in x], [(c["fp_mode"] or 0) for c in cls], w,
           label="False-positive mode (lower is better)", color=RED, zorder=3)
    ax.set_xticks(list(x))
    ax.set_xticklabels([c["label"] for c in cls])
    ax.set_ylim(0, 112)
    ax.set_yticks(range(0, 101, 20))
    ax.set_ylabel("Percent")
    # value labels offset clearly above each bar; FP-mode labelled only where it exists
    for i, c in enumerate(cls):
        ax.text(i - w, c["agreement"] + 1.5, f"{c['agreement']:.1f}", ha="center", va="bottom", fontsize=7, color=GREEN)
        ax.text(i, c["recall"] + 1.5, f"{c['recall']:.1f}", ha="center", va="bottom", fontsize=7, color=BLUE)
        if c["fp_mode"]:
            ax.text(i + w, c["fp_mode"] + 1.5, f"{c['fp_mode']:.2f}", ha="center", va="bottom", fontsize=7, color=RED)
    _style(ax)
    # legend ABOVE the axes, never over the bars
    ax.legend(frameon=False, fontsize=8.5, loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=3)
    fig.savefig(_OUT / "judge_F1_generalization.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

    # ---- F2: unauthorized-action FP-mode descent (v1 → v2 → v3) --------------
    fig, ax = plt.subplots(figsize=(6.6, 4.4), constrained_layout=True)
    stages = ["v1\n(REFINE)", "v2\n(rubric, SHIP)", "v3\n(trace, SHIP)"]
    fp = [UNAUTH_V1["fp_mode"], UNAUTH_V2["fp_mode"], _pct(unauth["fp_mode_rate"])]
    agr = [UNAUTH_V1["agreement"], UNAUTH_V2["agreement"], _pct(unauth["agreement_ci"][0])]
    # The ship gate is FP-mode CI-upper <= 10% (calibrate_over_block.py), not a point
    # threshold, so a fixed horizontal line on these point estimates would misread
    # (v1's point is under 10% yet REFINEs because its CI-upper crosses it). The verdict
    # therefore lives on the x-axis labels, and the gate is stated precisely in the caption.
    ax.plot(stages, agr, "-o", color=GREEN, lw=1.8, ms=6, label="Agreement", zorder=3)
    ax.plot(stages, fp, "-o", color=RED, lw=1.8, ms=6, label="False-positive mode (lower is better)", zorder=3)
    for i, v in enumerate(agr):
        ax.text(i, v + 2.4, f"{v:.2f}%", ha="center", va="bottom", color=GREEN, fontsize=8)
    for i, v in enumerate(fp):
        ax.text(i, v + 2.2, f"{v:.2f}%", ha="center", va="bottom", color=RED, fontsize=8)
    ax.set_ylim(0, 108)
    ax.set_yticks(range(0, 101, 20))
    ax.set_ylabel("Percent")
    _style(ax)
    ax.legend(frameon=False, fontsize=8.5, loc="center right", bbox_to_anchor=(1.0, 0.5))
    fig.savefig(_OUT / "judge_F2_refine_to_ship.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

    # ---- F3: the tool-trace resolution (text-only proxy → tool-trace) --------
    fig, ax = plt.subplots(figsize=(6.8, 4.4), constrained_layout=True)
    bars = [
        ("Info-disclosure\n(content)", _pct(infodisc["fp_mode_rate"]), GREEN),
        ("Unauth-action\n(text-only, v2)", UNAUTH_V2["fp_mode"], RED),
        ("Unauth-action\n(tool-trace, v3)", _pct(unauth["fp_mode_rate"]), GREEN),
    ]
    x = range(len(bars))
    ax.bar(list(x), [b[1] for b in bars], 0.55, color=[b[2] for b in bars], zorder=3)
    for i, b in enumerate(bars):
        ax.text(i, b[1] + 0.12, f"{b[1]:.2f}%", ha="center", va="bottom", fontsize=8.5, color=INK)
    ax.set_xticks(list(x))
    ax.set_xticklabels([b[0] for b in bars])
    ax.set_ylabel("False-positive-mode rate (%)")
    ax.set_ylim(0, 8)
    ax.set_yticks(range(0, 9, 2))
    _style(ax)
    fig.savefig(_OUT / "judge_F3_type_dependent.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

    print(f"wrote 3 figures → {_OUT}/judge_F{{1,2,3}}_*.png")


if __name__ == "__main__":
    main()
