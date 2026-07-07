"""A/B harness (AutoPT Feature 2) — run each searcher on the same seeds + target and compare on
BREACH-PER-DOLLAR (the pre-registered win criterion). ``make_rollout`` returns a fresh rollout per
run so per-run cost/state is isolated. Measure-first: promote MCTS over the bandit only if it wins.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, Optional

from .searcher import Action, Budget, RewardFn, RolloutFn, Searcher

MakeRollout = Callable[[str], RolloutFn]  # seed prompt -> a fresh rollout (target+judge) that judges vs that seed's goal
MakeReward = Callable[[], RewardFn]  # a fresh (stateful) reward per run — Feature 3 novelty resets
MakePruner = Callable[[], object]  # a fresh (stateful) PromptPruner per run — Feature 5 fired-set resets


@dataclass
class ABReport:
    per_searcher: dict  # name -> aggregate metrics
    winner: str  # highest breaches_per_dollar
    results: dict  # name -> list[SearchResult]


async def ab_compare(
    searchers: list[Searcher], seeds: list[str], make_rollout: MakeRollout,
    actions: list[Action], budget: Budget, make_reward: Optional[MakeReward] = None,
    concurrency: int = 1, make_pruner: Optional[MakePruner] = None,
) -> ABReport:
    """Run every (seed × searcher) search. ``concurrency`` > 1 runs them concurrently (each search is
    internally sequential — rollouts depend on prior results — so parallelism is across searches),
    bounded by a semaphore. Aggregate metrics are order-independent; the interleaving only affects
    per-run rng reproducibility, not the reported rates. ``make_pruner`` (Feature 5) mints a fresh
    per-search ``PromptPruner`` so pre-fire near-dup skipping can be A/B'd against the current path."""
    results: dict = {s.name: [] for s in searchers}
    sem = asyncio.Semaphore(max(1, concurrency))
    total, done = len(seeds) * len(searchers), 0  # per-search progress (never fly blind on ETA)

    async def _one(seed: str, s: Searcher):
        nonlocal done
        async with sem:
            reward_fn = make_reward() if make_reward is not None else None
            pruner = make_pruner() if make_pruner is not None else None
            res = await s.search(seed, make_rollout(seed), list(actions), budget, reward_fn, pruner=pruner)
        done += 1  # single-thread asyncio: no lock needed
        print(f"  [{done:>3}/{total}] {s.name:7} done  breaches={res.n_breaches:2} any={int(res.breached)} "
              f"cost=${res.total_cost_usd:.4f}  seed={seed[:34]!r}", flush=True)
        return s.name, res

    jobs = [_one(seed, s) for seed in seeds for s in searchers]
    if concurrency > 1:
        for name, res in await asyncio.gather(*jobs):
            results[name].append(res)
    else:
        for job in jobs:
            name, res = await job
            results[name].append(res)

    agg: dict = {}
    for name, rs in results.items():
        breaches = sum(r.n_breaches for r in rs)
        cost = sum(r.total_cost_usd for r in rs)
        pruned = sum(getattr(r, "n_pruned", 0) for r in rs)
        agg[name] = {
            "n_seeds": len(rs), "breaches": breaches, "cost_usd": round(cost, 6),
            "breaches_per_dollar": round(breaches / cost, 3) if cost > 0 else float(breaches),
            "mean_best_compliance": round(sum(r.best_compliance for r in rs) / len(rs), 3) if rs else 0.0,
            "any_breach_rate": round(sum(1 for r in rs if r.breached) / len(rs), 3) if rs else 0.0,
            "mean_rollouts": round(sum(r.n_rollouts for r in rs) / len(rs), 1) if rs else 0.0,
            "pruned": pruned,  # Feature 5: near-dup rollouts skipped (0 when pruning off)
            "prune_rate": round(pruned / (pruned + sum(r.n_rollouts for r in rs)), 3) if rs and pruned else 0.0,
        }
    winner = max(agg, key=lambda n: agg[n]["breaches_per_dollar"]) if agg else ""
    return ABReport(per_searcher=agg, winner=winner, results=results)


__all__ = ["ab_compare", "ABReport", "MakeRollout", "MakePruner"]
