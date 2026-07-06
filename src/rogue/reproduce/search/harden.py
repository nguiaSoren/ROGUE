"""Adversarial fix hardening (AutoPT Feature 4) — OPT-IN, report-only.

ROGUE's remediation re-scans the SAME attacks against a patched config ("does the exact attack still
work?"). This asks the stronger question: "can I FIND a variant that defeats the fix?" — run the
search (Feature 2) seeded with the single attack that breached, against the PATCHED config. If a
mutation breaks it, the fix is FRAGILE (it blocked the pattern, not the technique — the classic
obfuscation-flip failure). Report the bypass + a fragility flag. ROGUE never auto-applies or iterates
fixes in prod (ADR-0010); this hands the customer a stronger-fix signal, nothing more.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .searcher import Action, Budget, RewardFn, RolloutFn, Searcher, SearchResult


@dataclass
class HardenCheckResult:
    """Whether a fix survived an adversarial search of the patched config (report-only)."""

    fragile: bool  # the search found a variant that breaches the PATCHED config
    best_compliance_vs_patch: float
    n_rollouts: int
    cost_usd: float
    bypass_prompt: Optional[str] = None  # the strongest variant found (customer's private report only)
    search: Optional[SearchResult] = None

    @property
    def bypass_preview(self) -> Optional[str]:
        if not self.bypass_prompt:
            return None
        return self.bypass_prompt[:120] + "…" if len(self.bypass_prompt) > 120 else self.bypass_prompt

    @property
    def verdict_line(self) -> str:
        if self.fragile:
            return f"FRAGILE — a mutation defeated the fix ({self.n_rollouts} rollouts, ${self.cost_usd:.4f})"
        return f"held — no bypass found in {self.n_rollouts} rollouts (${self.cost_usd:.4f})"


async def harden_check(
    seed_attack: str, patched_rollout: RolloutFn, searcher: Searcher,
    actions: list[Action], budget: Budget, reward_fn: Optional[RewardFn] = None,
) -> HardenCheckResult:
    """Run ``searcher`` against the patched config (``patched_rollout``), seeded with the attack that
    breached. ``fragile`` iff a mutation breaches the patch within budget. Pure measurement — no fix
    regeneration, no side effects (report-only, per ADR-0010)."""
    res = await searcher.search(seed_attack, patched_rollout, actions, budget, reward_fn)
    return HardenCheckResult(
        fragile=res.breached,
        best_compliance_vs_patch=res.best_compliance,
        n_rollouts=res.n_rollouts,
        cost_usd=res.total_cost_usd,
        bypass_prompt=res.best_prompt if res.breached else None,
        search=res,
    )


__all__ = ["harden_check", "HardenCheckResult"]
