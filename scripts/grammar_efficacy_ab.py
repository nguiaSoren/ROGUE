#!/usr/bin/env python
"""§10.9 grammar-efficacy A/B — deterministic templates vs freeform planner.

The load-bearing open question after structured planning shipped: grammars *solved*
the planner-refusal bottleneck (validity 22%→100%), but do they *preserve attack
effectiveness*? Templates are now the primary path, so this is a regression check.

Runs the SAME escalation sweep two ways — Arm A: deterministic templates (default);
Arm B: ``--no-templates`` (freeform model) — holding parents / quota / planner-model
fixed, then compares the metrics from the ``ladder_attempts`` trace + the run logs:

    validity_rate · breach_rate · orchestration_failures (refused/render_error) ·
    attempts · avg ladder depth · cost/run

(Cross-run variance / reproducibility need repeated runs — re-run ``run`` a few times
and ``analyze`` aggregates by arm tag.)

Usage::

    uv run python scripts/grammar_efficacy_ab.py run --limit 12 --max-spend 8   [COSTS $]
    uv run python scripts/grammar_efficacy_ab.py analyze                         [FREE]
    uv run python scripts/grammar_efficacy_ab.py analyze --tag grameff_1733200000

⚠ ``run`` spends real money (both arms) + writes to Neon. ``analyze`` is read-only.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)


def _db_url() -> str:
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set (check .env)")
    return url


async def _arm(*, no_templates: bool, run_id: str, limit: int, max_spend: float) -> None:
    from scripts.reproduce_once import run_reproduction

    label = "freeform" if no_templates else "templates"
    print(f"\n>>> grammar A/B arm: {label}  run_id={run_id}  "
          f"(limit={limit}, max-spend=${max_spend})", flush=True)
    await run_reproduction(
        database_url=_db_url(),
        primitive_limit=limit,
        n_trials=1,
        temperature=0.7,
        concurrency=5,
        escalate=True,
        escalate_candidate_quota=1,  # force candidate evaluation in both arms
        escalate_no_templates=no_templates,
        escalate_max_spend=max_spend,
        run_id=run_id,
    )


def run(args: argparse.Namespace) -> None:
    stamp = f"grameff_{int(time.time())}"
    # Templates arm first, then freeform — same parents (deterministic --limit selection).
    asyncio.run(_arm(no_templates=False, run_id=f"{stamp}_tmpl",
                     limit=args.limit, max_spend=args.max_spend))
    asyncio.run(_arm(no_templates=True, run_id=f"{stamp}_free",
                     limit=args.limit, max_spend=args.max_spend))
    print(f"\n>>> both arms done. comparison (tag {stamp}):")
    analyze(argparse.Namespace(tag=stamp))


# Per-arm aggregates from ladder_attempts. Tier-5 entities (base/candidate) are the
# planner-driven ones — the only place templates vs freeform differ.
_METRICS_SQL = """
WITH arm AS (
  SELECT CASE WHEN run_id LIKE '%_tmpl' THEN 'templates'
              WHEN run_id LIKE '%_free' THEN 'freeform' ELSE run_id END AS arm,
         *
  FROM ladder_attempts
  {where}
)
SELECT arm,
       count(*)                                            AS attempts,
       sum((outcome IN ('breach','no_breach'))::int)       AS valid,
       sum(breached::int)                                  AS breaches,
       sum((outcome IN ('refused','render_error'))::int)   AS orch_failures,
       round(avg(ladder_depth)::numeric, 2)                AS avg_depth
FROM arm
WHERE entity_type IN ('base', 'candidate')   -- planner-driven tiers only
GROUP BY 1 ORDER BY 1
"""


def analyze(args: argparse.Namespace) -> None:
    eng = create_engine(_db_url())
    tag = getattr(args, "tag", None)
    where = f"WHERE run_id LIKE '{tag}%'" if tag else ""
    with eng.connect() as c:
        rows = c.execute(text(_METRICS_SQL.format(where=where))).all()
        if not rows:
            print("no planner-tier ladder_attempts found"
                  + (f" for tag '{tag}'" if tag else ""))
            eng.dispose()
            return
        print("\n── deterministic templates vs freeform (planner-driven tiers) ──"
              + (f"  [tag {tag}]" if tag else ""))
        print(f"  {'arm':>10} {'attempts':>9} {'valid':>6} {'breaches':>9} "
              f"{'validity':>9} {'breach_rt':>10} {'orch_fail':>10} {'avg_depth':>10}")
        for r in rows:
            vr = r.valid / r.attempts if r.attempts else 0
            br = r.breaches / r.attempts if r.attempts else 0
            print(f"  {r.arm:>10} {r.attempts:>9} {r.valid:>6} {r.breaches:>9} "
                  f"{vr:>9.2f} {br:>10.2f} {r.orch_failures:>10} {float(r.avg_depth or 0):>10.2f}")
        print("\nRead: templates should show ~0 orch_failures (no refusals) and stable "
              "depth; the open question is breach_rt — if templates ≈ freeform on breach "
              "while winning on orch_failures/stability, the structured-planning bet paid off. "
              "Cost/run + cross-run variance: compare est_cost in the run logs across repeats.")
    eng.dispose()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("run", help="run BOTH arms then analyze (SPENDS MONEY)")
    pr.add_argument("--limit", type=int, default=12)
    pr.add_argument("--max-spend", type=float, default=8.0)
    pr.set_defaults(func=run)
    pa = sub.add_parser("analyze", help="print the comparison from ladder_attempts (FREE)")
    pa.add_argument("--tag", default=None, help="restrict to one A/B (e.g. grameff_1733200000)")
    pa.set_defaults(func=analyze)
    args = p.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
