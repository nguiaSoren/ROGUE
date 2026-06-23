#!/usr/bin/env python3
"""P3 PER-OBJECTIVE DECOMPOSITION (offline; no spend, no DB writes).

Joins the LLM objective classification (p3_objective_classify.py) to the v3
reproduction verdicts (p3_v3_rejudge_trials.jsonl) and recomputes the collapse
funnel WITHIN each objective stratum, using the SAME method as the headline
figure (TAU=0.4, panel = max over 5 configs, frozen Llama-8B anchor, robust
Claude-Haiku). The question this answers for a reviewer: does reproduction
collapse within the harmful stratum and within the agentic/extraction strata
separately, or is the headline only an artifact of mixing easy and hard
objectives?

  uv run python scripts/research/p3_objective_decompose.py
"""
from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path


def bootstrap_ci(trials, B=1000, seed=20260524):
    """95% percentile-bootstrap CI for the mean of a 0/1 vector.

    Inlined percentile bootstrap so this script recomputes offline from the
    released supplement with no project dependency.
    """
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
TRIALS = ROOT / "data" / "research" / "p3_v3_rejudge_trials.jsonl"
CLASS = ROOT / "data" / "research" / "p3_objective_classification.jsonl"
OUT = ROOT / "data" / "research" / "p3_objective_decomposition.json"

BREACH = {"partial_breach", "full_breach"}
TAU = 0.4
SEED = 20260524
LLAMA = "acme-llama3-20260526"     # frozen open-weight anchor (9.0% overall)
ROBUST = "acme-claudehaiku-20260526"  # most robust model (3.7% overall)

cells = [json.loads(l) for l in TRIALS.read_text().splitlines() if l.strip()]
cell = defaultdict(lambda: [0, 0])
for x in cells:
    k = (x["primitive_id"], x["cfg"])
    cell[k][0] += 1
    if str(x["v3_verdict"]).lower() in BREACH:
        cell[k][1] += 1
prims_all = sorted({x["primitive_id"] for x in cells})


def rates(p):
    return {cf: (b / t if t else 0.) for (p2, cf), (t, b) in cell.items() if p2 == p}


def repro(p, only=None):
    rs = rates(p)
    return (rs.get(only, 0.) if only else (max(rs.values()) if rs else 0.)) >= TAU


def fci(ps, only=None):
    fl = [repro(p, only) for p in ps]
    r = sum(fl) / len(fl) if fl else 0.
    lo, hi = bootstrap_ci(fl, seed=SEED) if fl else (0., 0.)
    return r, lo, hi


# objective classification
cls = {}
if CLASS.exists():
    for l in CLASS.read_text().splitlines():
        if l.strip():
            r = json.loads(l)
            cls[r["primitive_id"]] = r["objective"]
else:
    raise SystemExit(f"missing {CLASS} -- run p3_objective_classify.py first")

# only primitives that are both classified AND in the trial set
prims = [p for p in prims_all if p in cls]
unmapped = [p for p in prims_all if p not in cls]


def line(label, ps):
    n = len(ps)
    if not n:
        return f"  {label:22s} n={n}"
    pan, _, _ = fci(ps)
    anc, alo, ahi = fci(ps, LLAMA)
    rob, rlo, rhi = fci(ps, ROBUST)
    return (f"  {label:22s} n={n:3d}   panel {100*pan:5.1f}%  ->  "
            f"Llama {100*anc:5.1f}% [{100*alo:.0f},{100*ahi:.0f}]  ->  "
            f"robust {100*rob:5.1f}% [{100*rlo:.0f},{100*rhi:.0f}]")


print(f"trial primitives: {len(prims_all)} | classified: {len(prims)} | unmapped: {len(unmapped)}")
print("\n=== OVERALL (sanity: should match 40.2 / 9.0 / 3.7) ===")
print(line("ALL", prims_all))

print("\n=== WITHIN each objective stratum ===")
from collections import Counter
dist = Counter(cls[p] for p in prims)
order = ["harmful_content", "agentic_compromise", "info_extraction", "generic_jailbreak", "ambiguous"]
strata = {}
for obj in order + [o for o in dist if o not in order]:
    ps = [p for p in prims if cls[p] == obj]
    if not ps:
        continue
    print(line(obj, ps))
    pan = fci(ps); anc = fci(ps, LLAMA); rob = fci(ps, ROBUST)
    strata[obj] = {"n": len(ps), "panel": pan, "anchor": anc, "robust": rob}

# combined "harm-relevant" stratum (content + agentic): the defender-relevant union
harm_rel = [p for p in prims if cls[p] in ("harmful_content", "agentic_compromise")]
print("\n=== grouped ===")
print(line("harmful+agentic", harm_rel))
print(line("extraction+generic", [p for p in prims if cls[p] in ("info_extraction", "generic_jailbreak")]))

OUT.write_text(json.dumps({
    "method": {"tau": TAU, "anchor_cfg": LLAMA, "robust_cfg": ROBUST, "seed": SEED},
    "n_trial_primitives": len(prims_all), "n_classified": len(prims),
    "distribution": dict(dist),
    "overall": {"panel": fci(prims_all), "anchor": fci(prims_all, LLAMA), "robust": fci(prims_all, ROBUST)},
    "strata": strata,
}, indent=2))
print(f"\nwrote {OUT}")
