"""BanditSearcher — the A/B baseline (AutoPT Feature 2). Thompson sampling over the SAME action
space MCTS uses, but flat: a greedy hill-climb from the best prompt so far, no tree. Same seed,
rollouts, actions, and compliance reward as MCTS, so breach-per-dollar compares tree-search vs
bandit on identical footing (mirrors ROGUE's prod Thompson escalation bandit, on the mutation task).
"""

from __future__ import annotations

import random

from typing import Callable, Optional

from .searcher import Action, Budget, RewardFn, RolloutFn, SearchResult, default_reward


class BanditSearcher:
    """Thompson-sampling over mutation actions; applies the sampled action to the best-so-far prompt."""

    name = "bandit"

    def __init__(self, seed: int = 0) -> None:
        self._rng = random.Random(seed)

    async def search(
        self, seed_prompt: str, rollout: RolloutFn, actions: list[Action], budget: Budget,
        reward_fn: Optional[RewardFn] = None, goal_check: Optional[Callable[[str], bool]] = None,
    ) -> SearchResult:
        reward = reward_fn or default_reward  # hill-climb on reward (Feature 3 adds novelty)
        # Beta(α,β) per action; an action is rewarded if it improved the reward or produced a breach.
        alpha = {a.name: 1.0 for a in actions}
        beta = {a.name: 1.0 for a in actions}

        out = await rollout(seed_prompt)
        n_rollouts, cost = 1, out.cost_usd
        best_reward_prompt, best_reward = seed_prompt, reward(out)  # hill-climb anchor
        best_reward_out = out
        best_prompt, best_comp = seed_prompt, out.compliance or 0.0  # reported result (pure compliance)
        n_breaches = 1 if out.breached else 0
        action_use: dict[str, int] = {}
        trace: list = [{"action": "seed", "verdict": out.verdict.value, "compliance": out.compliance}]
        attempts, max_attempts = 0, budget.max_rollouts * 3  # cap so goal-rejects can't loop forever

        while not budget.exhausted(n_rollouts, cost) and attempts < max_attempts:
            attempts += 1
            action = max(actions, key=lambda a: self._rng.betavariate(alpha[a.name], beta[a.name]))
            child_prompt, act_cost = await action.apply(best_reward_prompt, best_reward_out)
            # Goal-preservation gate (opt-in, AdvCodeGen-inspired): a mutation that neutered the
            # attack's goal never reaches the target — skip the rollout (its refusal would be a false
            # negative), charge only the mutation cost, and penalize the action's bandit arm.
            if goal_check is not None and not goal_check(child_prompt):
                cost += act_cost
                beta[action.name] += 1.0
                trace.append({"action": action.name, "kind": action.kind, "skipped": "goal_violation"})
                continue
            out = await rollout(child_prompt)
            n_rollouts += 1
            cost += out.cost_usd + act_cost
            action_use[action.name] = action_use.get(action.name, 0) + 1

            r, comp = reward(out), out.compliance or 0.0
            improved = r > best_reward
            if improved or out.breached:
                alpha[action.name] += 1.0
            else:
                beta[action.name] += 1.0
            if out.breached:
                n_breaches += 1
            if improved:
                best_reward, best_reward_prompt, best_reward_out = r, child_prompt, out
            if comp > best_comp:
                best_comp, best_prompt = comp, child_prompt
            trace.append({"action": action.name, "kind": action.kind,
                          "verdict": out.verdict.value, "compliance": out.compliance})

        return SearchResult(
            searcher=self.name, best_prompt=best_prompt, best_compliance=best_comp,
            n_rollouts=n_rollouts, total_cost_usd=cost, n_breaches=n_breaches,
            breached=n_breaches > 0, action_use=action_use, trace=trace,
        )


__all__ = ["BanditSearcher"]
