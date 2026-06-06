"""Tests for GrammarNode enum, GRAMMAR_NODE_META, and GrammarLabel.

No DB required — pure schema tests.
Run: uv run pytest tests/test_grammar_taxonomy.py -v
"""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from rogue.schemas import GRAMMAR_NODE_META, GrammarLabel, GrammarNode


# ---------- Enum integrity ----------


def test_member_count_in_range() -> None:
    """Enum has between 20 and 30 members (contract requirement)."""
    count = len(GrammarNode)
    assert 20 <= count <= 30, f"GrammarNode has {count} members; expected 20–30."


def test_values_are_lowercase_snake_case() -> None:
    """All enum values are lowercase snake_case with no spaces or uppercase letters."""
    pattern = re.compile(r"^[a-z][a-z0-9_]*$")
    bad = [m for m in GrammarNode if not pattern.match(m.value)]
    assert not bad, f"Non-snake_case values: {[m.value for m in bad]}"


def test_values_are_unique() -> None:
    """All enum values are unique (enum itself enforces this, but be explicit)."""
    values = [m.value for m in GrammarNode]
    assert len(values) == len(set(values)), "Duplicate enum values found."


# ---------- META completeness ----------


def test_every_member_has_meta_entry() -> None:
    """Every GrammarNode member must appear in GRAMMAR_NODE_META."""
    missing = [m for m in GrammarNode if m not in GRAMMAR_NODE_META]
    assert not missing, f"Missing META entries for: {missing}"


def test_meta_description_non_empty() -> None:
    """Every META entry has a non-empty 'description' string."""
    bad = [
        m
        for m, meta in GRAMMAR_NODE_META.items()
        if not meta.get("description", "").strip()
    ]
    assert not bad, f"Empty description in META for: {bad}"


def test_meta_derivation_non_empty() -> None:
    """Every META entry has a non-empty 'derivation' string (consumed by Engineer 3)."""
    bad = [
        m
        for m, meta in GRAMMAR_NODE_META.items()
        if not meta.get("derivation", "").strip()
    ]
    assert not bad, f"Empty derivation in META for: {bad}"


def test_no_extra_meta_keys() -> None:
    """GRAMMAR_NODE_META contains no keys beyond the enum members."""
    extra = [k for k in GRAMMAR_NODE_META if k not in set(GrammarNode)]
    assert not extra, f"Extra META keys not in enum: {extra}"


# ---------- Required cross-family nodes exist ----------


REQUIRED_CROSS_FAMILY = {
    GrammarNode.AUTHORITY_FRAME,
    GrammarNode.LANGUAGE_SHIFT,
    GrammarNode.ENCODING_OBFUSCATION,
    GrammarNode.STRUCTURED_OUTPUT,
    GrammarNode.MULTI_TURN_ESCALATION,
}


def test_required_cross_family_nodes_present() -> None:
    """The five mandated cross-family nodes must be present in the enum."""
    missing = REQUIRED_CROSS_FAMILY - set(GrammarNode)
    assert not missing, f"Required cross-family nodes missing: {missing}"


# ---------- GrammarLabel validation ----------


def test_grammar_label_basic_round_trip() -> None:
    """GrammarLabel constructs and serialises back to the same values."""
    label = GrammarLabel(
        primitive_id="01HXYZ123456789ABCDEFGHIJK",
        node=GrammarNode.AUTHORITY_FRAME,
    )
    assert label.primitive_id == "01HXYZ123456789ABCDEFGHIJK"
    assert label.node is GrammarNode.AUTHORITY_FRAME
    assert label.source == "heuristic"
    assert label.confidence == 1.0


def test_grammar_label_explicit_fields() -> None:
    """GrammarLabel accepts all optional fields."""
    label = GrammarLabel(
        primitive_id="abc123",
        node=GrammarNode.ENCODING_OBFUSCATION,
        source="llm",
        confidence=0.87,
    )
    assert label.source == "llm"
    assert abs(label.confidence - 0.87) < 1e-9


def test_grammar_label_json_round_trip() -> None:
    """GrammarLabel serialises to JSON and deserialises without loss."""
    label = GrammarLabel(
        primitive_id="test-id-001",
        node=GrammarNode.MULTI_TURN_ESCALATION,
        source="manual",
        confidence=0.95,
    )
    serialised = label.model_dump()
    restored = GrammarLabel(**serialised)
    assert restored.node is GrammarNode.MULTI_TURN_ESCALATION
    assert restored.source == "manual"
    assert abs(restored.confidence - 0.95) < 1e-9


def test_grammar_label_invalid_source_rejected() -> None:
    """GrammarLabel rejects an invalid source value."""
    with pytest.raises(ValidationError):
        GrammarLabel(
            primitive_id="abc",
            node=GrammarNode.ROLE_HIJACK,
            source="random_bad_value",  # type: ignore[arg-type]
        )


def test_grammar_label_confidence_out_of_range_rejected() -> None:
    """GrammarLabel rejects confidence outside [0, 1]."""
    with pytest.raises(ValidationError):
        GrammarLabel(
            primitive_id="abc",
            node=GrammarNode.EXFILTRATION,
            confidence=1.5,
        )

    with pytest.raises(ValidationError):
        GrammarLabel(
            primitive_id="abc",
            node=GrammarNode.EXFILTRATION,
            confidence=-0.1,
        )


def test_grammar_label_empty_primitive_id_rejected() -> None:
    """GrammarLabel rejects an empty primitive_id."""
    with pytest.raises(ValidationError):
        GrammarLabel(primitive_id="", node=GrammarNode.DIRECT_OVERRIDE)


# ---------- Importability from rogue.schemas ----------


def test_importable_from_rogue_schemas() -> None:
    """GrammarNode, GRAMMAR_NODE_META, and GrammarLabel are importable from rogue.schemas."""
    import rogue.schemas as s  # noqa: PLC0415

    assert hasattr(s, "GrammarNode")
    assert hasattr(s, "GRAMMAR_NODE_META")
    assert hasattr(s, "GrammarLabel")
    assert s.GrammarNode is GrammarNode
    assert s.GRAMMAR_NODE_META is GRAMMAR_NODE_META
    assert s.GrammarLabel is GrammarLabel


# ---------- Spot-checks on specific nodes ----------


def test_family_mirroring_nodes_present() -> None:
    """All 11 family-mirroring nodes expected by the contract are present."""
    expected_mirroring = {
        GrammarNode.ROLE_HIJACK,
        GrammarNode.DAN_PERSONA,
        GrammarNode.POLICY_ROLEPLAY,
        GrammarNode.REFUSAL_SUPPRESSION,
        GrammarNode.DIRECT_OVERRIDE,
        GrammarNode.SYSTEM_PROMPT_LEAK,
        GrammarNode.TRAINING_DATA_EXTRACTION,
        GrammarNode.INDIRECT_INJECTION,
        GrammarNode.TOOL_INVOCATION,
        GrammarNode.CHAIN_OF_THOUGHT_HIJACK,
        GrammarNode.MULTIMODAL,
    }
    missing = expected_mirroring - set(GrammarNode)
    assert not missing, f"Family-mirroring nodes missing: {missing}"


def test_node_values_match_names_where_applicable() -> None:
    """For family-mirroring nodes, the value should closely track the family name."""
    # DIRECT_OVERRIDE is a deliberate abbreviation of direct_instruction_override —
    # that's by design; just verify it resolves without error.
    assert GrammarNode("direct_override") is GrammarNode.DIRECT_OVERRIDE
    assert GrammarNode("authority_frame") is GrammarNode.AUTHORITY_FRAME
    assert GrammarNode("encoding_obfuscation") is GrammarNode.ENCODING_OBFUSCATION


def test_meta_derivation_references_slot_keys_for_cross_family() -> None:
    """Cross-family nodes should reference actual payload_slot keys in their derivation."""
    slot_key_nodes = {
        GrammarNode.AUTHORITY_FRAME: "authority_claim",
        GrammarNode.ENCODING_OBFUSCATION: "encoding_scheme",
        GrammarNode.STRUCTURED_OUTPUT: "target_output_format",
        GrammarNode.TRIGGER_BACKDOOR: "trigger_phrase",
        GrammarNode.EXFILTRATION: "exfil_destination",
    }
    for node, slot_key in slot_key_nodes.items():
        derivation = GRAMMAR_NODE_META[node]["derivation"]
        assert slot_key in derivation, (
            f"Expected slot key '{slot_key}' in derivation of {node.value!r}, "
            f"got: {derivation!r}"
        )
