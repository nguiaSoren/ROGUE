"""Emergent-taxonomy layer — auto-cluster proposed labels, draft promotion candidates. Deterministic,
no LLM, no DB. The promotion itself stays human-gated; this only surfaces candidates."""

from __future__ import annotations

from datetime import datetime, timezone

from rogue.extract.emergent_taxonomy import (
    cluster_emergent,
    promotion_candidates,
)
from rogue.schemas import (
    AttackFamily,
    AttackPrimitive,
    AttackVector,
    Severity,
    SourceProvenance,
)

_SRC = SourceProvenance(url="https://example.com/x", source_type="other",
                        fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc), archive_hash="abc1234",
                        bright_data_product="fixture")


def _prim(pid: str, label: str | None, fam=AttackFamily.INDIRECT_PROMPT_INJECTION,
          vec=AttackVector.TOOL_OUTPUT) -> AttackPrimitive:
    return AttackPrimitive(
        primitive_id=pid, family=fam, vector=vec, title=f"technique {pid}",
        short_description="a technique from a paper", payload_template="do the thing please now",
        reproducibility_score=5, sources=[_SRC], discovered_at=datetime.now(timezone.utc),
        base_severity=Severity.HIGH, severity_rationale="x",
        taxonomy_fit=("novel" if label else "clear"), emergent_label=label)


def test_labelless_primitives_are_ignored():
    prims = [_prim("prim-000001", None), _prim("prim-000002", None)]
    assert cluster_emergent(prims) == []


def test_fuzzy_labels_cluster_together():
    prims = [
        _prim("prim-000001", "calendar_invite_injection"),
        _prim("prim-000002", "calendar-invite injection"),   # separator variant
        _prim("prim-000003", "injection via calendar invite"),  # word-order + stopword
        _prim("prim-000004", "memory_poisoning"),            # a different pattern
    ]
    clusters = cluster_emergent(prims)
    by_size = {c.count: c for c in clusters}
    assert 3 in by_size and 1 in by_size  # the 3 calendar variants merge; memory_poisoning stands alone
    cal = by_size[3]
    assert set(cal.primitive_ids) == {"prim-000001", "prim-000002", "prim-000003"}
    assert len(cal.variants) >= 2


def test_promotion_candidates_respect_threshold_and_carry_context():
    prims = [_prim(f"prim-{i:06d}", "prompt_leaking_via_error_messages") for i in range(6)]
    prims += [_prim("prim-000099", "one_off_weird_thing")]  # singleton — below threshold
    props = promotion_candidates(prims, min_cluster_size=5)
    assert len(props) == 1
    p = props[0]
    assert p.count == 6
    assert p.proposed_value == "prompt_leaking_via_error_messages"[:40]
    assert p.dominant_family == "indirect_prompt_injection"
    assert p.dominant_vector == "tool_output"
    assert "HUMAN-approved" in p.migration_hint and "never automatic" in p.migration_hint


def test_works_on_plain_dicts_too():
    rows = [
        {"primitive_id": "a1", "emergent_label": "tool_chaining_escalation", "family": "tool_use_hijack", "vector": "user_turn"},
        {"primitive_id": "a2", "emergent_label": "tool-chaining escalation", "family": "tool_use_hijack", "vector": "user_turn"},
    ]
    clusters = cluster_emergent(rows)
    assert len(clusters) == 1 and clusters[0].count == 2
