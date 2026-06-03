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
    "ReachStat",
    "ContextStat",
    "strategy_breach_rates",
    "strategy_values",
    "strategy_reachability",
    "contextual_breach_rates",
    "winning_model_distribution",
    "starvation_adjusted_score",
    "order_by_prior",
    "order_by_value",
    "order_by_starvation",
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
_VALID_MODES = ("canonical", "discovery", "viability", "starvation", "fixed")

# §10.10 Phase 2 — viability-aware allocation weights. The scheduler stops asking
# "what breaches most?" and asks "what is worth spending evaluation budget on now?"
# A high raw breach rate is worthless if the strategy can't actually be evaluated
# (planner refusals / render errors → low validity) or if the system has locked onto
# it (no freshness). FRESHNESS_TAU_DAYS is the staleness horizon at which a strategy
# earns full freshness boost; the *_WEIGHT terms scale each ≥1 multiplicative bonus.
FRESHNESS_TAU_DAYS = float(os.environ.get("ROGUE_LADDER_FRESHNESS_TAU_DAYS", "14"))
FRESHNESS_WEIGHT = float(os.environ.get("ROGUE_LADDER_FRESHNESS_WEIGHT", "0.5"))
EXPLORE_WEIGHT = float(os.environ.get("ROGUE_LADDER_EXPLORE_WEIGHT", "0.5"))

# §10.10 Phase 2.2 — starvation-aware exploration pressure. The first sweep showed
# greedy reorder entrenches the renderer monopoly (planner tier 7% reachability; 3
# high-value candidates reached 0% of the time). The fix is NOT `value × reachability`
# — that REINFORCES incumbents (high reach → more wins → higher value → more reach,
# a second rich-get-richer loop). Instead reachability enters as a BOOST on the
# *starved*: a strategy keeps its rank on merit, and a starved high-value one is
# surfaced. bonus = W × starvation_rate, and starvation_rate ∈ [0,1], so the boost is
# inherently capped at (1 + W)×. mml:wr (starv 0) is unchanged — it loses its monopoly
# only because starved peers rise, never because it is penalised for being good.
STARVATION_WEIGHT = float(os.environ.get("ROGUE_LADDER_STARVATION_WEIGHT", "1.0"))


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


def starvation_adjusted_score(
    sv: "StrategyValue", rs: "ReachStat | None", now: datetime,
) -> float:
    """§10.10 Phase 2.2 — EV with starvation as exploration pressure (capped boost).

    ``value_score × (1 + W × starvation_rate)``. A non-starved strategy (``rs`` None,
    or starvation 0 like a monopolist renderer) is unchanged; a starved high-value one
    is boosted up to ``(1 + W)×``. Deliberately NOT ``value × reachability`` — see
    ``STARVATION_WEIGHT``."""
    starv = rs.starvation_rate if rs is not None else 0.0
    return sv.value_score(now) * (1.0 + STARVATION_WEIGHT * starv)


def order_by_starvation(
    elements: "tuple[str, ...] | list[str]",
    values: dict[str, "StrategyValue"],
    reach: dict[str, "ReachStat"],
    *,
    now: datetime,
    label_prefix: str = "",
) -> tuple[str, ...]:
    """§10.10 Phase 2.2 — reorder by the starvation-adjusted EV, surfacing starved
    high-value strategies without penalising strong reachable ones. Joins the value
    layer (``ladder_attempts``) with the reachability layer (``ladder_rotation_
    membership``) by full label; an element absent from either gets neutral defaults.
    """
    def _score(e: str) -> float:
        key = f"{label_prefix}{e}"
        sv = values.get(key, StrategyValue(key, 0, 0, 0))
        return starvation_adjusted_score(sv, reach.get(key), now)

    return _stable_order(elements, _score)


@dataclass(frozen=True)
class ReachStat:
    """§10.10 Phase 2.1 — per-strategy reachability over `ladder_rotation_membership`.

    The signal `strategy_values` could NOT see: of the ladders where a strategy was
    *eligible*, how often did it actually run vs get skipped (and why). `reachability`
    low ⇒ the strategy is starved (early-stopped past / lost the reorder) even though
    it was a legitimate candidate — "high value but never reached"."""

    strategy_id: str
    eligible: int
    executed: int
    early_stopped: int
    budgeted: int

    @property
    def reachability(self) -> float:
        return self.executed / self.eligible if self.eligible else 0.0

    @property
    def starvation_rate(self) -> float:
        """Fraction of eligible appearances lost specifically to early-stop — the
        rich-get-richer / reorder-loser signal (distinct from budget cutoff)."""
        return self.early_stopped / self.eligible if self.eligible else 0.0


@dataclass(frozen=True)
class ContextStat:
    """§10.10 — a CONTEXTUAL (target_model × attack_family) breach prior, sourced from
    the full ``breach_results`` matrix (not the short-circuiting ladder, which can't
    give per-model rates). This is the spec's warm-prior and the "per-model technique-
    effectiveness map": e.g. encoding-family attacks breach Mistral far more than
    Claude. Globally-greedy ordering can't see this; a contextual scheduler can.

    Keyed by (target_model × family) because that's the dimension ``breach_results``
    covers at full sample — per-(strategy × model) for the ladder's transform tiers is
    NOT cleanly measurable (the ladder stops at the first breaching model and renderer
    variants don't persist), so it'd need probe telemetry, not this table.
    """

    target_model: str
    family: str
    breaches: int
    trials: int

    @property
    def breach_rate(self) -> float:
        return (self.breaches + ALPHA) / (self.trials + ALPHA + BETA)


def contextual_breach_rates(
    session: "Session", *, target_model: str | None = None,
) -> dict[tuple[str, str], "ContextStat"]:
    """Per-(target_model × attack_family) breach rate over the ``breach_results``
    matrix — the contextual prior + effectiveness map. ``target_model`` optionally
    scopes to one model. Breach = verdict ∈ {partial_breach, full_breach}.
    """
    from sqlalchemy import case, func

    from rogue.db.models import AttackPrimitive, BreachResult, DeploymentConfig
    from rogue.schemas import JudgeVerdict

    breached = BreachResult.verdict.in_(
        [JudgeVerdict.PARTIAL_BREACH, JudgeVerdict.FULL_BREACH]
    )
    q = (
        session.query(
            DeploymentConfig.target_model.label("model"),
            AttackPrimitive.family.label("family"),
            func.count().label("trials"),
            func.sum(case((breached, 1), else_=0)).label("breaches"),
        )
        .join(
            DeploymentConfig,
            DeploymentConfig.config_id == BreachResult.deployment_config_id,
        )
        .join(
            AttackPrimitive,
            AttackPrimitive.primitive_id == BreachResult.primitive_id,
        )
        .group_by(DeploymentConfig.target_model, AttackPrimitive.family)
    )
    if target_model is not None:
        q = q.filter(DeploymentConfig.target_model == target_model)
    out: dict[tuple[str, str], ContextStat] = {}
    for row in q.all():
        fam = getattr(row.family, "value", None) or str(row.family)
        out[(row.model, fam)] = ContextStat(
            target_model=row.model,
            family=fam,
            breaches=int(row.breaches or 0),
            trials=int(row.trials or 0),
        )
    return out


def winning_model_distribution(
    session: "Session", *, run_id: str | None = None,
) -> dict[str, int]:
    """Which target model produced each ladder's WINNING breach, counted.

    This is the "who won first" signal — and it is **order-biased** by design:
    ``_strategy_breaches`` short-circuits at the first breaching (config × trial), so
    a model tried earlier in the panel gets disproportionate winner credit. The
    *unbiased* "who would succeed if reached" answer is ``contextual_breach_rates``
    (sourced from the full ``breach_results`` matrix). Comparing the two surfaces the
    early-stop attribution bias directly.

    Reads from already-logged data: ``ladder_attempts.config_id`` stores the winning
    **target_model** on winner rows (the column name is a legacy misnomer — see the
    model docstring). No new telemetry; this just makes the distribution first-class.
    """
    from sqlalchemy import func

    from rogue.db.models import LadderAttempt

    q = (
        session.query(
            LadderAttempt.config_id.label("model"), func.count().label("n"),
        )
        .filter(LadderAttempt.breached.is_(True), LadderAttempt.config_id.isnot(None))
        .group_by(LadderAttempt.config_id)
    )
    if run_id is not None:
        q = q.filter(LadderAttempt.run_id == run_id)
    return {r.model: int(r.n) for r in q.all() if r.model}


def strategy_reachability(
    session: "Session", *, config_id: str | None = None,
) -> dict[str, "ReachStat"]:
    """Aggregate `ladder_rotation_membership` into per-strategy reachability stats.

    Only rows where the strategy was ``eligible`` count toward the denominator (an
    ineligible appearance — e.g. audio with no audio-config — is not "starvation").
    ``config_id`` optionally scopes to the winner config of each ladder.
    """
    from sqlalchemy import case, func

    from rogue.db.models import LadderRotationMembership as M

    early = (M.skipped_reason == "early_stop")
    budget = (M.skipped_reason == "budget")
    q = (
        session.query(
            M.strategy_id.label("sid"),
            func.sum(case((M.eligible, 1), else_=0)).label("eligible"),
            func.sum(case(((M.eligible & M.executed), 1), else_=0)).label("executed"),
            func.sum(case((early, 1), else_=0)).label("early_stopped"),
            func.sum(case((budget, 1), else_=0)).label("budgeted"),
        )
        .group_by(M.strategy_id)
    )
    if config_id is not None:
        q = q.filter(M.config_id == config_id)
    out: dict[str, ReachStat] = {}
    for row in q.all():
        if row.sid is None:
            continue
        out[row.sid] = ReachStat(
            strategy_id=row.sid,
            eligible=int(row.eligible or 0),
            executed=int(row.executed or 0),
            early_stopped=int(row.early_stopped or 0),
            budgeted=int(row.budgeted or 0),
        )
    return out
