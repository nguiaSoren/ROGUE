"""Verification compute economics (Section D) — the N×M pruning + partition invariant."""

from __future__ import annotations

from rogue.memory.economics import (
    DEFAULT_RETRIEVAL_THRESHOLD,
    in_cohort_scope,
    is_applicable,
    plan_verifications,
    should_verify,
)


def test_is_applicable_empty_condition_is_applicable(skill_factory):
    s = skill_factory(skill_id="s", applicability_condition={})
    assert is_applicable(s, {"language": "python"}) is True


def test_is_applicable_unknown_key_biases_to_applicable(skill_factory):
    s = skill_factory(skill_id="s", applicability_condition={"language": "python"})
    # Profile doesn't mention 'language' → unknown → applicable (no silent skip).
    assert is_applicable(s, {"domain": "web"}) is True


def test_is_applicable_present_and_unmet_is_inapplicable(skill_factory):
    s = skill_factory(skill_id="s", applicability_condition={"language": "python"})
    assert is_applicable(s, {"language": "rust"}) is False


def test_is_applicable_list_intersection(skill_factory):
    s = skill_factory(skill_id="s", applicability_condition={"framework": ["fastapi", "flask"]})
    assert is_applicable(s, {"framework": "fastapi"}) is True
    assert is_applicable(s, {"framework": ["django"]}) is False


def test_should_verify_threshold():
    from rogue.db.models import Skill  # noqa: F401

    class _S:
        skill_id = "x"

    assert should_verify(_S(), DEFAULT_RETRIEVAL_THRESHOLD) is True
    assert should_verify(_S(), DEFAULT_RETRIEVAL_THRESHOLD - 1) is False


def test_in_cohort_scope(skill_factory):
    s = skill_factory(skill_id="s", cohort_id="team-a", trust_domain="domain-a")
    assert in_cohort_scope(s, "team-a") is True
    assert in_cohort_scope(s, "team-b") is False
    assert in_cohort_scope(s, "team-a", "domain-b") is False


def test_plan_prunes_to_retrieved_applicable_scoped(skill_factory):
    """An N×M grid prunes to retrieved-often × applicable × scoped; planned < naive."""
    # 3 skills across 2 cohorts.
    s_a = skill_factory(
        skill_id="s-a", cohort_id="team-a",
        applicability_condition={"language": "python"},
    )
    s_b = skill_factory(skill_id="s-b", cohort_id="team-b")
    s_a_lowpressure = skill_factory(skill_id="s-a-lp", cohort_id="team-a")

    candidates = [s_a, s_b, s_a_lowpressure]
    cohorts = ["team-a", "team-b"]

    retrieval_counts = {
        "s-a": 10,        # high pressure
        "s-b": 10,        # high pressure
        "s-a-lp": 1,      # below threshold → pruned by lazy gate
    }
    cohort_profiles = {
        "team-a": {"language": "python"},  # s-a applicable
        "team-b": {"language": "go"},
    }

    plan = plan_verifications(
        candidates, cohorts, retrieval_counts, cohort_profiles, threshold=5
    )

    # Surviving pairs: (s-a, team-a) and (s-b, team-b) only.
    surviving = {(s.skill_id, c) for s, c in plan.pairs}
    assert surviving == {("s-a", "team-a"), ("s-b", "team-b")}
    assert plan.planned == 2
    assert plan.naive == len(candidates) * len(cohorts) == 6
    assert plan.planned < plan.naive
    assert plan.reduction_factor == 3.0


def test_plan_partition_invariant(skill_factory):
    """planned + Σpruned == naive, and each pruned pair is attributed once."""
    s_a = skill_factory(
        skill_id="s-a", cohort_id="team-a",
        applicability_condition={"language": "python"},
    )
    s_b = skill_factory(skill_id="s-b", cohort_id="team-b")
    s_a_lp = skill_factory(skill_id="s-a-lp", cohort_id="team-a")
    candidates = [s_a, s_b, s_a_lp]
    cohorts = ["team-a", "team-b"]

    plan = plan_verifications(
        candidates, cohorts,
        retrieval_counts={"s-a": 10, "s-b": 10, "s-a-lp": 1},
        cohort_profiles={"team-a": {"language": "python"}, "team-b": {"language": "go"}},
        threshold=5,
    )
    total_pruned = (
        plan.pruned_inapplicable
        + plan.pruned_out_of_scope
        + plan.pruned_low_pressure
    )
    assert plan.planned + total_pruned == plan.naive


def test_plan_attributes_to_first_filter_scope_before_applicability(skill_factory):
    """Off-cohort pairs are pruned by SCOPE (first), not applicability/lazy-gate."""
    s_a = skill_factory(
        skill_id="s-a", cohort_id="team-a",
        applicability_condition={"language": "rust"},  # would be inapplicable to team-b
    )
    plan = plan_verifications(
        [s_a], ["team-a", "team-b"],
        retrieval_counts={"s-a": 10},
        cohort_profiles={"team-a": {"language": "python"}, "team-b": {"language": "python"}},
        threshold=5,
    )
    # team-b pair pruned by SCOPE (skill is team-a); team-a pair pruned by APPLICABILITY
    # (condition wants rust, profile is python).
    assert plan.pruned_out_of_scope == 1
    assert plan.pruned_inapplicable == 1
    assert plan.planned == 0
    assert plan.planned + plan.pruned_out_of_scope + plan.pruned_inapplicable + plan.pruned_low_pressure == 2
