"""Unit tests for the AI Red-Team Assurance Report (rogue.governance.assurance).

Pure composition/rendering — no DB, no network. Asserts:
  * the framework coverage matches what ``crosswalk_for_families`` returns;
  * the non-certification disclaimer is always present (markdown + JSON);
  * the signed attestation is referenced as evidence (hash/signature/seq);
  * JSON is serializable and structurally complete;
  * empty-scope and full-scope cases both render coherently.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from rogue.governance.assurance import (
    NON_CERTIFICATION,
    AssuranceScope,
    AttestationRef,
    PostureSummary,
    build_assurance_report,
    render_json,
    render_markdown,
)
from rogue.schemas import AttackFamily, Severity
from rogue.taxonomy import crosswalk_for_families
from rogue.taxonomy.crosswalk import frameworks_to_dict


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def families() -> list[AttackFamily]:
    return [
        AttackFamily.SYSTEM_PROMPT_LEAK,
        AttackFamily.DAN_PERSONA,
        AttackFamily.TRAINING_DATA_EXTRACTION,
    ]


@pytest.fixture
def full_scope() -> AssuranceScope:
    return AssuranceScope(
        config_id="cfg_acme_prod",
        config_name="Acme Support Bot",
        target_model="claude-3-5-sonnet",
        system_prompt_label="support-v4",
        tools=("search_kb", "create_ticket"),
        customer_id="acme",
        window_start=date(2026, 6, 1),
        window_end=date(2026, 6, 12),
    )


@pytest.fixture
def posture() -> PostureSummary:
    return PostureSummary(
        n_primitives=42,
        n_trials=210,
        by_severity={Severity.CRITICAL: 2, Severity.HIGH: 5, Severity.MEDIUM: 3},
        by_verdict={"refused": 180, "partial_breach": 18, "full_breach": 12},
        corpus_as_of="2026-06-12T00:00:00+00:00",
    )


@pytest.fixture
def attestation() -> AttestationRef:
    return AttestationRef(
        entry_hash="abc123def456",
        signature="sig:deadbeef",
        seq=7,
        corpus_as_of="2026-06-12T00:00:00+00:00",
        framing="threat-informed assurance, tested against the open-web corpus as of 2026-06-12; not a safety guarantee",
        org_id="org_acme",
    )


# --------------------------------------------------------------------------- #
# Framework coverage matches the crosswalk
# --------------------------------------------------------------------------- #


def test_coverage_matches_crosswalk(full_scope, posture, families):
    report = build_assurance_report(full_scope, posture, families)
    expected = crosswalk_for_families(families)
    assert report.coverage == expected
    # The centrepiece IDs must surface in the markdown.
    md = render_markdown(report)
    for code in expected.owasp:
        assert code in md
    for code in expected.atlas:
        assert code in md
    assert expected.nist in md


def test_coverage_section_present_in_markdown(full_scope, posture, families):
    md = render_markdown(build_assurance_report(full_scope, posture, families))
    assert "## Framework Coverage" in md
    assert "OWASP LLM Top 10" in md
    assert "MITRE ATLAS" in md
    assert "NIST AI RMF" in md
    # System-prompt-leak family contributes LLM07 specifically.
    assert "LLM07" in md


def test_json_frameworks_match_crosswalk(full_scope, posture, families):
    report = build_assurance_report(full_scope, posture, families)
    doc = render_json(report)
    assert doc["frameworks"] == frameworks_to_dict(crosswalk_for_families(families))


def test_string_families_accepted_and_resolved(full_scope, posture):
    # Caller may pass DB-string family values; unknown strings are dropped.
    report = build_assurance_report(
        full_scope,
        posture,
        ["dan_persona", "system_prompt_leak", "not_a_real_family"],
    )
    assert report.families == (
        AttackFamily.DAN_PERSONA,
        AttackFamily.SYSTEM_PROMPT_LEAK,
    )
    expected = crosswalk_for_families(["dan_persona", "system_prompt_leak"])
    assert report.coverage == expected


def test_duplicate_families_deduped(full_scope, posture):
    report = build_assurance_report(
        full_scope,
        posture,
        [AttackFamily.DAN_PERSONA, AttackFamily.DAN_PERSONA],
    )
    assert report.families == (AttackFamily.DAN_PERSONA,)


# --------------------------------------------------------------------------- #
# Non-certification disclaimer (honesty filter)
# --------------------------------------------------------------------------- #


def test_disclaimer_present_in_markdown(full_scope, posture, families):
    md = render_markdown(build_assurance_report(full_scope, posture, families))
    assert NON_CERTIFICATION in md
    assert "NOT a certification" in md
    assert "SOC 2" in md and "ISO 27001" in md
    assert "## Limitations & Framing" in md


def test_disclaimer_present_even_on_empty_scope(posture):
    report = build_assurance_report(AssuranceScope(), PostureSummary(), [])
    md = render_markdown(report)
    assert NON_CERTIFICATION in md
    doc = render_json(report)
    assert doc["non_certification"] == NON_CERTIFICATION


# --------------------------------------------------------------------------- #
# Attestation referenced as evidence (not re-signed)
# --------------------------------------------------------------------------- #


def test_attestation_referenced_in_markdown(full_scope, posture, families, attestation):
    report = build_assurance_report(
        full_scope, posture, families, attestation=attestation
    )
    md = render_markdown(report)
    assert "## Evidence & Attestation" in md
    assert attestation.entry_hash in md
    assert attestation.signature in md
    assert "7" in md  # chain sequence
    assert attestation.org_id in md


def test_attestation_referenced_in_json(full_scope, posture, families, attestation):
    report = build_assurance_report(
        full_scope, posture, families, attestation=attestation
    )
    att = render_json(report)["attestation"]
    assert att is not None
    assert att["entry_hash"] == attestation.entry_hash
    assert att["signature"] == attestation.signature
    assert att["seq"] == 7


def test_no_attestation_renders_unattested(full_scope, posture, families):
    report = build_assurance_report(full_scope, posture, families)
    md = render_markdown(report)
    assert "unattested" in md
    assert render_json(report)["attestation"] is None


def test_attestation_ref_from_entry_object():
    class _Entry:
        entry_hash = "h1"
        signature = "s1"
        seq = 3
        org_id = "org_x"
        payload = {
            "corpus_as_of": "2026-06-12T00:00:00+00:00",
            "framing": "threat-informed assurance; not a safety guarantee",
        }

    ref = AttestationRef.from_entry(_Entry())
    assert ref.entry_hash == "h1"
    assert ref.signature == "s1"
    assert ref.seq == 3
    assert ref.org_id == "org_x"
    assert ref.corpus_as_of == "2026-06-12T00:00:00+00:00"
    assert "not a safety guarantee" in ref.framing


def test_attestation_ref_from_entry_dict_and_missing_fields():
    ref = AttestationRef.from_entry({"entry_hash": "h2", "payload": {}})
    assert ref.entry_hash == "h2"
    assert ref.signature == ""
    assert ref.seq is None
    assert ref.corpus_as_of == ""


# --------------------------------------------------------------------------- #
# JSON serializability + structural completeness
# --------------------------------------------------------------------------- #


def test_json_is_serializable_and_complete(full_scope, posture, families, attestation):
    report = build_assurance_report(
        full_scope,
        posture,
        families,
        attestation=attestation,
        threat_brief_ref="data/threat_briefs/2026-06-12.json",
    )
    doc = render_json(report)
    # Round-trips through json with no custom encoder.
    restored = json.loads(json.dumps(doc))
    assert restored == doc

    for key in (
        "report_type",
        "non_certification",
        "scope",
        "posture",
        "families",
        "frameworks",
        "frameworks_line",
        "attestation",
        "threat_brief_ref",
    ):
        assert key in doc

    assert doc["report_type"] == "ai_red_team_assurance"
    assert doc["scope"]["target_model"] == "claude-3-5-sonnet"
    assert doc["scope"]["tools"] == ["search_kb", "create_ticket"]
    assert doc["scope"]["window_start"] == "2026-06-01"
    assert doc["scope"]["window_end"] == "2026-06-12"
    assert doc["families"] == [f.value for f in report.families]
    assert doc["threat_brief_ref"] == "data/threat_briefs/2026-06-12.json"


def test_posture_breakdown_in_json(full_scope, posture, families):
    doc = render_json(build_assurance_report(full_scope, posture, families))
    sev = doc["posture"]["by_severity"]
    assert sev == {"critical": 2, "high": 5, "medium": 3, "low": 0}
    assert doc["posture"]["n_breaching_primitives"] == 10
    assert doc["posture"]["by_verdict"]["full_breach"] == 12
    assert doc["posture"]["n_primitives"] == 42
    assert doc["posture"]["n_trials"] == 210


# --------------------------------------------------------------------------- #
# Empty-scope and full-scope rendering
# --------------------------------------------------------------------------- #


def test_empty_scope_renders_all_sections():
    report = build_assurance_report(AssuranceScope(), PostureSummary(), [])
    md = render_markdown(report)
    for header in (
        "## Scope & Posture",
        "## Framework Coverage",
        "## Evidence & Attestation",
        "## Limitations & Framing",
    ):
        assert header in md
    assert "No attack families were in scope" in md
    assert report.families == ()
    assert report.coverage.is_empty()


def test_full_scope_lists_families_and_severity(full_scope, posture, families):
    md = render_markdown(build_assurance_report(full_scope, posture, families))
    assert "Acme Support Bot" in md
    assert "claude-3-5-sonnet" in md
    assert "`search_kb`" in md
    assert "2026-06-01 → 2026-06-12" in md
    assert "42 primitives" in md
    assert "**CRITICAL:** 2" in md
    assert "**HIGH:** 5" in md


# --------------------------------------------------------------------------- #
# Exfiltration-channel breakdown (by_exfil_method)
# --------------------------------------------------------------------------- #


def test_exfil_channels_render_in_markdown_and_json(full_scope, families):
    posture = PostureSummary(
        n_primitives=42,
        n_trials=210,
        by_severity={Severity.CRITICAL: 2, Severity.HIGH: 5},
        by_verdict={"full_breach": 12},
        by_exfil_method={"markdown_image_beacon": 4, "pii_egress": 3},
        corpus_as_of="2026-06-12T00:00:00+00:00",
    )
    report = build_assurance_report(full_scope, posture, families)

    md = render_markdown(report)
    assert "Breaches by exfiltration channel:" in md
    assert "- `markdown_image_beacon`: 4" in md
    assert "- `pii_egress`: 3" in md
    # No "none observed" line when channels are present.
    assert "No data-exfiltration channel was observed" not in md

    doc = render_json(report)
    assert doc["posture"]["by_exfil_method"] == {
        "markdown_image_beacon": 4,
        "pii_egress": 3,
    }


def test_exfil_channels_empty_renders_honest_none_line(full_scope, posture, families):
    # The default fixture leaves by_exfil_method empty.
    report = build_assurance_report(full_scope, posture, families)

    md = render_markdown(report)
    assert "Breaches by exfiltration channel:" in md
    assert "- _No data-exfiltration channel was observed in the breaching trials._" in md

    doc = render_json(report)
    assert doc["posture"]["by_exfil_method"] == {}


def test_exfil_channels_sorted_by_key_for_determinism(full_scope, families):
    # Insertion order is intentionally not sorted; the renderer must sort by key.
    posture = PostureSummary(
        by_exfil_method={
            "pii_egress": 1,
            "base64_blob": 2,
            "hyperlink_exfil": 3,
        },
    )
    report = build_assurance_report(full_scope, posture, families)
    md = render_markdown(report)
    lines = [ln for ln in md.splitlines() if ln.startswith("- `")]
    exfil_lines = [
        ln for ln in lines
        if any(m in ln for m in ("pii_egress", "base64_blob", "hyperlink_exfil"))
    ]
    assert exfil_lines == [
        "- `base64_blob`: 2",
        "- `hyperlink_exfil`: 3",
        "- `pii_egress`: 1",
    ]
