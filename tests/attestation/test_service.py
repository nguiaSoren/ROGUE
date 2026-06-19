"""Offline tests for ``AttestationService`` — SQLite-backed, no live DB.

Creates only the platform tables the service touches (`organizations`,
`attestation_entries`) on an in-memory SQLite engine, so the research pgvector
column never loads. SQLite doesn't enforce the org FK and ignores
``with_for_update`` (single-threaded), so the per-org monotonic-seq + lazy-genesis
+ idempotency invariants are exercised without Postgres.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rogue.attestation.service import AttestationService
from rogue.db.models import Base
from rogue.platform.models import AttestationEntry, Organization  # noqa: F401  (register tables)

_AS_OF = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def service():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine, tables=[Organization.__table__, AttestationEntry.__table__]
    )
    return AttestationService(sessionmaker(bind=engine, expire_on_commit=False))


def test_first_append_writes_genesis_then_entry(service):
    entry = service.append("org_a", "scan", {"n": 1}, corpus_as_of=_AS_OF)
    # The appended scan entry is seq 1 (genesis is seq 0, written lazily).
    assert entry.seq == 1
    assert entry.entry_type == "scan"

    entries = service.list_entries("org_a", limit=100)
    assert [e.seq for e in entries] == [0, 1]
    assert entries[0].entry_type == "genesis"
    assert entries[0].prev_hash == "0" * 64
    # The scan entry links to genesis.
    assert entries[1].prev_hash == entries[0].entry_hash


def test_monotonic_seq_and_links(service):
    e1 = service.append("org_a", "scan", {"n": 1}, corpus_as_of=_AS_OF)
    e2 = service.append("org_a", "scan", {"n": 2}, corpus_as_of=_AS_OF)
    e3 = service.append("org_a", "scan", {"n": 3}, corpus_as_of=_AS_OF)
    assert [e1.seq, e2.seq, e3.seq] == [1, 2, 3]

    entries = service.list_entries("org_a", limit=100)
    prior = "0" * 64
    for e in entries:
        assert e.prev_hash == prior
        prior = e.entry_hash


def test_verify_ok_for_intact_chain(service):
    for i in range(3):
        service.append("org_a", "scan", {"n": i}, corpus_as_of=_AS_OF)
    result = service.verify("org_a")
    assert result.ok is True
    assert result.broken_at_seq is None


def test_verify_empty_chain_is_ok(service):
    assert service.verify("org_nobody").ok is True


def test_chains_are_per_org_isolated(service):
    service.append("org_a", "scan", {"n": 1}, corpus_as_of=_AS_OF)
    service.append("org_b", "scan", {"n": 1}, corpus_as_of=_AS_OF)
    # Each org has its own genesis at seq 0 + one scan at seq 1.
    assert [e.seq for e in service.list_entries("org_a", limit=100)] == [0, 1]
    assert [e.seq for e in service.list_entries("org_b", limit=100)] == [0, 1]
    assert service.verify("org_a").ok and service.verify("org_b").ok


def test_idempotent_on_reproducibility_ref(service):
    e1 = service.append("org_a", "scan", {"n": 1}, reproducibility_ref="scan_1", corpus_as_of=_AS_OF)
    # A retry with the SAME ref must NOT double-append.
    e2 = service.append("org_a", "scan", {"n": 1}, reproducibility_ref="scan_1", corpus_as_of=_AS_OF)
    assert e1.entry_id == e2.entry_id
    # genesis + exactly one scan entry.
    assert [e.seq for e in service.list_entries("org_a", limit=100)] == [0, 1]


def test_append_requires_corpus_as_of(service):
    with pytest.raises(ValueError, match="corpus_as_of"):
        service.append("org_a", "scan", {"n": 1}, corpus_as_of=None)


def test_head_returns_latest(service):
    assert service.head("org_a") is None
    service.append("org_a", "scan", {"n": 1}, corpus_as_of=_AS_OF)
    e2 = service.append("org_a", "scan", {"n": 2}, corpus_as_of=_AS_OF)
    head = service.head("org_a")
    assert head.seq == e2.seq == 2


def test_list_filters_by_entry_type_and_since_seq(service):
    service.append("org_a", "scan", {"n": 1}, corpus_as_of=_AS_OF)
    service.append("org_a", "decision", {"d": 1}, corpus_as_of=_AS_OF)
    service.append("org_a", "scan", {"n": 2}, corpus_as_of=_AS_OF)

    scans = service.list_entries("org_a", entry_type="scan", limit=100)
    assert all(e.entry_type == "scan" for e in scans)
    assert len(scans) == 2

    after = service.list_entries("org_a", since_seq=1, limit=100)
    assert all(e.seq > 1 for e in after)


def test_get_entry_cross_org_returns_none(service):
    e = service.append("org_a", "scan", {"n": 1}, corpus_as_of=_AS_OF)
    assert service.get_entry("org_a", e.entry_id).entry_id == e.entry_id
    # Cross-org read → not found (no existence leak).
    assert service.get_entry("org_b", e.entry_id) is None
