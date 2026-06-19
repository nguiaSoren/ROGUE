"""Verified-promotion gate (Section C) — THE CI canary.

Adversarial focus:
- admit IFF the bootstrap-CI lower bound > 0 (a net-positive mix that is too noisy
  to clear 0 is NOT admitted);
- a DEGRADING fixture is rejected (verdict=fail) and stays a candidate;
- a skill_verifications(kind=promotion) row is ALWAYS written (admit and reject);
- popularity is NOT a ranking signal.
"""

from __future__ import annotations

from rogue.db.models import (
    SkillStatus,
    SkillVerificationKind,
    SkillVerificationVerdict,
)
from rogue.memory.promotion import (
    RANKING_SIGNALS,
    FakeRolloutRunner,
    InMemoryVerificationStore,
    evaluate_promotion,
)

from tests.memory.conftest import stub_net_effect_judge


def _held_out(n: int) -> list[dict]:
    return [{"task": f"t{i}", "expected_outcome": "ok"} for i in range(n)]


def _candidate(skill_factory, status=SkillStatus.CANDIDATE):
    return skill_factory(skill_id="skill-promo", status=status)


def test_net_positive_skill_is_admitted_when_ci_lb_above_floor(skill_factory):
    """All-repair rollouts → repair-fraction CI-lb > 0.5 → admit, status→active, verdict=pass."""
    skill = _candidate(skill_factory)
    store = InMemoryVerificationStore()
    runner = FakeRolloutRunner(["repair"])  # cycles → every instance a repair
    v = evaluate_promotion(
        skill, "team-a", _held_out(20),
        runner=runner, judge=stub_net_effect_judge, store=store,
    )
    assert v.verdict is SkillVerificationVerdict.PASS
    assert v.ci_low > 0.5
    assert v.kind is SkillVerificationKind.PROMOTION
    assert skill.status is SkillStatus.ACTIVE
    assert skill.promoted_at is not None
    # The audit row was written.
    assert len(store.verifications) == 1
    assert store.verifications[0].verdict is SkillVerificationVerdict.PASS


def test_degrading_skill_is_rejected_and_stays_candidate(skill_factory):
    """All-regression rollouts → CI-lb ≤ 0 → reject, verdict=fail, stays candidate."""
    skill = _candidate(skill_factory)
    store = InMemoryVerificationStore()
    runner = FakeRolloutRunner(["regression"])
    v = evaluate_promotion(
        skill, "team-a", _held_out(20),
        runner=runner, judge=stub_net_effect_judge, store=store,
    )
    assert v.verdict is SkillVerificationVerdict.FAIL
    assert v.ci_low <= 0.0
    assert v.regressions == 20 and v.repairs == 0
    assert v.net_effect == -20.0
    assert skill.status is SkillStatus.CANDIDATE, "a rejected skill must NOT be promoted"
    assert skill.promoted_at is None
    # The reject is ALSO persisted (both sides go to the audit spine).
    assert len(store.verifications) == 1
    assert store.verifications[0].verdict is SkillVerificationVerdict.FAIL


def test_promote_decision_exactly_tracks_ci_low_gt_zero(skill_factory):
    """The promote/reject decision must be exactly ``ci_low > 0.5`` (the gate's contract).

    The gate admits IFF the bootstrap-CI lower bound of the decisive {0,1} (repair=1)
    repair-fraction vector clears 0.5 (repairs confidently more often than regressions).
    Asserted across a sweep so the decision can never silently drift away from its own CI.
    """
    for r in range(0, 21):
        skill = _candidate(skill_factory)
        store = InMemoryVerificationStore()
        # Build a runner whose first r decisive instances repair, the rest regress.
        outcomes = ["repair"] * r + ["regression"] * (20 - r)
        runner = FakeRolloutRunner(outcomes if outcomes else ["neutral"])
        v = evaluate_promotion(
            skill, "team-a", _held_out(20),
            runner=runner, judge=stub_net_effect_judge, store=store,
        )
        promoted = skill.status is SkillStatus.ACTIVE
        assert promoted == (v.ci_low > 0.5), f"r={r}: decision must track ci_low>0.5"
        assert (v.verdict is SkillVerificationVerdict.PASS) == promoted


def test_net_negative_skill_is_rejected(skill_factory):
    """A clearly net-NEGATIVE skill must NOT clear the gate (the consummation contract).

    The gate bootstraps the SIGNED per-instance net-effect vector (+1/-1/0); its mean is
    net-effect-per-instance, so CI-lb > 0 means "repairs MORE OFTEN than regressions",
    not merely "some repairs > 0". A skill with 4 repairs / 16 regressions (net -12) has a
    confidently-NEGATIVE mean → CI-lb <= 0 → rejected. (Regression test for the earlier bug
    where the gate bootstrapped a {0,1} decisive-rate vector and admitted net-negative skills.)
    """
    skill = _candidate(skill_factory)
    store = InMemoryVerificationStore()
    outcomes = ["repair"] * 4 + ["regression"] * 16
    runner = FakeRolloutRunner(outcomes)
    v = evaluate_promotion(
        skill, "team-a", _held_out(20),
        runner=runner, judge=stub_net_effect_judge, store=store,
    )
    assert v.repairs == 4 and v.regressions == 16
    assert v.net_effect == -12.0, "this skill is unambiguously net-NEGATIVE"
    # FIXED behaviour: a net-negative skill cannot clear the gate (repair fraction 0.2 ≤ 0.5).
    assert v.ci_low <= 0.5, "the repair-fraction CI lower bound must be <= 0.5 for net-negative"
    assert v.verdict is SkillVerificationVerdict.FAIL
    assert skill.status is SkillStatus.CANDIDATE


def test_judge_object_with_grade_is_supported(skill_factory):
    """The LIVE path: net_effect_judge() returns an OBJECT with .grade (not a bare callable).

    Regression for the bug where evaluate_promotion called ``judge(...)`` directly — fine for
    the callable test stubs, but TypeError on the real MemoryJudge. The gate must accept either.
    """
    from types import SimpleNamespace

    class _ObjJudge:  # mimics MemoryJudge: a .grade_sync method, not __call__
        def grade_sync(self, **_kw):
            return SimpleNamespace(verdict="repair")

    skill = _candidate(skill_factory)
    v = evaluate_promotion(
        skill, "team-a", _held_out(20),
        runner=FakeRolloutRunner(["repair"]), judge=_ObjJudge(),
        store=InMemoryVerificationStore(),
    )
    assert v.repairs == 20 and v.verdict is SkillVerificationVerdict.PASS
    assert skill.status is SkillStatus.ACTIVE


def test_neutrals_carry_no_signal(skill_factory):
    """All-neutral rollouts → empty decisive vector → CI (0,0) → not promoted."""
    skill = _candidate(skill_factory)
    store = InMemoryVerificationStore()
    runner = FakeRolloutRunner(["neutral"])
    v = evaluate_promotion(
        skill, "team-a", _held_out(10),
        runner=runner, judge=stub_net_effect_judge, store=store,
    )
    assert v.repairs == 0 and v.regressions == 0
    assert v.held_out_n == 10
    assert v.verdict is SkillVerificationVerdict.FAIL
    assert skill.status is SkillStatus.CANDIDATE


def test_decision_is_deterministic(skill_factory):
    """Same seed → identical CI both runs (bootstrap is seeded)."""
    runs = []
    for _ in range(2):
        skill = _candidate(skill_factory)
        runner = FakeRolloutRunner(["repair", "repair", "regression"])
        v = evaluate_promotion(
            skill, "team-a", _held_out(15),
            runner=runner, judge=stub_net_effect_judge, store=InMemoryVerificationStore(),
        )
        runs.append((v.ci_low, v.ci_high, v.verdict))
    assert runs[0] == runs[1]


def test_popularity_is_not_a_ranking_signal():
    assert "popularity" not in RANKING_SIGNALS
    assert RANKING_SIGNALS == frozenset(
        {"net_effect", "regression_rate", "leakage_score", "combination_risk"}
    )
    # There is also no popularity field on the Skill ORM.
    from rogue.db.models import Skill

    assert "popularity" not in Skill.__table__.columns
