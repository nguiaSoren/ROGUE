#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Figure 1 (teaser) for the ROGUE allocation paper.
#
# HONESTY-FIRST DESIGN (the thesis is honest telemetry; the teaser must be the
# most honest figure in the paper):
#   * The 20-square grids depict EXACTLY ONE experiment -- the least-tried tail
#     sweep (N=20) -- because that is the only place a 20-candidate population is
#     literally true. Greedy reaches ~0 of them (all grey = never evaluated);
#     growth evaluates all 20, of which 8 graduate and 12 are evaluated-no-breach.
#     This teaches the evaluated-vs-never-evaluated LENS, which is the contribution.
#   * The MATCHED quota-0 -> quota-3 result (Table 1: 0->3 graduations,
#     reachability 0.07->0.98, starvation 85%->1%) lives in its own labeled strip,
#     never mixed into the tail grid, so no reader mistakes the 8 for a matched arm.
#   * Cost-per-graduation inversion ($8.37 -> $1.44) folded in as a small sliver.
# Vector PDF, full text width (figure*), palette matched to the body figures.

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib.lines import Line2D

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["DejaVu Serif"],
    "pdf.fonttype": 42, "ps.fonttype": 42,
})

ORANGE   = "#E09000"
BLUE     = "#0070B0"
GREY_OUT = "#9aa0a6"
GREY_FILL= "#e6e8ea"
INK      = "#1a1a1a"
MUTE     = "#666666"
PANEL    = "#f6f7f8"
BLUEBG   = "#eaf3f9"

FIG_W, FIG_H = 7.1, 3.15
fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
ax.set_xlim(0, 100); ax.set_ylim(0, 46); ax.axis("off")
ASPECT = FIG_H/FIG_W

def box(x, y, w, h, fc, ec, lw=1.0, rounding=2.2, alpha=1.0, ls="-"):
    ax.add_patch(FancyBboxPatch((x, y), w, h,
        boxstyle=f"round,pad=0,rounding_size={rounding}",
        linewidth=lw, edgecolor=ec, facecolor=fc, alpha=alpha,
        linestyle=ls, mutation_aspect=ASPECT))

def arrow(x1, y1, x2, y2, color=MUTE, lw=1.5, style="-|>", rad=0.0):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style,
        mutation_scale=12, lw=lw, color=color,
        connectionstyle=f"arc3,rad={rad}", shrinkA=2, shrinkB=2))

def grid20(x0, y_top, fills, cell=2.35, gap=0.8, cols=5):
    for i, kind in enumerate(fills):
        r, c = divmod(i, cols)
        gx = x0 + c*(cell+gap); gy = y_top - r*(cell+gap)
        if kind == "grad":
            box(gx, gy, cell, cell, BLUE, BLUE, lw=0.6, rounding=0.5)
        elif kind == "eval":
            box(gx, gy, cell, cell, "white", GREY_OUT, lw=0.9, rounding=0.5)
        else:
            box(gx, gy, cell, cell, GREY_FILL, "#d4d7da", lw=0.6, rounding=0.5)

# ============================ HEADER =================================
ax.text(3.0, 44.2, "Allocation, not technique quality, gates repertoire growth.",
        ha="left", va="center", fontsize=9.2, color=INK, fontweight="bold")
ax.text(3.0, 41.7,
        "A candidate is grey because it was never evaluated \u2014 not because it failed. "
        "Make it reachable and it graduates.",
        ha="left", va="center", fontsize=6.8, color=MUTE)

# ===================== THE TAIL GRIDS (N=20) ========================
# Sub-label that fixes the grids to ONE experiment.
ax.text(3.0, 37.8, "The least-tried 20 candidates (the tail greedy never reaches)",
        ha="left", va="center", fontsize=6.6, color=INK, style="italic")

# LEFT: greedy
gx0 = 3.0
ax.text(gx0, 34.4, "Greedy", ha="left", va="center", fontsize=8.4,
        color=ORANGE, fontweight="bold")
ax.text(gx0+10.5, 34.4, "cost-optimal, stops at first breach", ha="left",
        va="center", fontsize=6.0, color=MUTE, style="italic")
grid20(gx0, 31.0, ["none"]*20)
ax.text(gx0, 16.6, "reaches \u2248 0 of 20", ha="left", va="center",
        fontsize=6.8, color=ORANGE, fontweight="bold")
ax.text(gx0, 14.6, "candidate tier starved by early-stop", ha="left",
        va="center", fontsize=6.0, color=MUTE, style="italic")

# CENTER flip
cL, cR = gx0+16.0, 52.0
midx = (cL+cR)/2
box(midx-8.0, 27.0, 16.0, 4.6, "white", BLUE, lw=1.2, rounding=1.5)
ax.text(midx, 29.8, "candidate quota", ha="center", va="center", fontsize=6.7,
        color=BLUE, fontweight="bold")
ax.text(midx, 28.0, "suppresses early-stop", ha="center", va="center",
        fontsize=5.9, color=MUTE)
arrow(cL, 24.4, cR, 24.4, color=INK, lw=1.7)
ax.text(midx, 22.4, "forces every candidate to run", ha="center", va="center",
        fontsize=5.9, color=MUTE, style="italic")

# RIGHT: growth
rx0 = 54.0
ax.text(rx0, 34.4, "Growth", ha="left", va="center", fontsize=8.4,
        color=BLUE, fontweight="bold")
ax.text(rx0+11.0, 34.4, "starvation order + quota", ha="left", va="center",
        fontsize=6.0, color=MUTE, style="italic")
grid20(rx0, 31.0, (["grad"]*8) + (["eval"]*12))
ax.text(rx0, 16.6, "8 of 20 graduate (40%)", ha="left", va="center",
        fontsize=6.8, color=BLUE, fontweight="bold")
ax.text(rx0, 14.6, "the other 12 ran but did not breach", ha="left",
        va="center", fontsize=6.0, color=MUTE, style="italic")

# legend, far right
lx = rx0 + 22.5
box(lx, 30.5, 1.9, 1.9, BLUE, BLUE, lw=0.6, rounding=0.4)
ax.text(lx+2.6, 31.45, "graduated", ha="left", va="center", fontsize=5.6, color=MUTE)
box(lx, 27.0, 1.9, 1.9, "white", GREY_OUT, lw=0.9, rounding=0.4)
ax.text(lx+2.6, 27.95, "evaluated,", ha="left", va="center", fontsize=5.6, color=MUTE)
ax.text(lx+2.6, 26.4, "no breach", ha="left", va="center", fontsize=5.6, color=MUTE)
box(lx, 23.0, 1.9, 1.9, GREY_FILL, "#d4d7da", lw=0.6, rounding=0.4)
ax.text(lx+2.6, 23.95, "never", ha="left", va="center", fontsize=5.6, color=MUTE)
ax.text(lx+2.6, 22.4, "evaluated", ha="left", va="center", fontsize=5.6, color=MUTE)

# ============ THE MATCHED RESULT STRIP (Table 1) ====================
# Visually separated band so its numbers are never read off the tail grid.
box(1.5, 4.6, 97, 7.4, BLUEBG, "#cfe0ee", lw=0.9, rounding=1.4)
ax.text(3.2, 10.6, "The matched A/B (Table 1):", ha="left", va="center",
        fontsize=7.0, color=INK, fontweight="bold")
ax.text(27.5, 10.6,
        "same 40 primitives, same inputs \u2014 only the scheduler policy changes.",
        ha="left", va="center", fontsize=6.4, color=MUTE)

# three matched deltas, evenly spaced
def delta(x, label, a, b):
    ax.text(x, 7.7, label, ha="center", va="center", fontsize=6.2, color=MUTE)
    ax.text(x, 5.7, a, ha="right", va="center", fontsize=8.0,
            color=ORANGE, fontweight="bold")
    ax.text(x, 5.7, "  \u2192  ", ha="center", va="center", fontsize=7.0, color=INK)
    ax.text(x, 5.7, b, ha="left", va="center", fontsize=8.0,
            color=BLUE, fontweight="bold")

# place three groups; offset a/b around center via small dx
def delta_group(xc, label, a, b):
    ax.text(xc, 8.0, label, ha="center", va="center", fontsize=6.2, color=MUTE)
    ax.text(xc-3.4, 5.9, a, ha="center", va="center", fontsize=8.4,
            color=ORANGE, fontweight="bold")
    ax.text(xc, 5.9, "\u2192", ha="center", va="center", fontsize=8.0, color=INK)
    ax.text(xc+3.4, 5.9, b, ha="center", va="center", fontsize=8.4,
            color=BLUE, fontweight="bold")

delta_group(24.0, "graduations",            "0",    "3")
delta_group(50.0, "planner reachability",   "0.07", "0.98")
delta_group(76.0, "starvation",             "85%",  "1%")

# ===================== BOTTOM SLIVER (K) ============================
ax.text(3.0, 1.7, "And evaluating more is cheaper, not costlier:",
        ha="left", va="center", fontsize=6.4, color=INK)
ax.text(38.5, 1.7, "cost per graduation  \\$8.37 at K=3  \u2192  \\$1.44 at K=20",
        ha="left", va="center", fontsize=6.4, color=BLUE, fontweight="bold")
ax.text(82.0, 1.7, "\u2014 the ladder is a fixed cost.", ha="left",
        va="center", fontsize=6.0, color=MUTE, style="italic")

plt.subplots_adjust(left=0.004, right=0.996, top=0.996, bottom=0.02)
fig.savefig("fig-teaser-new.pdf", bbox_inches="tight", pad_inches=0.03)
fig.savefig("fig-teaser-new.png", dpi=200, bbox_inches="tight", pad_inches=0.03)
print("wrote fig-teaser-new.pdf / .png")
