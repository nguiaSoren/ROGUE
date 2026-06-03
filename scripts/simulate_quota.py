#!/usr/bin/env python
"""§10.10 Phase 2.2 — candidate-quota SIMULATION (no paid calls).

The first sweep ran ``candidate_quota=0`` (pure early-stop), so candidates were
cross-tier starved (planner tier reachability 7%, 3 candidates at 0%). The open
question — "would a candidate quota actually move candidate reachability, and at
what cost?" — can be answered from the data already collected, because the quota
mechanic is DETERMINISTIC given the rotation.

How quota=N changes execution (from ``run_escalation_ladder_one``): a breach no
longer finalizes the ladder until N candidates have been *attempted*, so the ladder
runs strategies in rank order — suppressing early-stop — until the N-th candidate
runs (or budget). Candidates sit at the tail of the rotation (planner tier, after
base + active), so quota=N ⇒ everything up to and including the N-th candidate
executes. This replays the logged ``ladder_rotation_membership`` rows under each
quota and reports the reachability/cost tradeoff.

Reachability is simulatable; whether a now-reachable candidate would *breach* is NOT
(it never ran) — so this estimates reachability + cost, and tells you whether the
paid ``starvation + quota`` sweep is worth running. READ-ONLY.

Usage::

    uv run python scripts/simulate_quota.py --run-id $(cat /tmp/rogue_sweep_runid.txt)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402


def _conn():
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")
    return create_engine(url).connect()


def _cost_per_attempt(log_path: str, executed_actual: int) -> float | None:
    """$ / executed attempt, from the run's actual escalation_spend ÷ executions."""
    if not (log_path and Path(log_path).exists() and executed_actual):
        return None
    import re
    for line in reversed(Path(log_path).read_text(errors="ignore").splitlines()):
        if "escalation_spend=$" in line:
            m = re.search(r"escalation_spend=\$([0-9.]+)", line)
            if m:
                return float(m.group(1)) / executed_actual
    return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-id", required=True)
    p.add_argument("--log", default="/tmp/rogue_sweep.log")
    p.add_argument("--quotas", default="0,1,2,3")
    args = p.parse_args()
    quotas = [int(q) for q in args.quotas.split(",")]
    c = _conn()

    # candidate technique_ids (status candidate). Approx "as of run" via current status.
    cand_ids = {r[0] for r in c.execute(text(
        "SELECT technique_id FROM attack_strategies WHERE status = 'candidate'"
    )).all()}

    rows = c.execute(text(
        "SELECT parent_id, rank, strategy_id, tier, eligible, executed, outcome "
        "FROM ladder_rotation_membership WHERE run_id = :rid ORDER BY parent_id, rank"
    ), {"rid": args.run_id}).all()
    if not rows:
        print(f"no rotation rows for run_id={args.run_id}")
        return 0

    # group into ladders
    ladders: dict[str, list] = {}
    for r in rows:
        ladders.setdefault(r.parent_id, []).append(r)

    executed_actual = sum(1 for r in rows if r.executed)
    cpa = _cost_per_attempt(args.log, executed_actual)

    print(f"\nrun {args.run_id}: {len(ladders)} ladders, {len(rows)} eligible-strategy "
          f"appearances, {executed_actual} actually executed (quota=0).")
    if cpa:
        print(f"cost/attempt ≈ ${cpa:.3f} (escalation_spend ÷ executions)")
    print(f"\n{'quota':>6}{'cand_reach':>12}{'planner_reach':>15}"
          f"{'executions':>12}{'est_esc_cost':>14}")

    for q in quotas:
        cand_elig = cand_reached = plan_elig = plan_reached = executions = 0
        for rws in ladders.values():
            ranks_sorted = sorted(rws, key=lambda r: r.rank)
            cand_ranks = [r.rank for r in ranks_sorted
                          if r.strategy_id in cand_ids and r.eligible]
            if q == 0:
                # actual early-stop behaviour as logged.
                exec_set = {r.rank for r in ranks_sorted if r.executed}
            else:
                # quota=N: run until min(N, #candidates) candidates attempted →
                # everything (eligible) up to that candidate's rank executes.
                if cand_ranks:
                    stop_rank = cand_ranks[min(q, len(cand_ranks)) - 1]
                else:
                    stop_rank = max((r.rank for r in ranks_sorted if r.eligible),
                                    default=-1)
                exec_set = {r.rank for r in ranks_sorted
                            if r.eligible and r.rank <= stop_rank}
            executions += len(exec_set)
            for r in ranks_sorted:
                if r.strategy_id in cand_ids and r.eligible:
                    cand_elig += 1
                    cand_reached += int(r.rank in exec_set)
                if r.tier == "planner" and r.eligible:
                    plan_elig += 1
                    plan_reached += int(r.rank in exec_set)
        cr = cand_reached / cand_elig if cand_elig else 0.0
        pr = plan_reached / plan_elig if plan_elig else 0.0
        cost = f"${executions * cpa:.2f}" if cpa else "n/a"
        print(f"{q:>6}{cr:>12.2f}{pr:>15.2f}{executions:>12}{cost:>14}")

    print("\nRead: quota lifts candidate/planner reachability (deterministic) but cost "
          "scales with executions (early-stop suppressed → more of the ladder runs). "
          "If candidate reachability moves materially at affordable cost, the paid "
          "`starvation + quota` sweep is worth it. (Whether reached candidates BREACH "
          "is not simulatable — that needs the run.)")
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
