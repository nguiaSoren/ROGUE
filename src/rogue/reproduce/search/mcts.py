"""MCTSSearcher (AutoPT Feature 2) — PAIR generalized from a line to a tree, valued by the
continuous compliance signal (Feature 1). Node = a prompt; edge = a mutation/refine action; each
expansion is evaluated by a real rollout (target+judge), then backpropagated. UCB1 selection deepens
promising branches; the mixed action set (cheap mutations + LLM refine) is the expansion space.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional

from .searcher import Action, Budget, RewardFn, RolloutFn, RolloutOutcome, SearchResult, default_reward


@dataclass
class _Node:
    prompt: str
    parent: Optional["_Node"] = None
    outcome: Optional[RolloutOutcome] = None  # this node's own rollout
    children: list = field(default_factory=list)
    untried: list = field(default_factory=list)  # actions not yet expanded from here
    visits: int = 0
    value_sum: float = 0.0

    @property
    def value(self) -> float:
        return self.value_sum / self.visits if self.visits else 0.0


class MCTSSearcher:
    """Monte Carlo Tree Search over single-prompt mutations, reward = compliance."""

    name = "mcts"

    def __init__(self, exploration: float = 1.4, seed: int = 0) -> None:
        self.c = exploration
        self._rng = random.Random(seed)

    def _ucb(self, child: _Node, parent: _Node) -> float:
        return child.value + self.c * math.sqrt(math.log(parent.visits + 1) / child.visits)

    def _select(self, root: _Node) -> _Node:
        """Descend from root by UCB1 to the shallowest node that still has an untried action."""
        node = root
        while not node.untried and node.children:
            node = max(node.children, key=lambda ch: self._ucb(ch, node))
        return node

    def _backprop(self, node: Optional[_Node], value: float) -> None:
        while node is not None:
            node.visits += 1
            node.value_sum += value
            node = node.parent

    async def search(
        self, seed_prompt: str, rollout: RolloutFn, actions: list[Action], budget: Budget,
        reward_fn: Optional[RewardFn] = None,
    ) -> SearchResult:
        reward = reward_fn or default_reward  # value the tree climbs (Feature 3 adds novelty)
        root = _Node(prompt=seed_prompt, untried=list(actions))
        out = await rollout(seed_prompt)
        root.outcome = out
        self._backprop(root, reward(out))

        n_rollouts, cost = 1, out.cost_usd
        best_prompt, best_comp = seed_prompt, out.compliance or 0.0
        n_breaches = 1 if out.breached else 0
        action_use: dict[str, int] = {}
        trace: list = [{"depth": 0, "action": "seed", "verdict": out.verdict.value, "compliance": out.compliance}]

        while not budget.exhausted(n_rollouts, cost):
            node = self._select(root)
            if not node.untried:
                break  # tree fully expanded within budget (safety net; rare)
            action = node.untried.pop(self._rng.randrange(len(node.untried)))
            child_prompt, act_cost = await action.apply(node.prompt, node.outcome)
            out = await rollout(child_prompt)
            n_rollouts += 1
            cost += out.cost_usd + act_cost
            action_use[action.name] = action_use.get(action.name, 0) + 1

            child = _Node(prompt=child_prompt, parent=node, outcome=out, untried=list(actions))
            node.children.append(child)
            self._backprop(child, reward(out))  # dynamics use reward; best_compliance stays pure

            if out.breached:
                n_breaches += 1
            comp = out.compliance or 0.0
            if comp > best_comp:
                best_comp, best_prompt = comp, child_prompt
            trace.append({"action": action.name, "kind": action.kind,
                          "verdict": out.verdict.value, "compliance": out.compliance})

        return SearchResult(
            searcher=self.name, best_prompt=best_prompt, best_compliance=best_comp,
            n_rollouts=n_rollouts, total_cost_usd=cost, n_breaches=n_breaches,
            breached=n_breaches > 0, action_use=action_use, trace=trace,
        )


__all__ = ["MCTSSearcher"]
