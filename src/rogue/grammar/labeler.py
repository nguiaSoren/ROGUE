"""Heuristic labeler — assigns GrammarNode labels to AttackPrimitive records.

Derives labels purely from structured fields on :class:`~rogue.grammar.dataset.PrimitiveRecord`
(family, secondary_families, payload_slots, requires_multi_turn, vector).  No LLM calls,
no extra DB hits beyond what ``build_grammar_analysis_dataset`` already fetched.

The mapping rules are lifted directly from ``GRAMMAR_NODE_META[node]["derivation"]`` —
that field is the authoritative spec.  Each rule is documented inline so a reader can
cross-check it against the metadata without grepping.

Cross-family slot mapping (from live-corpus slot survey):
  authority_claim / justification     -> AUTHORITY_FRAME
  role_name / personality_trait       -> PERSONA_CONSTRUCTION (with role_description)
  role_description                    -> FICTIONAL_FRAMING + potential ROLE_HIJACK
  encoding_scheme                     -> ENCODING_OBFUSCATION
  target_output_format / NewResponseFormat -> STRUCTURED_OUTPUT
  tool_name                           -> TOOL_INVOCATION
  exfil_destination                   -> EXFILTRATION
  trigger_phrase                      -> TRIGGER_BACKDOOR
  language                            -> LANGUAGE_SHIFT
  rag_document / poison_payload       -> RAG_POISONING (when indirect_injection family)
  invisible_tag_instruction           -> INVISIBLE_INJECTION
  target_behavior / target_topic      -> TARGET_BEHAVIOR_SPECIFICATION
  requires_multi_turn=True            -> MULTI_TURN_ESCALATION
  vector multimodal_*                 -> MULTIMODAL
  vector rag_document/tool_output     -> INDIRECT_INJECTION
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rogue.grammar.dataset import PrimitiveRecord
from rogue.schemas import GrammarNode

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Family value -> GrammarNode (family-mirroring nodes).
# The mapping intentionally covers every family in AttackFamily; unknown families
# produce nothing (safe default).
_FAMILY_TO_NODE: dict[str, GrammarNode] = {
    "role_hijack": GrammarNode.ROLE_HIJACK,
    "dan_persona": GrammarNode.DAN_PERSONA,
    "policy_roleplay": GrammarNode.POLICY_ROLEPLAY,
    "refusal_suppression": GrammarNode.REFUSAL_SUPPRESSION,
    "direct_instruction_override": GrammarNode.DIRECT_OVERRIDE,
    "system_prompt_leak": GrammarNode.SYSTEM_PROMPT_LEAK,
    "training_data_extraction": GrammarNode.TRAINING_DATA_EXTRACTION,
    "indirect_prompt_injection": GrammarNode.INDIRECT_INJECTION,
    "tool_use_hijack": GrammarNode.TOOL_INVOCATION,
    "chain_of_thought_hijack": GrammarNode.CHAIN_OF_THOUGHT_HIJACK,
    "multimodal_injection": GrammarNode.MULTIMODAL,
    # Multi-turn families -> MULTI_TURN_ESCALATION (structural node, same derivation)
    "multi_turn_gradient": GrammarNode.MULTI_TURN_ESCALATION,
    "multi_turn_persona_chain": GrammarNode.MULTI_TURN_ESCALATION,
    # Encoding / language families
    "obfuscation_encoding": GrammarNode.ENCODING_OBFUSCATION,
    "language_switching": GrammarNode.LANGUAGE_SHIFT,
}

# Alter-ego keywords for the DAN heuristic (role_name slot matching)
_DAN_KEYWORDS = frozenset(["dan", "stan", "aim", "dude", "jailbreak", "evil", "chaos"])

# Families that trigger fictional framing when combined with role_description
_FICTIONAL_FRAMING_FAMILIES = frozenset(
    ["policy_roleplay", "dan_persona", "role_hijack"]
)

# Policy / story keywords in role_description for POLICY_ROLEPLAY heuristic
_POLICY_KEYWORDS = frozenset(
    ["policy", "rules", "guidelines", "fictional", "story", "fiction", "narrative", "game"]
)

# Indirect-injection vector prefixes
_INDIRECT_VECTORS = frozenset(["rag_document", "tool_output"])

# Multi-modal vector prefix
_MULTIMODAL_VECTOR_PREFIX = "multimodal_"


def _slot_present(slots: dict, *keys: str) -> bool:
    """Return True iff any of ``keys`` maps to a non-empty value in ``slots``."""
    for k in keys:
        v = slots.get(k)
        if v and str(v).strip():
            return True
    return False


def _slot_value(slots: dict, key: str) -> str:
    """Return the lowercased string value of a slot, or '' if absent/empty."""
    v = slots.get(key)
    return str(v).strip().lower() if v else ""


def _families_of(record: PrimitiveRecord) -> list[str]:
    """Return primary + all secondary families for a record (lowercase strings)."""
    out = [record.family]
    out.extend(record.secondary_families or [])
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def heuristic_labels(record: PrimitiveRecord) -> set[GrammarNode]:
    """Derive GrammarNode labels from structured PrimitiveRecord fields.

    A primitive routinely gets multiple nodes — that is the point.  The derivation
    is deterministic and requires no DB access beyond what the PrimitiveRecord
    already carries.

    Rules applied (in order; a primitive accumulates ALL that fire):
    1. Family-mirroring: primary + each secondary family -> node via _FAMILY_TO_NODE.
    2. Cross-family slot signals (the analytically interesting nodes).
    3. Flag signals (requires_multi_turn, vector).
    """
    nodes: set[GrammarNode] = set()
    slots = record.payload_slots or {}
    families = _families_of(record)
    family_set = set(families)

    # ------------------------------------------------------------------ #
    # Rule 1: Family → node (family-mirroring + multi-turn/encoding/lang)  #
    # ------------------------------------------------------------------ #
    for fam in families:
        node = _FAMILY_TO_NODE.get(fam)
        if node is not None:
            nodes.add(node)

    # ------------------------------------------------------------------ #
    # Rule 2: Cross-family slot signals                                     #
    # ------------------------------------------------------------------ #

    # AUTHORITY_FRAME: authority_claim OR justification present
    if _slot_present(slots, "authority_claim", "justification"):
        nodes.add(GrammarNode.AUTHORITY_FRAME)

    # ENCODING_OBFUSCATION: encoding_scheme slot (family already handled above)
    if _slot_present(slots, "encoding_scheme"):
        nodes.add(GrammarNode.ENCODING_OBFUSCATION)

    # STRUCTURED_OUTPUT: target_output_format OR NewResponseFormat
    if _slot_present(slots, "target_output_format", "NewResponseFormat"):
        nodes.add(GrammarNode.STRUCTURED_OUTPUT)

    # TOOL_INVOCATION: tool_name slot (family already handled above)
    if _slot_present(slots, "tool_name"):
        nodes.add(GrammarNode.TOOL_INVOCATION)

    # EXFILTRATION: exfil_destination slot
    if _slot_present(slots, "exfil_destination"):
        nodes.add(GrammarNode.EXFILTRATION)

    # TRIGGER_BACKDOOR: trigger_phrase slot
    if _slot_present(slots, "trigger_phrase"):
        nodes.add(GrammarNode.TRIGGER_BACKDOOR)

    # LANGUAGE_SHIFT: language slot (family already handled above)
    if _slot_present(slots, "language"):
        nodes.add(GrammarNode.LANGUAGE_SHIFT)

    # INVISIBLE_INJECTION: invisible_tag_instruction slot
    if _slot_present(slots, "invisible_tag_instruction"):
        nodes.add(GrammarNode.INVISIBLE_INJECTION)

    # RAG_POISONING: (rag_document OR poison_payload) AND indirect_injection family
    if _slot_present(slots, "rag_document", "poison_payload") and (
        "indirect_prompt_injection" in family_set
    ):
        nodes.add(GrammarNode.RAG_POISONING)

    # TARGET_BEHAVIOR_SPECIFICATION: target_behavior OR target_topic slot
    if _slot_present(slots, "target_behavior", "target_topic"):
        nodes.add(GrammarNode.TARGET_BEHAVIOR_SPECIFICATION)

    # PERSONA_CONSTRUCTION: role_name AND (role_description OR personality_trait)
    if _slot_present(slots, "role_name") and _slot_present(
        slots, "role_description", "personality_trait"
    ):
        nodes.add(GrammarNode.PERSONA_CONSTRUCTION)

    # DAN_PERSONA: role_name contains a known alter-ego keyword
    role_name_val = _slot_value(slots, "role_name")
    if role_name_val and any(kw in role_name_val for kw in _DAN_KEYWORDS):
        nodes.add(GrammarNode.DAN_PERSONA)

    # FICTIONAL_FRAMING: role_description present AND family is one of the fictional ones
    if _slot_present(slots, "role_description") and family_set & _FICTIONAL_FRAMING_FAMILIES:
        nodes.add(GrammarNode.FICTIONAL_FRAMING)

    # ROLE_HIJACK: role_name AND role_description both present (slot-level detection,
    # independent of family label — cross-family signal as stated in derivation)
    if _slot_present(slots, "role_name") and _slot_present(slots, "role_description"):
        nodes.add(GrammarNode.ROLE_HIJACK)

    # POLICY_ROLEPLAY: role_description references policy/story keywords
    role_desc_val = _slot_value(slots, "role_description")
    if role_desc_val and any(kw in role_desc_val for kw in _POLICY_KEYWORDS):
        nodes.add(GrammarNode.POLICY_ROLEPLAY)

    # INDIRECT_INJECTION (slot-level): rag_document OR poison_payload with
    # invisible_tag_instruction (as per derivation note)
    if _slot_present(slots, "rag_document", "poison_payload") and _slot_present(
        slots, "invisible_tag_instruction"
    ):
        nodes.add(GrammarNode.INDIRECT_INJECTION)

    # ------------------------------------------------------------------ #
    # Rule 3: Flag / vector signals                                         #
    # ------------------------------------------------------------------ #

    # MULTI_TURN_ESCALATION: requires_multi_turn flag
    if record.requires_multi_turn:
        nodes.add(GrammarNode.MULTI_TURN_ESCALATION)

    # MULTIMODAL: vector starts with "multimodal_"
    if record.vector and record.vector.startswith(_MULTIMODAL_VECTOR_PREFIX):
        nodes.add(GrammarNode.MULTIMODAL)

    # INDIRECT_INJECTION: vector is rag_document or tool_output
    if record.vector and record.vector in _INDIRECT_VECTORS:
        nodes.add(GrammarNode.INDIRECT_INJECTION)

    return nodes


def label_records(records: list[PrimitiveRecord]) -> dict[str, set[GrammarNode]]:
    """Apply :func:`heuristic_labels` to every record.

    Returns a mapping ``primitive_id -> set[GrammarNode]``.  Order matches input.
    """
    return {r.primitive_id: heuristic_labels(r) for r in records}


def label_distribution(labels: dict[str, set[GrammarNode]]) -> dict[GrammarNode, int]:
    """Count the number of primitives that carry each GrammarNode.

    ``labels`` is the output of :func:`label_records`.  Returns
    ``{node: count}``, including nodes with zero primitives (count=0) so the
    caller always gets a complete 23-entry dict.
    """
    counts: dict[GrammarNode, int] = {node: 0 for node in GrammarNode}
    for node_set in labels.values():
        for node in node_set:
            counts[node] += 1
    return counts


def persist_labels(
    session: "Session",
    labels: dict[str, set[GrammarNode]],
    *,
    source: str = "heuristic",
) -> int:
    """Upsert PrimitiveGrammarLabel rows for ``labels``.

    Respects the unique constraint on (primitive_id, node, source).  Existing rows
    with the same key are overwritten (confidence refreshed to 1.0 for heuristic
    labels).  Returns the number of rows written (inserted or updated).

    Import of :class:`~rogue.db.models.PrimitiveGrammarLabel` is deferred until
    call-time because Engineer 2's model is built in a parallel wave and may not
    exist at import time.
    """
    # Lazy import — model built by Engineer 2 in parallel.
    from rogue.db.models import PrimitiveGrammarLabel  # type: ignore[attr-defined]

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    rows_written = 0
    for primitive_id, node_set in labels.items():
        for node in node_set:
            stmt = (
                pg_insert(PrimitiveGrammarLabel)
                .values(
                    primitive_id=primitive_id,
                    node=node.value,
                    source=source,
                    confidence=1.0,
                )
                .on_conflict_do_update(
                    index_elements=["primitive_id", "node", "source"],
                    set_={"confidence": 1.0},
                )
            )
            session.execute(stmt)
            rows_written += 1

    session.flush()
    return rows_written
