#!/usr/bin/env python
"""Generate the adaptive-orchestration paper figures from live data → docs/figs/.

READ-ONLY (queries only, no writes, no model calls, no cost). Implements the
data-driven panels from `docs/paper_figures.md` (F2–F8, F10); the pure schematics
(F1 loop, F9 lifecycle) are hand-drawn elsewhere. Run-ids are the documented runs.

    uv run python scripts/paper_figs.py            # all figures → docs/figs/*.png
    uv run python scripts/paper_figs.py --only F2 F5
"""
# ruff: noqa: E702  — compact, semicolon-joined matplotlib layout statements are
# idiomatic here and keep each figure's styling readable as a block.

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless, no display
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

OUT = _ROOT / "docs" / "figs"
GREEDY = "sweep_p2_1780457963"          # canonical/greedy, K=3 quota=0
STARV = "sweep_starv_q3_1780462736"     # starvation + quota=3, K=3
GROWTH = "sweep_K5_q5_1780477935"       # growth, K=5 quota=5

# colour-blind-safe pair (Wong): greedy = orange, growth = blue
C_GREEDY, C_GROWTH = "#E69F00", "#0072B2"
TIER_ORDER = ["image", "coj", "structured", "audio", "planner"]  # ladder position


def _conn():
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")
    return create_engine(url).connect()


def _short(model: str) -> str:
    return model.split("/")[-1]


def _save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{name}.png"
    fig.savefig(p, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {p.relative_to(_ROOT)}")


# F2 ─────────────────────────────────────────────────────────────────────────
def f2_reachability(c) -> None:
    q = text("""SELECT tier,
        sum((eligible AND executed)::int)::float / NULLIF(sum(eligible::int),0) reach,
        sum(eligible::int) n FROM ladder_rotation_membership
        WHERE run_id = :r GROUP BY tier""")
    def by_tier(rid):
        d = {row.tier: (float(row.reach or 0), int(row.n)) for row in c.execute(q, {"r": rid})}
        return d
    g, w = by_tier(GREEDY), by_tier(STARV)
    tiers = [t for t in TIER_ORDER if t in g or t in w]
    x = np.arange(len(tiers))
    gv = [g.get(t, (0, 0))[0] for t in tiers]
    wv = [w.get(t, (0, 0))[0] for t in tiers]
    fig, ax = plt.subplots(figsize=(7.2, 4))
    ax.bar(x - 0.2, gv, 0.4, label="greedy (quota=0)", color=C_GREEDY)
    ax.bar(x + 0.2, wv, 0.4, label="growth (starvation+quota=3)", color=C_GROWTH)
    ax.set_xticks(x); ax.set_xticklabels(tiers)
    ax.set_ylabel("reachability  (executed ÷ eligible)"); ax.set_ylim(0, 1.05)
    ax.set_title("F2  Reachability by ladder tier — greedy vs growth")
    ax.annotate("planner tier:\n0.07 → 0.98", xy=(len(tiers) - 1, 0.5),
                ha="center", fontsize=9, color="#444")
    ax.legend(); ax.spines[["top", "right"]].set_visible(False)
    fig.text(0.5, -0.04, f"N_eligible per tier (greedy/growth) from {GREEDY} / {STARV}",
             ha="center", fontsize=7, color="#777")
    _save(fig, "F2_reachability_by_tier")


# F3 ─────────────────────────────────────────────────────────────────────────
def f3_starvation(c) -> None:
    q = text("""SELECT COALESCE(skipped_reason,'executed') o, count(*) n
        FROM ladder_rotation_membership WHERE run_id = :r GROUP BY 1""")
    order = ["executed", "early_stop", "budget", "no_compatible_config", "not_reached"]
    colors = {"executed": C_GROWTH, "early_stop": C_GREEDY, "budget": "#999",
              "no_compatible_config": "#CC79A7", "not_reached": "#666"}
    runs = [("greedy", GREEDY), ("growth", STARV)]
    fig, ax = plt.subplots(figsize=(7.2, 2.8))
    for i, (lbl, rid) in enumerate(runs):
        d = {row.o: int(row.n) for row in c.execute(q, {"r": rid})}
        tot = sum(d.values()) or 1
        left = 0.0
        for o in order:
            v = d.get(o, 0) / tot
            if v <= 0:
                continue
            ax.barh(i, v, left=left, color=colors[o],
                    label=o if i == 0 else None)
            if v > 0.06:
                ax.text(left + v / 2, i, f"{v:.0%}", va="center", ha="center",
                        fontsize=8, color="white")
            left += v
    ax.set_yticks([0, 1]); ax.set_yticklabels(["greedy", "growth"])
    ax.set_xlim(0, 1); ax.set_xlabel("share of eligible strategy-appearances")
    ax.set_title("F3  Where eligible opportunities went")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.3), ncol=3, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    _save(fig, "F3_starvation_distribution")


# F4 ─────────────────────────────────────────────────────────────────────────
def f4_cost_per_grad(_c) -> None:
    # Derived from the run done: lines (escalation_spend ÷ graduations). Two points.
    K = [3, 5]; cpg = [25.10 / 3, 28.06 / 4]
    fig, ax = plt.subplots(figsize=(6.4, 4))
    ax.plot(K, cpg, "o-", color=C_GROWTH, lw=2, ms=8, label="measured")
    for k, v in zip(K, cpg):
        ax.annotate(f"${v:.2f}", (k, v), textcoords="offset points",
                    xytext=(0, 10), ha="center", fontsize=9)
    ax.axvspan(5, 9, color="#eee", alpha=0.7)
    ax.plot([5, 8], [cpg[1], cpg[1] * 1.4], "--", color="#bbb", lw=1.5)
    ax.annotate("saturation point\nunknown (probe at K=8)", (7.4, cpg[1] * 1.2),
                ha="center", fontsize=8, color="#777")
    ax.set_xlabel("K  (candidates evaluated per growth sweep)")
    ax.set_ylabel("cost per graduation  ($)")
    ax.set_title("F4  Cost-per-graduation falls as K rises (the economic inversion)")
    ax.set_xticks([3, 5, 8]); ax.set_xlim(2.5, 8.5); ax.set_ylim(0, 11)
    ax.legend(loc="lower left"); ax.spines[["top", "right"]].set_visible(False)
    fig.text(0.5, -0.03, "N=2 measured points; post-K=5 region hypothesized (dashed), not fitted.",
             ha="center", fontsize=7, color="#777")
    _save(fig, "F4_cost_per_graduation_vs_K")


# F5 ─────────────────────────────────────────────────────────────────────────
def f5_allocation_bias(c) -> None:
    win = {r.model: float(r.s) for r in c.execute(text("""
        SELECT config_id model, count(*)::float/sum(count(*)) OVER () s
        FROM ladder_attempts WHERE breached AND config_id IS NOT NULL AND run_id=:r
        GROUP BY config_id"""), {"r": GREEDY})}
    unbiased = {r.target_model: float(r.rate) for r in c.execute(text("""
        SELECT dc.target_model,
          sum((br.verdict IN ('partial_breach','full_breach'))::int)::float/count(*) rate
        FROM breach_results br JOIN deployment_configs dc
          ON dc.config_id=br.deployment_config_id GROUP BY 1"""))}
    models = sorted(set(win) | set(unbiased), key=lambda m: -win.get(m, 0))
    x = np.arange(len(models))
    wv = [win.get(m, 0) for m in models]; uv = [unbiased.get(m, 0) for m in models]
    fig, ax = plt.subplots(figsize=(7.6, 4.2))
    ax.bar(x - 0.2, wv, 0.4, label="ladder win-share (greedy)", color=C_GREEDY)
    ax.bar(x + 0.2, uv, 0.4, label="unbiased breach rate (full matrix)", color=C_GROWTH)
    ax.set_xticks(x); ax.set_xticklabels([_short(m) for m in models], rotation=30, ha="right")
    ax.set_ylabel("fraction"); ax.set_title(
        "F5  Allocation bias: ladder winner-share is near-inverted from true vulnerability")
    ax.legend(); ax.spines[["top", "right"]].set_visible(False)
    fig.text(0.5, -0.12, "Different measures/denominators (winner-of-ladder vs trial-level breach, "
             "~1,800 balanced trials/model); the point is the RANK inversion.",
             ha="center", fontsize=7, color="#777")
    _save(fig, "F5_allocation_bias")


# F6 ─────────────────────────────────────────────────────────────────────────
def f6_quota_sim(_c) -> None:
    # From `simulate_quota.py --run-id GREEDY` (deterministic replay of logged rotations).
    quota = [0, 1, 2, 3]; reach = [0.00, 0.33, 0.67, 1.00]; cost = [2.80, 17.13, 17.79, 18.45]
    fig, ax = plt.subplots(figsize=(6.6, 4))
    ax.plot(quota, reach, "o-", color=C_GROWTH, lw=2, label="candidate reachability")
    ax.set_xlabel("candidate quota"); ax.set_ylabel("candidate reachability", color=C_GROWTH)
    ax.set_ylim(0, 1.05); ax.set_xticks(quota)
    ax2 = ax.twinx()
    ax2.plot(quota, cost, "s--", color=C_GREEDY, lw=2, label="est. escalation cost")
    ax2.set_ylabel("est. escalation cost ($)", color=C_GREEDY); ax2.set_ylim(0, 22)
    ax.annotate("binary cost jump\n(suppress early-stop)", (0.5, 0.18),
                fontsize=8, color="#777")
    ax.set_title("F6  Quota simulation (zero-cost replay): reachability & cost vs quota")
    ax.spines["top"].set_visible(False); ax2.spines["top"].set_visible(False)
    fig.text(0.5, -0.03, "Simulation (deterministic replay); cannot predict whether a reached "
             "candidate BREACHES — that needs the paid run.", ha="center", fontsize=7, color="#777")
    _save(fig, "F6_quota_simulation")


# F7 ─────────────────────────────────────────────────────────────────────────
def f7_heatmap(c) -> None:
    rows = c.execute(text("""
        SELECT dc.target_model m, ap.family f,
          sum((br.verdict IN ('partial_breach','full_breach'))::int)::float/count(*) rate,
          count(*) n
        FROM breach_results br
        JOIN deployment_configs dc ON dc.config_id=br.deployment_config_id
        JOIN attack_primitives ap ON ap.primitive_id=br.primitive_id
        GROUP BY 1,2""")).all()
    models = sorted({r.m for r in rows}); fams = sorted({str(r.f) for r in rows})
    M = np.full((len(models), len(fams)), np.nan)
    for r in rows:
        if int(r.n) >= 20:  # mask sparse cells (honesty)
            M[models.index(r.m), fams.index(str(r.f))] = float(r.rate)
    fig, ax = plt.subplots(figsize=(max(8, len(fams) * 0.7), 4.5))
    im = ax.imshow(M, aspect="auto", cmap="magma", vmin=0, vmax=1)
    ax.set_xticks(range(len(fams))); ax.set_xticklabels([f[:16] for f in fams], rotation=40, ha="right", fontsize=7)
    ax.set_yticks(range(len(models))); ax.set_yticklabels([_short(m) for m in models], fontsize=8)
    ax.set_title("F7  Per-model × family breach rate (unbiased matrix)")
    fig.colorbar(im, ax=ax, label="breach rate", shrink=0.8)
    fig.text(0.5, -0.06, "Cells with N<20 trials greyed (masked). Overall spread "
             "Opus 1.4% → Mistral 48.6%.", ha="center", fontsize=7, color="#777")
    _save(fig, "F7_contextual_heatmap")


# F8 ─────────────────────────────────────────────────────────────────────────
def f8_growth(_c) -> None:
    # Status snapshots at each sweep checkpoint (from the done: lines / lab notes).
    labels = ["after greedy\n(quota=0)", "after causal test\n(quota=3)", "after growth\n(K=5)"]
    active = [7, 10, 14]; candidate = [15, 12, 8]; grads = [0, 3, 4]
    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(x, active, "o-", color=C_GROWTH, lw=2, label="active repertoire")
    ax.plot(x, candidate, "s--", color=C_GREEDY, lw=2, label="candidate pool")
    for i, g in enumerate(grads):
        ax.annotate(f"+{g}", (x[i], active[i]), textcoords="offset points",
                    xytext=(0, 10), ha="center", fontsize=9, color=C_GROWTH)
    ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("technique count"); ax.set_title("F8  Repertoire growth across sweeps")
    ax.legend(); ax.spines[["top", "right"]].set_visible(False)
    _save(fig, "F8_repertoire_growth")


# F10 ────────────────────────────────────────────────────────────────────────
def f10_rank(c) -> None:
    q = text("""SELECT rank FROM ladder_rotation_membership
        WHERE run_id=:r AND executed AND config_id IS NOT NULL""")
    g = [int(r.rank) for r in c.execute(q, {"r": GREEDY})]
    w = [int(r.rank) for r in c.execute(q, {"r": STARV})]
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


FIGS = {"F2": f2_reachability, "F3": f3_starvation, "F4": f4_cost_per_grad,
        "F5": f5_allocation_bias, "F6": f6_quota_sim, "F7": f7_heatmap,
        "F8": f8_growth, "F10": f10_rank}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", nargs="*", help="subset, e.g. --only F2 F5")
    args = p.parse_args()
    chosen = args.only or list(FIGS)
    c = _conn()
    print(f"generating {len(chosen)} figure(s) → {OUT.relative_to(_ROOT)}/")
    try:
        for k in chosen:
            fn = FIGS.get(k.upper())
            if fn is None:
                print(f"  unknown figure {k}; choices: {list(FIGS)}"); continue
            try:
                fn(c)
            except Exception as exc:  # one figure failing shouldn't kill the rest
                print(f"  {k} FAILED: {exc}")
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
