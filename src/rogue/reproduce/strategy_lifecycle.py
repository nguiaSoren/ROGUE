"""Strategy lifecycle — graduation / retirement / resurrection (§10.9 Phase 4).

Pure-ish transition functions over an ``attack_strategies`` ORM row. They mutate
the row in place (the caller owns the session + commit); none make network calls,
so the lifecycle semantics are deterministic and fully unit-testable.

The state machine (locked in tasks/todo.md from answers.md):

    candidate ──win──▶ active ──Rule A/B──▶ retired ──win──▶ active (resurrected)
        │                                      │
        └──Rule A/B (0 breaches)──────────────▶┘

  - **Graduation** is *winner-only*: a candidate flips to ``active`` only when it
    is the terminal *winning* strategy of a ladder (it caused the breach). Merely
    appearing in a ladder that breached elsewhere is a weak ``supporting`` signal,
    not graduation (§10.9 attribution integrity).
  - **Retirement** is *soft + reversible*. Rule A (evidence): tried ≥ MIN_TRIALS
    with zero breaches AND enough *time diversity* (last try > a week after first
    seen — 5 fast retries are weak evidence). Rule B (staleness): old + never
    breached. Retired rows are skipped in routine sweeps but kept for analytics.
  - **Resurrection**: a retired technique that later breaches goes back to
    ``active`` with ``resurrected=True``; latency = ``last_breached_at − retired_at``
    (derived, not stored).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

from sqlalchemy import nulls_first

from rogue.schemas import AUTO_INTEGRABLE_MODALITIES, RetireReason, StrategyStatus

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from rogue.db.models import AttackStrategy

__all__ = [
    "MIN_TRIALS",
    "TTL_DAYS",
    "MIN_AGE_DAYS",
    "record_trial",
    "graduate",
    "evaluate_retirement",
    "apply_retirement",
    "select_candidates",
    "ladder_config_from_env",
    "build_ladder_rotation",
    "apply_ladder_outcome",
    "RotationPlan",
    "build_rotation_plan",
    "format_rotation_plan",
    "log_ladder_attempts",
    "build_rotation_membership",
    "log_rotation_membership",
]

# ARMS planner-tier strategy ids (Tier 5, not lifecycle-tracked harvested candidates).
_ARMS_BASE_IDS: frozenset[str] = frozenset({"crescendo", "actor_attack", "acronym"})


def _classify_ladder_entity(
    label: str, candidate_ids: "frozenset[str] | set[str]"
) -> tuple[str, int]:
    """Map a ladder attempt label → ``(entity_type, ladder_depth)`` (tier 1..5)."""
    if label in candidate_ids:
        return ("candidate", 5)
    if label.startswith("image:"):
        return ("renderer", 1)
    if label.startswith("coj:"):
        return ("coj", 2)
    if label.startswith("structured:"):
        return ("structured", 3)
    if label.startswith("audio:"):
        return ("renderer", 4)
    if label in _ARMS_BASE_IDS:
        return ("base", 5)
    return ("meta", 5)  # "budget"/unknown markers


def log_ladder_attempts(
    session: "Session",
    *,
    run_id: str,
    parent_id: str,
    attempts: list[tuple[str, str]],
    winning_strategy: Optional[str],
    breached_on: Optional[str],
    candidate_ids: "frozenset[str] | set[str]",
    quota: int,
    now: datetime,
    configs: "list | None" = None,
) -> None:
    """Append the orchestration trace for one parent's ladder to ``ladder_attempts``.

    Derived from the ``LadderResult`` (attempts + winning_strategy + breached_on) +
    the scheduler policy (``quota``). ``stopped_run`` marks the attempt that
    early-stopped the ladder — only meaningful at quota=0 (quota>0 suppresses
    early-stop). Telemetry-only; never raises into the caller's transaction.

    **§10.10 Adaptive Technique Prioritization (vendor/family tagging).** ``configs``
    is the panel this ladder ran against. When it is a SINGLE config (the per-target /
    benchmark case — the one the contextual blend keys on), every attempt's
    ``target_vendor`` / ``target_family`` is derived from that config's ``target_model``
    via :func:`extract_vendor` / :func:`extract_model_family`. With a multi-model panel
    (or no configs) the target a given attempt actually broke on is ambiguous — the
    ladder short-circuits at the first breaching config inside ``_strategy_breaches`` and
    doesn't surface which model each non-winning attempt was scored against — so vendor/
    family are left NULL rather than guessed (``vendor_family_strategy_rates`` counts NULL
    rows globally only, which is the correct, honest fallback). This per-attempt tagging
    is what makes the contextual blend non-cold on FUTURE single-target runs.
    """
    from rogue.adapters.model_specs import extract_model_family, extract_vendor
    from rogue.db.models import LadderAttempt

    # Unambiguous target only when the ladder ran against exactly one config.
    target_vendor: Optional[str] = None
    target_family: Optional[str] = None
    target_size_class: Optional[str] = None
    if configs is not None and len(configs) == 1:
        _model = configs[0].target_model
        target_vendor = extract_vendor(_model)
        target_family = extract_model_family(_model)
        from .config_features import derive_config_features  # noqa: PLC0415

        target_size_class = derive_config_features(_model, base_url=getattr(configs[0], "base_url", None)).sibling_key

    rows = []
    for idx, (label, outcome) in enumerate(attempts):
        etype, depth = _classify_ladder_entity(label, candidate_ids)
        breached = outcome == "breach"
        is_winner = breached and label == winning_strategy
        rows.append(
            LadderAttempt(
                run_id=run_id,
                parent_id=parent_id,
                attempt_index=idx,
                ladder_depth=depth,
                entity_type=etype,
                entity_id=label,
                technique_id=(label if label in candidate_ids else None),
                candidate_attempt_quota=quota,
                config_id=breached_on if is_winner else None,
                outcome=outcome,
                breached=breached,
                # Early-stop only happens at quota=0 (quota>0 suppresses it).
                stopped_run=bool(quota == 0 and is_winner),
                target_vendor=target_vendor,
                target_family=target_family,
                target_size_class=target_size_class,
                is_winner=is_winner,
                created_at=now,
            )
        )
    session.add_all(rows)


def build_rotation_membership(
    *,
    run_id: str,
    parent_id: str,
    rotation: "list[tuple[str, str]]",
    attempts: "list[tuple[str, str]]",
    winning_strategy: Optional[str],
    breached_on: Optional[str],
    audio_eligible: bool,
    now: datetime,
) -> list:
    """§10.10 Phase 2.1 — reconstruct the REACHABILITY trace for one ladder.

    Post-hoc (the ladder execution path is untouched): given the full ordered
    eligible ``rotation`` (``[(label, tier), …]``) the ladder was handed, plus what
    actually ran (``attempts`` = ``[(label, outcome), …]`` from the ``LadderResult``)
    and how it ended, classify EVERY eligible strategy as executed-or-skipped (and
    why). Returns ``LadderRotationMembership`` rows (not yet added to the session).

    Skip reasons:
      - ``no_compatible_config`` — its tier wasn't runnable (today only audio is
        config-gated: it needs an audio-capable config).
      - ``early_stop`` — a breach earlier in the rotation ended the ladder before it.
      - ``budget`` — the per-parent spend cap stopped the ladder before it.
      - ``not_reached`` — eligible + before the stop boundary but produced no attempt
        (e.g. a candidate-quota break in the planner tier). Honest catch-all.
    """
    from rogue.db.models import LadderRotationMembership

    executed = {lbl: out for (lbl, out) in attempts if out != "stopped"}
    budget_stopped = any(out == "stopped" for (_, out) in attempts)
    ranked = [(lbl, tier, i) for i, (lbl, tier) in enumerate(rotation)]
    winner_rank = (
        next((r for (lbl, _t, r) in ranked if lbl == winning_strategy), None)
        if winning_strategy is not None
        else None
    )
    last_exec_rank = max(
        (r for (lbl, _t, r) in ranked if lbl in executed), default=-1
    )

    rows = []
    for label, tier, rank in ranked:
        is_exec = label in executed
        eligible = not (tier == "audio" and not audio_eligible)
        if is_exec:
            reason = None
        elif not eligible:
            reason = "no_compatible_config"
        elif winner_rank is not None and rank > winner_rank:
            reason = "early_stop"
        elif budget_stopped and rank > last_exec_rank:
            reason = "budget"
        else:
            reason = "not_reached"
        rows.append(
            LadderRotationMembership(
                run_id=run_id,
                parent_id=parent_id,
                strategy_id=label,
                tier=tier,
                rank=rank,
                eligible=eligible,
                executed=is_exec,
                outcome=executed.get(label),
                skipped_reason=reason,
                config_id=(
                    breached_on if (is_exec and label == winning_strategy) else None
                ),
                created_at=now,
            )
        )
    return rows


def log_rotation_membership(session: "Session", rows: list) -> None:
    """Append reachability rows. Telemetry-only — never raises into the caller's
    transaction (mirrors ``log_ladder_attempts``)."""
    if rows:
        session.add_all(rows)


# Retirement thresholds (env-overridable). Defaults from answers.md.
MIN_TRIALS: int = int(os.environ.get("STRATEGY_MIN_TRIALS", "5"))
TTL_DAYS: int = int(os.environ.get("STRATEGY_TTL_DAYS", "30"))
# Time-diversity floor for Rule A: the last trial must be at least this many days
# after the row was first seen, so "5 retries in 10 minutes" can't retire it.
MIN_AGE_DAYS: int = int(os.environ.get("STRATEGY_MIN_AGE_DAYS", "7"))


def graduate(row: "AttackStrategy", *, config_id: Optional[str], now: datetime) -> None:
    """Promote ``row`` to ``active`` on a winning breach (idempotent on re-wins).

    Sets the first-breach audit once; bumps ``n_breaches`` + ``last_breached_at``
    every win. A win on a ``retired`` row resurrects it (``resurrected=True``);
    ``retired_at`` is intentionally preserved so resurrection latency stays
    measurable.
    """
    was_retired = row.status == StrategyStatus.RETIRED
    row.n_breaches += 1
    row.last_breached_at = now
    if row.first_breach_at is None:
        row.first_breach_at = now
        row.first_breach_config_id = config_id
    if was_retired:
        row.resurrected = True  # retired_at + retire_reason kept for latency/history
    row.status = StrategyStatus.ACTIVE


def record_trial(
    row: "AttackStrategy",
    *,
    won: bool,
    valid: bool,
    ladder_breached: bool,
    config_id: Optional[str] = None,
    now: datetime,
) -> None:
    """Record one ladder attempt of ``row`` and apply graduation.

    ``won`` — ``row`` was the terminal winning strategy (it caused the breach).
    ``valid`` — the attempt was a real semantic test (breach/no_breach), NOT an
    orchestration failure (planner-refused / render_error). Every attempt advances
    ``n_attempts_total`` (selection ordering); only valid ones advance
    ``n_valid_trials`` (what retirement measures — attack failure, not orchestration
    failure). A win is always valid.
    ``ladder_breached`` — the ladder run breached on *some* strategy (used only to
    increment the weak ``supporting_breach_count`` when ``row`` was NOT the winner).
    """
    row.n_attempts_total += 1
    if valid:
        row.n_valid_trials += 1
    row.last_tried_at = now
    if won:
        graduate(row, config_id=config_id, now=now)
    elif ladder_breached and valid:
        row.supporting_breach_count += 1


def evaluate_retirement(
    row: "AttackStrategy",
    now: datetime,
    *,
    min_trials: int = MIN_TRIALS,
    ttl_days: int = TTL_DAYS,
    min_age_days: int = MIN_AGE_DAYS,
) -> tuple[bool, Optional[RetireReason]]:
    """Decide whether ``row`` should retire. Pure — returns ``(retire?, reason)``.

    Only an un-breached ``candidate`` is eligible. Rule A (evidence-based, with
    time diversity) is checked before Rule B (staleness).
    """
    if row.status != StrategyStatus.CANDIDATE or row.n_breaches > 0:
        return (False, None)
    created = row.created_at
    # Rule A — evidence-based: enough VALID trials (not blocked orchestration
    # attempts) AND enough elapsed time. A candidate that was only ever
    # planner-refused / render-errored never accrues valid trials → never retires
    # on Rule A (it was never actually tested — orchestration failure ≠ attack failure).
    if (
        row.n_valid_trials >= min_trials
        and row.last_tried_at is not None
        and created is not None
        and row.last_tried_at > created + timedelta(days=min_age_days)
    ):
        return (True, RetireReason.NEVER_BREACHED_N_RUNS)
    # Rule B — staleness.
    if created is not None and created < now - timedelta(days=ttl_days):
        return (True, RetireReason.EXPIRED_TTL)
    return (False, None)


def apply_retirement(
    row: "AttackStrategy", now: datetime, **kwargs
) -> bool:
    """Evaluate + apply soft retirement in place. Returns True iff retired."""
    retire, reason = evaluate_retirement(row, now, **kwargs)
    if retire:
        row.status = StrategyStatus.RETIRED
        row.retired_at = now
        row.retire_reason = reason
    return retire


def select_candidates(
    session: "Session",
    k: int,
    *,
    statuses: tuple[StrategyStatus, ...] = (StrategyStatus.CANDIDATE,),
) -> list["AttackStrategy"]:
    """Pick up to ``k`` planner-drivable candidates to try this run.

    Least-tried-first (best exploration value under a hard budget), with a
    ``last_tried_at NULLS FIRST`` tiebreak so a never-tried candidate beats a
    recently-tried one and we don't hammer the same row in a short window. A light
    exact dedup (by directive/name) is applied AFTER ordering so the K slots aren't
    spent on near-identical techniques.
    """
    if k <= 0:
        return []
    from rogue.db.models import AttackStrategy

    rows = (
        session.query(AttackStrategy)
        .filter(
            AttackStrategy.status.in_(statuses),
            AttackStrategy.modality.in_(tuple(AUTO_INTEGRABLE_MODALITIES)),
        )
        .order_by(
            AttackStrategy.n_attempts_total.asc(),
            nulls_first(AttackStrategy.last_tried_at.asc()),
            AttackStrategy.created_at.asc(),
        )
        .all()
    )

    seen: set[str] = set()
    out: list["AttackStrategy"] = []
    for r in rows:
        if not (r.directive and r.directive.strip()):
            continue  # un-driveable without a directive
        key = (r.directive or r.name or "").strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
        if len(out) >= k:
            break
    return out


# --------------------------------------------------------------------------- #
# Ladder integration (4-wire) — assemble the rotation + apply the outcome.
# --------------------------------------------------------------------------- #


def ladder_config_from_env() -> tuple[str, int]:
    """Resolve ``(scope, cap)`` for candidate-trying from the environment.

    ``CAND_LADDER_SCOPE`` = ``run`` (default — cap the whole run, predictable
    spend) | ``parent`` (cap per EVADE parent, deep-eval). ``CAND_LADDER_CAP``
    (default 3) is the per-scope cap. See answers.md for the rationale.
    """
    scope = os.environ.get("CAND_LADDER_SCOPE", "run").strip().lower()
    if scope not in ("run", "parent"):
        scope = "run"
    try:
        cap = int(os.environ.get("CAND_LADDER_CAP", "3"))
    except ValueError:
        cap = 3
    return scope, max(0, cap)


def _select_rotation(
    session: "Session", base_ladder: tuple[str, ...], cap: int
) -> tuple[list[str], list[str], list[str]]:
    """Return ``(base_ids, active_ids, candidate_ids)`` for the rotation.

    Active harvested strategies are always included; candidates are the capped,
    least-tried, deduped selection. ``base_ladder`` (ARMS) is passed through.
    """
    from rogue.reproduce.strategy_library import load_strategy_library

    active = load_strategy_library(session, statuses=(StrategyStatus.ACTIVE,))
    active_ids = [
        sid
        for sid, view in active.items()
        if view.origin == "harvested" and view.planner_drivable
    ]
    candidate_ids = [r.technique_id for r in select_candidates(session, cap)]
    return list(base_ladder), active_ids, candidate_ids


def _assemble_rotation(
    base_ids: list[str], active_ids: list[str], candidate_ids: list[str]
) -> tuple[str, ...]:
    """Base → active → candidates, order-preserving + deduped."""
    rotation: list[str] = list(base_ids)
    for sid in active_ids + candidate_ids:
        if sid not in rotation:
            rotation.append(sid)
    return tuple(rotation)


def build_ladder_rotation(
    session: "Session",
    base_ladder: tuple[str, ...],
    *,
    cap: int,
) -> tuple[tuple[str, ...], set[str]]:
    """Assemble the escalation-ladder strategy rotation including harvested techniques.

    Returns ``(rotation, harvested_ids)`` where ``rotation`` is
    ``base_ladder (ARMS) + active harvested ids + up-to-cap candidate ids`` and
    ``harvested_ids`` is the subset that came from ``attack_strategies`` (so the
    caller knows which trials to feed back into :func:`apply_ladder_outcome`).
    ``base_ladder`` entries (ARMS) are never lifecycle-tracked.
    """
    base_ids, active_ids, candidate_ids = _select_rotation(session, base_ladder, cap)
    rotation = _assemble_rotation(base_ids, active_ids, candidate_ids)
    return rotation, set(active_ids) | set(candidate_ids)


@dataclass(frozen=True)
class RotationPlan:
    """The escalation rotation + cost estimate — shared by ``--dry-run`` and live.

    Built by the same code on both paths so the preview can never lie about what
    the live run will do (the dry-run just stops before paid calls). Counts come
    from real DB queries; the cost is an explicit UPPER BOUND (every new strategy
    tried against every estimated EVADE parent across configs × trials, before the
    first-breach short-circuit).
    """

    rotation: tuple[str, ...]
    base_ids: tuple[str, ...]
    active_ids: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    harvested_ids: frozenset[str]
    n_parents_est: int
    n_configs: int
    n_trials: int
    est_target_calls: int
    est_judge_calls: int
    est_usd: float

    @property
    def n_new_strategies(self) -> int:
        """Harvested strategies added to the base ladder (the cost driver)."""
        return len(self.active_ids) + len(self.candidate_ids)


def build_rotation_plan(
    session: "Session",
    *,
    base_ladder: tuple[str, ...],
    cap: int,
    n_parents_est: int,
    n_configs: int,
    n_trials: int,
    target_cost_usd: float,
    judge_cost_usd: float,
) -> RotationPlan:
    """Build the rotation + an upper-bound cost estimate (real DB queries, no spend).

    The SAME function feeds the ``--dry-run`` preview and the live run. The cost is
    a deliberate upper bound: ``n_new_strategies × n_parents_est × n_configs ×
    n_trials`` target calls (the ladder short-circuits at the first breach, so real
    spend is ≤ this), plus an equal number of judge calls.
    """
    base_ids, active_ids, candidate_ids = _select_rotation(session, base_ladder, cap)
    rotation = _assemble_rotation(base_ids, active_ids, candidate_ids)
    n_new = len(active_ids) + len(candidate_ids)
    est_target = n_new * max(0, n_parents_est) * max(1, n_configs) * max(1, n_trials)
    est_judge = est_target
    est_usd = est_target * target_cost_usd + est_judge * judge_cost_usd
    return RotationPlan(
        rotation=rotation,
        base_ids=tuple(base_ids),
        active_ids=tuple(active_ids),
        candidate_ids=tuple(candidate_ids),
        harvested_ids=frozenset(active_ids) | frozenset(candidate_ids),
        n_parents_est=n_parents_est,
        n_configs=n_configs,
        n_trials=n_trials,
        est_target_calls=est_target,
        est_judge_calls=est_judge,
        est_usd=round(est_usd, 2),
    )


def format_rotation_plan(plan: RotationPlan) -> str:
    """Human-readable execution plan (printed before a run / on ``--dry-run``)."""
    cand = ", ".join(plan.candidate_ids) if plan.candidate_ids else "(none)"
    active = ", ".join(plan.active_ids) if plan.active_ids else "(none)"
    return (
        "ROGUE escalation rotation plan (§10.9 Phase 4)\n"
        "  rotation summary:\n"
        f"    base ladder strategies: {len(plan.base_ids)} ({', '.join(plan.base_ids)})\n"
        f"    active harvested:       {len(plan.active_ids)} [{active}]\n"
        f"    candidates selected:    {len(plan.candidate_ids)} [{cand}]\n"
        f"    EVADE parents (est):    {plan.n_parents_est}\n"
        "  selected by: least-tried-first (n_attempts_total ASC)\n"
        "  estimated ADDED escalation cost (UPPER BOUND — short-circuits at first breach):\n"
        f"    target calls: {plan.est_target_calls}  (= {plan.n_new_strategies} new "
        f"× {plan.n_parents_est} parents × {plan.n_configs} configs × {plan.n_trials} trials)\n"
        f"    judge calls:  {plan.est_judge_calls}\n"
        f"    est usd:      ~${plan.est_usd:.2f}"
    )


def apply_ladder_outcome(
    session: "Session",
    *,
    attempts: list[tuple[str, str]],
    winning_strategy: Optional[str],
    harvested_ids: set[str],
    config_id: Optional[str],
    now: datetime,
) -> None:
    """Feed one parent's ladder result back into the harvested strategies' lifecycle.

    ``attempts`` is the ladder's ``(strategy_id, outcome)`` list. For every harvested
    strategy that was actually tried, ``record_trial`` is called with
    ``won=(outcome == "breach")`` — so **any harvested strategy whose OWN outcome was
    breach graduates**, not only the single ladder "winner". This is mode-adaptive by
    construction, NOT a special case:
      - early-stop ladders (``candidate_quota=0``): the ladder stops at the first
        breach, so only the winner ever *runs* → only the winner can breach →
        effectively winner-only graduation.
      - quota / growth-sweep ladders (``candidate_quota>0``): early-stop is
        suppressed, so *every reached candidate runs*, and *each one that breaches
        graduates* (verified live 2026-06-03: all 3 selected candidates breached
        under quota=3 → all 3 graduated).
    A non-winner in a ladder that breached elsewhere → ``supporting_breach_count``.
    Then soft retirement is evaluated. ARMS base-ladder ids are skipped. Commits once.
    Note: the per-sweep graduation ceiling is the candidate *selection* cap K (see
    ``select_candidates``), NOT this attribution rule.
    """
    from rogue.db.models import AttackStrategy

    ladder_breached = winning_strategy is not None
    touched = False
    for sid, outcome in attempts:
        if sid not in harvested_ids:
            continue
        row = session.get(AttackStrategy, sid)
        if row is None:
            continue
        record_trial(
            row,
            won=(outcome == "breach"),
            # A real semantic test, not an orchestration failure. refused (planner
            # declined) / render_error (slot/render failure) reached the candidate
            # tier but never actually tested it → not a valid trial.
            valid=(outcome in ("breach", "no_breach")),
            ladder_breached=ladder_breached,
            config_id=config_id,
            now=now,
        )
        apply_retirement(row, now)
        touched = True
    if touched:
        session.commit()
