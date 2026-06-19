"""Family re-aiming — point a harvested attack family at a specific policy rule (build-04 §3.2).

Pipeline position (build-04 §3, the part only ROGUE can do):

    PolicyRule  +  corpus(list[AttackPrimitive])  ->  build_attack_pack  ->  RuleAttackPack

No new attacks are invented. A *re-aimed* family is an existing harvested
:class:`AttackPrimitive` with (1) its goal slot overridden to the rule's
``elicitation_target`` and (2) its ``short_description`` rewritten to name that
target — because the judge reads ``short_description`` as the "Attack goal"
(``reproduce/judge.py:393``), so re-aiming the description re-aims what the judge
scores against. Slot substitution is REUSE (``reproduce.instantiator.render``);
candidate selection is REUSE (``packs.filter_attacks`` / ``packs.load_pack``).

Two explicit, reviewable tables drive the mapping (build-04 §3.2 "build the
family→breach_type map as a reviewable table, not buried heuristics"):

  * ``FAMILY_BREACH_TYPE`` — every offense family → the consummation shape it
    naturally exercises. The classifier of which families CAN exercise a rule.
  * ``BREACH_TYPE_FAMILIES`` — the inverse, the candidate-family allow-list per
    breach type, ordered most-on-target first. ``build_attack_pack`` selects
    from this set, intersected with the corpus actually available.

Re-aiming is DETERMINISTIC (build-04 §3.2 decision): the goal slot is overridden
and the description rewritten from a template — cheap, reproducible, no live
call, fully auditable. An optional offline LLM ``short_description`` rewrite is
left as a documented future hook (it would be stored on the primitive, audited);
it is intentionally NOT wired here so the gate runs with zero model calls.
"""

from __future__ import annotations

import logging

from rogue.packs import filter_attacks
from rogue.schemas import AttackFamily, AttackPrimitive
from rogue.schemas.governance import BreachType, PolicyRule, RuleAttackPack

logger = logging.getLogger("rogue.governance.reaim")

__all__ = [
    "FAMILY_BREACH_TYPE",
    "BREACH_TYPE_FAMILIES",
    "GOAL_SLOT_BY_FAMILY",
    "DEFAULT_GOAL_SLOT",
    "build_attack_pack",
    "reaim_primitive",
]


# ---------------------------------------------------------------------------
# Reviewable table 1 — which consummation shape each offense family exercises.
# ---------------------------------------------------------------------------
# This is the join between an AttackFamily and a BreachType. It is the explicit,
# eyeballable contract build-04 §3.2 asks for: every family ROGUE harvests is
# assigned the breach shape it naturally drives. Reviewers correct THIS table,
# not buried heuristics. (No AUTHORITY_IMPERSONATION family exists — authority
# impersonation maps onto ROLE_HIJACK + DIRECT_INSTRUCTION_OVERRIDE per §3.2.)
FAMILY_BREACH_TYPE: dict[AttackFamily, BreachType] = {
    # Persona / role-play / hypothetical framing → coax out a protected datum.
    AttackFamily.POLICY_ROLEPLAY: BreachType.INFORMATION_DISCLOSURE,
    AttackFamily.DAN_PERSONA: BreachType.INFORMATION_DISCLOSURE,
    AttackFamily.ROLE_HIJACK: BreachType.INFORMATION_DISCLOSURE,
    # Extraction families → pull out secrets / PII (disclosure).
    AttackFamily.TRAINING_DATA_EXTRACTION: BreachType.INFORMATION_DISCLOSURE,
    AttackFamily.SYSTEM_PROMPT_LEAK: BreachType.INFORMATION_DISCLOSURE,
    AttackFamily.MULTI_TURN_GRADIENT: BreachType.INFORMATION_DISCLOSURE,
    AttackFamily.MULTI_TURN_PERSONA_CHAIN: BreachType.INFORMATION_DISCLOSURE,
    # Override / instruction families → make the agent take a forbidden action.
    AttackFamily.DIRECT_INSTRUCTION_OVERRIDE: BreachType.UNAUTHORIZED_ACTION,
    AttackFamily.TOOL_USE_HIJACK: BreachType.UNAUTHORIZED_ACTION,
    AttackFamily.INDIRECT_PROMPT_INJECTION: BreachType.UNAUTHORIZED_ACTION,
    # CoT-hijack / refusal-suppression → coax a forbidden opinion/action via
    # "reason step by step" framing (used for the no-legal-opinions rule).
    AttackFamily.CHAIN_OF_THOUGHT_HIJACK: BreachType.UNAUTHORIZED_ACTION,
    AttackFamily.REFUSAL_SUPPRESSION: BreachType.UNAUTHORIZED_ACTION,
    # Encoding/obfuscation, language-switching, multimodal → classic harm/
    # capability-transfer carriers.
    AttackFamily.OBFUSCATION_ENCODING: BreachType.CAPABILITY_TRANSFER,
    AttackFamily.LANGUAGE_SWITCHING: BreachType.CAPABILITY_TRANSFER,
    AttackFamily.MULTIMODAL_INJECTION: BreachType.CAPABILITY_TRANSFER,
}


def _invert_to_ordered_families() -> dict[BreachType, list[AttackFamily]]:
    """Build the per-breach-type candidate family list from ``FAMILY_BREACH_TYPE``.

    Insertion order of ``FAMILY_BREACH_TYPE`` is the priority order (most-on-
    target families are listed first within each breach type), so the inverse
    preserves it. Keeping the inverse derived — not a second hand-maintained
    table — means the two tables can never disagree.
    """
    out: dict[BreachType, list[AttackFamily]] = {bt: [] for bt in BreachType}
    for family, breach_type in FAMILY_BREACH_TYPE.items():
        out[breach_type].append(family)
    return out


# ---------------------------------------------------------------------------
# Reviewable table 2 — candidate families per breach type (derived inverse).
# ---------------------------------------------------------------------------
BREACH_TYPE_FAMILIES: dict[BreachType, list[AttackFamily]] = _invert_to_ordered_families()


# ---------------------------------------------------------------------------
# Reviewable table 3 — which payload slot carries the attack's GOAL per family.
# ---------------------------------------------------------------------------
# Most harvested families use `target_behavior` as the goal slot, but a few name
# it differently (DIO carries the goal in `poison_payload`, TDE in
# `target_secret`). Overriding the wrong slot would leave the original generic
# goal in place and re-aim nothing — so the goal slot is an explicit table too.
GOAL_SLOT_BY_FAMILY: dict[AttackFamily, str] = {
    AttackFamily.DIRECT_INSTRUCTION_OVERRIDE: "poison_payload",
    AttackFamily.TRAINING_DATA_EXTRACTION: "target_secret",
}
DEFAULT_GOAL_SLOT = "target_behavior"


def _allowed_families(rule: PolicyRule) -> list[AttackFamily]:
    """The candidate families for a rule = those mapped to its breach type."""
    return BREACH_TYPE_FAMILIES.get(rule.breach_type, [])


def reaim_primitive(primitive: AttackPrimitive, rule: PolicyRule) -> AttackPrimitive:
    """Return a COPY of ``primitive`` re-aimed at ``rule`` (deterministic).

    Two overrides, both auditable on the returned primitive:
      1. the family's goal slot (``GOAL_SLOT_BY_FAMILY``, default
         ``target_behavior``) is set to ``rule.elicitation_target`` so
         ``reproduce.instantiator.render`` substitutes the rule's goal into the
         payload at scan time;
      2. ``short_description`` is rewritten to name the rule's elicitation target
         — the judge reads this as the "Attack goal" (``judge.py:393``), so the
         re-aimed description is what the judge scores the response against.

    The source primitive is never mutated (``model_copy``); ``derived_from_
    primitive_id`` records the parent and ``synthesized=True`` keeps re-aimed
    rows separable from harvested ones in the matrix, consistent with §10.7.
    """
    goal_slot = GOAL_SLOT_BY_FAMILY.get(primitive.family, DEFAULT_GOAL_SLOT)
    new_slots = dict(primitive.payload_slots)
    new_slots[goal_slot] = rule.elicitation_target

    new_description = (
        f"Re-aimed at policy rule {rule.rule_id} ({rule.breach_type.value}): "
        f"make the agent {rule.elicitation_target}. "
        f"Base technique: {primitive.title}."
    )
    # short_description is capped at 2_000 chars on the schema; elicitation
    # targets are one phrase, so this never approaches the cap, but guard anyway.
    new_description = new_description[:2_000]

    return primitive.model_copy(
        update={
            "payload_slots": new_slots,
            "short_description": new_description,
            "synthesized": True,
            "derived_from_primitive_id": primitive.primitive_id,
        }
    )


def build_attack_pack(rule: PolicyRule, corpus: list[AttackPrimitive]) -> RuleAttackPack:
    """Select + re-aim corpus primitives into a :class:`RuleAttackPack` for ``rule``.

    1. **Select** candidate primitives whose family is in the rule's allow-list
       (``BREACH_TYPE_FAMILIES[rule.breach_type]``) via REUSE of
       ``packs.filter_attacks`` (family-slug match).
    2. **Re-aim** each via :func:`reaim_primitive` (deterministic slot override +
       description rewrite).

    ``coverage_score`` / ``coverage_status`` are left ``None`` — area §5
    (``governance.coverage``) fills them. Returns an empty pack (not an error)
    when the corpus has no family for this breach type, so a caller can report
    honestly that the rule is un-exercised rather than crash.

    Args:
        rule: the typed policy rule to aim at.
        corpus: the harvested primitives to draw from (e.g.
            ``packs.load_pack("aggressive")`` or a DB query by family).
    """
    allowed = _allowed_families(rule)
    allowed_slugs = [f.value for f in allowed]
    candidates = filter_attacks(corpus, allowed_slugs)

    if not candidates:
        logger.warning(
            "build_attack_pack: no corpus primitive matched rule %s (breach_type=%s, "
            "allowed families=%s) — emitting empty pack",
            rule.rule_id,
            rule.breach_type.value,
            allowed_slugs,
        )

    primitives = [reaim_primitive(p, rule) for p in candidates]
    return RuleAttackPack(rule_id=rule.rule_id, primitives=primitives)
