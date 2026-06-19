"""Offline tests for `PostgresJobQueue` — the durable dispatch state machine.

These run against an in-memory SQLite engine (no live DB). SQLite silently drops
`with_for_update(skip_locked=True)`, so these tests exercise the lease/ack/fail/reap state machine
single-threaded; the SKIP-LOCKED concurrency guard is Postgres-only and is verified live, not here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rogue.platform.models import ScanJob, ScanRun
from rogue.platform.queue import PostgresJobQueue
from rogue.platform.schemas import ScanSpec, TargetSpec

ORG_ID = "org_test"
SCAN_ID = "scan_test"


def _spec() -> ScanSpec:
    return ScanSpec(
        target=TargetSpec(provider="anthropic", model="claude-opus-4-8", system_prompt="be safe"),
        pack="default",
        max_tests=10,
    )


@pytest.fixture()
def session_factory():
    """In-memory SQLite with the two platform tables created. Seeds a ScanRun for the FK target
    (FKs aren't enforced on SQLite, but seeding keeps the fixture honest)."""
    engine = create_engine("sqlite://")
    # Only the tables the queue touches — not the whole research schema.
    ScanRun.__table__.create(engine)
    ScanJob.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(
            ScanRun(
                scan_id=SCAN_ID,
                org_id=ORG_ID,
                status="queued",
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
    return factory


@pytest.mark.asyncio
async def test_enqueue_lease_ack(session_factory):
    q = PostgresJobQueue(session_factory)
    spec = _spec()

    job_id = await q.enqueue(SCAN_ID, spec, org_id=ORG_ID)
    assert job_id.startswith("job_")

    leased = await q.lease(worker_id="w1")
    assert leased is not None
    assert leased.job_id == job_id
    assert leased.scan_id == SCAN_ID
    assert leased.org_id == ORG_ID
    assert leased.attempts == 0
    # Spec round-trips through payload JSON.
    assert isinstance(leased.spec, ScanSpec)
    assert leased.spec.target.model == "claude-opus-4-8"
    assert leased.spec.max_tests == 10

    # Row is now leased with lease bookkeeping set.
    with session_factory() as session:
        row = session.get(ScanJob, job_id)
        assert row.status == "leased"
        assert row.locked_by == "w1"
        assert row.lease_expires_at is not None

    await q.ack(job_id)
    with session_factory() as session:
        assert session.get(ScanJob, job_id).status == "done"


@pytest.mark.asyncio
async def test_lease_empty_returns_none(session_factory):
    q = PostgresJobQueue(session_factory)
    assert await q.lease(worker_id="w1") is None


@pytest.mark.asyncio
async def test_lease_skips_future_available_at(session_factory):
    """A job whose available_at is in the future (e.g. backoff) is not leasable yet."""
    q = PostgresJobQueue(session_factory)
    job_id = await q.enqueue(SCAN_ID, _spec(), org_id=ORG_ID)
    with session_factory() as session:
        session.get(ScanJob, job_id).available_at = datetime.now(timezone.utc) + timedelta(hours=1)
        session.commit()
    assert await q.lease(worker_id="w1") is None


@pytest.mark.asyncio
async def test_fail_with_retry_is_releasable(session_factory):
    q = PostgresJobQueue(session_factory)
    job_id = await q.enqueue(SCAN_ID, _spec(), org_id=ORG_ID)
    await q.lease(worker_id="w1")

    await q.fail(job_id, error="boom", retry=True)
    with session_factory() as session:
        row = session.get(ScanJob, job_id)
        assert row.status == "queued"
        assert row.attempts == 1
        assert row.error == "boom"
        assert row.locked_by is None
        # Backoff parks it in the future — pull it back to now so we can re-lease in-test.
        # (SQLite returns DateTime(timezone=True) values tz-naive, so compare naive-to-naive.)
        assert row.available_at > datetime.now(timezone.utc).replace(tzinfo=None)
        row.available_at = datetime.now(timezone.utc)
        session.commit()

    released = await q.lease(worker_id="w2")
    assert released is not None
    assert released.job_id == job_id
    assert released.attempts == 1


@pytest.mark.asyncio
async def test_fail_without_retry_dead_letters(session_factory):
    q = PostgresJobQueue(session_factory)
    job_id = await q.enqueue(SCAN_ID, _spec(), org_id=ORG_ID)
    await q.lease(worker_id="w1")

    await q.fail(job_id, error="fatal", retry=False)
    with session_factory() as session:
        row = session.get(ScanJob, job_id)
        assert row.status == "failed"
        assert row.error == "fatal"

    # Dead-lettered job is no longer leasable.
    assert await q.lease(worker_id="w2") is None


@pytest.mark.asyncio
async def test_fail_retry_exhausted_dead_letters(session_factory):
    """When attempts+1 reaches max_attempts, retry=True still dead-letters."""
    q = PostgresJobQueue(session_factory)
    job_id = await q.enqueue(SCAN_ID, _spec(), org_id=ORG_ID)
    with session_factory() as session:
        # Pre-load attempts so the next fail crosses max_attempts (default 3).
        session.get(ScanJob, job_id).attempts = 2
        session.commit()

    await q.fail(job_id, error="last", retry=True)
    with session_factory() as session:
        assert session.get(ScanJob, job_id).status == "failed"


@pytest.mark.asyncio
async def test_extend_lease(session_factory):
    q = PostgresJobQueue(session_factory)
    job_id = await q.enqueue(SCAN_ID, _spec(), org_id=ORG_ID)
    await q.lease(worker_id="w1", lease_seconds=10)
    with session_factory() as session:
        before = session.get(ScanJob, job_id).lease_expires_at

    await q.extend_lease(job_id, lease_seconds=3600)
    with session_factory() as session:
        after = session.get(ScanJob, job_id).lease_expires_at
    assert after > before


@pytest.mark.asyncio
async def test_reap_expired_requeues_stale_lease(session_factory):
    q = PostgresJobQueue(session_factory)
    job_id = await q.enqueue(SCAN_ID, _spec(), org_id=ORG_ID)
    await q.lease(worker_id="dead-worker")

    # Simulate a crashed worker: lease expired in the past, never acked.
    with session_factory() as session:
        session.get(ScanJob, job_id).lease_expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        )
        session.commit()

    n = q.reap_expired()
    assert n == 1
    with session_factory() as session:
        row = session.get(ScanJob, job_id)
        assert row.status == "queued"
        assert row.locked_by is None
        assert row.lease_expires_at is None

    # Reaped job is leasable again.
    releaseable = await q.lease(worker_id="w-fresh")
    assert releaseable is not None
    assert releaseable.job_id == job_id


@pytest.mark.asyncio
async def test_reap_expired_leaves_live_lease(session_factory):
    """A lease still in the future is left alone by the sweep."""
    q = PostgresJobQueue(session_factory)
    job_id = await q.enqueue(SCAN_ID, _spec(), org_id=ORG_ID)
    await q.lease(worker_id="w1", lease_seconds=3600)

    assert q.reap_expired() == 0
    with session_factory() as session:
        assert session.get(ScanJob, job_id).status == "leased"
