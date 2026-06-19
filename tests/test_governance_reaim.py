"""build-04 §3.2 — build_attack_pack re-aims harvested families at a rule (offline).

EXIT-GATE §3 (re-aim half): with a saved corpus fixture, ``build_attack_pack``
returns a NON-EMPTY :class:`RuleAttackPack` per rule whose primitives'
``short_description`` names the rule's elicitation target and whose families are
in the rule's allowed set. Re-aiming is deterministic; slot substitution reuses
``reproduce.instantiator.render``. No network, no API key, no paid script.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rogue.governance.reaim import (
    BREACH_TYPE_FAMILIES,
    DEFAULT_GOAL_SLOT,
    FAMILY_BREACH_TYPE,
    GOAL_SLOT_BY_FAMILY,
    build_attack_pack,
    reaim_primitive,
)
from rogue.reproduce.instantiator import render
from rogue.schemas import AttackPrimitive
from rogue.schemas.deployment_config import demo_deployment_configs
from rogue.schemas.governance import BreachType, ClientPolicy, RuleAttackPack

FIX = Path(__file__).parent / "fixtures" / "governance"


@pytest.fixture
def corpus() -> list[AttackPrimitive]:
    raw = json.loads((FIX / "mini_corpus.json").read_text(encoding="utf-8"))
    return [AttackPrimitive.model_validate(r) for r in raw]


@pytest.fixture
def policy() -> ClientPolicy:
    return ClientPolicy.model_validate_json((FIX / "sample_policy.json").read_text("utf-8"))


# ---- the two reviewable tables stay self-consistent --------------------------


def test_inverse_table_is_consistent_with_forward_table() -> None:
    for family, breach_type in FAMILY_BREACH_TYPE.items():
        assert family in BREACH_TYPE_FAMILIES[breach_type]
    for breach_type, families in BREACH_TYPE_FAMILIES.items():
        for family in families:
            assert FAMILY_BREACH_TYPE[family] == breach_type


def test_every_breach_type_has_candidate_families() -> None:
    for breach_type in (
        BreachType.INFORMATION_DISCLOSURE,
        BreachType.UNAUTHORIZED_ACTION,
        BreachType.CAPABILITY_TRANSFER,
    ):
        assert BREACH_TYPE_FAMILIES[breach_type], breach_type


# ---- the EXIT-GATE assertions ------------------------------------------------


def test_pack_is_non_empty_for_every_rule(corpus, policy) -> None:
    for rule in policy.rules:
        pack = build_attack_pack(rule, corpus)
        assert isinstance(pack, RuleAttackPack)
        assert pack.rule_id == rule.rule_id
        assert pack.primitives, f"empty pack for {rule.rule_id}"


def test_pack_families_are_in_the_rules_allowed_set(corpus, policy) -> None:
    for rule in policy.rules:
        allowed = set(BREACH_TYPE_FAMILIES[rule.breach_type])
        pack = build_attack_pack(rule, corpus)
        for prim in pack.primitives:
            assert prim.family in allowed, (rule.rule_id, prim.family)


def test_short_description_names_the_elicitation_target(corpus, policy) -> None:
    for rule in policy.rules:
        pack = build_attack_pack(rule, corpus)
        for prim in pack.primitives:
            assert rule.elicitation_target in prim.short_description


def test_goal_slot_carries_the_elicitation_target(corpus, policy) -> None:
    """The family's goal slot is overridden to the rule's elicitation target."""
    for rule in policy.rules:
        pack = build_attack_pack(rule, corpus)
        for prim in pack.primitives:
            goal_slot = GOAL_SLOT_BY_FAMILY.get(prim.family, DEFAULT_GOAL_SLOT)
            assert prim.payload_slots.get(goal_slot) == rule.elicitation_target


def test_reaimed_primitive_renders(corpus, policy) -> None:
    """Slot substitution (reproduce.instantiator.render) works on a re-aimed primitive
    and the elicitation target actually lands in the rendered prompt text."""
    cfg = demo_deployment_configs()[0]
    for rule in policy.rules:
        pack = build_attack_pack(rule, corpus)
        for prim in pack.primitives:
            rendered = render(prim, cfg)
            assert rendered.messages
            # the overridden goal slot value is present in resolved_slots
            assert rule.elicitation_target in rendered.resolved_slots.values()


def test_coverage_fields_left_for_section5(corpus, policy) -> None:
    for rule in policy.rules:
        pack = build_attack_pack(rule, corpus)
        assert pack.coverage_score is None
        assert pack.coverage_status is None


# ---- re-aiming is deterministic + non-destructive ----------------------------


def test_reaim_is_deterministic(corpus, policy) -> None:
    rule = policy.rules[0]
    a = build_attack_pack(rule, corpus)
    b = build_attack_pack(rule, corpus)
    assert [p.model_dump() for p in a.primitives] == [p.model_dump() for p in b.primitives]


def test_reaim_does_not_mutate_source_primitive(corpus, policy) -> None:
    rule = policy.rules[0]
    source = corpus[0]
    before = source.model_dump()
    reaim_primitive(source, rule)
    assert source.model_dump() == before


def test_reaimed_primitive_tracks_provenance(corpus, policy) -> None:
    rule = policy.rules[0]
    source = next(
        p for p in corpus if p.family in BREACH_TYPE_FAMILIES[rule.breach_type]
    )
    reaimed = reaim_primitive(source, rule)
    assert reaimed.synthesized is True
    assert reaimed.derived_from_primitive_id == source.primitive_id


def test_empty_pack_when_corpus_lacks_breach_type(policy) -> None:
    """A capability_transfer rule against a disclosure/action-only corpus → empty
    pack, not a crash (honest 'un-exercised' report)."""
    rule = policy.rules[0].model_copy(update={"breach_type": BreachType.CAPABILITY_TRANSFER})
    # corpus with no capability_transfer families
    disclosure_only = [
        AttackPrimitive.model_validate(r)
        for r in json.loads((FIX / "mini_corpus.json").read_text("utf-8"))
    ]
    pack = build_attack_pack(rule, disclosure_only)
    assert pack.primitives == []
