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

GREEN, INK, MUTED, RED = "#1f9d55", "#14161b", "#8a9098", "#c0392b"
plt.rcParams.update({"font.size": 10, "axes.edgecolor": "#d8ddd9", "figure.dpi": 150})


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
    fig, ax = plt.subplots(figsize=(8.2, 4.3))
    x = range(len(cls))
    w = 0.27
    ax.bar([i - w for i in x], [c["agreement"] for c in cls], w, label="Agreement", color=GREEN)
    ax.bar(list(x), [c["recall"] for c in cls], w, label="Recall", color=INK)
    ax.bar([i + w for i in x], [(c["fp_mode"] or 0) for c in cls], w, label="FP-mode (lower=better)", color=RED)
    ax.set_xticks(list(x))
    ax.set_xticklabels([c["label"] for c in cls])
    ax.set_ylim(0, 108)
    ax.set_ylabel("%")
    ax.set_title("One consummation-gate template, calibrated across four breach classes", fontweight="bold")
    ax.legend(frameon=False, fontsize=8, loc="lower center", ncol=3)
    ax.spines[["top", "right"]].set_visible(False)
    for i, c in enumerate(cls):
        ax.text(i - w, c["agreement"] + 1, f"{c['agreement']:.1f}", ha="center", fontsize=7)
    fig.tight_layout()
    fig.savefig(_OUT / "judge_F1_generalization.png")
    plt.close(fig)

    # ---- F2: unauthorized-action FP-mode descent (v1 → v2 → v3) --------------
    fig, ax = plt.subplots(figsize=(6.2, 4.0))
    stages = ["v1\n(REFINE)", "v2\n(rubric, SHIP)", "v3\n(tool-trace)"]
    fp = [UNAUTH_V1["fp_mode"], UNAUTH_V2["fp_mode"], _pct(unauth["fp_mode_rate"])]
    agr = [UNAUTH_V1["agreement"], UNAUTH_V2["agreement"], _pct(unauth["agreement_ci"][0])]
    ax.plot(stages, fp, "-o", color=RED, label="FP-mode (lower=better)")
    ax.plot(stages, agr, "-o", color=GREEN, label="Agreement")
    for i, v in enumerate(fp):
        ax.text(i, v + 1.6, f"{v:.2f}%", ha="center", color=RED, fontsize=8)
    for i, v in enumerate(agr):
        ax.text(i, v - 4, f"{v:.2f}%", ha="center", color=GREEN, fontsize=8)
    ax.axhline(15, ls="--", lw=0.8, color=MUTED)
    ax.text(2.02, 15, "FP-mode ship ceiling", va="center", fontsize=7, color=MUTED)
    ax.set_ylim(0, 105)
    ax.set_ylabel("%")
    ax.set_title("Diagnose → rubric refinement → tool-trace\n(unauthorized-action: FP-mode 9.38 → 6.25 → 3.12%)", fontweight="bold")
    ax.legend(frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(_OUT / "judge_F2_refine_to_ship.png")
    plt.close(fig)

    # ---- F3: the tool-trace resolution (text-only proxy → tool-trace) --------
    fig, ax = plt.subplots(figsize=(6.6, 4.0))
    bars = [
        ("Info-disclosure\n(content)", _pct(infodisc["fp_mode_rate"]), GREEN),
        ("Unauth-action\n(text-only, v2)", UNAUTH_V2["fp_mode"], RED),
        ("Unauth-action\n(tool-trace, v3)", _pct(unauth["fp_mode_rate"]), GREEN),
    ]
    x = range(len(bars))
    ax.bar(list(x), [b[1] for b in bars], 0.55, color=[b[2] for b in bars])
    for i, b in enumerate(bars):
        ax.text(i, b[1] + 0.2, f"{b[1]:.2f}%", ha="center", fontsize=8)
    ax.set_xticks(list(x))
    ax.set_xticklabels([b[0] for b in bars])
    ax.set_ylabel("FP-mode %")
    ax.set_ylim(0, 8)
    ax.set_title("Action consummation was a text-only-proxy artifact\n(the tool-trace makes 'executed' a fact: 6.25% → 3.12%)", fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(_OUT / "judge_F3_type_dependent.png")
    plt.close(fig)

    print(f"wrote 3 figures → {_OUT}/judge_F{{1,2,3}}_*.png")


if __name__ == "__main__":
    main()
