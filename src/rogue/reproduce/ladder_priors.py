"""§10.10 Step 1 — greedy ladder reordering from breach telemetry.

The escalation ladder (`synthesize_escalations.run_escalation_ladder_one`) tries
~18 strategies across 5 tiers in a **fixed, hand-coded order** and short-circuits
on first breach. A fully-resisting primitive runs *all* of them (~181 LLM calls /
~13 min observed) because the order has no idea which strategy is likely to win.

This is the **first, smallest** increment of the §10.10 break-bandit: not online
posterior sampling yet — just *sort the tiers by historical breach rate* so the
likely winner is tried early (breach on attempt 2, not 15). It changes **only the
evaluation priority**; the execution loop, lifecycle, and persistence are untouched.
The reorder happens at the call site on the tier lists *before* the ladder iterates,
so this module never reaches into ladder execution.

Why **Laplace smoothing** is load-bearing (not cosmetic): a self-growing repertoire
must keep newly-harvested strategies reachable. Raw breach rate would make the
image-renderer tier (which historically wins most) monopolize the front of the
ladder forever (rich-get-richer) and drive every unseen strategy's rate to 0 →
never tried → never any evidence → dead on arrival. Add-1 smoothing gives an unseen
strategy a prior of ALPHA/(ALPHA+BETA)=0.5 — above most *proven-weak* incumbents —
so **cold-start survivability** is structural, not hoped-for. The existing
candidate-attempt quota is the second floor (it reserves exploration regardless of
order); `discovery` mode's optimism bonus is the third.

Two modes (the spec's canonical/discovery split — protects §10.3 reproducibility):
  - ``canonical``  — deterministic argmax: sort by smoothed breach rate, original
    order breaks ties. Reproducible given a telemetry snapshot. The exploit order.
  - ``discovery``  — optimism in the face of uncertainty: add a bonus that decays
    with trials, so under-tried strategies are front-loaded. The explore order.
  - ``fixed``      — identity (the hand-coded order); the escape hatch / cold start.

Keying: reward rows (`ladder_attempts.entity_id`) store the FULL label
(``image:mml:wr`` / ``coj:delete_then_insert`` / a Tier-5 strategy id). Tier lists
hold bare elements (``mml:wr``), so callers pass the tier's ``label_prefix``
(``"image:"``) and ordering reconstructs the label to look it up.

Spec: ROGUE_PLAN.md §10.10 ("the greedy 'sort by historical breach rate' version is
just the first commit of this, not a different thing"). The full contextual Thompson
bandit (posterior sampling, hierarchical family×model priors, persisted arm-state)
is the deliberate NEXT increment, delayed until the telemetry substrate matures.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

__all__ = [
    "BreachStat",
    "strategy_breach_rates",
    "order_by_prior",
    "ladder_order_mode",
    "LADDER_ORDER_ENV",
]

# Add-1 (Laplace) smoothing on a Beta(ALPHA, BETA) prior. ALPHA=BETA=1 ⇒ an unseen
# strategy's prior breach rate is 0.5 — optimistic enough to be tried ahead of
# proven-weak incumbents, the cold-start survivability guarantee.
ALPHA = 1.0
BETA = 1.0

# Discovery-mode optimism weight: bonus = C / sqrt(trials + 1), decaying with
# evidence. At trials=0 the bonus is C (front-loads the unseen); it →0 as a strategy
# accrues trials, so discovery converges toward the canonical exploit order.
DISCOVERY_C = float(os.environ.get("ROGUE_LADDER_DISCOVERY_C", "0.5"))

# Mode selector. Default ``canonical`` — the deterministic greedy reorder is the
# operative increment; ``fixed`` restores the legacy hand-coded order for ablation.
LADDER_ORDER_ENV = "ROGUE_LADDER_ORDER"
_VALID_MODES = ("canonical", "discovery", "fixed")


@dataclass(frozen=True)
class BreachStat:
    """Per-strategy reward summary over *valid* ladder trials (breach/no_breach;
    orchestration failures — refused/render_error — are excluded so the prior
    measures attack efficacy, not orchestration health)."""

    label: str
    breaches: int
    trials: int

    @property
    def smoothed_rate(self) -> float:
        """Laplace-smoothed breach rate — the canonical (exploit) score."""
        return (self.breaches + ALPHA) / (self.trials + ALPHA + BETA)

    def discovery_score(self, c: float = DISCOVERY_C) -> float:
        """Smoothed rate + an optimism bonus that decays with trials (explore)."""
        return self.smoothed_rate + c / math.sqrt(self.trials + 1)


def ladder_order_mode() -> str:
    """Resolve the ordering mode from ``ROGUE_LADDER_ORDER`` (default canonical)."""
    mode = os.environ.get(LADDER_ORDER_ENV, "canonical").strip().lower()
    return mode if mode in _VALID_MODES else "canonical"


def strategy_breach_rates(
    session: "Session", *, config_id: str | None = None,
) -> dict[str, BreachStat]:
    """Aggregate ``ladder_attempts`` into per-label breach stats (keyed by the full
    ``entity_id`` label). ``config_id`` optionally scopes to one deployment config
    (the per-context prior the future contextual bandit will key on); ``None`` =
    pooled across all configs. Only valid trials count toward ``trials``.
    """
    from sqlalchemy import case, func

    from rogue.db.models import LadderAttempt

    valid = LadderAttempt.outcome.in_(("breach", "no_breach"))
    q = (
        session.query(
            LadderAttempt.entity_id.label("label"),
            func.sum(case((LadderAttempt.breached, 1), else_=0)).label("breaches"),
            func.sum(case((valid, 1), else_=0)).label("trials"),
        )
        .group_by(LadderAttempt.entity_id)
    )
    if config_id is not None:
        # Winner rows carry config_id; for a per-config prior, scope to those + the
        # global rows would over-count, so restrict to this config's winner evidence.
        q = q.filter(LadderAttempt.config_id == config_id)
    out: dict[str, BreachStat] = {}
    for row in q.all():
        if row.label is None:
            continue
        out[row.label] = BreachStat(
            label=row.label,
            breaches=int(row.breaches or 0),
            trials=int(row.trials or 0),
        )
    return out


def order_by_prior(
    elements: "tuple[str, ...] | list[str]",
    rates: dict[str, BreachStat],
    *,
    mode: str | None = None,
    label_prefix: str = "",
) -> tuple[str, ...]:
    """Reorder ``elements`` by their breach prior, most-promising first.

    Each element ``e`` is looked up as ``f"{label_prefix}{e}"`` in ``rates``; an
    element with no telemetry gets a fresh ``BreachStat(0, 0)`` (smoothed rate 0.5),
    so unseen strategies sort ahead of proven-weak ones. The sort is **stable** with
    the original position as the tiebreak, so equal scores preserve the hand-coded
    order — ``fixed`` mode and all-unseen cold starts are exactly the legacy order.
    """
    mode = mode or ladder_order_mode()
    seq = list(elements)
    if mode == "fixed":
        return tuple(seq)

    def _stat(e: str) -> BreachStat:
        return rates.get(f"{label_prefix}{e}", BreachStat(f"{label_prefix}{e}", 0, 0))

    def _score(e: str) -> float:
        s = _stat(e)
        return s.discovery_score() if mode == "discovery" else s.smoothed_rate

    # Negate score for descending; original index keeps the sort stable/deterministic.
    return tuple(
        sorted(seq, key=lambda e: (-_score(e), seq.index(e)))
    )
