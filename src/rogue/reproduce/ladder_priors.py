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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

__all__ = [
    "BreachStat",
    "StrategyValue",
    "strategy_breach_rates",
    "strategy_values",
    "order_by_prior",
    "order_by_value",
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
# operative increment; ``fixed`` restores the legacy hand-coded order for ablation;
# ``viability`` is §10.10 Phase 2 (the EV-weighted heuristic scheduler).
LADDER_ORDER_ENV = "ROGUE_LADDER_ORDER"
_VALID_MODES = ("canonical", "discovery", "viability", "fixed")

# §10.10 Phase 2 — viability-aware allocation weights. The scheduler stops asking
# "what breaches most?" and asks "what is worth spending evaluation budget on now?"
# A high raw breach rate is worthless if the strategy can't actually be evaluated
# (planner refusals / render errors → low validity) or if the system has locked onto
# it (no freshness). FRESHNESS_TAU_DAYS is the staleness horizon at which a strategy
# earns full freshness boost; the *_WEIGHT terms scale each ≥1 multiplicative bonus.
FRESHNESS_TAU_DAYS = float(os.environ.get("ROGUE_LADDER_FRESHNESS_TAU_DAYS", "14"))
FRESHNESS_WEIGHT = float(os.environ.get("ROGUE_LADDER_FRESHNESS_WEIGHT", "0.5"))
EXPLORE_WEIGHT = float(os.environ.get("ROGUE_LADDER_EXPLORE_WEIGHT", "0.5"))


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


@dataclass(frozen=True)
class StrategyValue:
    """§10.10 Phase 2 — the full viability record for one strategy, superset of
    ``BreachStat``. Adds the two telemetry axes the greedy reorder ignored:

      - ``attempts_total`` (all ladder rows incl. orchestration failures) vs
        ``valid_trials`` (breach/no_breach only) → **validity_rate**, i.e. how often
        an attempt was actually a real evaluation rather than a planner refusal /
        render error. This is the *viability* signal: a high breach rate is worthless
        if the strategy can rarely be evaluated.
      - ``last_tried_at`` → **freshness**, so the scheduler doesn't lock onto a fixed
        set forever (anti-stagnation).

    The expected-value score multiplies effectiveness × viability × two ≥1 bonuses
    (freshness, exploration). Multiplicative on purpose: a strategy must be BOTH
    effective AND viable to score high — a 0.9-breach / 0.1-validity strategy
    (breaks when it runs, but almost never runs) correctly scores *below* a
    0.4-breach / 0.9-validity one. Laplace smoothing keeps every factor in (0, 1] so
    nothing catastrophically zeroes and the unseen get a fair 0.5 prior.
    """

    label: str
    breaches: int
    valid_trials: int
    attempts_total: int
    last_tried_at: datetime | None = None

    @property
    def breach_rate(self) -> float:
        """Laplace-smoothed breach rate over VALID trials (effectiveness)."""
        return (self.breaches + ALPHA) / (self.valid_trials + ALPHA + BETA)

    @property
    def validity_rate(self) -> float:
        """Laplace-smoothed fraction of attempts that were real evaluations
        (planner/render **viability**). Low ⇒ mostly refusals/render-errors."""
        return (self.valid_trials + ALPHA) / (self.attempts_total + ALPHA + BETA)

    def freshness_bonus(self, now: datetime) -> float:
        """≥1 multiplier rising with staleness (anti-lock-in). An unseen strategy
        (no ``last_tried_at``) is treated as maximally stale → full boost, so it is
        not buried by long-incumbent winners."""
        if self.last_tried_at is None:
            days = FRESHNESS_TAU_DAYS
        else:
            last = self.last_tried_at
            ref = now
            # Tolerate naive/aware mismatch defensively (telemetry is UTC-aware).
            if last.tzinfo is None and ref.tzinfo is not None:
                ref = ref.replace(tzinfo=None)
            days = max(0.0, (ref - last).total_seconds() / 86_400.0)
        return 1.0 + FRESHNESS_WEIGHT * min(days / FRESHNESS_TAU_DAYS, 1.0)

    @property
    def exploration_bonus(self) -> float:
        """≥1 multiplier decaying with evidence (cold-start protection) — the same
        optimism idea as ``discovery`` mode, here a factor: 1 + C/√(valid+1)."""
        return 1.0 + EXPLORE_WEIGHT / math.sqrt(self.valid_trials + 1)

    def value_score(self, now: datetime) -> float:
        """Expected-value allocation score: effectiveness × viability × freshness ×
        exploration. The §10.10 Phase-2 answer to "what is worth budget right now?"."""
        return (
            self.breach_rate
            * self.validity_rate
            * self.freshness_bonus(now)
            * self.exploration_bonus
        )


def ladder_order_mode() -> str:
    """Resolve the ordering mode from ``ROGUE_LADDER_ORDER`` (default canonical)."""
    mode = os.environ.get(LADDER_ORDER_ENV, "canonical").strip().lower()
    return mode if mode in _VALID_MODES else "canonical"


def _stable_order(
    elements: "tuple[str, ...] | list[str]", score: Callable[[str], float],
) -> tuple[str, ...]:
    """Sort ``elements`` by ``score`` descending, with the original position as a
    stable tiebreak — so equal scores (and cold-start all-unseen) preserve the
    hand-coded order deterministically."""
    seq = list(elements)
    return tuple(sorted(seq, key=lambda e: (-score(e), seq.index(e))))


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
    if mode == "fixed":
        return tuple(elements)

    def _score(e: str) -> float:
        s = rates.get(f"{label_prefix}{e}", BreachStat(f"{label_prefix}{e}", 0, 0))
        return s.discovery_score() if mode == "discovery" else s.smoothed_rate

    return _stable_order(elements, _score)


def strategy_values(
    session: "Session", *, config_id: str | None = None,
) -> dict[str, "StrategyValue"]:
    """§10.10 Phase 2 — richer per-label telemetry for the viability scheduler.

    Like ``strategy_breach_rates`` but also surfaces ``attempts_total`` (all rows,
    incl. orchestration failures) and ``last_tried_at`` (max ``created_at``), so the
    expected-value score can weight **validity** and **freshness**, not just breach
    rate. Keyed by the full ``entity_id`` label; ``config_id`` optionally scopes it.
    """
    from sqlalchemy import case, func

    from rogue.db.models import LadderAttempt

    valid = LadderAttempt.outcome.in_(("breach", "no_breach"))
    q = (
        session.query(
            LadderAttempt.entity_id.label("label"),
            func.sum(case((LadderAttempt.breached, 1), else_=0)).label("breaches"),
            func.sum(case((valid, 1), else_=0)).label("valid_trials"),
            func.count().label("attempts_total"),
            func.max(LadderAttempt.created_at).label("last_tried_at"),
        )
        .group_by(LadderAttempt.entity_id)
    )
    if config_id is not None:
        q = q.filter(LadderAttempt.config_id == config_id)
    out: dict[str, StrategyValue] = {}
    for row in q.all():
        if row.label is None:
            continue
        out[row.label] = StrategyValue(
            label=row.label,
            breaches=int(row.breaches or 0),
            valid_trials=int(row.valid_trials or 0),
            attempts_total=int(row.attempts_total or 0),
            last_tried_at=row.last_tried_at,
        )
    return out


def order_by_value(
    elements: "tuple[str, ...] | list[str]",
    values: dict[str, "StrategyValue"],
    *,
    now: datetime,
    label_prefix: str = "",
) -> tuple[str, ...]:
    """§10.10 Phase 2 — reorder ``elements`` by expected-value allocation score
    (effectiveness × viability × freshness × exploration), most-worth-budget first.

    An element with no telemetry gets a fresh ``StrategyValue(0, 0, 0)`` — breach
    0.5, validity 0.5, full freshness + exploration bonus — so the unseen are tried
    eagerly (cold-start) but a *proven-unviable* strategy (high breach, low validity)
    is correctly demoted. Stable tiebreak preserves the hand-coded order on ties.
    """
    def _score(e: str) -> float:
        key = f"{label_prefix}{e}"
        sv = values.get(key, StrategyValue(key, 0, 0, 0))
        return sv.value_score(now)

    return _stable_order(elements, _score)
