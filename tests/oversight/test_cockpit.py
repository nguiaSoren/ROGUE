"""Surface 2 cockpit assembler — facts to CHECK, never prose to PERSUADE (build 07 §4).

The strip copies the case's structured facts verbatim, carries the two numbers
(calibrated confidence + class historical false-approve rate), and has NO
recommendation field. ``no_persuasive_prose`` must flag a strip whose facts read
as a verdict.
"""

from __future__ import annotations

from dataclasses import fields

import pytest

from rogue.oversight.case_corpus import GatedCase
from rogue.oversight.cockpit import (
    CockpitStrip,
    assemble_cockpit,
    assert_no_persuasive_prose,
    no_persuasive_prose,
)


def _case(facts: dict[str, str] | None = None) -> GatedCase:
    return GatedCase(
        case_id="c1",
        case_class="large_wire",
        facts=facts
        or {
            "amount": "USD 37,000,000",
            "what_was_flagged": "changed beneficiary banking details via email",
            "verification_done": "none",
        },
        designed_label="DENY",
        designed_rationale="this is the BEC pattern",
        label_provenance="synthetic_designed",
        source_refs=["https://example.com/x"],
    )


def test_assemble_copies_facts_verbatim_and_carries_numbers():
    case = _case()
    strip = assemble_cockpit(
        case, calibrated_confidence=0.83, class_false_approve_rate=0.22
    )
    assert strip.case_id == "c1"
    assert strip.case_class == "large_wire"
    assert strip.facts == case.facts  # verbatim
    assert strip.calibrated_confidence == 0.83
    assert strip.class_false_approve_rate == 0.22


def test_facts_are_a_copy_not_an_alias():
    case = _case()
    strip = assemble_cockpit(case)
    assert strip.facts == case.facts
    assert strip.facts is not case.facts  # defensive copy


def test_strip_has_no_recommendation_field():
    # The dataclass must not carry any verdict / recommendation field — by design.
    names = {f.name for f in fields(CockpitStrip)}
    assert names == {
        "case_id",
        "case_class",
        "facts",
        "calibrated_confidence",
        "class_false_approve_rate",
    }
    for forbidden in ("recommendation", "verdict", "advice", "suggestion"):
        assert forbidden not in names


def test_numbers_default_to_none():
    strip = assemble_cockpit(_case())
    assert strip.calibrated_confidence is None
    assert strip.class_false_approve_rate is None


def test_no_persuasive_prose_clean_strip():
    strip = assemble_cockpit(_case())
    assert no_persuasive_prose(strip) == []


def test_no_persuasive_prose_flags_recommendation_in_facts():
    case = _case(
        facts={
            "amount": "USD 1,000,000",
            "analyst_note": "you should approve this transfer, it looks fine",
        }
    )
    # The guard fires inside assemble_cockpit → it refuses to ship the strip.
    with pytest.raises(ValueError, match="persuasive prose"):
        assemble_cockpit(case)

    # And the bare guard reports the offending field + marker.
    strip = CockpitStrip(
        case_id="c1",
        case_class="large_wire",
        facts=case.facts,
        calibrated_confidence=None,
        class_false_approve_rate=None,
    )
    violations = no_persuasive_prose(strip)
    assert violations
    assert any("you should" in v for v in violations)
    assert any("analyst_note" in v for v in violations)


@pytest.mark.parametrize(
    "phrase",
    [
        "we recommend denying this",
        "i suggest you approve this",
        "you must deny",
        "recommend approving",
    ],
)
def test_persuasive_markers_caught(phrase):
    strip = CockpitStrip(
        case_id="c1",
        case_class="large_wire",
        facts={"note": phrase},
        calibrated_confidence=None,
        class_false_approve_rate=None,
    )
    assert no_persuasive_prose(strip)
    with pytest.raises(ValueError):
        assert_no_persuasive_prose(strip)
