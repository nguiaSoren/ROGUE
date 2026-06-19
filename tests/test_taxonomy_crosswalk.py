"""Tests for ``rogue.taxonomy.crosswalk`` — the framework crosswalk lookup.

Pure-Python, no DB. Covers:
  * Completeness: every frozen AttackFamily has a mapping (driven off the enum so it can't silently drift).
  * Honesty invariants: OWASP IDs are real 2025 codes; ATLAS IDs are real verified IDs; NIST is a coarse string, never a fake ID.
  * Spot-check mappings the spec calls out as clean (system_prompt_leak → LLM07; training_data_extraction → AML.T0057).
  * Vector augmentation: indirect-injection vectors fold LLM01 in; non-indirect vectors don't.
  * Lookup API: unknown family string never raises; union over families; render helpers.

Spec: framework crosswalk reporting layer (does NOT touch the frozen taxonomy in rogue.schemas).
"""

from __future__ import annotations

import re

from rogue.schemas import AttackFamily, AttackVector
from rogue.taxonomy import (
    FAMILY_CROSSWALK,
    FrameworkMapping,
    crosswalk_coverage,
    crosswalk_for_families,
    crosswalk_for_family,
    format_frameworks_line,
)
from rogue.taxonomy.crosswalk import (
    ATLAS_TITLES,
    OWASP_2025_TITLES,
    frameworks_to_dict,
)

# The verified-real OWASP 2025 codes and ATLAS IDs. A mapping may only ever cite
# something in these sets — anything else is a fabricated identifier.
VALID_OWASP = {f"LLM{n:02d}" for n in range(1, 11)}
VALID_ATLAS = set(ATLAS_TITLES.keys())
ATLAS_RE = re.compile(r"^AML\.T\d{4}(\.\d{3})?$")


# --------------------------------------------------------------------------- #
# Completeness — driven off the frozen enum
# --------------------------------------------------------------------------- #


def test_every_family_has_a_mapping() -> None:
    """Completeness: the crosswalk must cover all 15 frozen families. Driven off
    AttackFamily itself so adding a 16th family fails this test until mapped."""
    assert set(FAMILY_CROSSWALK.keys()) == set(AttackFamily)
    assert len(FAMILY_CROSSWALK) == 15


def test_coverage_iterates_the_enum() -> None:
    """crosswalk_coverage() returns one entry per frozen family."""
    cov = crosswalk_coverage()
    assert set(cov.keys()) == set(AttackFamily)
    for family, mapping in cov.items():
        assert isinstance(mapping, FrameworkMapping)
        # No family in ROGUE's taxonomy is framework-silent: every one is at
        # minimum an adversarial-prompt issue, so NIST is always populated.
        assert mapping.nist, f"{family} has an empty NIST tag"


# --------------------------------------------------------------------------- #
# Honesty invariants — no fabricated identifiers
# --------------------------------------------------------------------------- #


def test_all_owasp_ids_are_real_2025_codes() -> None:
    for family, mapping in FAMILY_CROSSWALK.items():
        for code in mapping.owasp:
            assert code in VALID_OWASP, f"{family}: bogus OWASP code {code!r}"


def test_all_atlas_ids_are_verified_and_well_formed() -> None:
    for family, mapping in FAMILY_CROSSWALK.items():
        for code in mapping.atlas:
            assert ATLAS_RE.match(code), f"{family}: malformed ATLAS id {code!r}"
            assert code in VALID_ATLAS, f"{family}: unverified ATLAS id {code!r}"


def test_nist_is_a_string_never_an_id() -> None:
    """NIST AI RMF has no per-attack technique IDs — the tag must be prose,
    not anything that looks like an OWASP/ATLAS code."""
    for family, mapping in FAMILY_CROSSWALK.items():
        assert isinstance(mapping.nist, str)
        assert not mapping.nist.startswith(("LLM", "AML."))


def test_no_duplicate_ids_within_a_family() -> None:
    for family, mapping in FAMILY_CROSSWALK.items():
        assert len(mapping.owasp) == len(set(mapping.owasp)), f"{family} dup OWASP"
        assert len(mapping.atlas) == len(set(mapping.atlas)), f"{family} dup ATLAS"


# --------------------------------------------------------------------------- #
# Spot-check the clean mappings the spec calls out
# --------------------------------------------------------------------------- #


def test_system_prompt_leak_maps_to_llm07() -> None:
    m = FAMILY_CROSSWALK[AttackFamily.SYSTEM_PROMPT_LEAK]
    assert "LLM07" in m.owasp
    assert "AML.T0056" in m.atlas  # Extract LLM System Prompt


def test_training_data_extraction_maps_to_atlas_data_leakage() -> None:
    m = FAMILY_CROSSWALK[AttackFamily.TRAINING_DATA_EXTRACTION]
    assert m.owasp == ("LLM02",)
    assert m.atlas == ("AML.T0057",)


def test_dan_persona_maps_to_jailbreak() -> None:
    m = FAMILY_CROSSWALK[AttackFamily.DAN_PERSONA]
    assert "LLM01" in m.owasp
    assert "AML.T0054" in m.atlas


def test_tool_use_hijack_maps_to_excessive_agency() -> None:
    m = FAMILY_CROSSWALK[AttackFamily.TOOL_USE_HIJACK]
    assert "LLM06" in m.owasp


# --------------------------------------------------------------------------- #
# Vector augmentation
# --------------------------------------------------------------------------- #


def test_indirect_vector_adds_llm01() -> None:
    """A family carried over rag_document / tool_output is indirect injection →
    LLM01 folded in."""
    # training_data_extraction's base OWASP is LLM02 (no LLM01) — a clean probe.
    base = crosswalk_for_family(AttackFamily.TRAINING_DATA_EXTRACTION)
    assert "LLM01" not in base.owasp

    via_rag = crosswalk_for_family(
        AttackFamily.TRAINING_DATA_EXTRACTION, AttackVector.RAG_DOCUMENT
    )
    assert "LLM01" in via_rag.owasp
    assert "LLM02" in via_rag.owasp  # base preserved

    via_tool = crosswalk_for_family(
        AttackFamily.TRAINING_DATA_EXTRACTION, AttackVector.TOOL_OUTPUT
    )
    assert "LLM01" in via_tool.owasp


def test_non_indirect_vector_does_not_augment() -> None:
    base = crosswalk_for_family(AttackFamily.DAN_PERSONA)
    via_user = crosswalk_for_family(AttackFamily.DAN_PERSONA, AttackVector.USER_TURN)
    assert via_user.owasp == base.owasp


def test_augmentation_does_not_duplicate_llm01() -> None:
    """A family that already has LLM01 stays single-LLM01 under an indirect vector."""
    via = crosswalk_for_family(
        AttackFamily.INDIRECT_PROMPT_INJECTION, AttackVector.RAG_DOCUMENT
    )
    assert via.owasp.count("LLM01") == 1


def test_vector_augmentation_never_touches_atlas_or_nist() -> None:
    base = crosswalk_for_family(AttackFamily.TRAINING_DATA_EXTRACTION)
    via = crosswalk_for_family(
        AttackFamily.TRAINING_DATA_EXTRACTION, AttackVector.RAG_DOCUMENT
    )
    assert via.atlas == base.atlas
    assert via.nist == base.nist


# --------------------------------------------------------------------------- #
# Lookup API robustness — strings + unknowns
# --------------------------------------------------------------------------- #


def test_lookup_accepts_string_values() -> None:
    """The brief passes DB-sourced strings, not enum instances."""
    by_str = crosswalk_for_family("system_prompt_leak", "user_turn")
    by_enum = crosswalk_for_family(
        AttackFamily.SYSTEM_PROMPT_LEAK, AttackVector.USER_TURN
    )
    assert by_str == by_enum


def test_unknown_family_returns_empty_never_raises() -> None:
    """A future enum value must not crash the brief — clamp to empty."""
    m = crosswalk_for_family("some_future_family_2027")
    assert m.is_empty()
    assert format_frameworks_line(m) == ""


def test_unknown_vector_is_ignored_not_fatal() -> None:
    m = crosswalk_for_family(AttackFamily.DAN_PERSONA, "telepathy")
    assert m == crosswalk_for_family(AttackFamily.DAN_PERSONA)


# --------------------------------------------------------------------------- #
# Union across families — the assurance-report entry point
# --------------------------------------------------------------------------- #


def test_crosswalk_for_families_unions_ids() -> None:
    fams = [
        AttackFamily.SYSTEM_PROMPT_LEAK,
        AttackFamily.TRAINING_DATA_EXTRACTION,
    ]
    m = crosswalk_for_families(fams)
    assert "LLM07" in m.owasp  # from system_prompt_leak
    assert "LLM02" in m.owasp  # from training_data_extraction
    assert "AML.T0057" in m.atlas
    assert "AML.T0056" in m.atlas
    # dedup: order-stable, no repeats
    assert len(m.owasp) == len(set(m.owasp))
    assert len(m.atlas) == len(set(m.atlas))


def test_crosswalk_for_families_skips_unknowns() -> None:
    m = crosswalk_for_families(["dan_persona", "bogus_family"])
    assert "LLM01" in m.owasp


def test_crosswalk_for_families_empty_input() -> None:
    m = crosswalk_for_families([])
    assert m.is_empty()


# --------------------------------------------------------------------------- #
# Render helpers
# --------------------------------------------------------------------------- #


def test_format_frameworks_line_shape() -> None:
    m = crosswalk_for_family(AttackFamily.SYSTEM_PROMPT_LEAK)
    line = format_frameworks_line(m)
    assert line.startswith("OWASP LLM07")
    assert "ATLAS AML.T0056" in line
    assert "NIST:" in line
    assert " · " in line  # uses the middot separator
    assert "\n" not in line  # single line, no hard-wrap


def test_frameworks_to_dict_expands_titles() -> None:
    m = crosswalk_for_family(AttackFamily.DAN_PERSONA)
    d = frameworks_to_dict(m)
    assert d["owasp"][0] == {"id": "LLM01", "title": "Prompt Injection"}
    assert any(
        entry["id"] == "AML.T0054" and entry["title"] == "LLM Jailbreak"
        for entry in d["atlas"]
    )
    assert isinstance(d["nist"], str)


def test_title_tables_cover_every_used_id() -> None:
    """Every OWASP/ATLAS id cited in the crosswalk has a title in the lookup
    tables, so frameworks_to_dict never renders a blank title."""
    for mapping in FAMILY_CROSSWALK.values():
        for code in mapping.owasp:
            assert OWASP_2025_TITLES.get(code), f"missing OWASP title for {code}"
        for code in mapping.atlas:
            assert ATLAS_TITLES.get(code), f"missing ATLAS title for {code}"
