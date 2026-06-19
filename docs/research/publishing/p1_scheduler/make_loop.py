#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Figure: the self-expansion loop for the ROGUE allocation paper.
# Replaces the ASCII verbatim figure with a vector diagram matched to the
# teaser/body palette (same ORANGE/BLUE/INK/MUTE, DejaVu Serif, type-42 PDF).
#
# The cycle: harvest -> pool grows -> pool >= 5 ? -> GROWTH -> graduate
#            -> pool drains -> CANONICAL (cheap) -> pool refills -> back to start.
# The decision node (pool >= 5 ?) gates the two modes; GROWTH spends, drains the
# pool, CANONICAL stays cheap until harvest refills it.

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, PathPatch
from matplotlib.path import Path

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["DejaVu Serif"],
    "pdf.fonttype": 42, "ps.fonttype": 42,
})

ORANGE   = "#E09000"
BLUE     = "#0070B0"
INK      = "#1a1a1a"
MUTE     = "#666666"
PANEL    = "#f6f7f8"
BLUEBG   = "#eaf3f9"
ORANGEBG = "#fbf1de"
EDGE     = "#c9ccd0"

FIG_W, FIG_H = 7.1, 2.05
fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
ax.set_xlim(0, 100); ax.set_ylim(0, 29); ax.axis("off")
ASPECT = FIG_H / FIG_W

def box(cx, cy, w, h, fc, ec, lw=1.1, rounding=2.0, tc=INK, label="",
        fs=7.4, bold=False, sub="", subfs=6.0, subc=MUTE):
    ax.add_patch(FancyBboxPatch((cx - w/2, cy - h/2), w, h,
        boxstyle=f"round,pad=0,rounding_size={rounding}",
        linewidth=lw, edgecolor=ec, facecolor=fc, mutation_aspect=ASPECT))
    if sub:
        ax.text(cx, cy + h*0.16, label, ha="center", va="center",
                fontsize=fs, color=tc, fontweight="bold" if bold else "normal")
        ax.text(cx, cy - h*0.24, sub, ha="center", va="center",
                fontsize=subfs, color=subc)
    else:
        ax.text(cx, cy, label, ha="center", va="center",
                fontsize=fs, color=tc, fontweight="bold" if bold else "normal")

def diamond(cx, cy, w, h, fc, ec, label, lw=1.1, fs=7.0, tc=INK):
    pts = [(cx, cy + h/2), (cx + w/2, cy), (cx, cy - h/2), (cx - w/2, cy)]
    ax.add_patch(PathPatch(Path(pts + [pts[0]], closed=True),
        facecolor=fc, edgecolor=ec, lw=lw))
    ax.text(cx, cy, label, ha="center", va="center", fontsize=fs,
            color=tc, fontweight="bold")

def arrow(x1, y1, x2, y2, color=MUTE, lw=1.5, rad=0.0, style="-|>"):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style,
        mutation_scale=11, lw=lw, color=color,
        connectionstyle=f"arc3,rad={rad}", shrinkA=3, shrinkB=3))

def alabel(x, y, txt, color=MUTE, fs=5.9, style="normal", ha="center", bold=False):
    ax.text(x, y, txt, ha=ha, va="center", fontsize=fs, color=color,
            style=style, fontweight="bold" if bold else "normal")

def elbow(x1, y1, xc, yc, x2, y2, color=MUTE, lw=1.5):
    # plain line for the first leg, arrow for the final leg -> one continuous path
    ax.add_patch(FancyArrowPatch((x1, y1), (xc, yc), arrowstyle="-",
        mutation_scale=11, lw=lw, color=color, shrinkA=3, shrinkB=0))
    ax.add_patch(FancyArrowPatch((xc, yc), (x2, y2), arrowstyle="-|>",
        mutation_scale=11, lw=lw, color=color, shrinkA=0, shrinkB=3))

# ---- geometry ----
TOP, BOT = 20.5, 7.5
BW, BH = 16.5, 7.6
x_harv, x_pool, x_dec, x_grow = 10.5, 31.5, 52.5, 73.0
x_grad = 91.0

# ================= TOP ROW (growth path) =================
box(x_harv, TOP, BW, BH, PANEL, EDGE, label="harvest", sub="scrape techniques")
box(x_pool, TOP, BW, BH, PANEL, EDGE, label="candidate pool", sub="grows")
diamond(x_dec, TOP, 16.0, 11.5, "white", INK, "pool $\\geq$ 5 ?")
box(x_grow, TOP, 15.0, BH, ORANGEBG, ORANGE, label="GROWTH", bold=True, tc=ORANGE,
    sub="full rotation", subc="#9a6b14")
box(x_grad, TOP, 13.0, BH, BLUE, BLUE, label="graduate", bold=True, tc="white", fs=7.6)

arrow(x_harv + BW/2, TOP, x_pool - BW/2, TOP, color=MUTE)
arrow(x_pool + BW/2, TOP, x_dec - 8.0, TOP, color=MUTE)
arrow(x_dec + 8.0, TOP, x_grow - 7.5, TOP, color=ORANGE, lw=1.7)
alabel((x_dec + 8.0 + x_grow - 7.5)/2, TOP + 2.6, "yes", color=ORANGE, bold=True)
arrow(x_grow + 7.5, TOP, x_grad - 6.5, TOP, color=ORANGE, lw=1.7)

# ================= BOTTOM ROW (canonical path) =================
box(x_grow, BOT, 15.0, BH, BLUEBG, BLUE, label="CANONICAL", bold=True, tc=BLUE,
    sub="cheap sweep", subc="#0a5a85")
# graduate -> down -> left into CANONICAL right edge (one continuous path)
elbow(x_grad, TOP - BH/2, x_grad, BOT, x_grow + 15/2, BOT, color=MUTE)
alabel(x_grad + 1.5, (TOP - BH/2 + BOT)/2 + 0.5, "pool drains", color=MUTE, ha="left")

# decision "no" branch: from diamond bottom vertex down to canonical top-left
arrow(x_dec, TOP - 11.5/2, x_grow - 7.5 + 1, BOT + BH/2, color=BLUE, lw=1.4, rad=-0.28)
alabel(x_dec + 9.5, TOP - 5.3, "no", color=BLUE, bold=True, fs=6.4)

# canonical -> refills harvest (long return along the bottom/left)
arrow(x_grow - 7.5, BOT, x_harv, BOT, color=MUTE)
arrow(x_harv, BOT, x_harv, TOP - BH/2, color=MUTE, rad=0.0)
alabel((x_grow - BW/2 + x_harv)/2 - 2, BOT + 2.5, "pool refills (harvest)", color=MUTE)

# ================= CAPTION-IN-FIGURE cue (self-regulating) =================
ax.text(50, 1.3,
        "GROWTH drains the pool below threshold \\u2192 scheduler reverts to cheap "
        "CANONICAL sweeps until harvest refills it.".replace("\\u2192", "\u2192"),
        ha="center", va="center", fontsize=6.0, color=MUTE, style="italic")

plt.subplots_adjust(left=0.005, right=0.995, top=0.995, bottom=0.005)
fig.savefig("fig-loop.pdf", bbox_inches="tight", pad_inches=0.02)
print("wrote fig-loop.pdf")
