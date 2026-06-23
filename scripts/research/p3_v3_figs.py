"""Regenerate P3's three data figures from the frozen v3 re-judge artifacts (offline, no database).

Writes fig-funnel.png / fig-scatter.png / fig-family.png INTO the paper folder
(docs/research/publishing/p3_reproducibility_gap/): measured rates from
data/research/p3_v3_rejudge_trials.jsonl and per-primitive metadata (source_type,
family, claimed_rate) from data/research/p3_v3_rejudge_pairs.csv, so the figures
match the v3 captions and recompute from the released supplement with no database.
Prints the rendered headline numbers for the caption match-gate.

Run:  python3 scripts/research/p3_v3_figs.py   (needs matplotlib)
"""
from __future__ import annotations
import json, csv, random
from collections import defaultdict
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt


def bootstrap_ci(trials, B=1000, seed=20260524):
    """95% percentile-bootstrap CI for the mean of a 0/1 vector (inlined; offline, no project dependency)."""
    if not trials:
        return (0.0, 0.0)
    n = len(trials)
    bools = [1 if t else 0 for t in trials]
    s = sum(bools)
    if s == 0:
        return (0.0, 0.0)
    if s == n:
        return (1.0, 1.0)
    rng = random.Random(seed)
    means = [sum(rng.choices(bools, k=n)) / n for _ in range(B)]
    means.sort()
    lo = means[max(0, min(B - 1, int(0.025 * B)))]
    hi = means[max(0, min(B - 1, int(0.975 * B) - 1))]
    return (max(0.0, min(1.0, lo)), max(0.0, min(1.0, hi)))

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/research/publishing/p3_reproducibility_gap"
OUT.mkdir(parents=True, exist_ok=True)  # so the figures regenerate from the unzipped supplement (the publishing dir is not in the zip)
BREACH = {"partial_breach", "full_breach"}; TAU = 0.4; SEED = 20260524
LLAMA = "acme-llama3-20260526"; ROBUST = "acme-claudehaiku-20260526"
INK = "#16181d"; GREY = "#999999"; ARXIV = "#0072B2"; GREYLIT = "#E69F00"; ROBUSTC = "#c2354d"
plt.rcParams.update({"legend.labelspacing": 1.0, "font.size": 11, "axes.edgecolor": "#444444", "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "grid.color": "#bbbbbb", "grid.linewidth": 0.6,
    "grid.alpha": 0.25, "axes.axisbelow": True, "figure.facecolor": "white", "axes.facecolor": "white",
    "savefig.facecolor": "white", "figure.dpi": 150, "savefig.dpi": 200, "savefig.bbox": "tight",
    "font.family": "serif", "font.serif": ["STIXGeneral", "DejaVu Serif"], "mathtext.fontset": "stix"})

cells = [json.loads(l) for l in (ROOT/"data/research/p3_v3_rejudge_trials.jsonl").read_text().splitlines() if l.strip()]
# metadata (source_type, family, claimed_rate) from the FROZEN released pairs CSV — no database, exact-match to the body's numbers
src = defaultdict(set); fam = {}; claimed = {}
for r in csv.DictReader((ROOT/"data/research/p3_v3_rejudge_pairs.csv").open()):
    pid = r["primitive_id"]; src[pid].add(r["source_type"]); fam[pid] = r["family"]
    if r.get("claimed_rate") not in (None, ""): claimed[pid] = float(r["claimed_rate"])

cell = defaultdict(lambda: [0, 0])
for x in cells:
    k = (x["primitive_id"], x["cfg"]); cell[k][0] += 1
    if str(x["v3_verdict"]).lower() in BREACH: cell[k][1] += 1
prims = sorted({x["primitive_id"] for x in cells})
def strat(p): return "arxiv" if "arxiv" in src.get(p, set()) else "grey-lit"
def rates(p): return {cf: (b/t if t else 0.) for (p2, cf), (t, b) in cell.items() if p2 == p}
def repro(p, only=None): rs = rates(p); return (rs.get(only, 0.) if only else (max(rs.values()) if rs else 0.)) >= TAU
def fci(ps, only=None):
    fl = [repro(p, only) for p in ps]; r = sum(fl)/len(fl) if fl else 0.; lo, hi = bootstrap_ci(fl, seed=SEED); return r, lo, hi
def pooled(p):
    rs = rates(p); tt = sum(cell[(p, cf)][0] for cf in rs); tb = sum(cell[(p, cf)][1] for cf in rs); return tb/tt if tt else 0.

# ---- F1 funnel ----
stages = ["≥1 of 5\nmodels", "frozen\nLlama-8B", "robust\nClaude-Haiku"]
fig, ax = plt.subplots(figsize=(7, 4.4), constrained_layout=True); ax.grid(axis="x", visible=False)
funnel_print = {}
for label, color in [("arxiv", ARXIV), ("grey-lit", GREYLIT)]:
    ps = [p for p in prims if strat(p) == label]
    pts = [fci(ps), fci(ps, LLAMA), fci(ps, ROBUST)]
    ys = [p[0] for p in pts]; los = [p[1] for p in pts]; his = [p[2] for p in pts]
    funnel_print[label] = [round(y, 3) for y in ys]
    err = [[y-lo for y, lo in zip(ys, los)], [hi-y for y, hi in zip(ys, his)]]
    ax.errorbar(range(3), ys, yerr=err, marker="o", ms=8, lw=2.5, capsize=4, color=color, ecolor=color,
                elinewidth=1.4, zorder=3, label={"arxiv": "arXiv", "grey-lit": "grey literature"}[label])
    voff = 9 if label == "arxiv" else -18; hoff = 11 if label == "arxiv" else 13
    for xi, yi in zip(range(3), ys):
        ax.annotate(f"{yi:.0%}", (xi, yi), textcoords="offset points", xytext=(hoff, voff), fontsize=10, color=color, weight="bold", zorder=4)
ax.set_xticks(range(3)); ax.set_xticklabels(stages); ax.set_xlim(-0.3, 2.45)
ax.set_ylabel("reproduction rate (τ = 0.4)"); ax.set_ylim(0, 0.68)
ax.legend(frameon=False, loc="upper right", handlelength=1.6)
ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
fig.savefig(OUT / "fig-funnel.png"); plt.close(fig)

# ---- F2 family ----
byf = defaultdict(list)
for p in prims: byf[fam[p]].append(p)
rows = []
for f, ps in byf.items():
    if len(ps) < 3: continue
    cl = [claimed[p] for p in ps if p in claimed]
    rows.append({"family": f, "n": len(ps), "repro": sum(repro(p) for p in ps)/len(ps), "claim": (sum(cl)/len(cl) if cl else None)})
rows.sort(key=lambda r: r["repro"])
fig, ax = plt.subplots(figsize=(8, 5.2))
ax.barh(range(len(rows)), [r["repro"] for r in rows], color=ARXIV, alpha=0.85, label="measured reproduction (τ=0.4)")
for yi, r in enumerate(rows):
    if r["claim"] is not None: ax.plot(r["claim"], yi, marker="D", ms=8, color=ROBUSTC, ls="none", zorder=4)
    # n= label sits white-inside the bar; for a bar too short to hold it (e.g. a family that
    # reproduces at 0%) place it just right of the bar end in dark ink so the count stays visible
    if r["repro"] >= 0.07:
        ax.annotate(f"n={r['n']}", (0.005, yi), va="center", fontsize=8, color="white", weight="bold")
    else:
        ax.annotate(f"n={r['n']}", (r["repro"] + 0.008, yi), va="center", ha="left", fontsize=8, color="#555555", weight="bold")
ax.set_yticks(range(len(rows))); ax.set_yticklabels([r["family"].replace("_", " ") for r in rows], fontsize=9)
ax.set_xlim(0, 1.05); ax.set_xlabel("rate")
ax.plot([], [], marker="D", color=ROBUSTC, ls="none", label="mean claimed success (source)")
ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.09), ncol=2, fontsize=9)
fig.savefig(OUT / "fig-family.png"); plt.close(fig)

# ---- F3 scatter ----
cp = [p for p in prims if p in claimed]
xs = [claimed[p] for p in cp]; ys = [pooled(p) for p in cp]; isarx = [strat(p) == "arxiv" for p in cp]
def ranks(v):
    o = sorted(range(len(v)), key=lambda i: v[i]); rk = [0.]*len(v); i = 0
    while i < len(v):
        j = i
        while j+1 < len(v) and v[o[j+1]] == v[o[i]]: j += 1
        for k in range(i, j+1): rk[o[k]] = (i+j)/2+1
        i = j+1
    return rk
def pear(a, b):
    n = len(a); ma, mb = sum(a)/n, sum(b)/n; num = sum((a[i]-ma)*(b[i]-mb) for i in range(n))
    da = sum((a[i]-ma)**2 for i in range(n))**.5; db = sum((b[i]-mb)**2 for i in range(n))**.5
    return num/(da*db) if da and db else 0.
def sp(x, y): return pear(ranks(x), ranks(y))
rng = random.Random(SEED); bs = []
for _ in range(2000):
    idx = [rng.randrange(len(xs)) for _ in range(len(xs))]; bs.append(sp([xs[i] for i in idx], [ys[i] for i in idx]))
bs.sort(); rho = sp(xs, ys); lo, hi = bs[50], bs[1949]
hi100 = [p for p in cp if claimed[p] >= 0.999]
n100, repro100 = len(hi100), sum(repro(p) for p in hi100); mean100 = sum(pooled(p) for p in hi100)/len(hi100)
fig, ax = plt.subplots(figsize=(7, 5), constrained_layout=True)
ax.plot([0, 1], [0, 1], ls="--", lw=1.2, color=GREY, zorder=1, label="claim = measured")
for flag, col, lab in [(True, ARXIV, "arXiv"), (False, GREYLIT, "grey literature")]:
    ax.scatter([x for x, a in zip(xs, isarx) if a == flag], [y for y, a in zip(ys, isarx) if a == flag],
               c=col, s=48, alpha=0.85, edgecolor="white", lw=0.6, zorder=3, label=lab)
ax.set_xlabel("claimed success rate (source)"); ax.set_ylabel("measured pooled breach rate")
ax.set_xlim(-0.02, 1.05); ax.set_ylim(-0.02, 1.05)
ax.annotate(f"{n100} sources claim ≈100%;\nmean measured = {mean100:.1%}", (0.50, 0.86), ha="center", va="center",
            fontsize=9, color=INK, bbox=dict(boxstyle="round,pad=0.35", fc="#fbf3e7", ec=GREYLIT, lw=1.0))
ax.annotate(f"Spearman ρ = {rho:+.2f}\n95% CI [{lo:+.2f}, {hi:+.2f}],  n = {len(cp)}", (0.04, 0.50), ha="left", va="center", fontsize=9.5, color=INK)
ax.legend(frameon=False, loc="upper left", handletextpad=0.5)
fig.savefig(OUT / "fig-scatter.png"); plt.close(fig)

print("MATCH-GATE (rendered figure numbers must equal v3 captions):")
print(f"  funnel arxiv={funnel_print['arxiv']}  grey-lit={funnel_print['grey-lit']}  (caption: arXiv 53.2/16.5/10.1, grey 35.6/6.3/1.4)")
allf = [fci(prims), fci(prims, LLAMA), fci(prims, ROBUST)]
print(f"  funnel ALL={[round(p[0],3) for p in allf]}  (caption table ALL: 40.2/9.0/3.7)")
print(f"  scatter rho={rho:+.3f} CI[{lo:+.2f},{hi:+.2f}] n={len(cp)}  claims100: {repro100}/{n100} mean={mean100:.1%}  (caption: rho -0.07, n=56, 6/17, 13.5%)")
print(f"  family Spearman={sp([r['repro'] for r in [x for x in rows if x['claim'] is not None]], [r['claim'] for r in [x for x in rows if x['claim'] is not None]]):+.3f}  (caption: -0.17, but fig is over >=3-measured; c3 over claim-carrying)")
print("wrote fig-funnel.png, fig-family.png, fig-scatter.png to", OUT)
