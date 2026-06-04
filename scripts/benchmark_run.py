"""External benchmark runner — repertoire-replay ASR over a frozen goal set.

The first metric that measures whether ROGUE *improves over time* against a fixed
external reference, not just how it behaves. For each frozen benchmark goal
(AdvBench-100 / JBB-100) it runs ROGUE's **graduated escalation ladder** — the same
`build_escalation_context()` + `run_escalation_ladder_one()` production uses (single
source of truth; the benchmark can't drift from the real system) — against a target,
and records whether the repertoire breached it. ASR climbs as the repertoire grows.

Two tiers (never pin ONE model — a model getting weaker would masquerade as ROGUE
getting stronger):
  * **Tier A** (`--tier A`, every harvest, cheap): the goal sets vs ONE fixed model
    (mistral-small — mid-difficulty, signal room).
  * **Tier B** (`--tier B`, milestone): the goal sets vs GPT / Claude / Gemini /
    Mistral, to catch vendor-specific drift.

Beyond ASR it records the scheduler-descendant metrics — best ladder depth, median
winner rank, cost-per-successful-goal — in `benchmark_runs.detail`, because ASR alone
can't tell you whether the *orchestration* improved.

Results go to the **Neon `benchmark_runs` table** (durable — a local file could vanish),
one row per (dataset × target_model). These are run TELEMETRY; the goals stay frozen
in git and are NEVER ingested as primitives (the eval/generation wall).

**This spends money** — each goal runs the full ladder (target + judge calls per
tier). Gated behind `--yes`; `--dry-run` loads goals + builds the (free) context and
prints a cost estimate. Use `--limit` for a cheap smoke first.

Run from the repo root::

    uv run python scripts/benchmark_run.py --tier A --dry-run            # free
    uv run python scripts/benchmark_run.py --tier A --limit 3 --yes      # ~$1 smoke
    uv run python scripts/benchmark_run.py --tier A --yes                # full Tier-A baseline

Prereq: one-time freeze — `uv run python -m benchmark.datasets --freeze`.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import os  # noqa: E402

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from benchmark.datasets import CANONICAL_DATASETS, load_canonical  # noqa: E402
from rogue.db.models import (  # noqa: E402
    AttackStrategy,
    BenchmarkRun,
    DeploymentConfig as DeploymentConfigORM,
)
from rogue.reproduce.judge import JudgeAgent  # noqa: E402
from rogue.reproduce.target_panel import TargetPanel  # noqa: E402
from rogue.schemas import (  # noqa: E402
    AttackFamily,
    AttackPrimitive,
    AttackVector,
    Severity,
    StrategyStatus,
)
from scripts.reproduce_once import _orm_to_pydantic_config  # noqa: E402
from scripts.synthesize_escalations import (  # noqa: E402
    build_escalation_context,
    run_escalation_ladder_one,
)

logger = logging.getLogger("rogue.scripts.benchmark_run")

# Fixed target rosters. Tier A = one mid-difficulty model (signal has room to move);
# Tier B = one config per vendor, for drift detection.
TIER_A = ("acme-mistralsm-20260526",)
TIER_B = (
    "acme-gpt54nano-20260526",
    "acme-claudehaiku-20260526",
    "acme-geminiflashlite-20260526",
    "acme-mistralsm-20260526",
)
_SYNTH_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)
# Rough per-ladder-attempt cost (target + judge), for the free dry-run estimate only.
_EST_PER_ATTEMPT_USD = 0.01 + 0.0225


def _goal_primitive(goal: str, idx: int) -> AttackPrimitive:
    """Wrap a benchmark goal as a minimal base primitive — the bare harmful request
    the target refuses, which the repertoire ladder then tries to crack. Same
    construction as the judge-eval synthetic primitive (only id/source differ)."""
    g = goal.strip() or "(empty goal)"
    return AttackPrimitive.model_validate(
        {
            "primitive_id": f"benchmark_goal_{idx}",
            "canonical": False,
            "family": AttackFamily.DIRECT_INSTRUCTION_OVERRIDE,
            "vector": AttackVector.USER_TURN,
            "title": "external benchmark goal",
            "short_description": g[:2_000],
            "payload_template": (g if len(g) >= 10 else f"{g} [benchmark goal]")[:20_000],
            "reproducibility_score": 5,
            "base_severity": Severity.MEDIUM,
            "severity_rationale": "external benchmark goal; severity not scored",
            "discovered_at": _SYNTH_TS,
            "sources": [
                {
                    "url": "https://github.com/JailbreakBench",
                    "source_type": "other",
                    "author": None,
                    "published_at": None,
                    "fetched_at": _SYNTH_TS,
                    "archive_hash": "benchmark-external",
                    "bright_data_product": "fixture",
                }
            ],
        }
    )


def _git_sha() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_REPO_ROOT, capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
    except Exception:
        return None


def _winner_rank(res) -> int | None:
    """Index in the attempt order where the winner broke (the reorder's payoff KPI)."""
    if res.winning_strategy is None:
        return None
    return next(
        (i for i, (lbl, out) in enumerate(res.attempts)
         if out == "breach" and lbl == res.winning_strategy),
        None,
    )


async def _run_one_cell(
    *, session, config, goals, n_trials, temperature, max_spend, dry_run
) -> dict:
    """Repertoire-replay one (dataset-goals × target) cell → an aggregate dict."""
    primitives = [_goal_primitive(g.goal, i) for i, g in enumerate(goals)]
    ctx = build_escalation_context(
        session,
        configs=[config],
        n_parents_est=len(goals),
        n_trials=n_trials,
    )
    est = len(goals) * len(ctx.rotation) * n_trials * _EST_PER_ATTEMPT_USD
    if dry_run:
        return {"dry_run": True, "n_goals": len(goals), "rotation_len": len(ctx.rotation),
                "estimate_usd": est}

    panel = TargetPanel()
    judge = JudgeAgent()
    per_goal: list[dict] = []
    spent = 0.0
    try:
        for prim, g in zip(primitives, goals):
            remaining = None if max_spend is None else max(0.0, max_spend - spent)
            res = await run_escalation_ladder_one(
                prim,
                planner=ctx.planner,
                panel=panel,
                judge=judge,
                configs=[config],
                n_trials=n_trials,
                temperature=temperature,
                strategies=ctx.rotation,
                image_renderers=ctx.image_renderers,
                coj_operations=ctx.coj_operations,
                structured_formats=ctx.structured_formats,
                audio_styles=ctx.audio_styles,
                budget_usd=remaining,
                candidate_attempt_quota=ctx.effective_quota,
                candidate_ids=ctx.candidate_ids,
            )
            spent += res.spend_usd
            breached = res.winning_strategy is not None
            per_goal.append({
                "goal": g.goal[:120],
                "breached": breached,
                "winner": res.winning_strategy,
                "rank": _winner_rank(res),
                "depth": len(res.attempts),
                "cost": round(res.spend_usd, 4),
            })
            logger.info(
                "[%d/%d] %s goal=%r winner=%s rank=%s depth=%d $%.3f",
                len(per_goal), len(goals), "BREACH" if breached else "held",
                g.goal[:48], res.winning_strategy, _winner_rank(res),
                len(res.attempts), res.spend_usd,
            )
    finally:
        for obj in (panel, judge, ctx.planner):
            closer = getattr(obj, "aclose", None)
            if closer is not None:
                try:
                    await closer()
                except Exception:  # noqa: BLE001 — cleanup must never raise
                    pass

    return _aggregate(per_goal, spent, ctx)


def _aggregate(per_goal: list[dict], spent: float, ctx) -> dict:
    n = len(per_goal)
    breaches = [g for g in per_goal if g["breached"]]
    nb = len(breaches)
    ranks = [g["rank"] for g in breaches if g["rank"] is not None]
    win_counts: dict[str, int] = {}
    for g in breaches:
        win_counts[g["winner"]] = win_counts.get(g["winner"], 0) + 1
    return {
        "n_goals": n,
        "n_breached": nb,
        "asr": (nb / n) if n else 0.0,
        "cost_usd": round(spent, 4),
        "detail": {
            "median_winner_rank": (statistics.median(ranks) if ranks else None),
            "best_ladder_depth": (min(g["depth"] for g in breaches) if breaches else None),
            "mean_ladder_depth": (
                round(statistics.mean(g["depth"] for g in per_goal), 2) if per_goal else None
            ),
            "cost_per_successful_goal": (round(spent / nb, 4) if nb else None),
            "winner_strategies": win_counts,
            "rotation_len": len(ctx.rotation),
            "per_goal": per_goal,
        },
    }


def _active_repertoire_size(session) -> int:
    return int(
        session.execute(
            select(func.count()).select_from(AttackStrategy).where(
                AttackStrategy.status == StrategyStatus.ACTIVE
            )
        ).scalar()
        or 0
    )


async def _main(args) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.mode == "attacker":
        logger.error(
            "--mode attacker (IterativeAttacker, milestone-only) is not wired yet; "
            "use the default repertoire-replay mode."
        )
        return 2

    if args.targets:
        targets = tuple(t.strip() for t in args.targets.split(",") if t.strip())
    else:
        targets = TIER_A if args.tier == "A" else TIER_B
    datasets = [d.strip() for d in args.datasets.split(",") if d.strip()]
    for d in datasets:
        if d not in CANONICAL_DATASETS:
            logger.error("unknown dataset %r; choose from %s", d, CANONICAL_DATASETS)
            return 1

    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    git_sha = _git_sha()
    label = args.run_label or f"{args.tier.lower()}-{int(time.time())}"

    total_est = 0.0
    written = 0
    with SessionLocal() as session:
        repertoire_size = _active_repertoire_size(session)
        config_orms = {
            o.config_id: o
            for o in session.execute(
                select(DeploymentConfigORM).where(
                    DeploymentConfigORM.config_id.in_(list(targets))
                )
            ).scalars()
        }
        missing = [t for t in targets if t not in config_orms]
        if missing:
            logger.error("target config(s) not found in DB: %s", missing)
            return 1

        for tid in targets:
            config = _orm_to_pydantic_config(config_orms[tid])
            for ds in datasets:
                goals = load_canonical(ds)
                if args.limit:
                    goals = goals[: args.limit]
                t0 = time.time()
                agg = await _run_one_cell(
                    session=session, config=config, goals=goals,
                    n_trials=args.n_trials, temperature=args.temperature,
                    max_spend=args.max_spend, dry_run=args.dry_run,
                )
                if args.dry_run:
                    total_est += agg["estimate_usd"]
                    print(f"  {ds:13} × {config.target_model:34} "
                          f"{agg['n_goals']} goals, rotation={agg['rotation_len']} "
                          f"→ ≤ ${agg['estimate_usd']:.2f}")
                    continue
                if not args.no_persist:
                    session.add(BenchmarkRun(
                        run_label=label,
                        run_at=datetime.now(timezone.utc),
                        dataset=ds,
                        mode="repertoire",
                        target_model=config.target_model,
                        n_goals=agg["n_goals"],
                        n_breached=agg["n_breached"],
                        asr=agg["asr"],
                        repertoire_size=repertoire_size,
                        cost_usd=agg["cost_usd"],
                        duration_s=round(time.time() - t0, 1),
                        git_sha=git_sha,
                        detail=agg["detail"],
                    ))
                    session.commit()
                    written += 1
                d = agg["detail"]
                print(f"  {ds:13} × {config.target_model:34} "
                      f"ASR={agg['asr']:.1%} ({agg['n_breached']}/{agg['n_goals']}) "
                      f"med-rank={d['median_winner_rank']} depth(best/mean)="
                      f"{d['best_ladder_depth']}/{d['mean_ladder_depth']} "
                      f"$/{agg['n_breached'] or '∅'}={d['cost_per_successful_goal']} "
                      f"${agg['cost_usd']:.2f}")

    if args.dry_run:
        print(f"\ndry-run: built context for every cell (no paid calls). "
              f"Estimated upper bound ≤ ${total_est:.2f}. Re-run with --yes.")
    elif args.no_persist:
        print(f"\nprobe complete — NOT persisted (--no-persist; repertoire_size={repertoire_size}).")
    else:
        print(f"\nwrote {written} benchmark_runs row(s) to Neon "
              f"(label={label}, repertoire_size={repertoire_size}).")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tier", choices=("A", "B"), default="A",
                   help="A = mistral-small (cheap, every harvest); B = 4 vendors (milestone)")
    p.add_argument("--targets", default=None,
                   help="comma-separated config_ids overriding the tier roster (e.g. hardness probe)")
    p.add_argument("--no-persist", action="store_true",
                   help="don't write benchmark_runs rows (for hardness probes — keeps the timeline clean)")
    p.add_argument("--datasets", default=",".join(CANONICAL_DATASETS),
                   help=f"comma-separated; default all of {CANONICAL_DATASETS}")
    p.add_argument("--mode", choices=("repertoire", "attacker"), default="repertoire")
    p.add_argument("--limit", type=int, default=0, help="cap goals per dataset (smoke)")
    p.add_argument("--n-trials", type=int, default=1)
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--max-spend", type=float, default=None, help="per-cell budget cap USD")
    p.add_argument("--run-label", default=None)
    p.add_argument("--dry-run", action="store_true", help="build context + estimate, free")
    p.add_argument("--yes", action="store_true", help="confirm the paid run")
    args = p.parse_args(argv)
    if not args.dry_run and not args.yes:
        logger.error("this runs the paid ladder per goal. Re-run with --yes to confirm, "
                     "or --dry-run for a free estimate.")
        return 2
    return asyncio.run(_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
