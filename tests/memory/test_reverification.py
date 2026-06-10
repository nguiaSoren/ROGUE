"""Scheduled re-verification (Section C, continuous) — drift demotes, healthy stays."""

from __future__ import annotations

import pytest

from rogue.db.models import (
    SkillStatus,
    SkillVerificationKind,
    SkillVerificationVerdict,
)
from rogue.memory.promotion import FakeRolloutRunner, InMemoryVerificationStore
from rogue.memory.reverification import reverify_skill
from tests.memory.conftest import stub_net_effect_judge


def _held_out(n: int) -> list[dict]:
    return [{"task": f"t{i}", "expected_outcome": "ok"} for i in range(n)]


def test_drifted_active_skill_demotes_to_quarantined(skill_factory):
    skill = skill_factory(skill_id="skill-rv", status=SkillStatus.ACTIVE)
    store = InMemoryVerificationStore()
    runner = FakeRolloutRunner(["regression"])  # the skill now hurts
    v = reverify_skill(
        skill, "team-a", _held_out(20),
        runner=runner, judge=stub_net_effect_judge, store=store,
    )
    assert v.kind is SkillVerificationKind.REVERIFICATION
    assert v.verdict is SkillVerificationVerdict.FAIL
    assert skill.status is SkillStatus.QUARANTINED
    assert len(store.verifications) == 1


def test_healthy_active_skill_stays_active(skill_factory):
    skill = skill_factory(skill_id="skill-rv2", status=SkillStatus.ACTIVE)
    store = InMemoryVerificationStore()
    runner = FakeRolloutRunner(["repair"])
    v = reverify_skill(
        skill, "team-a", _held_out(20),
        runner=runner, judge=stub_net_effect_judge, store=store,
    )
    assert v.verdict is SkillVerificationVerdict.PASS
    assert skill.status is SkillStatus.ACTIVE
    assert skill.last_verified_at is not None


def test_reverify_only_accepts_active_skills(skill_factory):
    candidate = skill_factory(skill_id="skill-cand", status=SkillStatus.CANDIDATE)
    with pytest.raises(ValueError):
        reverify_skill(
            candidate, "team-a", _held_out(5),
            runner=FakeRolloutRunner(["repair"]), judge=stub_net_effect_judge,
            store=InMemoryVerificationStore(),
        )
