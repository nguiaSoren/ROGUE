"""Reproducible figures for the judge-calibration paper (docs/research/judge_calibration_paper.md).

Reads the measured calibration reports from `data/calibration/*.json` (+ a few
frozen historical constants that are no longer in the live JSONs: the harm/v3
JBB result and the unauthorized-action *v1* pre-refinement result) and writes
three clean PNGs to `docs/research/figs/`:

    judge_F1_generalization.png   — one gate template across breach classes (agreement / recall / FP-mode)
    judge_F2_refine_to_ship.png   — the REFINE→SHIP loop (unauthorized-action v1 vs v2)
    judge_F3_type_dependent.png   — type-dependent difficulty (content vs action: FP-mode + independent κ)

    uv run python scripts/calibration/judge_figs.py

Offline, no network, no paid call. matplotlib only (already a project dep via
scripts/paper_figs.py). Re-run after any new calibration sweep to refresh.
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
    infodisc = _load("information_disclosure")
    unauth = _load("unauthorized_action")  # this is the v2 (current) result

    # Frozen historical constants (recorded in the paper; not in the live JSONs):
    HARM = {"label": "Harm\n(content)", "agreement": 89.3, "recall": 95.5, "fp_mode": None}
    UNAUTH_V1 = {"agreement": 96.67, "fp_mode": 9.38, "gate": "REFINE"}  # pre-refinement

    # ---- F1: one gate template across breach classes -------------------------
    cls = [
        HARM,
        {"label": "Info-disclosure\n(content)", "agreement": _pct(infodisc["agreement_ci"][0]),
         "recall": _pct(infodisc["recall_ci"][0]), "fp_mode": _pct(infodisc["fp_mode_rate"])},
        {"label": "Unauth-action\n(action, v2)", "agreement": _pct(unauth["agreement_ci"][0]),
         "recall": _pct(unauth["recall_ci"][0]), "fp_mode": _pct(unauth["fp_mode_rate"])},
    ]
    fig, ax = plt.subplots(figsize=(7.4, 4.2))
    x = range(len(cls))
    w = 0.27
    ax.bar([i - w for i in x], [c["agreement"] for c in cls], w, label="Agreement", color=GREEN)
    ax.bar([i for i in x], [c["recall"] for c in cls], w, label="Recall", color=INK)
    ax.bar([i + w for i in x], [(c["fp_mode"] or 0) for c in cls], w, label="FP-mode (lower=better)", color=RED)
    ax.set_xticks(list(x))
    ax.set_xticklabels([c["label"] for c in cls])
    ax.set_ylim(0, 105)
    ax.set_ylabel("%")
    ax.set_title("One consummation-gate template, calibrated across breach classes", fontweight="bold")
    ax.legend(frameon=False, fontsize=8, loc="lower center", ncol=3)
    ax.spines[["top", "right"]].set_visible(False)
    for i, c in enumerate(cls):
        ax.text(i - w, c["agreement"] + 1, f"{c['agreement']:.1f}", ha="center", fontsize=7)
    fig.tight_layout()
    fig.savefig(_OUT / "judge_F1_generalization.png")
    plt.close(fig)

    # ---- F2: the REFINE -> SHIP loop (unauthorized-action) -------------------
    fig, ax = plt.subplots(figsize=(6.0, 4.0))
    stages = ["v1\n(REFINE)", "v2\n(SHIP)"]
    fp = [UNAUTH_V1["fp_mode"], _pct(unauth["fp_mode_rate"])]
    agr = [UNAUTH_V1["agreement"], _pct(unauth["agreement_ci"][0])]
    ax.plot(stages, fp, "-o", color=RED, label="FP-mode (lower=better)")
    ax.plot(stages, agr, "-o", color=GREEN, label="Agreement")
    for i, v in enumerate(fp):
        ax.text(i, v + 1.5, f"{v:.2f}%", ha="center", color=RED, fontsize=8)
    for i, v in enumerate(agr):
        ax.text(i, v - 4, f"{v:.2f}%", ha="center", color=GREEN, fontsize=8)
    ax.axhline(15, ls="--", lw=0.8, color=MUTED)
    ax.text(1.02, 15, "FP-mode ship ceiling", va="center", fontsize=7, color=MUTED)
    ax.set_ylim(0, 105)
    ax.set_ylabel("%")
    ax.set_title("Diagnose → targeted gate → re-measure → ship\n(unauthorized-action)", fontweight="bold")
    ax.legend(frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(_OUT / "judge_F2_refine_to_ship.png")
    plt.close(fig)

    # ---- F3: type-dependent difficulty (content vs action) -------------------
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    rows = [
        ("Info-disclosure\n(content)", _pct(infodisc["fp_mode_rate"]), 0.786),  # boundary κ
        ("Unauth-action\n(action, v2)", _pct(unauth["fp_mode_rate"]), 0.746),
    ]
    x = range(len(rows))
    w = 0.32
    ax.bar([i - w / 2 for i in x], [r[1] for r in rows], w, label="FP-mode %", color=RED)
    ax2 = ax.twinx()
    ax2.bar([i + w / 2 for i in x], [r[2] for r in rows], w, label="Independent κ (boundary)", color=GREEN)
    ax2.axhline(0.80, ls="--", lw=0.8, color=MUTED)
    ax2.text(1.5, 0.80, "κ floor", va="center", fontsize=7, color=MUTED)
    ax.set_xticks(list(x))
    ax.set_xticklabels([r[0] for r in rows])
    ax.set_ylabel("FP-mode %", color=RED)
    ax2.set_ylabel("Cohen's κ", color=GREEN)
    ax2.set_ylim(0, 1.0)
    ax.set_ylim(0, 12)
    ax.set_title("Action consummation is harder than content\n(for the judge AND an independent human)", fontweight="bold")
    ax.spines[["top"]].set_visible(False)
    ax2.spines[["top"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(_OUT / "judge_F3_type_dependent.png")
    plt.close(fig)

    print(f"wrote 3 figures → {_OUT}/judge_F{{1,2,3}}_*.png")


if __name__ == "__main__":
    main()
