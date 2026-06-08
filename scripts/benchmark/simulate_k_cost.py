#!/usr/bin/env python
"""$0 cost-curve projection for higher-K growth sweeps — read-only, no spend.

Projects the escalation cost of a growth sweep as a function of the selection cap K,
grounded in the two growth sweeps already run. It answers the COST half of the
K-saturation question for free; the GRADUATION half (does yield hold as K rises?) is
the irreducible unknown that needs a paid run (see docs/research/RESEARCH_TODO.md).

Model (every parameter measured, not assumed):
    cost(K) = n_parents × (fixed_rotation + K) × per_attempt
  - per_attempt   = escalation_spend ÷ executed attempts   (≈ $0.09, from the runs)
  - fixed_rotation = attempts/ladder − K                   (the non-candidate tiers)
  - n_parents     = EVADE parents covered (target coverage; default = observed max)
Because each extra candidate is one more attempt per ladder, the slope is shallow
(~per_attempt × n_parents per K-step) — which is exactly the "candidates ride nearly
free" finding, projected forward. Caveat: this assumes FULL coverage at the target
n_parents; under a fixed spend cap a larger K means fewer parents fit, a coverage↔K
tradeoff the cap induces.

    uv run python scripts/benchmark/simulate_k_cost.py
    uv run python scripts/benchmark/simulate_k_cost.py --parents 12 --ks 3,5,8,10,12,15
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

DATA = _ROOT / "docs" / "figs" / "data"
GROWTH_RUNS = {  # the two quota=K growth sweeps (greedy quota=0 is excluded)
    "sweep_starv_q3_1780462736": 3,
    "sweep_K5_q5_1780477935": 5,
}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ks", default="3,5,8,10,12,15")
    p.add_argument("--parents", type=int, default=None, help="target EVADE-parent coverage")
    args = p.parse_args()
    ks = [int(k) for k in args.ks.split(",")]

    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")
    c = create_engine(url).connect()

    # measured spend per run (from the frozen metrics.json, written by export_paper_data.py)
    spend = {}
    mpath = DATA / "metrics.json"
    if mpath.exists():
        for r in json.loads(mpath.read_text()).get("runs", {}).values():
            spend[r["run_id"]] = r.get("escalation_spend")

    rows = []
    for rid, K in GROWTH_RUNS.items():
        n_att = c.execute(text("SELECT count(*) FROM ladder_attempts WHERE run_id=:r AND outcome<>'stopped'"),
                          {"r": rid}).scalar() or 0
        n_lad = c.execute(text("SELECT count(DISTINCT parent_id) FROM ladder_attempts WHERE run_id=:r"),
                          {"r": rid}).scalar() or 1
        s = spend.get(rid)
        rows.append({"rid": rid, "K": K, "attempts": int(n_att), "ladders": int(n_lad), "spend": s})

    # derive parameters (average across the two growth runs)
    per_attempt = sum(r["spend"] / r["attempts"] for r in rows if r["spend"]) / sum(1 for r in rows if r["spend"])
    fixed = sum(r["attempts"] / r["ladders"] - r["K"] for r in rows) / len(rows)
    n_parents = args.parents or max(r["ladders"] for r in rows)
    c.close()

    print("\n  measured (the two growth sweeps):")
    for r in rows:
        print(f"    K={r['K']}: {r['attempts']} attempts / {r['ladders']} ladders "
              f"= {r['attempts'] / r['ladders']:.0f} per ladder, spend ${r['spend']:.2f} (CAPPED)")
    print(f"\n  derived: per_attempt ≈ ${per_attempt:.3f}   fixed_rotation ≈ {fixed:.0f} strategies/ladder")
    print(f"  projection at FULL coverage of {n_parents} EVADE parents:\n")
    print(f"    {'K':>4}{'attempts/ladder':>17}{'est. escalation cost':>22}")
    proj = []
    for K in ks:
        apl = fixed + K
        cost = n_parents * apl * per_attempt
        proj.append({"K": K, "attempts_per_ladder": round(apl, 1), "est_escalation_cost": round(cost, 2)})
        print(f"    {K:>4}{apl:>17.0f}{'$' + format(cost, '.2f'):>22}")

    # persist for a figure / the TODO doc
    if mpath.exists():
        m = json.loads(mpath.read_text())
        m["k_cost_projection"] = {"per_attempt": round(per_attempt, 4), "fixed_rotation": round(fixed, 1),
                                  "n_parents": n_parents, "points": proj,
                                  "note": "FULL-coverage projection; measured K=3/K=5 spends were spend-capped. "
                                          "Cost half only — graduation yield at higher K needs a paid run."}
        mpath.write_text(json.dumps(m, indent=2, default=str))
        print(f"\n  wrote k_cost_projection → {mpath.relative_to(_ROOT)}")

    print("\n  Read: the slope is shallow (~${:.2f}/K-step at this coverage) — raising K is cheap because\n"
          "  each extra candidate is one more attempt per ladder. So a K=8 full-coverage growth sweep is\n"
          "  ≈ ${:.0f}. What this CANNOT tell you: whether candidates 6–8 graduate — that is the paid unknown."
          .format(per_attempt * n_parents, next(x["est_escalation_cost"] for x in proj if x["K"] == 8)
                  if any(x["K"] == 8 for x in proj) else proj[-1]["est_escalation_cost"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
