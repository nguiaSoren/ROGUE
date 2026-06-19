"""Pool attestation adapter (Section H) — the FOUR numbers + framing, verify/tamper.

SQLite-backed AttestationService (mirrors tests/attestation/test_service.py): the
adapter reads synthetic skill_verifications rows, assembles the spec §3 payload, and
appends to the per-org hash chain. verify(org).ok is True intact; tampering the
stored payload breaks the chain (verify → False).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rogue.attestation.service import AttestationService
from rogue.db.models import (
    Base,
    SkillVerification,
    SkillVerificationKind,
    SkillVerificationVerdict,
)
from rogue.memory.attestation import (
    POOL_ENTRY_TYPE,
    append_pool_attestation,
    build_pool_attestation_payload,
)
from rogue.memory.cohorts import resolve_scope
from rogue.platform.models import AttestationEntry, Organization  # noqa: F401

_AS_OF = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def service():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine, tables=[Organization.__table__, AttestationEntry.__table__]
    )
    return AttestationService(sessionmaker(bind=engine, expire_on_commit=False))


def _verifications() -> list[SkillVerification]:
    now = datetime(2026, 6, 8, 11, 0, 0, tzinfo=timezone.utc)
    return [
        # two promotion PASS rows (number 1: N active, net-positive, CIs)
        SkillVerification(
            verification_id="v-promo-1", skill_id="skill-1", cohort_id="team-a",
            kind=SkillVerificationKind.PROMOTION, net_effect=8.0, repairs=14, regressions=6,
            ci_low=0.5, ci_high=0.9, held_out_n=20, judge_calibration_ref="cal:net@v1",
            decided_at=now, verdict=SkillVerificationVerdict.PASS,
        ),
        SkillVerification(
            verification_id="v-promo-2", skill_id="skill-2", cohort_id="team-a",
            kind=SkillVerificationKind.PROMOTION, net_effect=4.0, repairs=10, regressions=6,
            ci_low=0.3, ci_high=0.8, held_out_n=20, judge_calibration_ref="cal:net@v1",
            decided_at=now, verdict=SkillVerificationVerdict.PASS,
        ),
        # a promotion FAIL row — must NOT count toward N active
        SkillVerification(
            verification_id="v-promo-3", skill_id="skill-3", cohort_id="team-a",
            kind=SkillVerificationKind.PROMOTION, net_effect=-2.0, repairs=4, regressions=6,
            ci_low=0.0, ci_high=0.3, held_out_n=10, decided_at=now,
            verdict=SkillVerificationVerdict.FAIL,
        ),
        # latest leakage row (number 2: measured rate + CI)
        SkillVerification(
            verification_id="v-leak-1", skill_id="pool:extraction-pack-v1", cohort_id="team-a",
            kind=SkillVerificationKind.LEAKAGE, leakage_rate=0.30, ci_low=0.12, ci_high=0.50,
            held_out_n=20, judge_calibration_ref="cal:leak@v1", decided_at=now,
            verdict=SkillVerificationVerdict.FAIL,
        ),
        # a combination PASS row (number 3: M quarantined neighborhoods)
        SkillVerification(
            verification_id="v-comb-1", skill_id="skill-1", cohort_id="team-a",
            kind=SkillVerificationKind.COMBINATION, net_effect=0.9, held_out_n=1,
            scan_run_id="scan-7", decided_at=now, verdict=SkillVerificationVerdict.PASS,
        ),
    ]


def _scope():
    return resolve_scope(org_id="org-a", cohort_id="team-a", trust_domain="domain-a")


def test_payload_carries_the_four_numbers_and_framing():
    payload = build_pool_attestation_payload(
        _verifications(),
        cohort_id="team-a",
        scope=_scope(),
        corpus_as_of=_AS_OF,
        pack_coverage={"pack_id": "extraction-pack-v1", "version": 1, "tier": "standard"},
    )
    # Number 1 — N active, net-positive (FAIL excluded).
    assert payload["active_skills"]["n_active_verified"] == 2
    assert {s["skill_id"] for s in payload["active_skills"]["skills"]} == {"skill-1", "skill-2"}
    assert all(s["ci_low"] is not None for s in payload["active_skills"]["skills"])
    # Number 2 — measured leakage rate + CI + coverage.
    assert payload["leakage"]["measured"] is True
    assert payload["leakage"]["leakage_rate"] == 0.30
    assert payload["leakage"]["ci_low"] == 0.12 and payload["leakage"]["ci_high"] == 0.50
    assert payload["leakage"]["pack_coverage"]["tier"] == "standard"
    # Number 3 — M quarantined neighborhoods.
    assert payload["combination_quarantine"]["m_quarantined"] == 1
    # Number 4 — cohort isolation summary.
    assert payload["cohort_isolation"]["isolation_held"] is True
    assert payload["cohort_isolation"]["trust_domain"] == "domain-a"
    # Framing discipline (non-negotiable).
    assert "framing" in payload and payload["framing"]
    assert "NOT a safety guarantee" in payload["measurement_note"]
    assert payload["entry_type"] == POOL_ENTRY_TYPE


def test_payload_is_deterministic():
    a = build_pool_attestation_payload(
        _verifications(), cohort_id="team-a", scope=_scope(), corpus_as_of=_AS_OF,
    )
    b = build_pool_attestation_payload(
        _verifications(), cohort_id="team-a", scope=_scope(), corpus_as_of=_AS_OF,
    )
    assert a == b


def test_leakage_block_when_no_leakage_row():
    payload = build_pool_attestation_payload(
        [v for v in _verifications() if v.kind is not SkillVerificationKind.LEAKAGE],
        cohort_id="team-a", scope=_scope(), corpus_as_of=_AS_OF,
    )
    assert payload["leakage"]["measured"] is False
    assert payload["leakage"]["leakage_rate"] is None


def test_append_writes_entry_and_verify_ok(service):
    entry = append_pool_attestation(
        service, "org-a",
        cohort_id="team-a", scope=_scope(), corpus_as_of=_AS_OF,
        verifications=_verifications(),
        pack_coverage={"pack_id": "extraction-pack-v1", "version": 1, "tier": "standard"},
    )
    assert entry.entry_type == POOL_ENTRY_TYPE
    assert service.verify("org-a").ok is True
    # The four numbers survived into the stored payload.
    stored = service.get_entry("org-a", entry.entry_id)
    assert stored.payload["active_skills"]["n_active_verified"] == 2
    assert stored.payload["leakage"]["leakage_rate"] == 0.30
    assert stored.payload["combination_quarantine"]["m_quarantined"] == 1


def test_tamper_breaks_the_chain(service):
    entry = append_pool_attestation(
        service, "org-a",
        cohort_id="team-a", scope=_scope(), corpus_as_of=_AS_OF,
        verifications=_verifications(),
    )
    assert service.verify("org-a").ok is True

    # Tamper with the stored payload directly (entry_hash now disagrees with content).
    SessionFactory = service._session_factory  # noqa: SLF001 — test reaches into the store
    with SessionFactory() as s:
        row = s.get(AttestationEntry, entry.entry_id)
        bad = dict(row.payload)
        bad["leakage"] = {**bad["leakage"], "leakage_rate": 0.01}  # forge a better number
        row.payload = bad
        s.commit()

    result = service.verify("org-a")
    assert result.ok is False
    assert result.broken_at_seq is not None
