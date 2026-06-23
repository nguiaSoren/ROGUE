#!/usr/bin/env python
"""Generate the adaptive-orchestration paper figures from the FROZEN data → docs/research/figs/.

Plots only — reads `docs/research/figs/data/` (CSVs + metrics.json) written by
`scripts/export_paper_data.py`. No DB, no run-ids, no cost: once the data is
exported, figures regenerate offline and deterministically. This separation
(export = live→frozen ; this = frozen→png) is what makes the figures reproducible
rather than merely regenerable-by-the-author.

    uv run python scripts/export_paper_data.py      # 1. freeze live data (DB)
    uv run python scripts/paper_figs.py             # 2. plot (offline)
    uv run python scripts/paper_figs.py --only F2 F5
"""
# ruff: noqa: E701, E702  — compact one-line guards + semicolon-joined matplotlib
# layout statements are idiomatic here and keep each figure's styling readable as a block.

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

# Paper-matching serif (STIX ships with matplotlib; mirrors the LaTeX Computer-Modern look).
plt.rcParams.update({
    "legend.labelspacing": 1.0,  # spread legend entries (avoid cramped stacking)
    "font.family": "serif",
    "font.serif": ["STIXGeneral", "DejaVu Serif"],
    "mathtext.fontset": "stix",
    "axes.facecolor": "white",
    "figure.facecolor": "white",
})

_ROOT = Path(__file__).resolve().parent.parent
DATA = _ROOT / "docs" / "research" / "figs" / "data"
OUT = _ROOT / "docs" / "research" / "figs"

# Okabe–Ito colour-blind-safe palette. blue = "good"/growth ; orange = baseline/greedy.
C_GROWTH = "#0072B2"   # blue
C_GREEDY = "#E69F00"   # orange
C_GREEN = "#009E73"
C_VERMILLION = "#D55E00"
C_SKY = "#56B4E9"
C_GREY = "#999999"
TIER_ORDER = ["image", "coj", "structured", "audio", "planner"]
GREEDY_RUN = "sweep_p2_1780457963"
STARV_RUN = "sweep_starv_q3_1780462736"


def _clean(ax) -> None:
    """Shared design spec: hide top/right spines, light horizontal gridlines behind data."""
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_axisbelow(True)
    ax.grid(axis="y", alpha=0.25, lw=0.6, color=C_GREY, zorder=0)


def _load_csv(name: str) -> list[dict]:
    p = DATA / f"{name}.csv"
    if not p.exists():
        raise SystemExit(f"missing {p.relative_to(_ROOT)} — run scripts/export_paper_data.py first")
    with p.open() as f:
        return list(csv.DictReader(f))


def _metrics() -> dict:
    p = DATA / "metrics.json"
    if not p.exists():
        raise SystemExit(f"missing {p.relative_to(_ROOT)} — run scripts/export_paper_data.py first")
    return json.loads(p.read_text())


def _short(m: str) -> str:
    return m.split("/")[-1]


# Vendor-class labels for the PUBLISHED allocation figure (F5). The named mapping
# stays in F5_allocation.csv (released artifact); the paper figure shows classes
# only, so a security-minded ethics reviewer sees no named commercial product with
# a breach rate. The rank-inversion finding is brand-independent.
CLASS_LABELS = {
    "openai/gpt-5.4-nano": "GPT-class",
    "anthropic/claude-haiku-4-5": "Claude-class (S)",
    "anthropic/claude-opus-4-8": "Claude-class (frontier)",
    "google/gemini-3.1-flash-lite": "Gemini-class",
    "meta-llama/llama-3.1-8b-instruct": "Llama-class 8B",
    "mistralai/mistral-small-2603": "Mistral-class (open)",
}


def _klass(m: str) -> str:
    return CLASS_LABELS.get(m, _short(m))


def _save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{name}.png"
    fig.savefig(p, dpi=200, bbox_inches="tight"); plt.close(fig)
    print(f"  wrote {p.relative_to(_ROOT)}")


# F2 ─────────────────────────────────────────────────────────────────────────
def f2_reachability() -> None:
    rows = _load_csv("F2_reachability")
    by = {GREEDY_RUN: {}, STARV_RUN: {}}
    for r in rows:
        by.setdefault(r["run_id"], {})[r["tier"]] = float(r["reachability"])
    tiers = [t for t in TIER_ORDER if t in by[GREEDY_RUN] or t in by[STARV_RUN]]
    labels = {"coj": "chain-of-\njailbreak"}
    x = np.arange(len(tiers))
    gv = [by[GREEDY_RUN].get(t, 0) for t in tiers]
    wv = [by[STARV_RUN].get(t, 0) for t in tiers]
    fig, ax = plt.subplots(figsize=(7.2, 4.2), constrained_layout=True)
    bg = ax.bar(x - 0.2, gv, 0.4, label="greedy (quota=0)", color=C_GREEDY, zorder=3)
    bw = ax.bar(x + 0.2, wv, 0.4, label="growth (starvation + quota=3)", color=C_GROWTH, zorder=3)
    # value labels offset above each bar, clear of the bar top
    for bars, vals in ((bg, gv), (bw, wv)):
        for rect, v in zip(bars, vals):
            ax.text(rect.get_x() + rect.get_width() / 2, v + 0.02, f"{v:.2f}",
                    ha="center", va="bottom", fontsize=8, color="#333")
    ax.set_xticks(x); ax.set_xticklabels([labels.get(t, t) for t in tiers])
    ax.set_ylabel("reachability  (executed ÷ eligible)"); ax.set_ylim(0, 1.12)
    # (the planner 0.07->0.98 jump is the rightmost bar pair + the caption; no in-plot note needed)
    # growth bars all reach ~1.0, so an in-axes legend lands on the bars — park it above the axes
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, frameon=False)
    _clean(ax)
    _save(fig, "F2_reachability_by_tier")


# F3 ─────────────────────────────────────────────────────────────────────────
def f3_starvation() -> None:
    rows = _load_csv("F3_starvation")
    d = defaultdict(dict)
    for r in rows:
        d[r["run_id"]][r["outcome"]] = int(r["n"])
    order = ["executed", "early_stop", "budget", "no_compatible_config", "not_reached"]
    col = {"executed": C_GROWTH, "early_stop": C_GREEDY, "budget": "#999",
           "no_compatible_config": "#CC79A7", "not_reached": "#666"}
    runs = [("greedy", GREEDY_RUN), ("growth", STARV_RUN)]
    fig, ax = plt.subplots(figsize=(7.2, 2.8))
    for i, (lbl, rid) in enumerate(runs):
        tot = sum(d[rid].values()) or 1
        left = 0.0
        for o in order:
            v = d[rid].get(o, 0) / tot
            if v <= 0: continue
            ax.barh(i, v, left=left, color=col[o], label=o if i == 0 else None)
            if v > 0.06:
                ax.text(left + v / 2, i, f"{v:.0%}", va="center", ha="center", fontsize=8, color="white")
            left += v
    ax.set_yticks([0, 1]); ax.set_yticklabels(["greedy", "growth"])
    ax.set_xlim(0, 1); ax.set_xlabel("share of eligible strategy-appearances")
    ax.set_title("F3  Where eligible opportunities went")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.3), ncol=3, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    _save(fig, "F3_starvation_distribution")


# F4 ─────────────────────────────────────────────────────────────────────────
# f4_cost_per_grad was RETIRED 2026-06-22. The cost-per-graduation figure (fig-cost-per-grad.png)
# is now generated HONESTLY by scripts/research/p1_cost_fig.py — discrete points on a NON-common
# cost basis (K=3,5 spend-capped circles; K=20 uncapped diamond) joined only by a dashed directional
# guide, NOT a fitted "o-" curve, matching the paper's structural claim-reduction. That script reads
# the frozen data/research/scheduler_results.json directly (no metrics.json / DB) and writes straight
# to the submission path, so it stays reproducible from the released artifacts.


# F5 ─────────────────────────────────────────────────────────────────────────
def f5_allocation_bias() -> None:
    rows = _load_csv("F5_allocation")
    rows.sort(key=lambda r: -float(r["ladder_win_share"]))
    models = [r["model"] for r in rows]
    x = np.arange(len(models))
    wv = [float(r["ladder_win_share"]) for r in rows]
    uv = [float(r["unbiased_breach_rate"]) for r in rows]
    fig, ax = plt.subplots(figsize=(7.6, 4.4), constrained_layout=True)
    ax.bar(x - 0.2, wv, 0.4, label="ladder win-share (greedy)", color=C_GREEDY, zorder=3)
    ax.bar(x + 0.2, uv, 0.4, label="unbiased breach rate (full matrix)", color=C_GROWTH, zorder=3)
    ax.set_xticks(x); ax.set_xticklabels([_klass(m) for m in models], rotation=25, ha="right")
    ax.set_ylabel("fraction"); ax.set_ylim(0, max(max(wv), max(uv)) * 1.18)
    # legend parked above the axes — never over the tall mistral / gpt-nano bars
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, frameon=False)
    _clean(ax)
    fig.text(0.5, -0.10, "Different measures/denominators (winner-of-ladder vs trial-level breach, "
             "11,075 trials across 6 models, judge_v3); the point is the RANK inversion.", ha="center", fontsize=7, color="#777")
    _save(fig, "F5_allocation_bias")


# F6 ─────────────────────────────────────────────────────────────────────────
def f6_quota_sim() -> None:
    sim = _metrics().get("quota_sim")
    if not sim or not sim.get("quota"):
        print("  F6 skipped (no quota_sim in metrics)"); return
    quota, reach, cost = sim["quota"], sim["candidate_reach"], sim["est_cost"]
    fig, ax = plt.subplots(figsize=(6.6, 4))
    ax.plot(quota, reach, "o-", color=C_GROWTH, lw=2, label="candidate reachability")
    ax.set_xlabel("candidate quota"); ax.set_ylabel("candidate reachability", color=C_GROWTH)
    ax.set_ylim(0, 1.05); ax.set_xticks(quota)
    ax2 = ax.twinx()
    ax2.plot(quota, cost, "s--", color=C_GREEDY, lw=2, label="est. escalation cost")
    ax2.set_ylabel("est. escalation cost ($)", color=C_GREEDY); ax2.set_ylim(0, max(cost) * 1.2)
    ax.annotate("binary cost jump\n(suppress early-stop)", (0.5, 0.18), fontsize=8, color="#777")
    ax.set_title("F6  Quota simulation (zero-cost replay): reachability & cost vs quota")
    ax.spines["top"].set_visible(False); ax2.spines["top"].set_visible(False)
    fig.text(0.5, -0.03, "Simulation (deterministic replay); cannot predict whether a reached candidate "
             "BREACHES; that needs the paid run.", ha="center", fontsize=7, color="#777")
    _save(fig, "F6_quota_simulation")


# F7 ─────────────────────────────────────────────────────────────────────────
def f7_heatmap() -> None:
    rows = _load_csv("F7_heatmap")
    models = sorted({r["model"] for r in rows}); fams = sorted({r["family"] for r in rows})
    M = np.full((len(models), len(fams)), np.nan)
    for r in rows:
        if int(r["n"]) >= 20:
            M[models.index(r["model"]), fams.index(r["family"])] = float(r["breach_rate"])
    fig, ax = plt.subplots(figsize=(max(8, len(fams) * 0.7), 4.5))
    im = ax.imshow(M, aspect="auto", cmap="magma", vmin=0, vmax=1)
    ax.set_xticks(range(len(fams))); ax.set_xticklabels([f[:16] for f in fams], rotation=40, ha="right", fontsize=7)
    ax.set_yticks(range(len(models))); ax.set_yticklabels([_short(m) for m in models], fontsize=8)
    ax.set_title("F7  Per-model × family breach rate (unbiased matrix)")
    fig.colorbar(im, ax=ax, label="breach rate", shrink=0.8)
    fig.text(0.5, -0.06, "Cells with N<20 trials greyed (masked). Spread Opus 1.4% → Mistral 48.6%.",
             ha="center", fontsize=7, color="#777")
    _save(fig, "F7_contextual_heatmap")


# F8 ─────────────────────────────────────────────────────────────────────────
def f8_growth() -> None:
    runs = _metrics()["runs"]
    seq = ["greedy", "starv_q3", "growth_k5"]
    seq = [s for s in seq if s in runs]
    labels = {"greedy": "after greedy\n(quota=0)", "starv_q3": "after causal test\n(quota=3)",
              "growth_k5": "after growth\n(K=5)"}
    active = [runs[s]["active_after"] for s in seq]
    cand = [runs[s]["candidate_after"] for s in seq]
    grads = [runs[s]["graduations"] for s in seq]
    x = np.arange(len(seq))
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(x, active, "o-", color=C_GROWTH, lw=2, label="active repertoire")
    ax.plot(x, cand, "s--", color=C_GREEDY, lw=2, label="candidate pool")
    for i, g in enumerate(grads):
        ax.annotate(f"+{g}", (x[i], active[i]), textcoords="offset points", xytext=(0, 10),
                    ha="center", fontsize=9, color=C_GROWTH)
    ax.set_xticks(x); ax.set_xticklabels([labels[s] for s in seq], fontsize=8)
    ax.set_ylabel("technique count"); ax.set_title("F8  Repertoire growth across sweeps")
    ax.legend(); ax.spines[["top", "right"]].set_visible(False)
    _save(fig, "F8_repertoire_growth")


# F10 ────────────────────────────────────────────────────────────────────────
def f10_rank() -> None:
    rows = _load_csv("F10_rank")
    g = [int(r["rank"]) for r in rows if r["run_id"] == GREEDY_RUN]
    w = [int(r["rank"]) for r in rows if r["run_id"] == STARV_RUN]
    if not g and not w:
        print("  F10 skipped (no winner rows)"); return
    fig, ax = plt.subplots(figsize=(6.6, 3.6))
    bins = range(0, max(g + w + [1]) + 2)
    ax.hist(g, bins=bins, alpha=0.6, color=C_GREEDY, label=f"greedy (median {int(np.median(g)) if g else 0})")
    ax.hist(w, bins=bins, alpha=0.6, color=C_GROWTH, label=f"growth (median {int(np.median(w)) if w else 0})")
    ax.set_xlabel("rank of winning strategy in the rotation"); ax.set_ylabel("ladders")
    ax.set_title("F10  Rank-of-winner: greedy front-loads (rank 0); quota suppresses early-stop")
    ax.legend(); ax.spines[["top", "right"]].set_visible(False)
    _save(fig, "F10_rank_of_winner")


# Schematics (no data) ───────────────────────────────────────────────────────
def _box(ax, cx, cy, w, h, txt, fc="#eef3fb", ec="#0072B2", fs=9, bold=False):
    ax.add_patch(FancyBboxPatch((cx - w / 2, cy - h / 2), w, h, zorder=3,
                 boxstyle="round,pad=0.006,rounding_size=0.02", fc=fc, ec=ec, lw=1.5))
    ax.text(cx, cy, txt, ha="center", va="center", fontsize=fs, zorder=5,
            fontweight="bold" if bold else "normal")
    return {"l": (cx - w / 2, cy), "r": (cx + w / 2, cy),
            "t": (cx, cy + h / 2), "b": (cx, cy - h / 2), "c": (cx, cy)}


def _arrow(ax, p1, p2, label=None, rad=0.0, color="#555", fs=8, lx=0.0, ly=0.035):
    ax.add_patch(FancyArrowPatch(p1, p2, connectionstyle=f"arc3,rad={rad}",
                 arrowstyle="-|>", mutation_scale=13, lw=1.3, color=color, zorder=2))
    if label:
        mx = (p1[0] + p2[0]) / 2 + lx + rad * (p2[1] - p1[1]) * 0.5
        my = (p1[1] + p2[1]) / 2 + ly - rad * (p2[0] - p1[0]) * 0.5
        ax.text(mx, my, label, ha="center", va="center", fontsize=fs, color=color, zorder=6)


def f1_pipeline() -> None:
    fig, (axp, axl) = plt.subplots(2, 1, figsize=(11, 6.6),
                                   gridspec_kw={"height_ratios": [1, 1.3]})
    for a in (axp, axl):
        a.set_xlim(0, 1); a.set_ylim(0, 1); a.axis("off")
    # (a) reproduction pipeline
    axp.set_title("F1a  reproduction pipeline", fontsize=11, loc="left")
    labels = ["open web", "harvest", "extract\ntechnique | payload",
              "lifecycle\ncandidate→active", "escalation\nladder", "judge", "threat\nbrief"]
    xs = np.linspace(0.075, 0.925, len(labels)); prev = None
    for x, lab in zip(xs, labels):
        b = _box(axp, x, 0.5, 0.118, 0.42, lab, fs=8.3)
        if prev is not None:
            _arrow(axp, prev["r"], b["l"])
        prev = b
    # (b) self-expansion loop (clockwise: harvest→scheduler→growth→graduate→canonical→refill)
    axl.set_title("F1b  The self-expansion loop", fontsize=11, loc="left")
    h = _box(axl, 0.13, 0.74, 0.18, 0.3, "harvest\n→ candidate pool", fc="#fff4e0", ec=C_GREEDY, fs=8.3)
    sch = _box(axl, 0.41, 0.74, 0.18, 0.3, "scheduler:\npool ≥ 5 ?", fs=8.3, bold=True)
    gr = _box(axl, 0.71, 0.74, 0.21, 0.3, "GROWTH sweep\n(K=quota, starvation)", fc="#e3f0fb", ec=C_GROWTH, fs=8.3)
    grad = _box(axl, 0.71, 0.24, 0.21, 0.3, "graduate → active\ncandidate pool drains", fc="#e3f0fb", ec=C_GROWTH, fs=8.3)
    can = _box(axl, 0.32, 0.24, 0.2, 0.3, "CANONICAL\n(cheap reproduction)", fc="#f2f2f2", ec="#888", fs=8.3)
    _arrow(axl, h["r"], sch["l"])
    _arrow(axl, sch["r"], gr["l"], label="yes", ly=0.05, color=C_GROWTH)
    _arrow(axl, gr["b"], grad["t"])
    _arrow(axl, grad["l"], can["r"], label="pool drains", ly=0.05)
    _arrow(axl, sch["b"], can["t"], label="no", rad=0.25, color="#999")
    _arrow(axl, can["l"], h["b"], label="harvest refills", rad=-0.35, color=C_GREEDY)
    axl.text(0.52, 0.5, "thermostat: graduations drain the pool →\nreverts to cheap mode until harvesting refills it",
             ha="center", va="center", fontsize=7.3, color="#888", style="italic")
    _save(fig, "F1_system_and_loop")


def f9_lifecycle() -> None:
    fig, ax = plt.subplots(figsize=(9, 5.2)); ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    ax.set_title("F9  Technique lifecycle state machine", fontsize=12, loc="left")
    cand = _box(ax, 0.18, 0.74, 0.22, 0.2, "candidate\n(harvested, unproven)", fc="#fff4e0", ec=C_GREEDY, fs=9)
    act = _box(ax, 0.74, 0.74, 0.2, 0.2, "active\n(in repertoire)", fc="#e3f0fb", ec=C_GROWTH, fs=9, bold=True)
    ret = _box(ax, 0.42, 0.24, 0.2, 0.2, "retired\n(soft, reversible)", fc="#f2f2f2", ec="#888", fs=9)
    arch = _box(ax, 0.80, 0.24, 0.16, 0.2, "archived", fc="#ededed", ec="#aaa", fs=9)
    _arrow(ax, cand["r"], act["l"], color=C_GROWTH,
           label="breach (graduate:\nANY breaching candidate,\nmode-adaptive)", ly=0.075)
    _arrow(ax, cand["b"], ret["l"], rad=-0.12, label="never wins", lx=-0.02, ly=-0.03)
    # soft-retire (active→retired) lands on retired's RIGHT edge; resurrect leaves its
    # TOP edge — so the two active↔retired arrows never overlap.
    _arrow(ax, act["b"], ret["r"], rad=0.12,
           label="soft-retire\n(Rule A: ≥5 valid trials,\n0 breaches, >7d)", lx=0.21, ly=0.0)
    _arrow(ax, ret["t"], act["b"], rad=-0.4, color=C_GROWTH,
           label="breach again\n(resurrect)", lx=-0.11, ly=0.02)
    _arrow(ax, ret["b"], arch["b"], rad=-0.3, label="TTL (Rule B)", ly=-0.05)
    _save(fig, "F9_lifecycle")


FIGS = {"F1": f1_pipeline, "F2": f2_reachability, "F3": f3_starvation,
        "F5": f5_allocation_bias, "F6": f6_quota_sim,  # F4 retired -> scripts/research/p1_cost_fig.py
        "F7": f7_heatmap, "F8": f8_growth, "F9": f9_lifecycle, "F10": f10_rank}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", nargs="*", help="subset, e.g. --only F2 F5")
    args = p.parse_args()
    # F1/F9 are schematics (no data); the data figures' loaders raise their own clear
    # error if docs/research/figs/data/ is missing — so no hard pre-check here.
    chosen = args.only or list(FIGS)
    print(f"plotting {len(chosen)} figure(s) from {DATA.relative_to(_ROOT)}/ → {OUT.relative_to(_ROOT)}/")
    for k in chosen:
        fn = FIGS.get(k.upper())
        if fn is None:
            print(f"  unknown figure {k}; choices: {list(FIGS)}"); continue
        try:
            fn()
        except SystemExit:
            raise
        except Exception as exc:
            print(f"  {k} FAILED: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
