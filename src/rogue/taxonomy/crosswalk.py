"""Static crosswalk: ROGUE's frozen attack taxonomy → industry framework IDs.

Why this exists
---------------
ROGUE's 15 internal `AttackFamily` names (e.g. `dan_persona`, `refusal_suppression`) are precise but unfamiliar to enterprise buyers. Those buyers recognize standard framework identifiers instantly: OWASP LLM Top 10, MITRE ATLAS technique IDs, NIST AI RMF functions. This module is a PURE REPORTING-LAYER lookup that tags each frozen family with the framework IDs it maps to, so the daily threat brief (`rogue.diff.threat_brief`) and the assurance report can surface "OWASP LLM01, LLM07 · ATLAS AML.T0054 · NIST: Secure & Resilient" next to ROGUE's own labels.

Honesty filter (ROGUE hard rule — every claim traces to something true)
------------------------------------------------------------------------
* OWASP IDs use the **OWASP Top 10 for LLM Applications 2025** list, verified against genai.owasp.org on 2026-06-12: LLM01 Prompt Injection, LLM02 Sensitive Information Disclosure, LLM03 Supply Chain, LLM04 Data and Model Poisoning, LLM05 Improper Output Handling, LLM06 Excessive Agency, LLM07 System Prompt Leakage, LLM08 Vector and Embedding Weaknesses, LLM09 Misinformation, LLM10 Unbounded Consumption.
* MITRE ATLAS technique IDs were verified against the canonical ATLAS.yaml (github.com/mitre-atlas/atlas-data, fetched 2026-06-12). Only IDs confirmed to exist are used. Where no ATLAS technique cleanly matches a family, the list is left empty rather than guessed — inventing an ID is a failure, not a gap. Verified IDs used here: AML.T0051 LLM Prompt Injection (with sub-techniques .000 Direct, .001 Indirect, .002 Triggered), AML.T0054 LLM Jailbreak, AML.T0056 Extract LLM System Prompt, AML.T0057 LLM Data Leakage, AML.T0024.002 Extract AI Model, AML.T0069 Discover LLM System Information.
* NIST AI RMF has no per-attack technique IDs, so this is kept deliberately coarse and honest: a short prose tag naming the relevant trustworthiness characteristic ("Secure and Resilient") and/or core function. It is a string, never a fake ID.

Design
------
The map is keyed on `AttackFamily` (the frozen enum itself drives completeness — see `crosswalk_coverage` and the completeness test, so it can never silently drift if a 16th family is ever added). `AttackVector` is used only as a defensible OWASP augmentation: an attack family carried over a `rag_document` or `tool_output` vector is, by construction, indirect prompt injection — OWASP explicitly folds indirect injection under LLM01 — so those vectors add LLM01 to the family's base OWASP set via `crosswalk_for_family(family, vector=...)`. No vector ever adds an ATLAS ID or changes the NIST tag; the augmentation is OWASP-only and one-directional (additive).
"""

from __future__ import annotations

from dataclasses import dataclass

from rogue.schemas import AttackFamily, AttackVector


@dataclass(frozen=True)
class FrameworkMapping:
    """Framework identifiers for one attack family (or a resolved family+vector).

    All three fields are honest by construction: `owasp` and `atlas` hold only verified, currently-existing IDs (empty list = no clean match, not "unknown"); `nist` is a coarse prose tag, never a fabricated technique ID.
    """

    owasp: tuple[str, ...] = ()
    atlas: tuple[str, ...] = ()
    nist: str = ""
    # Optional one-line note documenting a judgment call / stretch, surfaced
    # nowhere in the brief itself but useful for auditors reading the map.
    note: str = ""

    def merge_owasp(self, extra: tuple[str, ...]) -> "FrameworkMapping":
        """Return a copy with `extra` OWASP IDs folded in (dedup, order-stable)."""
        if not extra:
            return self
        merged: list[str] = list(self.owasp)
        for code in extra:
            if code not in merged:
                merged.append(code)
        return FrameworkMapping(
            owasp=tuple(merged),
            atlas=self.atlas,
            nist=self.nist,
            note=self.note,
        )

    def is_empty(self) -> bool:
        """True iff this family has no framework signal at all (no OWASP, no ATLAS, no NIST)."""
        return not self.owasp and not self.atlas and not self.nist


# --------------------------------------------------------------------------- #
# OWASP 2025 short titles — for rendering "LLM01 Prompt Injection" rather than
# a bare code. Verified against genai.owasp.org 2026-06-12.
# --------------------------------------------------------------------------- #
OWASP_2025_TITLES: dict[str, str] = {
    "LLM01": "Prompt Injection",
    "LLM02": "Sensitive Information Disclosure",
    "LLM03": "Supply Chain",
    "LLM04": "Data and Model Poisoning",
    "LLM05": "Improper Output Handling",
    "LLM06": "Excessive Agency",
    "LLM07": "System Prompt Leakage",
    "LLM08": "Vector and Embedding Weaknesses",
    "LLM09": "Misinformation",
    "LLM10": "Unbounded Consumption",
}

# ATLAS technique short names — verified against ATLAS.yaml 2026-06-12.
ATLAS_TITLES: dict[str, str] = {
    "AML.T0051": "LLM Prompt Injection",
    "AML.T0051.000": "LLM Prompt Injection: Direct",
    "AML.T0051.001": "LLM Prompt Injection: Indirect",
    "AML.T0051.002": "LLM Prompt Injection: Triggered",
    "AML.T0054": "LLM Jailbreak",
    "AML.T0056": "Extract LLM System Prompt",
    "AML.T0057": "LLM Data Leakage",
    "AML.T0024.002": "Extract AI Model",
    "AML.T0069": "Discover LLM System Information",
}

# Reusable NIST AI RMF tag. NIST AI RMF (NIST AI 100-1) defines trustworthiness
# characteristics + the GOVERN/MAP/MEASURE/MANAGE core functions; "Secure and
# Resilient" is the characteristic every adversarial-prompt finding maps to.
_NIST_SECURE_RESILIENT = "Secure & Resilient (MANAGE)"


# --------------------------------------------------------------------------- #
# The crosswalk. Keyed on AttackFamily. One entry per frozen family — the
# completeness test asserts this dict's keys == set(AttackFamily) so a future
# 16th family can never silently ship without a mapping decision.
# --------------------------------------------------------------------------- #
FAMILY_CROSSWALK: dict[AttackFamily, FrameworkMapping] = {
    # Classic "ignore your instructions" — textbook direct prompt injection.
    AttackFamily.DIRECT_INSTRUCTION_OVERRIDE: FrameworkMapping(
        owasp=("LLM01",),
        atlas=("AML.T0051.000",),
        nist=_NIST_SECURE_RESILIENT,
    ),
    # Reassigning the model's role/identity to slip its guardrails. Achieved
    # via crafted input (injection) toward a jailbreak outcome.
    AttackFamily.ROLE_HIJACK: FrameworkMapping(
        owasp=("LLM01",),
        atlas=("AML.T0051", "AML.T0054"),
        nist=_NIST_SECURE_RESILIENT,
    ),
    # DAN / "do anything now" personas are the canonical jailbreak pattern.
    AttackFamily.DAN_PERSONA: FrameworkMapping(
        owasp=("LLM01",),
        atlas=("AML.T0054",),
        nist=_NIST_SECURE_RESILIENT,
    ),
    # "Let's roleplay a scenario where policy doesn't apply" — jailbreak.
    AttackFamily.POLICY_ROLEPLAY: FrameworkMapping(
        owasp=("LLM01",),
        atlas=("AML.T0054",),
        nist=_NIST_SECURE_RESILIENT,
    ),
    # Suppressing refusals ("never say you can't") — a jailbreak technique.
    AttackFamily.REFUSAL_SUPPRESSION: FrameworkMapping(
        owasp=("LLM01",),
        atlas=("AML.T0054",),
        nist=_NIST_SECURE_RESILIENT,
    ),
    # Crescendo / many-shot gradual escalation across turns — multi-turn
    # jailbreak delivered via injected user turns.
    AttackFamily.MULTI_TURN_GRADIENT: FrameworkMapping(
        owasp=("LLM01",),
        atlas=("AML.T0054", "AML.T0051"),
        nist=_NIST_SECURE_RESILIENT,
    ),
    # Hijacking the model's reasoning/CoT to launder a disallowed request.
    # Judgment call: this is a jailbreak strategy delivered by injection;
    # no dedicated ATLAS technique exists, so we tag the injection+jailbreak
    # pair rather than invent one.
    AttackFamily.CHAIN_OF_THOUGHT_HIJACK: FrameworkMapping(
        owasp=("LLM01",),
        atlas=("AML.T0051", "AML.T0054"),
        nist=_NIST_SECURE_RESILIENT,
        note="CoT-hijack has no dedicated ATLAS technique; mapped to the injection+jailbreak pair it is built from.",
    ),
    # Leaking the system prompt — OWASP added a dedicated 2025 entry (LLM07),
    # and ATLAS has a dedicated technique (AML.T0056).
    AttackFamily.SYSTEM_PROMPT_LEAK: FrameworkMapping(
        owasp=("LLM07", "LLM01"),
        atlas=("AML.T0056", "AML.T0051"),
        nist=_NIST_SECURE_RESILIENT,
        note="LLM07 is the primary 2025 mapping; LLM01 retained because the leak is induced via injection.",
    ),
    # Extracting memorized training data — OWASP LLM02 (sensitive info
    # disclosure); ATLAS AML.T0057 LLM Data Leakage.
    AttackFamily.TRAINING_DATA_EXTRACTION: FrameworkMapping(
        owasp=("LLM02",),
        atlas=("AML.T0057",),
        nist=_NIST_SECURE_RESILIENT,
    ),
    # Injection that arrives through a non-user channel (doc/tool/web). The
    # OWASP-canonical indirect-injection case; ATLAS Indirect sub-technique.
    AttackFamily.INDIRECT_PROMPT_INJECTION: FrameworkMapping(
        owasp=("LLM01",),
        atlas=("AML.T0051.001",),
        nist=_NIST_SECURE_RESILIENT,
    ),
    # Coercing the model to misuse its tools/plugins — OWASP LLM06 Excessive
    # Agency is the 2025 home for over-powered tool actions; delivered via
    # injection (LLM01). No dedicated ATLAS technique for tool misuse → omit.
    AttackFamily.TOOL_USE_HIJACK: FrameworkMapping(
        owasp=("LLM06", "LLM01"),
        atlas=("AML.T0051",),
        nist=_NIST_SECURE_RESILIENT,
        note="LLM06 (Excessive Agency) is the consequence; LLM01 the delivery. No ATLAS technique specific to tool/plugin misuse, so ATLAS = the injection technique only.",
    ),
    # Base64 / leetspeak / token-smuggling to evade filters — an evasion
    # technique in service of injection+jailbreak. Judgment call: OWASP folds
    # obfuscated payloads under LLM01; no dedicated ATLAS obfuscation technique.
    AttackFamily.OBFUSCATION_ENCODING: FrameworkMapping(
        owasp=("LLM01",),
        atlas=("AML.T0051", "AML.T0054"),
        nist=_NIST_SECURE_RESILIENT,
        note="Encoding/obfuscation is an evasion wrapper on injection+jailbreak; no standalone ATLAS technique, so mapped to the pair it wraps.",
    ),
    # Switching language to bypass English-centric guardrails — same shape as
    # obfuscation: an evasion wrapper on injection+jailbreak.
    AttackFamily.LANGUAGE_SWITCHING: FrameworkMapping(
        owasp=("LLM01",),
        atlas=("AML.T0051", "AML.T0054"),
        nist=_NIST_SECURE_RESILIENT,
        note="Low-resource-language evasion has no dedicated ATLAS technique; mapped to the injection+jailbreak pair it wraps.",
    ),
    # Injection carried in an image/audio modality — still LLM01 (OWASP treats
    # multimodal injection as a prompt-injection variant); ATLAS injection.
    AttackFamily.MULTIMODAL_INJECTION: FrameworkMapping(
        owasp=("LLM01",),
        atlas=("AML.T0051",),
        nist=_NIST_SECURE_RESILIENT,
        note="Multimodal injection is an LLM01 variant in OWASP 2025; ATLAS has no modality-specific injection ID, so mapped to AML.T0051.",
    ),
    # Persona-impersonation multi-turn chains (ActorAttack) — a multi-turn
    # jailbreak delivered via injected turns.
    AttackFamily.MULTI_TURN_PERSONA_CHAIN: FrameworkMapping(
        owasp=("LLM01",),
        atlas=("AML.T0054", "AML.T0051"),
        nist=_NIST_SECURE_RESILIENT,
    ),
}


# Vectors that, by construction, make any family an INDIRECT prompt injection
# (payload enters through a non-user channel). OWASP folds indirect injection
# under LLM01, so carrying a family over one of these vectors adds LLM01 to its
# OWASP set if not already present. This is the only vector-based augmentation,
# and it is OWASP-only + additive (never touches ATLAS or NIST).
_INDIRECT_VECTORS: frozenset[AttackVector] = frozenset(
    {
        AttackVector.RAG_DOCUMENT,
        AttackVector.TOOL_OUTPUT,
    }
)


# --------------------------------------------------------------------------- #
# Lookup API — what the threat brief + assurance report import.
# --------------------------------------------------------------------------- #


def crosswalk_for_family(
    family: AttackFamily | str,
    vector: AttackVector | str | None = None,
) -> FrameworkMapping:
    """Framework mapping for one family, optionally augmented by its vector.

    `family` / `vector` accept either the enum or its string value (the threat brief carries them as DB-sourced strings). An unknown family string returns an empty `FrameworkMapping` rather than raising — the brief must never crash on a future enum value (mirrors `_compute_severity_score`'s clamp-don't-crash contract). When `vector` is one of the indirect-injection vectors (rag_document, tool_output), LLM01 is folded into the OWASP set.
    """
    fam = _coerce_family(family)
    if fam is None:
        return FrameworkMapping()
    mapping = FAMILY_CROSSWALK[fam]

    vec = _coerce_vector(vector)
    if vec is not None and vec in _INDIRECT_VECTORS:
        mapping = mapping.merge_owasp(("LLM01",))
    return mapping


def crosswalk_for_families(
    families: list[AttackFamily | str] | tuple[AttackFamily | str, ...],
) -> FrameworkMapping:
    """Union mapping across a set of families (e.g. an assurance report covering many primitives).

    OWASP and ATLAS IDs are unioned (order-stable, dedup); the NIST tag is the shared "Secure & Resilient" tag if any family carries it. Notes are dropped (per-family auditing detail, not meaningful in aggregate). Unknown family strings are skipped. This is the symbol the assurance-report agent should call to get crosswalk coverage for a set of families.
    """
    owasp: list[str] = []
    atlas: list[str] = []
    nist = ""
    for f in families:
        m = crosswalk_for_family(f)
        for code in m.owasp:
            if code not in owasp:
                owasp.append(code)
        for code in m.atlas:
            if code not in atlas:
                atlas.append(code)
        if m.nist and not nist:
            nist = m.nist
    return FrameworkMapping(owasp=tuple(owasp), atlas=tuple(atlas), nist=nist)


def crosswalk_coverage() -> dict[AttackFamily, FrameworkMapping]:
    """Return the full family → mapping table, driven off the frozen enum.

    Built by iterating `AttackFamily` (not the dict literal) so any family missing from `FAMILY_CROSSWALK` raises KeyError here and in the completeness test — the enum, not the literal, is authoritative for which families must be covered.
    """
    return {family: FAMILY_CROSSWALK[family] for family in AttackFamily}


def format_frameworks_line(mapping: FrameworkMapping) -> str:
    """Render a compact one-line framework tag for the markdown brief.

    Example: ``OWASP LLM01, LLM07 · ATLAS AML.T0056, AML.T0051 · NIST: Secure & Resilient (MANAGE)``. Returns an empty string when the mapping has no signal at all (caller decides whether to emit a line).
    """
    if mapping.is_empty():
        return ""
    parts: list[str] = []
    if mapping.owasp:
        parts.append("OWASP " + ", ".join(mapping.owasp))
    if mapping.atlas:
        parts.append("ATLAS " + ", ".join(mapping.atlas))
    if mapping.nist:
        parts.append(f"NIST: {mapping.nist}")
    return " · ".join(parts)


def frameworks_to_dict(mapping: FrameworkMapping) -> dict[str, object]:
    """Structured JSON form of a mapping for the brief's per-primitive `frameworks` object.

    OWASP and ATLAS entries are expanded to ``{"id", "title"}`` objects (titles from the verified OWASP_2025_TITLES / ATLAS_TITLES tables); NIST stays a coarse string.
    """
    return {
        "owasp": [
            {"id": code, "title": OWASP_2025_TITLES.get(code, "")}
            for code in mapping.owasp
        ],
        "atlas": [
            {"id": code, "title": ATLAS_TITLES.get(code, "")}
            for code in mapping.atlas
        ],
        "nist": mapping.nist,
    }


# --------------------------------------------------------------------------- #
# Coercion helpers — accept enum or raw string, never raise on unknown.
# --------------------------------------------------------------------------- #


def _coerce_family(family: AttackFamily | str) -> AttackFamily | None:
    if isinstance(family, AttackFamily):
        return family
    try:
        return AttackFamily(family)
    except ValueError:
        return None


def _coerce_vector(vector: AttackVector | str | None) -> AttackVector | None:
    if vector is None:
        return None
    if isinstance(vector, AttackVector):
        return vector
    try:
        return AttackVector(vector)
    except ValueError:
        return None


__all__ = [
    "ATLAS_TITLES",
    "FAMILY_CROSSWALK",
    "OWASP_2025_TITLES",
    "FrameworkMapping",
    "crosswalk_coverage",
    "crosswalk_for_families",
    "crosswalk_for_family",
    "format_frameworks_line",
    "frameworks_to_dict",
]
