"""Live orchestration entry points (AutoPT F1-F4) — the opt-in seams a flag-gated caller invokes to
run the search subsystem against real targets. NOT the default path: measure-first, the bandit stays
prod-default until the paid A/B shows MCTS wins (RESEARCH_TODO). Composes the live adapters + the
searcher into two callables the escalation and remediation paths can invoke behind a flag.
"""

from __future__ import annotations

from typing import Optional

from .actions import cheap_mutation_actions
from .coverage import NoveltyReward
from .goal_preservation import make_goal_check
from .harden import HardenCheckResult, harden_check
from .live import make_refine_action, make_rollout
from .mcts import MCTSSearcher
from .searcher import Budget, Searcher, SearchResult


async def search_escalate(
    primitive, config, panel, judge, *,
    searcher: Optional[Searcher] = None, budget: Optional[Budget] = None,
    refine_attacker=None, embed_fn=None, lam: float = 0.0, seed_prompt: Optional[str] = None,
    enforce_goal: bool = False, goal_judge_fn=None,
) -> SearchResult:
    """Opt-in escalation: run the search on a (typically refused) primitive against a LIVE config to
    find a breaking mutation. The alternative to the current escalation — a caller enables it behind a
    flag; it is not the default until the A/B validates MCTS. ``refine_attacker`` adds the PAIR
    LLM-refine action; ``embed_fn``+``lam`` add the coverage/novelty reward. ``enforce_goal`` (AdvCodeGen-
    inspired) gates mutations through the goal-preservation validator so a neutered variant never
    reaches the target (its refusal would be a false negative); ``goal_judge_fn`` supplies the
    authoritative LLM check, else it falls back to structural + embedding/lexical signals."""
    searcher = searcher or MCTSSearcher()
    budget = budget or Budget(max_rollouts=30)
    rollout = make_rollout(panel, judge, config, primitive)
    actions = cheap_mutation_actions()
    if refine_attacker is not None:
        actions.append(make_refine_action(refine_attacker, goal=primitive.short_description))
    reward_fn = NoveltyReward(embed_fn, lam) if (embed_fn is not None and lam > 0) else None
    goal_check = make_goal_check(
        primitive.payload_template, primitive.short_description, embed_fn=embed_fn, judge_fn=goal_judge_fn,
    ) if enforce_goal else None
    return await searcher.search(
        seed_prompt or primitive.payload_template, rollout, actions, budget, reward_fn, goal_check,
    )


async def harden_from_remediation(
    breaching_payload: str, patched_config, panel, judge, primitive, *,
    searcher: Optional[Searcher] = None, budget: Optional[Budget] = None,
) -> HardenCheckResult:
    """Feature 4 (opt-in, report-only): pressure-test a fix by searching the PATCHED config for a
    bypass, seeded with the attack that breached. A caller in the remediation path invokes it after a
    fix mutates the config; a ``fragile`` result flags a fix that blocks the pattern, not the technique."""
    searcher = searcher or MCTSSearcher()
    budget = budget or Budget(max_rollouts=20)
    patched_rollout = make_rollout(panel, judge, patched_config, primitive)
    return await harden_check(breaching_payload, patched_rollout, searcher, cheap_mutation_actions(), budget)


__all__ = ["search_escalate", "harden_from_remediation"]
