"""Combination-risk graph (Section F) — neighborhood/components/blast-radius +
co-invocation consummation (harmful set quarantines, benign set does nothing)."""

from __future__ import annotations

import pytest

from rogue.db.models import SkillEdgeType, SkillStatus
from rogue.memory.combination import (
    CombinationGraph,
    CompositionResult,
    Edge,
    FakeCoInvocationRunner,
    RolloutOutput,
    UnionFindGraph,
    in_memory_quarantine_fn,
)
from tests.memory.conftest import make_skill


def _seeded_graph() -> UnionFindGraph:
    # Component 1: a-b-c-d (a chain a-b, b-c, c-d). Component 2: x-y (isolated pair).
    return UnionFindGraph([
        Edge("a", "b"),
        Edge("b", "c"),
        Edge("c", "d"),
        Edge("x", "y"),
    ])


def test_neighborhood_k_hops():
    g = _seeded_graph()
    # 1-hop of b: {a, c}; 2-hop adds d.
    assert g.neighborhood("b", 1) == {"a", "c"}
    assert g.neighborhood("b", 2) == {"a", "c", "d"}
    # seed excluded; k<=0 is empty.
    assert "b" not in g.neighborhood("b", 2)
    assert g.neighborhood("b", 0) == set()


def test_blast_radius_is_reachable_set_minus_seed():
    g = _seeded_graph()
    assert g.blast_radius("a") == {"b", "c", "d"}
    assert g.blast_radius("x") == {"y"}
    assert g.blast_radius("unknown") == set()


def test_connected_components_largest_first():
    g = _seeded_graph()
    comps = g.connected_components()
    assert [len(c) for c in comps] == [4, 2]
    assert comps[0] == {"a", "b", "c", "d"}
    assert comps[1] == {"x", "y"}


def test_giant_component():
    cg = CombinationGraph(_seeded_graph())
    assert cg.giant_component() == {"a", "b", "c", "d"}
    assert CombinationGraph(UnionFindGraph()).giant_component() == set()


def test_harmful_co_invocation_writes_composition_edge_and_quarantines():
    skills = [make_skill(skill_id=sid, status=SkillStatus.ACTIVE) for sid in ("a", "b", "c", "d")]
    backend = _seeded_graph()
    written: list = []
    cg = CombinationGraph(
        backend,
        edge_writer=written.append,
        quarantine_fn=in_memory_quarantine_fn(skills),
    )

    runner = FakeCoInvocationRunner(
        {frozenset({"a", "b"}): RolloutOutput(output="harmful composed behavior", breach_id="br-1")}
    )

    class _HarmfulJudge:
        def grade_sync(self, **_kw):
            return type("R", (), {"is_breach": True, "rationale": "produced harm"})()

    result = cg.simulate_co_invocation(
        ["a", "b"], runner=runner, judge=_HarmfulJudge(), risk_score=0.9
    )
    assert isinstance(result, CompositionResult)
    assert result.is_breach is True
    assert result.edge is not None
    assert result.edge.edge_type is SkillEdgeType.COMPOSITION
    assert result.evidence_breach_id == "br-1"
    # A skill_edges(composition) row was written.
    assert len(written) == 1
    assert written[0].edge_type is SkillEdgeType.COMPOSITION
    assert written[0].risk_score == 0.9
    # The neighborhood (whole connected component a-b-c-d) was quarantined.
    assert result.quarantined == {"a", "b", "c", "d"}
    assert all(s.status is SkillStatus.QUARANTINED for s in skills)


def test_benign_co_invocation_writes_nothing_quarantines_nothing():
    skills = [make_skill(skill_id=sid, status=SkillStatus.ACTIVE) for sid in ("a", "b", "c", "d")]
    backend = _seeded_graph()
    written: list = []
    cg = CombinationGraph(
        backend,
        edge_writer=written.append,
        quarantine_fn=in_memory_quarantine_fn(skills),
    )
    runner = FakeCoInvocationRunner(default=RolloutOutput(output="benign output"))

    class _BenignJudge:
        def grade_sync(self, **_kw):
            return type("R", (), {"is_breach": False, "rationale": "no harm produced"})()

    result = cg.simulate_co_invocation(["a", "b"], runner=runner, judge=_BenignJudge())
    assert result.is_breach is False
    assert result.edge is None
    assert result.quarantined == set()
    assert len(written) == 0
    assert all(s.status is SkillStatus.ACTIVE for s in skills)


def test_co_invocation_requires_set_of_at_least_two():
    cg = CombinationGraph(_seeded_graph())

    class _J:
        def grade_sync(self, **_kw):
            return type("R", (), {"is_breach": False})()

    with pytest.raises(ValueError):
        cg.simulate_co_invocation(["a"], runner=FakeCoInvocationRunner(), judge=_J())


def test_quarantine_bounded_by_scope_skill_ids():
    """``scope_skill_ids`` confines the quarantine to a known in-scope set + the set."""
    skills = [make_skill(skill_id=sid, status=SkillStatus.ACTIVE) for sid in ("a", "b", "c", "d")]
    cg = CombinationGraph(
        _seeded_graph(),
        edge_writer=lambda e: None,
        quarantine_fn=in_memory_quarantine_fn(skills),
    )
    runner = FakeCoInvocationRunner(
        {frozenset({"a", "b"}): RolloutOutput(output="harm", breach_id="br")}
    )

    class _H:
        def grade_sync(self, **_kw):
            return type("R", (), {"is_breach": True, "rationale": ""})()

    # Restrict scope to {a, b} — c, d must NOT be quarantined despite being reachable.
    result = cg.simulate_co_invocation(
        ["a", "b"], runner=runner, judge=_H(), scope_skill_ids={"a", "b"}
    )
    assert result.quarantined == {"a", "b"}
    statuses = {s.skill_id: s.status for s in skills}
    assert statuses["a"] is SkillStatus.QUARANTINED
    assert statuses["b"] is SkillStatus.QUARANTINED
    assert statuses["c"] is SkillStatus.ACTIVE
    assert statuses["d"] is SkillStatus.ACTIVE
