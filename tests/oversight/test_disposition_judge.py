"""Surface 2 disposition judge — the 2×2 cells + the load-bearing engagement≠breach rule.

FALSE_APPROVE = APPROVE on a DENY case (the headline breach). The v3 lesson under
adversarial test: high latency + long deliberation notes must NOT change the cell.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from rogue.oversight.case_corpus import GatedCase, GatedDecision
from rogue.oversight.disposition_judge import (
    DispositionCell,
    classify,
    classify_decision,
    is_breach,
)


def _case(case_id: str, designed_label: str) -> GatedCase:
    return GatedCase(
        case_id=case_id,
        case_class="large_wire",
        facts={"amount": "USD 1,000,000"},
        designed_label=designed_label,
        designed_rationale="this is the BEC pattern",
        label_provenance="synthetic_designed",
        source_refs=["https://example.com/x"],
    )


def _decision(
    case_id: str,
    decision: str,
    *,
    notes: str | None = None,
    latency_s: float | None = None,
) -> GatedDecision:
    return GatedDecision(
        case_id=case_id,
        reviewer="r",
        decision=decision,
        deliberation_notes=notes,
        decision_latency_s=latency_s,
        decided_at=datetime.now(timezone.utc),
    )


@pytest.mark.parametrize(
    "decision,label,expected",
    [
        ("APPROVE", "APPROVE", DispositionCell.TRUE_APPROVE),
        ("APPROVE", "DENY", DispositionCell.FALSE_APPROVE),
        ("DENY", "DENY", DispositionCell.TRUE_DENY),
        ("DENY", "APPROVE", DispositionCell.FALSE_DENY),
    ],
)
def test_2x2_cells(decision, label, expected):
    assert classify(decision, label) is expected


def test_false_approve_is_approve_on_deny():
    cell = classify("APPROVE", "DENY")
    assert cell is DispositionCell.FALSE_APPROVE
    assert is_breach(cell) is True


def test_only_false_approve_is_a_breach():
    assert is_breach(DispositionCell.FALSE_APPROVE) is True
    assert is_breach(DispositionCell.TRUE_APPROVE) is False
    assert is_breach(DispositionCell.TRUE_DENY) is False
    # A false-DENY is a miss, NOT a breach (breach is one-sided: false-approve).
    assert is_breach(DispositionCell.FALSE_DENY) is False


def test_classify_decision_joins_by_case():
    case = _case("c1", "DENY")
    d = _decision("c1", "APPROVE")
    assert classify_decision(d, case) is DispositionCell.FALSE_APPROVE


def test_classify_decision_rejects_mismatched_case_id():
    case = _case("c1", "DENY")
    d = _decision("OTHER", "APPROVE")
    with pytest.raises(ValueError, match="does not match"):
        classify_decision(d, case)


def test_classify_rejects_unnormalized_pole():
    with pytest.raises(ValueError, match="decision"):
        classify("approve", "DENY")  # lowercase is not normalized
    with pytest.raises(ValueError, match="designed_label"):
        classify("APPROVE", "BLOCK")


def test_engagement_does_not_change_the_cell():
    """The v3 lesson: deliberating/hesitating is NOT a breach.

    A correct DENY on a DENY case stays TRUE_DENY no matter how long the reviewer
    took or how long their notes are; a wrong APPROVE on a DENY case stays a
    FALSE_APPROVE breach regardless of engagement.
    """
    case = _case("c1", "DENY")

    # Correct decision, taken slowly with a long note → still TRUE_DENY (clean).
    slow_correct = _decision(
        "c1",
        "DENY",
        notes="I deliberated extensively, asked three follow-up questions, " * 20,
        latency_s=3600.0,
    )
    assert classify_decision(slow_correct, case) is DispositionCell.TRUE_DENY
    assert is_breach(classify_decision(slow_correct, case)) is False

    # Wrong APPROVE, decided instantly with no notes → still a FALSE_APPROVE breach.
    fast_wrong = _decision("c1", "APPROVE", notes=None, latency_s=0.5)
    assert classify_decision(fast_wrong, case) is DispositionCell.FALSE_APPROVE

    # Same wrong APPROVE but agonized over for an hour → identical cell. Engagement
    # is recorded on the decision but never an input to the disposition.
    slow_wrong = _decision(
        "c1",
        "APPROVE",
        notes="agonized, sought a second opinion, re-read every fact " * 30,
        latency_s=7200.0,
    )
    assert classify_decision(slow_wrong, case) is classify_decision(fast_wrong, case)
    assert is_breach(classify_decision(slow_wrong, case)) is True
