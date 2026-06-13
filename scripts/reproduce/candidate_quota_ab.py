#!/usr/bin/env python
"""§10.9 candidate-quota A/B — measure the reserved-exploration-slot's value.

Runs the SAME escalation sweep twice — ``quota=0`` (baseline; the Tier-1 image
renderers early-stop and starve candidates) vs ``quota=1`` (reserve one slot so a
harvested candidate is guaranteed an attempt) — then reads the ``ladder_attempts``
orchestration trace and prints the comparison. Because ``--primitive-limit N`` picks
the top-N primitives by reproducibility_score deterministically, both arms hit the
SAME parents, so the only varying factor is the scheduler policy.

This is the empirical baseline for the §10.10 adaptive scheduler (break-bandit).

Usage::

    # one command — run BOTH arms then analyze  (COSTS REAL MONEY: target+judge calls)
    uv run python scripts/reproduce/candidate_quota_ab.py run --limit 12 --max-spend 8

    # FREE — re-print the comparison from already-logged ladder_attempts
    uv run python scripts/reproduce/candidate_quota_ab.py analyze
    uv run python scripts/reproduce/candidate_quota_ab.py analyze --run-prefix abq_1733180000

⚠ The ``run`` mode spends real money and writes to the live Neon DB. It is never
run automatically — only when you invoke it. ``analyze`` is read-only and free.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

# Surface run_reproduction's INFO logs (start / [progress] / escalation breach) —
# without this the run is silent because we call run_reproduction() directly
# rather than through reproduce_once's main(), which is where logging is set up.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

# Put the project root on sys.path so `scripts.*` (the escalation ladder) and
# `rogue.*` both import when run as a bare script.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402


def _db_url() -> str:
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set (check .env)")
    return url


async def _run_arm(*, quota: int, run_id: str, limit: int, max_spend: float) -> None:
    from scripts.reproduce.reproduce_once import run_reproduction

    print(f"\n>>> A/B arm quota={quota}  run_id={run_id}  "
          f"(primitive-limit={limit}, max-spend=${max_spend})", flush=True)
    await run_reproduction(
        database_url=_db_url(),
        primitive_limit=limit,
        n_trials=1,
        temperature=0.7,
        concurrency=5,
        escalate=True,
        escalate_candidate_quota=quota,
        escalate_max_spend=max_spend,
        run_id=run_id,
    )


def run(args: argparse.Namespace) -> None:
    """Run both arms (quota=0 then quota=1), then analyze. Spends money."""
    stamp = f"abq_{int(time.time())}"
    sq = getattr(args, "single_quota", None)
    if sq is not None:
        asyncio.run(
            _run_arm(quota=sq, run_id=f"{stamp}_q{sq}", limit=args.limit,
                     max_spend=args.max_spend)
        )
        print(f"\n>>> single arm (quota={sq}) done. comparison (run-prefix {stamp}):")
        analyze(argparse.Namespace(run_prefix=stamp))
        return
    asyncio.run(
        _run_arm(quota=0, run_id=f"{stamp}_q0", limit=args.limit, max_spend=args.max_spend)
    )
    asyncio.run(
        _run_arm(quota=1, run_id=f"{stamp}_q1", limit=args.limit, max_spend=args.max_spend)
    )
    print(f"\n>>> both arms done. comparison (run-prefix {stamp}):")
    analyze(argparse.Namespace(run_prefix=stamp))


_BY_POLICY_SQL = """
SELECT candidate_attempt_quota AS quota,
       entity_type,
       count(*)                          AS attempts,
       sum(breached::int)                AS breaches,
       round(avg(breached::int)::numeric, 3) AS success_rate,
       sum(stopped_run::int)             AS early_stops
FROM ladder_attempts
{where}
GROUP BY 1, 2
ORDER BY 1, 2
"""

_CANDIDATE_SQL = """
SELECT candidate_attempt_quota AS quota,
       count(*)                          AS candidate_attempts,
       sum(breached::int)                AS candidate_breaches,
       count(DISTINCT technique_id)      AS distinct_candidates
FROM ladder_attempts
WHERE entity_type = 'candidate' {and_where}
GROUP BY 1
ORDER BY 1
"""


def analyze(args: argparse.Namespace) -> None:
    """Print the A/B comparison from ladder_attempts. Read-only, free."""
    eng = create_engine(_db_url())
    prefix = getattr(args, "run_prefix", None)
    where = f"WHERE run_id LIKE '{prefix}%'" if prefix else ""
    and_where = f"AND run_id LIKE '{prefix}%'" if prefix else ""
    with eng.connect() as c:
        n = c.execute(text("SELECT count(*) FROM ladder_attempts")).scalar()
        print(f"\nladder_attempts rows: {n}"
              + (f"  (filtered to run-prefix '{prefix}')" if prefix else ""))

        print("\n── attempts by (quota × entity_type) ──")
        print(f"  {'quota':>5} {'entity':>10} {'attempts':>9} {'breaches':>9} "
              f"{'succ%':>6} {'early_stops':>11}")
        for r in c.execute(text(_BY_POLICY_SQL.format(where=where))):
            print(f"  {r.quota:>5} {r.entity_type:>10} {r.attempts:>9} {r.breaches:>9} "
                  f"{float(r.success_rate):>6.3f} {r.early_stops:>11}")

        print("\n── candidate evaluation (the reserved-slot payoff) ──")
        print(f"  {'quota':>5} {'cand_attempts':>14} {'cand_breaches':>14} "
              f"{'distinct':>9}")
        for r in c.execute(text(_CANDIDATE_SQL.format(and_where=and_where))):
            print(f"  {r.quota:>5} {r.candidate_attempts:>14} {r.candidate_breaches:>14} "
                  f"{r.distinct_candidates:>9}")
        print("\nRead: quota=0 should show ~0 candidate_attempts (starved); quota=1 "
              "should show candidate attempts + any breaches = graduations bought by "
              "the reserved slot. Compare early_stops to quantify the starvation.")
    eng.dispose()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="run BOTH arms then analyze (SPENDS MONEY)")
    pr.add_argument("--limit", type=int, default=12,
                    help="--primitive-limit for each arm (default 12)")
    pr.add_argument("--max-spend", type=float, default=8.0,
                    help="--escalate-max-spend per arm (default $8)")
    pr.add_argument("--single-quota", type=int, default=None,
                    help="run ONE arm at this quota (skip the q0/q1 pair). "
                         "Use when the baseline already exists and you want the "
                         "full budget on one treatment arm, e.g. --single-quota 3")
    pr.set_defaults(func=run)

    pa = sub.add_parser("analyze", help="print the comparison from ladder_attempts (FREE)")
    pa.add_argument("--run-prefix", default=None,
                    help="restrict to a specific A/B (e.g. abq_1733180000)")
    pa.set_defaults(func=analyze)

    args = p.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
