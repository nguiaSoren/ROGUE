"""Offline tests for `PostgresScanStore` — SQLite-backed, no live DB, no pgvector.

We create ONLY the two platform tables this store touches (`scan_runs`, `reports`) on an in-memory
SQLite engine, so the research tables' pgvector column never loads. SQLite doesn't enforce the
org/project foreign keys by default, so a `ScanRun` inserts fine without parent org/project rows.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rogue.db.models import Base
from rogue.platform.models import (  # noqa: F401  (import registers tables on Base.metadata)
    ApiKey,
    Membership,
    Organization,
    Project,
    Report,
    ScanJob,
    ScanRun,
    User,
)
from rogue.platform.schemas import ScanRecord, ScanStatus
from rogue.platform.store import (
    PostgresScanStore,
    _orm_to_record,
    _record_to_orm,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def session_factory():
    """In-memory SQLite with only the platform `scan_runs` + `reports` tables created."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[ScanRun.__table__, Report.__table__])
    return sessionmaker(bind=engine)


@pytest.fixture
def store(session_factory):
    return PostgresScanStore(session_factory)


def _record(scan_id: str, org_id: str = "org_a", **over) -> ScanRecord:
    base = dict(
        scan_id=scan_id,
        org_id=org_id,
        project_id="proj_1",
        status=ScanStatus.QUEUED,
        progress=0,
        n_tests=10,
        target={"provider": "openai", "model": "gpt-4o", "has_api_key": True},
        pack="default",
        created_at=datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc),
    )
    base.update(over)
    return ScanRecord(**base)


# --------------------------------------------------------------------------- #
# Pure mapping round-trip (no IO)
# --------------------------------------------------------------------------- #


def test_record_orm_roundtrip():
    rec = _record(
        "scan_rt",
        status=ScanStatus.COMPLETED,
        progress=100,
        n_completed=10,
        n_breaches=3,
        top_attack="dan_v11",
        score=0.42,
        cost_usd=1.23,
        report_id="rep_1",
        error=None,
        started_at=datetime(2026, 6, 5, 12, 1, tzinfo=timezone.utc),
        completed_at=datetime(2026, 6, 5, 12, 5, tzinfo=timezone.utc),
    )
    row = _record_to_orm(rec)
    # Status is stored as the bare string value, not the enum.
    assert row.status == "completed"
    assert isinstance(row.status, str)

    back = _orm_to_record(row)
    assert back == rec
    # The enum re-parses on the way back.
    assert back.status is ScanStatus.COMPLETED


def test_orm_to_record_null_target_defaults_to_empty_dict(session_factory):
    # Insert through the DB so the column `default=` values (progress=0, n_tests=0, ...) apply —
    # a bare unflushed `ScanRun(...)` leaves them None. We force `target=None` to exercise the guard.
    with session_factory() as s:
        s.add(
            ScanRun(
                scan_id="scan_nulltgt",
                org_id="org_a",
                status="queued",
                target=None,
                created_at=datetime(2026, 6, 5, tzinfo=timezone.utc),
            )
        )
        s.commit()
        row = s.get(ScanRun, "scan_nulltgt")
        rec = _orm_to_record(row)
    assert rec.target == {}


# --------------------------------------------------------------------------- #
# create / get (+ cross-tenant scoping)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_create_then_get(store):
    created = await store.create(_record("scan_1"))
    assert created.scan_id == "scan_1"
    assert created.status is ScanStatus.QUEUED

    got = await store.get("scan_1")
    assert got is not None
    assert got.scan_id == "scan_1"
    assert got.org_id == "org_a"
    assert got.n_tests == 10
    assert got.target["model"] == "gpt-4o"


@pytest.mark.asyncio
async def test_get_missing_returns_none(store):
    assert await store.get("nope") is None


@pytest.mark.asyncio
async def test_get_cross_tenant_returns_none(store):
    await store.create(_record("scan_1", org_id="org_a"))
    # Same scan_id, wrong tenant → not found (no existence leak).
    assert await store.get("scan_1", org_id="org_b") is None
    # Correct tenant resolves.
    assert (await store.get("scan_1", org_id="org_a")).scan_id == "scan_1"


# --------------------------------------------------------------------------- #
# update
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_update_patches_and_returns_fresh(store):
    await store.create(_record("scan_1"))
    updated = await store.update(
        "scan_1",
        status=ScanStatus.RUNNING,
        progress=55,
        score=0.7,
        n_completed=5,
    )
    assert updated.status is ScanStatus.RUNNING
    assert updated.progress == 55
    assert updated.score == 0.7
    assert updated.n_completed == 5
    # Persisted, not just returned.
    again = await store.get("scan_1")
    assert again.status is ScanStatus.RUNNING
    assert again.progress == 55


@pytest.mark.asyncio
async def test_update_accepts_status_as_string(store):
    await store.create(_record("scan_1"))
    updated = await store.update("scan_1", status="failed", error="boom")
    assert updated.status is ScanStatus.FAILED
    assert updated.error == "boom"


@pytest.mark.asyncio
async def test_update_missing_raises(store):
    with pytest.raises(KeyError):
        await store.update("ghost", progress=1)


# --------------------------------------------------------------------------- #
# list (filter by org / project / status, newest-first, limited)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_list_filters_and_orders(store):
    await store.create(
        _record("scan_old", created_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
    )
    await store.create(
        _record("scan_new", created_at=datetime(2026, 6, 5, tzinfo=timezone.utc))
    )
    await store.create(_record("scan_other_org", org_id="org_b"))
    await store.create(_record("scan_running", status=ScanStatus.RUNNING))

    # Org scoping: org_b's scan is excluded.
    rows = await store.list(org_id="org_a")
    ids = [r.scan_id for r in rows]
    assert "scan_other_org" not in ids
    # Newest-first ordering.
    assert ids.index("scan_new") < ids.index("scan_old")

    # Status filter.
    running = await store.list(org_id="org_a", status=ScanStatus.RUNNING)
    assert [r.scan_id for r in running] == ["scan_running"]

    # Project filter (none match a bogus project).
    assert await store.list(org_id="org_a", project_id="proj_other") == []
    assert len(await store.list(org_id="org_a", project_id="proj_1")) >= 1


@pytest.mark.asyncio
async def test_list_respects_limit(store):
    for i in range(5):
        await store.create(
            _record(f"scan_{i}", created_at=datetime(2026, 6, i + 1, tzinfo=timezone.utc))
        )
    rows = await store.list(org_id="org_a", limit=2)
    assert len(rows) == 2
    # The two newest.
    assert [r.scan_id for r in rows] == ["scan_4", "scan_3"]


# --------------------------------------------------------------------------- #
# reports
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_save_then_get_report_roundtrip(store):
    await store.create(_record("scan_1"))
    payload = {"summary": "3 breaches", "findings": [{"attack": "dan_v11"}]}
    await store.save_report(report_id="rep_1", scan_id="scan_1", payload=payload)
    assert await store.get_report("rep_1") == payload


@pytest.mark.asyncio
async def test_save_report_upserts(store):
    await store.create(_record("scan_1"))
    await store.save_report(report_id="rep_1", scan_id="scan_1", payload={"v": 1})
    await store.save_report(report_id="rep_1", scan_id="scan_1", payload={"v": 2})
    assert await store.get_report("rep_1") == {"v": 2}


@pytest.mark.asyncio
async def test_get_report_missing_returns_none(store):
    assert await store.get_report("nope") is None
