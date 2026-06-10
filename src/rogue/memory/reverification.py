"""Scheduled re-verification of ``active`` skills (Surface 3, Section C — continuous).

One-shot admission is not enough: a skill that helped last month can regress as the
codebase / base model drifts (build 08 §4). So ``active`` skills are **continuously
re-verified** with the *same* net-effect gate as promotion, and a skill whose
re-check comes back net-negative (CI lower bound ≤ 0) is **demoted ``active`` →
``quarantined``** — the consummation principle applied on an ongoing basis, not a
"looks stale" heuristic.

This ties to the §D economics: re-verification is **only triggered under retrieval
pressure** (lazy gating — a skill nobody retrieves costs nothing to keep, so we
don't pay to re-roll it). ``economics.should_verify`` gates the call; this module
runs the net-effect re-check for the skills that clear that gate and applies the
demotion.

It REUSES the promotion machinery wholesale — same rollout runner, same net-effect
judge, same bootstrap CI, same verification-store seam — writing a
``skill_verifications(kind=reverification)`` row instead of ``promotion``. The only
behavioural difference from :func:`promotion.evaluate_promotion` is the
*direction*: a pass keeps the skill ``active`` (refreshing ``last_verified_at``); a
fail demotes it to ``quarantined``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any, Optional

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
from rogue.memory.promotion import (
    PROMOTION_RATE_FLOOR,
    InMemoryVerificationStore,
    JudgeFn,
    RolloutRunner,
    VerificationStore,
    _grade,
    _new_verification_id,
    _verdict_of,
)

__all__ = ["reverify_skill"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def reverify_skill(
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
    """Re-verify one ``active`` skill; demote → ``quarantined`` on a net-negative re-check.

    Same net-effect gate as :func:`promotion.evaluate_promotion` (rollout WITH/
    WITHOUT → net-effect judge → bootstrap CI on the signed +1/-1/0 vector), writing
    a ``skill_verifications(kind=reverification)`` row. CI-lb > 0 → **pass** (skill
    stays ``active``, ``last_verified_at`` refreshed); CI-lb ≤ 0 → **fail** (skill
    demoted to ``quarantined`` — it no longer measurably helps).

    Intended to be called only for skills past the lazy-gate retrieval-pressure
    threshold (``economics.should_verify``) — re-verifying the long tail nobody
    retrieves is wasted rollout spend (build 08 §5).

    Only ``active`` skills are re-verifiable: a ``candidate`` has never been
    promoted (use the promotion gate), and ``quarantined`` / ``retired`` are not
    re-promoted here (that is a fresh promotion decision). Raises ``ValueError``
    otherwise.
    """
    if skill.status is not SkillStatus.ACTIVE:
        raise ValueError(
            f"reverify_skill only re-checks ACTIVE skills; {skill.skill_id!r} is "
            f"{skill.status.value!r}"
        )
    if scope is not None:
        enforce_scope(scope, skill)

    store = store if store is not None else InMemoryVerificationStore()
    judge = judge if judge is not None else net_effect_judge()

    repairs = 0
    regressions = 0
    decisive: list[int] = []  # 1 = repair, 0 = regression (neutrals carry no net-effect signal)
    for instance in held_out_set:
        without_output, with_output = runner.rollout(skill, instance)
        scored = _grade(
            judge,
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

    net_effect = repairs - regressions
    held_out_n = len(held_out_set)
    # Same gate as promotion: repair-fraction CI lower bound > PROMOTION_RATE_FLOOR (0.5) ⇒
    # confidently net-positive (repairs more often than regressions). A drifted net-negative
    # skill (repair fraction <= 0.5) fails and is demoted.
    ci_low, ci_high = bootstrap_ci(decisive, B=bootstrap_b, seed=seed)

    still_good = ci_low > PROMOTION_RATE_FLOOR
    when = _now()
    verdict_value = (
        SkillVerificationVerdict.PASS if still_good else SkillVerificationVerdict.FAIL
    )

    verification = SkillVerification(
        verification_id=_new_verification_id(),
        skill_id=skill.skill_id,
        cohort_id=cohort_id,
        kind=SkillVerificationKind.REVERIFICATION,
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

    if still_good:
        # Stays active; just refresh last_verified_at (no promoted_at change).
        store.set_status(skill, SkillStatus.ACTIVE, when=when)
    else:
        store.set_status(skill, SkillStatus.QUARANTINED, when=when)
    store.record(verification)
    return verification
