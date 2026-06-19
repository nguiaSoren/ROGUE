#!/usr/bin/env python
"""§10.9 grammar-efficacy A/B — deterministic templates vs freeform planner.

The load-bearing open question after structured planning shipped: grammars *solved*
the planner-refusal bottleneck (validity 22%→100%), but do they *preserve attack
effectiveness*? Templates are now the primary path, so this is a regression check.

Runs the SAME escalation sweep three ways — Arm A: deterministic templates (default);
Arm B: template + model SEMANTIC slot-fill (``--slot-fill``, §10.9 Step 3); Arm C:
``--no-templates`` (freeform model) — holding parents / quota / planner-model fixed,
then compares the metrics from the ``ladder_attempts`` trace + the run logs:

    validity_rate · breach_rate · orchestration_failures (refused/render_error) ·
    attempts · avg ladder depth · cost/run

(Cross-run variance / reproducibility need repeated runs — re-run ``run`` a few times
and ``analyze`` aggregates by arm tag.)

Usage::

    uv run python scripts/reproduce/grammar_efficacy_ab.py run --limit 12 --max-spend 8   [COSTS $]
    uv run python scripts/reproduce/grammar_efficacy_ab.py analyze                         [FREE]
    uv run python scripts/reproduce/grammar_efficacy_ab.py analyze --tag grameff_1733200000

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

_ROOT = Path(__file__).resolve().parents[2]
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


async def _arm(
    *, no_templates: bool, slot_fill: bool, run_id: str, limit: int, max_spend: float,
) -> None:
    from scripts.reproduce.reproduce_once import run_reproduction

    label = "freeform" if no_templates else ("slotfill" if slot_fill else "templates")
    print(f"\n>>> grammar A/B arm: {label}  run_id={run_id}  "
          f"(limit={limit}, max-spend=${max_spend})", flush=True)
    await run_reproduction(
        database_url=_db_url(),
        primitive_limit=limit,
        n_trials=1,
        temperature=0.7,
        concurrency=5,
        escalate=True,
        escalate_candidate_quota=1,  # force candidate evaluation in every arm
        escalate_no_templates=no_templates,
        escalate_slot_fill=slot_fill,
        escalate_max_spend=max_spend,
        run_id=run_id,
    )


def _run_arm_guarded(label: str, timeout_s: float, **arm_kwargs: object) -> bool:
    """Run ONE arm with a hard wall-clock cap + total exception isolation.

    Returns True on clean completion. A timeout, a provider hang, an arm-level
    exception, or a Ctrl-C on this arm is logged and SWALLOWED so the sweep moves
    on to the next arm and still reaches the final analysis. This is the lesson
    from the 2026-06-03 run that hung ~8h on one un-timed-out request: no single
    arm may be able to stall the whole experiment, and partial data must survive.
    """
    async def _capped() -> None:
        await asyncio.wait_for(_arm(**arm_kwargs), timeout=timeout_s)  # type: ignore[arg-type]

    try:
        asyncio.run(_capped())
        return True
    except asyncio.TimeoutError:
        logging.error("arm %s exceeded %.0fs wall-clock — aborting this arm, "
                      "continuing to the next", label, timeout_s)
    except KeyboardInterrupt:
        logging.warning("arm %s interrupted (Ctrl-C) — continuing to analysis", label)
    except Exception as exc:  # one arm's failure must not sink the run
        logging.error("arm %s failed: %s — continuing to the next", label, exc)
    return False


def run(args: argparse.Namespace) -> None:
    stamp = f"grameff_{int(time.time())}"
    # Three arms, same parents (deterministic --limit selection):
    #   tmpl  — pure deterministic template (no model on the planner path)
    #   slot  — template skeleton + model-filled SEMANTIC slots (§10.9 Step 3)
    #   free  — freeform model authoring (no template)
    # slot-fill is the middle tier: it should recover freeform's breach lift while
    # keeping the template's validity / orchestration reliability.
    arms: list[tuple[str, dict[str, object]]] = [
        ("templates", dict(no_templates=False, slot_fill=False, run_id=f"{stamp}_tmpl")),
    ]
    if not args.skip_slot_fill:
        arms.append(
            ("slotfill", dict(no_templates=False, slot_fill=True, run_id=f"{stamp}_slot")),
        )
    arms.append(
        ("freeform", dict(no_templates=True, slot_fill=False, run_id=f"{stamp}_free")),
    )

    completed: list[str] = []
    try:
        for label, kw in arms:
            ok = _run_arm_guarded(
                label, args.arm_timeout,
                limit=args.limit, max_spend=args.max_spend, **kw,
            )
            if ok:
                completed.append(label)
    finally:
        # ALWAYS analyze what landed — even on interrupt or per-arm failure, the
        # paid attempts that did complete are reported instead of lost.
        print(f"\n>>> arms attempted ({len(completed)}/{len(arms)} clean: "
              f"{completed or 'none'}). comparison (tag {stamp}):")
        analyze(argparse.Namespace(tag=stamp))


# Per-arm aggregates from ladder_attempts. Tier-5 entities (base/candidate) are the
# planner-driven ones — the only place templates vs freeform differ.
_METRICS_SQL = """
WITH arm AS (
  SELECT CASE WHEN run_id LIKE '%_tmpl' THEN 'templates'
              WHEN run_id LIKE '%_slot' THEN 'slotfill'
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
    pr = sub.add_parser("run", help="run ALL arms then analyze (SPENDS MONEY)")
    pr.add_argument("--limit", type=int, default=12)
    pr.add_argument("--max-spend", type=float, default=8.0)
    pr.add_argument("--skip-slot-fill", action="store_true",
                    help="run only templates + freeform (the original 2-arm A/B)")
    pr.add_argument("--arm-timeout", type=float, default=3600.0,
                    help="hard wall-clock cap per arm in seconds (default 3600=1h); "
                         "a hung arm is aborted and the sweep continues")
    pr.set_defaults(func=run)
    pa = sub.add_parser("analyze", help="print the comparison from ladder_attempts (FREE)")
    pa.add_argument("--tag", default=None, help="restrict to one A/B (e.g. grameff_1733200000)")
    pa.set_defaults(func=analyze)
    args = p.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
