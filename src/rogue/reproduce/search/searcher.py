"""The pluggable ``Searcher`` seam (AutoPT Feature 2) — bandit / MCTS / (future) hierarchical are
interchangeable strategies the A/B harness swaps. Each searches the single-prompt mutation space,
scored by the continuous compliance signal (Feature 1); the A/B metric is breach-per-dollar.

A rollout = run one prompt against target+judge → a verdict/confidence → a compliance value. An
Action mutates a prompt into a child (cheap deterministic op OR an LLM refine — the mixed set).
Searchers differ only in HOW they choose and organize expansions (tree+UCB1 vs flat+Thompson), so
the comparison is on identical footing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional, Protocol

from rogue.schemas.breach_result import BREACH_VERDICTS, JudgeVerdict

from .compliance import compliance_score


@dataclass
class RolloutOutcome:
    """The result of running one prompt against target+judge (the search's evaluation unit)."""

    verdict: JudgeVerdict
    confidence: float = 1.0
    response: str = ""
    cost_usd: float = 0.0

    @property
    def compliance(self) -> Optional[float]:
        """Continuous compliance (Feature 1), or None on ERROR."""
        return compliance_score(self.verdict, self.confidence)

    @property
    def breached(self) -> bool:
        return self.verdict in BREACH_VERDICTS


# run one prompt → outcome (owns the target + judge calls + their cost)
RolloutFn = Callable[[str], Awaitable[RolloutOutcome]]

# the value a searcher climbs (backprop / UCB / hill-climb). Default = compliance only; Feature 3
# swaps in a stateful reward that adds λ·novelty. Kept separate from the REPORTED best_compliance,
# which stays pure compliance (novelty is a search aid, not a result metric).
RewardFn = Callable[[RolloutOutcome], float]


def default_reward(outcome: RolloutOutcome) -> float:
    return outcome.compliance or 0.0


@dataclass
class Action:
    """One expansion edge: mutate a prompt into a child (+ its own cost). ``kind`` distinguishes a
    cheap deterministic mutation from an LLM refine so cost/mix can be measured. ``apply`` receives
    the parent node's rollout outcome so a PAIR-style refine can condition on how the target last
    behaved (its response + compliance); cheap mutations ignore it."""

    name: str
    apply: Callable[[str, "Optional[RolloutOutcome]"], Awaitable[tuple[str, float]]]
    kind: str = "mutation"  # "mutation" (cheap, ~$0) | "refine" (LLM, real cost)


@dataclass
class Budget:
    """A rollout cap and/or a hard cost ceiling. A searcher stops at whichever binds first."""

    max_rollouts: int = 30
    max_cost_usd: Optional[float] = None

    def exhausted(self, n_rollouts: int, cost_usd: float) -> bool:
        if n_rollouts >= self.max_rollouts:
            return True
        return self.max_cost_usd is not None and cost_usd >= self.max_cost_usd


@dataclass
class SearchResult:
    """One searcher's outcome on one seed — the unit the A/B harness compares."""

    searcher: str
    best_prompt: str
    best_compliance: float
    n_rollouts: int
    total_cost_usd: float
    n_breaches: int
    breached: bool
    action_use: dict = field(default_factory=dict)  # action.name -> times applied
    trace: list = field(default_factory=list)

    @property
    def breaches_per_dollar(self) -> float:
        """The A/B win metric: breaches found per unit spend (rollouts with a breach verdict)."""
        return self.n_breaches / self.total_cost_usd if self.total_cost_usd > 0 else float(self.n_breaches)


class Searcher(Protocol):
    """Interchangeable escalation search. Same (seed, rollout, actions, budget) → a comparable result."""

    name: str

    async def search(
        self, seed_prompt: str, rollout: RolloutFn, actions: list[Action], budget: Budget,
        reward_fn: Optional[RewardFn] = None, goal_check: Optional[Callable[[str], bool]] = None,
    ) -> SearchResult: ...


__all__ = [
    "RolloutOutcome", "RolloutFn", "RewardFn", "default_reward",
    "Action", "Budget", "SearchResult", "Searcher",
]
