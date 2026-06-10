"""Surface 2 gate-decision attestation — rides the EXISTING per-org hash chain (build 07 §5).

Offline, SQLite-backed (mirrors ``tests/attestation/test_service.py``). Appends a
gate decision (a false-approve) as an ``entry_type="decision"`` record, verifies the
chain is intact and the payload carries the disposition cell + designed_label +
framing, then TAMPERS with a stored entry and proves ``verify().ok`` flips to False.
Skips cleanly if the SQLite/SQLAlchemy substrate is unavailable.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from rogue.attestation.service import AttestationService  # noqa: E402
from rogue.db.models import Base  # noqa: E402
from rogue.oversight.attestation import (  # noqa: E402
    append_gate_decision,
    append_gate_run,
    decision_record,
)
from rogue.oversight.case_corpus import GatedCase, GatedDecision  # noqa: E402
from rogue.platform.models import (  # noqa: E402, F401  (register tables)
    AttestationEntry,
    Organization,
)

_AS_OF = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)
_ORG = "org_gate"


@pytest.fixture
def service():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine, tables=[Organization.__table__, AttestationEntry.__table__]
    )
    return AttestationService(sessionmaker(bind=engine, expire_on_commit=False))


def _case(case_id: str = "wire-001", designed_label: str = "DENY") -> GatedCase:
    return GatedCase(
        case_id=case_id,
        case_class="large_wire",
        facts={"amount": "USD 37,000,000"},
        designed_label=designed_label,
        designed_rationale="this is the vendor-email-compromise BEC pattern",
        label_provenance="synthetic_designed",
        source_refs=["https://example.com/x"],
    )


def _decision(case_id: str, decision: str) -> GatedDecision:
    return GatedDecision(
        case_id=case_id,
        reviewer="analyst-7",
        decision=decision,
        deliberation_notes="reviewed",
        decision_latency_s=42.0,
        decided_at=datetime.now(timezone.utc),
    )


def test_append_gate_decision_writes_decision_entry(service):
    case = _case()  # DENY-truth
    decision = _decision("wire-001", "APPROVE")  # false-approve (the headline breach)

    entry = append_gate_decision(
        service, _ORG, decision, case, corpus_as_of=_AS_OF
    )

    assert entry.entry_type == "decision"
    # Genesis (seq 0) written lazily, this is the first real entry → seq 1.
    assert entry.seq == 1

    # Chain verifies intact.
    result = service.verify(_ORG)
    assert result.ok is True
    assert result.broken_at_seq is None


def test_decision_payload_carries_cell_label_and_framing(service):
    case = _case()
    decision = _decision("wire-001", "APPROVE")
    entry = append_gate_decision(service, _ORG, decision, case, corpus_as_of=_AS_OF)

    p = entry.payload
    assert p["disposition_cell"] == "false_approve"
    assert p["breach"] is True
    assert p["verdict"] == "breach"
    assert p["designed_label"] == "DENY"  # the independent key travels with the record
    assert p["case_class"] == "large_wire"
    assert "threat-informed assurance" in p["framing"]
    assert "not a safety guarantee" in p["framing"]
    # measure-don't-claim discipline.
    assert "does not claim the gate improves accuracy" in p["measurement_note"]
    # The independent-label pointer rides as ground_truth_ref (ADR-0011).
    assert entry.ground_truth_ref == "oversight-corpus:wire-001"


def test_clean_decision_marked_not_breach(service):
    case = _case()  # DENY-truth
    decision = _decision("wire-001", "DENY")  # correct → true_deny, not a breach
    entry = append_gate_decision(service, _ORG, decision, case, corpus_as_of=_AS_OF)
    assert entry.payload["disposition_cell"] == "true_deny"
    assert entry.payload["breach"] is False
    assert entry.payload["verdict"] == "clean"


def test_decision_record_is_deterministic():
    case = _case()
    decision = _decision("wire-001", "APPROVE")
    r1 = decision_record(decision, case, corpus_as_of=_AS_OF)
    r2 = decision_record(decision, case, corpus_as_of=_AS_OF)
    assert r1 == r2


def test_append_gate_decision_rejects_mismatched_case(service):
    case = _case("wire-001")
    decision = _decision("OTHER", "APPROVE")
    with pytest.raises(ValueError, match="does not match"):
        append_gate_decision(service, _ORG, decision, case, corpus_as_of=_AS_OF)


def test_append_gate_run_is_complete_one_entry_per_decision(service):
    cases = [_case("wire-001", "DENY"), _case("wire-002", "APPROVE")]
    decisions = [
        _decision("wire-001", "APPROVE"),  # false-approve
        _decision("wire-002", "APPROVE"),  # true-approve
    ]
    entries = append_gate_run(service, _ORG, decisions, cases, corpus_as_of=_AS_OF)
    assert len(entries) == 2  # complete: one per decision, not just the breach
    assert all(e.entry_type == "decision" for e in entries)
    assert service.verify(_ORG).ok is True


def test_tamper_breaks_verification(service):
    """Mutate a stored entry's payload → the content hash no longer matches → verify fails."""
    case = _case()
    decision = _decision("wire-001", "APPROVE")
    entry = append_gate_decision(service, _ORG, decision, case, corpus_as_of=_AS_OF)
    entry_id = entry.entry_id

    # Pre-tamper: intact.
    assert service.verify(_ORG).ok is True

    # Tamper directly in the DB: flip the recorded breach to hide the false-approve.
    sf = service._session_factory
    with sf() as session:
        row = session.get(AttestationEntry, entry_id)
        payload = dict(row.payload)
        payload["breach"] = False
        payload["disposition_cell"] = "true_deny"
        payload["verdict"] = "clean"
        row.payload = payload
        session.commit()

    # Post-tamper: the chain re-walk recomputes compute_hash(prev, payload) and it
    # no longer equals the stored entry_hash → verification fails at that seq.
    result = service.verify(_ORG)
    assert result.ok is False
    assert result.broken_at_seq == entry.seq
