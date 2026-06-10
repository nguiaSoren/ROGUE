"""Verified-promotion gate — the SkillGen intervention model (Surface 3, Section C).

**The consummation principle for the degradation breach (build 08 §4):** a skill
enters ``active`` ONLY after a *measured* net-positive effect on a held-out set —
``net_effect = repairs - regressions`` — whose **bootstrap-CI lower bound > 0**.
"Looks risky" / "looks worse" is not a breach; only a worse OUTCOME (a REGRESSION
from the net-effect judge) counts (build 08 §4, ``memory.judges``). A degrading
skill (regressions > repairs, CI-lb ≤ 0) is REJECTED, never promoted.

How the gate runs (offline-testable by construction):

1. For each held-out instance the injected :class:`RolloutRunner` produces the
   agent output **WITHOUT** and **WITH** the candidate skill — the only seam that
   touches the (paid) scan engine. Tests inject :class:`FakeRolloutRunner`; the
   real scan-engine-backed runner is a thin adapter wired later (see the Protocol
   docstring for the shape).
2. Each (without, with) pair is scored by the **net-effect judge**
   (``memory.judges.net_effect_judge`` — Area 02 dep, injected so verification
   needs no LLM in tests): REPAIR / REGRESSION / NEUTRAL.
3. The {0,1} repair-fraction vector over the *decisive* instances (repair=1,
   regression=0; neutrals carry no net-effect signal) is bootstrapped via
   :func:`rogue.diff.bootstrap.bootstrap_ci` (REUSE — never hand-roll a CI).
   ``net_effect = repairs - regressions``.
4. **Promote (status → active) iff the repair-fraction CI lower bound >
   ``PROMOTION_RATE_FLOOR`` (0.5)** for that cohort — confidently repairs MORE OFTEN
   than it regresses, not merely "some repairs". A ``skill_verifications(kind=promotion,
   verdict=pass|fail, …CIs…)`` row is always written — both the admit and the reject
   are persisted to the audit spine.

**Ranking signals discipline (build 08 §4 / spec §1):** the gate ranks/admits on
**measured** signals only — net-effect, regression rate (and, downstream, leakage
score + combination risk owned by other engineers). **Popularity is NOT a safety
signal** (>90% of high-popularity skills failed audit, SkillProbe). There is no
popularity field on ``Skill`` and none is read here — see :data:`RANKING_SIGNALS`.

The economics (lazy gating / cohort scoping / applicability pre-filter) live in
``rogue.memory.economics`` and decide *whether* to call this gate at all; this
module is the gate itself (it assumes the decision to verify was already made).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, runtime_checkable

from rogue.db.models import (
    Skill,
    SkillStatus,
    SkillVerification,
    SkillVerificationKind,
    SkillVerificationVerdict,
)
from rogue.diff.bootstrap import DEFAULT_SEED, bootstrap_ci
from rogue.memory.cohorts import CohortScope, enforce_scope
from rogue.memory.judges import NetEffectVerdict, net_effect_judge

__all__ = [
    "RANKING_SIGNALS",
    "RolloutRunner",
    "FakeRolloutRunner",
    "VerificationStore",
    "InMemoryVerificationStore",
    "PostgresVerificationStore",
    "evaluate_promotion",
]

# ----------------------------------------------------------------------------------
# Ranking signals — measured-only. Popularity is explicitly NOT here (build 08 §4).
# ----------------------------------------------------------------------------------
#
# The ONLY signals that may feed skill ranking / admission. Asserted in code so a
# future "rank by popularity / usage count" change has to delete this comment to
# happen — >90% of high-popularity skills failed audit (SkillProbe); popularity is
# never a safety signal. (Leakage + combination scores are owned by other
# engineers; named here for completeness — this gate measures net-effect.)
RANKING_SIGNALS: frozenset[str] = frozenset(
    {"net_effect", "regression_rate", "leakage_score", "combination_risk"}
)
assert "popularity" not in RANKING_SIGNALS, (
    "popularity is NOT a safety signal — no popularity field may feed ranking "
    "(build 08 §4 / SkillProbe: >90% of high-popularity skills failed audit)"
)

# The verified-promotion gate admits a skill IFF the bootstrap-CI lower bound of its
# repair fraction (repairs / decisive instances) is confidently ABOVE this floor — i.e.
# the skill repairs MORE OFTEN than it regresses (net-positive), not merely "some repairs".
# 0.5 is the consummation boundary: a repair fraction <= 0.5 is net-neutral-or-negative.
PROMOTION_RATE_FLOOR: float = 0.5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_verification_id() -> str:
    return f"skver-{uuid.uuid4().hex[:16]}"


# ----------------------------------------------------------------------------------
# Rollout seam — the ONE place the (paid) scan engine is touched.
# ----------------------------------------------------------------------------------


@runtime_checkable
class RolloutRunner(Protocol):
    """Produces the agent output WITHOUT and WITH a candidate skill on one instance.

    This is the single seam between the offline gate and the (paid) scan engine.
    The real adapter wired later is thin: given a held-out ``instance`` (a task
    spec — at minimum ``task`` + ``expected_outcome`` keys the net-effect judge
    reads), it runs the cohort's agent twice via ``rogue.platform.scan_service``
    (``DefaultScanService`` + ``worker``/``queue``) — once with the candidate
    skill injected into the agent's retrieved set, once without — and returns the
    two final outputs. Tests inject :class:`FakeRolloutRunner` instead, so the
    whole gate runs with no creds / no LLM.

    Implementations MUST be side-effect-free w.r.t. the skill pool (a rollout
    never promotes/persists a skill — only :func:`evaluate_promotion` does, after
    the CI decision).
    """

    def rollout(
        self, skill: Skill, instance: dict[str, Any]
    ) -> tuple[str, str]:
        """Return ``(without_output, with_output)`` for ``skill`` on ``instance``."""
        ...


class FakeRolloutRunner:
    """Deterministic offline runner with a configurable repair/regression mix.

    For tests / EXIT GATE C: no scan engine, no LLM. ``outcomes`` is a per-instance
    list of ``"repair" | "regression" | "neutral"`` labels; the runner emits a
    matching (without, with) output pair that the *stub* net-effect judge maps to
    the corresponding verdict (the offline judge in the tests keys off these
    sentinel strings). If ``outcomes`` is shorter than the held-out set it cycles,
    so a single label (e.g. all-``"regression"``) configures a uniformly-degrading
    fixture skill.
    """

    def __init__(self, outcomes: Sequence[str]) -> None:
        if not outcomes:
            raise ValueError("FakeRolloutRunner needs at least one outcome label")
        self.outcomes = [str(o).strip().lower() for o in outcomes]
        self._i = 0

    def rollout(
        self, skill: Skill, instance: dict[str, Any]
    ) -> tuple[str, str]:
        label = self.outcomes[self._i % len(self.outcomes)]
        self._i += 1
        # Sentinel-bearing outputs: a stub judge reads the label off the WITH side;
        # the real net-effect judge would compare the two on outcome.
        without = f"[baseline] {instance.get('task', '')}"
        with_ = f"[{label}] {instance.get('task', '')}"
        return without, with_


# ----------------------------------------------------------------------------------
# Verification-store seam (mirrors pool.SkillStore: in-memory + Postgres).
# ----------------------------------------------------------------------------------


class VerificationStore(Protocol):
    """Persistence + status-mutation seam for the promotion gate.

    Mirrors ``pool.SkillStore``: a Protocol with an offline
    :class:`InMemoryVerificationStore` (tests) and a
    :class:`PostgresVerificationStore` (durable, over ``skill_verifications`` +
    the ``skills.status`` column). Keeping it a Protocol is what makes the gate
    unit-testable with no DB.
    """

    def record(self, verification: SkillVerification) -> SkillVerification:
        """Persist a verification audit row. Returns it."""
        ...

    def set_status(
        self, skill: Skill, status: SkillStatus, *, when: datetime
    ) -> None:
        """Flip a skill's lifecycle status (promote → active / demote → quarantined)."""
        ...


class InMemoryVerificationStore:
    """Offline verification store — collects rows + mutates the in-memory skill."""

    def __init__(self) -> None:
        self.verifications: list[SkillVerification] = []

    def record(self, verification: SkillVerification) -> SkillVerification:
        self.verifications.append(verification)
        return verification

    def set_status(
        self, skill: Skill, status: SkillStatus, *, when: datetime
    ) -> None:
        # promoted_at is stamped once, on the FIRST transition into active (the
        # promotion event) — a passing re-verify keeps the original promoted_at.
        if status is SkillStatus.ACTIVE and skill.promoted_at is None:
            skill.promoted_at = when
        skill.status = status
        skill.last_verified_at = when


class PostgresVerificationStore:
    """Durable verification store over ``skill_verifications`` + ``skills.status``.

    ORM/SQLAlchemy imported lazily inside methods so importing this module needs
    no DB/driver (mirrors ``pool.PostgresSkillStore`` / ``tenancy.py``).
    ``session_factory`` is a ``sessionmaker`` (or any zero-arg callable returning a
    ``Session`` usable as a context manager).
    """

    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self._session_factory = session_factory

    def record(self, verification: SkillVerification) -> SkillVerification:
        with self._session_factory() as session:
            session.add(verification)
            session.commit()
            session.refresh(verification)
            session.expunge(verification)
        return verification

    def set_status(
        self, skill: Skill, status: SkillStatus, *, when: datetime
    ) -> None:
        with self._session_factory() as session:
            row = session.get(Skill, skill.skill_id)
            if row is None:
                raise ValueError(f"skill {skill.skill_id!r} not found for status update")
            if status is SkillStatus.ACTIVE and row.promoted_at is None:
                row.promoted_at = when
                skill.promoted_at = when
            row.status = status
            row.last_verified_at = when
            session.commit()
        # Keep the caller's in-memory object consistent with what was persisted.
        skill.status = status
        skill.last_verified_at = when


# ----------------------------------------------------------------------------------
# The gate
# ----------------------------------------------------------------------------------

# How a held-out rollout pair is scored. A real judge call returns a structured
# result with ``.verdict``; a stub in tests returns the verdict directly. We accept
# either (project to a NetEffectVerdict) so verification never needs an LLM offline.
JudgeFn = Callable[..., Any]


def _verdict_of(scored: Any) -> NetEffectVerdict:
    """Project a judge result (or a bare verdict) to a :class:`NetEffectVerdict`."""
    verdict = getattr(scored, "verdict", scored)
    if isinstance(verdict, NetEffectVerdict):
        return verdict
    return NetEffectVerdict(str(verdict).strip().lower().replace(" ", "_").replace("-", "_"))


def evaluate_promotion(
    skill: Skill,
    cohort_id: str,
    held_out_set: Sequence[dict[str, Any]],
    *,
    runner: RolloutRunner,
    judge: Optional[JudgeFn] = None,
    store: Optional[VerificationStore] = None,
    scope: Optional[CohortScope] = None,
    bootstrap_b: int = 1000,
    seed: int = DEFAULT_SEED,
    scan_run_id: Optional[str] = None,
    judge_calibration_ref: Optional[str] = None,
) -> SkillVerification:
    """Run the verified-promotion gate for ``skill`` on ``cohort_id``'s held-out set.

    For each held-out instance the ``runner`` produces (without, with) outputs; the
    pair is scored by ``judge`` (a ``net_effect_judge``-style grader returning a
    REPAIR/REGRESSION/NEUTRAL verdict — defaults to the real ``net_effect_judge()``,
    which makes a live LLM call, so tests inject a stub). The per-instance net-effect
    vector (+1 repair / -1 regression / 0 neutral) is bootstrapped via
    :func:`bootstrap_ci`. ``net_effect = repairs - regressions``.

    **Promote (status → active) iff the bootstrap-CI lower bound > 0** for this
    cohort. A ``skill_verifications(kind=promotion)`` row is always recorded
    (verdict=pass on promote, fail otherwise) and returned.

    The bootstrap operates on the {0,1} repair-fraction vector (repair=1, regression=0)
    over the *decisive* instances (neutrals carry no net-effect signal, so they are
    excluded — they only widen ``held_out_n``). ``bootstrap_ci`` is a boolean-proportion
    estimator, so the bound is on the repair FRACTION; the gate ``ci_low >
    PROMOTION_RATE_FLOOR`` (0.5) means "with high confidence the repair fraction is above
    one-half — the skill repairs MORE OFTEN than it regresses", exactly the consummation
    test: a net-negative (repair fraction ≤ 0.5) skill cannot clear it. (Empty/all-neutral
    decisive set → (0,0) → not promoted — no measured net-positive effect.)

    Args:
        skill: the candidate (``status`` should be ``candidate``; raises if already
            retired). Its ``(org, cohort, trust_domain)`` is checked against
            ``scope`` when one is supplied (Section G isolation — a gate run for
            cohort X cannot promote a cohort-Y skill).
        cohort_id: the cohort this verification is scoped to (written on the row).
        held_out_set: the held-out instances; each a dict with at least ``task``
            and ``expected_outcome`` (the net-effect judge's required fields).
        runner: the :class:`RolloutRunner` (FakeRolloutRunner offline / scan-engine
            adapter in prod).
        judge: a grader ``(task, expected_outcome, output_without_skill,
            output_with_skill) -> result_with_.verdict``. Defaults to the real
            ``net_effect_judge()`` (LLM); tests pass a stub.
        store: the :class:`VerificationStore` (in-memory offline / Postgres
            durable). When ``None`` an :class:`InMemoryVerificationStore` is used
            (the row is still returned; nothing durable is written).
        bootstrap_b / seed: forwarded to :func:`bootstrap_ci` (REUSE; deterministic).
        scan_run_id / judge_calibration_ref: provenance written on the audit row.

    Returns:
        the recorded :class:`SkillVerification` (kind=promotion).
    """
    if skill.status is SkillStatus.RETIRED:
        raise ValueError(
            f"skill {skill.skill_id!r} is retired; the promotion gate does not "
            "resurrect retired skills"
        )
    if scope is not None:
        # Direct-access isolation guard (Section G): a gate run scoped to cohort X
        # may not promote a skill belonging to another cohort/trust_domain.
        enforce_scope(scope, skill)

    store = store if store is not None else InMemoryVerificationStore()
    judge = judge if judge is not None else net_effect_judge()

    repairs = 0
    regressions = 0
    decisive: list[int] = []  # 1 = repair, 0 = regression (neutrals carry no net-effect signal)
    for instance in held_out_set:
        without_output, with_output = runner.rollout(skill, instance)
        scored = judge(
            task=instance.get("task", ""),
            expected_outcome=instance.get("expected_outcome", ""),
            output_without_skill=without_output,
            output_with_skill=with_output,
        )
        verdict = _verdict_of(scored)
        if verdict is NetEffectVerdict.REPAIR:
            repairs += 1
            decisive.append(1)
        elif verdict is NetEffectVerdict.REGRESSION:
            regressions += 1
            decisive.append(0)
        # NEUTRAL → no net-effect signal; excluded from the decisive vector.

    net_effect = repairs - regressions
    held_out_n = len(held_out_set)

    # Bootstrap the {0,1} repair-fraction vector over decisive instances (REUSE bootstrap_ci,
    # which is a boolean-proportion estimator). The gate is ``ci_low > PROMOTION_RATE_FLOOR``
    # (0.5): the repair fraction must be confidently ABOVE one-half — i.e. the skill repairs
    # MORE OFTEN than it regresses (net-positive), not merely "some repairs > 0". A net-negative
    # skill (repair fraction <= 0.5) cannot clear it; an empty/all-neutral decisive set → (0,0).
    ci_low, ci_high = bootstrap_ci(decisive, B=bootstrap_b, seed=seed)

    promote = ci_low > PROMOTION_RATE_FLOOR
    when = _now()
    verdict_value = (
        SkillVerificationVerdict.PASS if promote else SkillVerificationVerdict.FAIL
    )

    verification = SkillVerification(
        verification_id=_new_verification_id(),
        skill_id=skill.skill_id,
        cohort_id=cohort_id,
        kind=SkillVerificationKind.PROMOTION,
        net_effect=float(net_effect),
        repairs=repairs,
        regressions=regressions,
        ci_low=float(ci_low),
        ci_high=float(ci_high),
        held_out_n=held_out_n,
        judge_calibration_ref=judge_calibration_ref,
        scan_run_id=scan_run_id,
        decided_at=when,
        verdict=verdict_value,
    )

    if promote:
        store.set_status(skill, SkillStatus.ACTIVE, when=when)
    store.record(verification)
    return verification
