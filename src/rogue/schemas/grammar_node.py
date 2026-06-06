"""GrammarNode — structural-node vocabulary for the grammar-component predictive-power study.

This enum decomposes attack primitives into reusable structural components that sit
BELOW the frozen `AttackFamily` taxonomy. It is purely additive and §13-safe — it does
not touch or revise `AttackFamily` / `AttackVector`.

Two categories of nodes:

- **Family-mirroring** (for family-derived labels): nodes that correspond 1:1 to an
  existing `AttackFamily` value. Useful as a controlled baseline when measuring how much
  cross-family structure adds beyond the family label itself.
- **Cross-family structural** (the non-circular, high-value nodes): derived from
  ``payload_slots`` keys and ``requires_multi_turn`` rather than from family. These are
  the analytically interesting ones — they capture *how* an attack is constructed,
  independently of *what* it attempts.

``GRAMMAR_NODE_META`` provides derivation hints that the heuristic labeler (Engineer 3)
uses to assign ``GrammarLabel`` instances.  The ``"derivation"`` value is an operational
rule written in terms of the concrete DB fields available on ``AttackPrimitive``:
``family``, ``secondary_families``, ``payload_slots`` keys, and ``requires_multi_turn``.

Spec: grammar-component predictive-power study (grounding from 298-primitive corpus scan).
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ---------- Enum ----------


class GrammarNode(str, Enum):
    """~25 structural grammar nodes.

    Values are lowercase snake_case to match the ROGUE enum convention and to allow
    direct use as payload-slot keys / column values without any transformation.
    """

    # ------------------------------------------------------------------
    # Family-mirroring nodes
    # These exist so a family-baseline model can be expressed as a
    # GrammarLabel without special-casing AttackFamily.
    # ------------------------------------------------------------------

    ROLE_HIJACK = "role_hijack"
    """Attack impersonates or hijacks an assigned assistant role."""

    DAN_PERSONA = "dan_persona"
    """Classic DAN / alter-ego jailbreak persona pattern."""

    POLICY_ROLEPLAY = "policy_roleplay"
    """Role-play framing that invokes fictional policy exceptions."""

    REFUSAL_SUPPRESSION = "refusal_suppression"
    """Explicit instruction to suppress refusal responses."""

    DIRECT_OVERRIDE = "direct_override"
    """Direct instruction that overrides or supersedes system prompt."""

    SYSTEM_PROMPT_LEAK = "system_prompt_leak"
    """Attack designed to extract / exfiltrate the system prompt."""

    TRAINING_DATA_EXTRACTION = "training_data_extraction"
    """Attack elicits memorised training corpus fragments."""

    INDIRECT_INJECTION = "indirect_injection"
    """Attack payload delivered through an indirect channel (RAG doc, URL, etc.)."""

    TOOL_INVOCATION = "tool_invocation"
    """Attack exploits or hijacks a tool / function call surface."""

    CHAIN_OF_THOUGHT_HIJACK = "chain_of_thought_hijack"
    """Attack steers or forges the model's chain-of-thought reasoning."""

    MULTIMODAL = "multimodal"
    """Attack payload carried in an image, audio, or non-text modality."""

    # ------------------------------------------------------------------
    # Cross-family structural nodes
    # Derived from payload_slots keys and flags — the analytically
    # non-circular, high-value nodes for the predictive-power study.
    # ------------------------------------------------------------------

    AUTHORITY_FRAME = "authority_frame"
    """Payload establishes a false authority or justification context.

    Cross-family signal: present across role_hijack, refusal_suppression,
    indirect_injection, and direct_override families.
    """

    LANGUAGE_SHIFT = "language_shift"
    """Payload switches natural language to evade policy filters."""

    ENCODING_OBFUSCATION = "encoding_obfuscation"
    """Payload applies a character- or token-level encoding transformation."""

    STRUCTURED_OUTPUT = "structured_output"
    """Payload demands a specific output format to bypass safety constraints."""

    FICTIONAL_FRAMING = "fictional_framing"
    """Payload wraps the harmful request in a narrative / story / game frame."""

    MULTI_TURN_ESCALATION = "multi_turn_escalation"
    """Attack unfolds across multiple turns, escalating toward the target behavior."""

    TRIGGER_BACKDOOR = "trigger_backdoor"
    """Attack plants a trigger phrase that activates a hidden behaviour."""

    EXFILTRATION = "exfiltration"
    """Attack includes an explicit exfiltration destination or vector."""

    PERSONA_CONSTRUCTION = "persona_construction"
    """Payload constructs a named persona with specified traits to enable bypass."""

    TARGET_BEHAVIOR_SPECIFICATION = "target_behavior_specification"
    """Payload explicitly specifies a forbidden target behavior or topic."""

    INVISIBLE_INJECTION = "invisible_injection"
    """Attack embeds instructions in whitespace, Unicode, or hidden HTML tags."""

    RAG_POISONING = "rag_poisoning"
    """Attack injects a malicious document into the retrieval context."""


# ---------- Metadata ----------


GRAMMAR_NODE_META: dict[GrammarNode, dict[str, str]] = {
    # ------------------------------------------------------------------ #
    # Family-mirroring                                                      #
    # ------------------------------------------------------------------ #
    GrammarNode.ROLE_HIJACK: {
        "description": (
            "The attack overrides or hijacks the assistant's assigned role identity, "
            "causing it to act as a different entity with fewer restrictions."
        ),
        "derivation": (
            "family == 'role_hijack' OR 'role_hijack' in secondary_families; "
            "OR payload_slots has 'role_name' AND 'role_description' both non-empty."
        ),
    },
    GrammarNode.DAN_PERSONA: {
        "description": (
            "Classic DAN ('Do Anything Now') or equivalent alter-ego jailbreak that "
            "instantiates an unconstrained parallel persona."
        ),
        "derivation": (
            "family == 'dan_persona' OR 'dan_persona' in secondary_families; "
            "OR payload_slots has 'role_name' containing 'DAN', 'STAN', 'AIM', or "
            "similar alter-ego keywords."
        ),
    },
    GrammarNode.POLICY_ROLEPLAY: {
        "description": (
            "Attack frames the request as a role-play scenario that implicitly or "
            "explicitly claims fictional policy exceptions apply."
        ),
        "derivation": (
            "family == 'policy_roleplay' OR 'policy_roleplay' in secondary_families; "
            "OR payload_slots has 'role_description' referencing 'policy', 'rules', "
            "'guidelines', 'fictional', or 'story'."
        ),
    },
    GrammarNode.REFUSAL_SUPPRESSION: {
        "description": (
            "Payload contains an explicit directive instructing the model not to refuse, "
            "add caveats, or break character."
        ),
        "derivation": (
            "family == 'refusal_suppression' OR 'refusal_suppression' in secondary_families; "
            "OR payload_slots has 'target_behavior' referencing 'never refuse', "
            "'no caveats', 'do not break character'."
        ),
    },
    GrammarNode.DIRECT_OVERRIDE: {
        "description": (
            "Payload issues a direct imperative that explicitly supersedes or voids the "
            "system prompt or prior instructions."
        ),
        "derivation": (
            "family == 'direct_instruction_override' OR "
            "'direct_instruction_override' in secondary_families."
        ),
    },
    GrammarNode.SYSTEM_PROMPT_LEAK: {
        "description": (
            "Attack is designed to elicit or exfiltrate the contents of the model's "
            "system prompt."
        ),
        "derivation": (
            "family == 'system_prompt_leak' OR 'system_prompt_leak' in secondary_families; "
            "OR payload_slots has 'exfil_destination' AND target_topic references "
            "'system prompt', 'instructions', 'configuration'."
        ),
    },
    GrammarNode.TRAINING_DATA_EXTRACTION: {
        "description": (
            "Attack attempts to elicit memorised text from the model's training corpus, "
            "such as copyrighted material or PII."
        ),
        "derivation": (
            "family == 'training_data_extraction' OR "
            "'training_data_extraction' in secondary_families."
        ),
    },
    GrammarNode.INDIRECT_INJECTION: {
        "description": (
            "Malicious instructions are delivered through an indirect channel — a "
            "retrieved document, URL, tool output, or environment observation."
        ),
        "derivation": (
            "family == 'indirect_prompt_injection' OR "
            "'indirect_prompt_injection' in secondary_families; "
            "OR payload_slots has 'rag_document' OR 'poison_payload' non-empty "
            "with 'invisible_tag_instruction' also present."
        ),
    },
    GrammarNode.TOOL_INVOCATION: {
        "description": (
            "Attack exploits a tool/function-call surface — either hijacking an "
            "existing tool or forging a tool invocation to exfiltrate data."
        ),
        "derivation": (
            "family == 'tool_use_hijack' OR 'tool_use_hijack' in secondary_families; "
            "OR payload_slots has 'tool_name' non-empty."
        ),
    },
    GrammarNode.CHAIN_OF_THOUGHT_HIJACK: {
        "description": (
            "Attack steers the model's chain-of-thought reasoning toward a harmful "
            "conclusion, or forges a CoT prefix to bypass post-hoc safety checks."
        ),
        "derivation": (
            "family == 'chain_of_thought_hijack' OR "
            "'chain_of_thought_hijack' in secondary_families."
        ),
    },
    GrammarNode.MULTIMODAL: {
        "description": (
            "Attack payload is embedded in or relies on a non-text modality: image, "
            "audio, video, or document rendering."
        ),
        "derivation": (
            "family == 'multimodal_injection' OR 'multimodal_injection' in secondary_families."
        ),
    },
    # ------------------------------------------------------------------ #
    # Cross-family structural nodes                                         #
    # ------------------------------------------------------------------ #
    GrammarNode.AUTHORITY_FRAME: {
        "description": (
            "Payload establishes a false authority, identity, or justification context "
            "to lower the model's guard — e.g., 'I am a doctor', 'this is for "
            "authorized red-team research', 'my boss approved this'."
        ),
        "derivation": (
            "payload_slots has 'authority_claim' (n=60) OR 'justification' (n=51) "
            "non-empty. Cross-family: fires across role_hijack, refusal_suppression, "
            "indirect_injection, direct_override, and others."
        ),
    },
    GrammarNode.LANGUAGE_SHIFT: {
        "description": (
            "Payload switches natural language (e.g., English → Chinese, French, or "
            "a low-resource language) to evade English-biased safety filters."
        ),
        "derivation": (
            "payload_slots has 'language' (n=3) non-empty; "
            "OR family == 'language_switching' OR 'language_switching' in secondary_families."
        ),
    },
    GrammarNode.ENCODING_OBFUSCATION: {
        "description": (
            "Payload applies a character- or token-level encoding transformation — "
            "Base64, ROT13, leetspeak, Morse, Unicode homoglyphs — to hide the "
            "harmful content from surface-level pattern matchers."
        ),
        "derivation": (
            "payload_slots has 'encoding_scheme' (n=34) non-empty; "
            "OR family == 'obfuscation_encoding' OR 'obfuscation_encoding' in secondary_families."
        ),
    },
    GrammarNode.STRUCTURED_OUTPUT: {
        "description": (
            "Payload demands a specific output format (JSON, YAML, markdown table, "
            "numbered list, code block) in order to channel harmful content through a "
            "formatting bypass."
        ),
        "derivation": (
            "payload_slots has 'target_output_format' (n=53) OR 'NewResponseFormat' (n=4) "
            "non-empty. Cross-family: appears in refusal_suppression, direct_override, "
            "tool_use_hijack, and indirect_injection."
        ),
    },
    GrammarNode.FICTIONAL_FRAMING: {
        "description": (
            "Payload wraps the harmful request inside a narrative, story, game, or "
            "hypothetical scenario to exploit the model's creative-writing compliance mode."
        ),
        "derivation": (
            "payload_slots has 'role_description' OR 'role_name' referencing fictional "
            "context; AND family in {policy_roleplay, dan_persona, role_hijack}. "
            "Distinguished from ROLE_HIJACK by the narrative/story framing — "
            "the model is asked to write fiction, not to become a persona."
        ),
    },
    GrammarNode.MULTI_TURN_ESCALATION: {
        "description": (
            "Attack is structurally multi-turn: it builds compliance over several "
            "exchanges before issuing the harmful request (Crescendo / many-shot / "
            "gradual escalation patterns)."
        ),
        "derivation": (
            "requires_multi_turn == True (n=42); "
            "OR family in {multi_turn_gradient, multi_turn_persona_chain} OR either "
            "in secondary_families."
        ),
    },
    GrammarNode.TRIGGER_BACKDOOR: {
        "description": (
            "Attack plants a trigger phrase or token that, when encountered later, "
            "activates a hidden behaviour — analogous to a software backdoor."
        ),
        "derivation": (
            "payload_slots has 'trigger_phrase' (n=59) non-empty. "
            "Cross-family: appears in indirect_injection, multi_turn_gradient, "
            "and tool_use_hijack."
        ),
    },
    GrammarNode.EXFILTRATION: {
        "description": (
            "Payload specifies or implies a concrete exfiltration destination — a URL, "
            "webhook, email address, or other data-sink to which the model should "
            "transmit harvested information."
        ),
        "derivation": (
            "payload_slots has 'exfil_destination' (n=45) non-empty. "
            "Cross-family: fires in system_prompt_leak, tool_use_hijack, and "
            "indirect_injection."
        ),
    },
    GrammarNode.PERSONA_CONSTRUCTION: {
        "description": (
            "Payload constructs a named persona with explicit personality traits to "
            "enable bypass — going beyond a simple role assignment to building a "
            "character with stated 'no-limits' traits."
        ),
        "derivation": (
            "payload_slots has 'role_name' (n=57) AND ('role_description' (n=46) OR "
            "'personality_trait' (n=4)) non-empty. Overlaps with ROLE_HIJACK/DAN_PERSONA "
            "but fires specifically on the construction pattern, not just the family."
        ),
    },
    GrammarNode.TARGET_BEHAVIOR_SPECIFICATION: {
        "description": (
            "Payload explicitly names a forbidden target topic or behavior that the "
            "model is being asked to produce — the 'ask' is unambiguous."
        ),
        "derivation": (
            "payload_slots has 'target_behavior' (n=206) AND/OR 'target_topic' (n=73) "
            "non-empty. Near-universal (n=206 is 69% of corpus) — useful as a baseline "
            "coverage node and for precision-recall calibration."
        ),
    },
    GrammarNode.INVISIBLE_INJECTION: {
        "description": (
            "Attack embeds instructions in whitespace, Unicode zero-width characters, "
            "HTML comment tags, or other invisible / non-rendered content."
        ),
        "derivation": (
            "payload_slots has 'invisible_tag_instruction' (n=4) non-empty; "
            "OR family == 'indirect_prompt_injection' AND payload contains zero-width "
            "Unicode codepoints (U+200B, U+FEFF, U+200C, etc.)."
        ),
    },
    GrammarNode.RAG_POISONING: {
        "description": (
            "Attack injects a malicious document or chunk into the retrieval-augmented "
            "generation (RAG) context, causing the model to process and act on attacker "
            "instructions as if they were legitimate retrieved knowledge."
        ),
        "derivation": (
            "payload_slots has 'rag_document' (n=4) OR 'poison_payload' (n=119) "
            "non-empty; AND family == 'indirect_prompt_injection' OR "
            "'indirect_prompt_injection' in secondary_families."
        ),
    },
}


# ---------- Wire form ----------


class GrammarLabel(BaseModel):
    """A single grammar-node label assigned to one ``AttackPrimitive``.

    One primitive can carry multiple ``GrammarLabel`` instances (one per assigned node).
    Labels are produced by the heuristic labeler (Engineer 3) and optionally overridden
    by a human or LLM reviewer.
    """

    primitive_id: str = Field(
        ...,
        min_length=1,
        description="ULID of the AttackPrimitive this label is attached to.",
    )
    node: GrammarNode = Field(
        ...,
        description="The grammar node assigned to this primitive.",
    )
    source: Literal["heuristic", "manual", "llm"] = Field(
        "heuristic",
        description="How this label was produced.",
    )
    confidence: float = Field(
        1.0,
        ge=0.0,
        le=1.0,
        description=(
            "Labeler confidence in [0, 1]. Heuristic labels default to 1.0; "
            "LLM labels should propagate the model's probability estimate."
        ),
    )

    model_config = {"use_enum_values": False}
