"""Postgres-backed `ScanStore` — the production durable store for scan records + reports.

The in-memory twin (`memory.InMemoryScanStore`) is the test substrate; this is the same interface
backed by the `ScanRun`/`Report` ORM in `rogue.platform.models`. Per the API's pooling discipline
(`rogue.api.main._session_factory`, hardened after the 2026-06-01 Neon outage), every method opens a
short-lived session via `with self._session_factory() as s:` and never holds a transaction across an
await boundary — the engine is created with `pool_pre_ping` so a Neon-dropped idle connection is
validated/replaced on checkout rather than handed out dead.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import create_engine, select

from .interfaces import ScanStore
from .models import Report, ScanRun
from .schemas import ScanRecord, ScanStatus

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker


# --------------------------------------------------------------------------- #
# Pure mapping helpers (no IO) — the single place wire<->storage shapes meet.
# --------------------------------------------------------------------------- #

# Columns the ORM owns that have no `ScanRecord` field (or differ in shape): we never copy these
# through the record round-trip. `spec`/`idempotency_key` are dispatch-side bookkeeping set by the
# service layer, not by the record itself.
_RECORD_FIELDS: tuple[str, ...] = (
    "scan_id",
    "org_id",
    "project_id",
    "status",
    "progress",
    "n_tests",
    "n_completed",
    "n_breaches",
    "top_attack",
    "score",
    "cost_usd",
    "report_id",
    "error",
    "target",
    "pack",
    "created_at",
    "started_at",
    "completed_at",
)


def _record_to_orm(rec: ScanRecord) -> ScanRun:
    """Build a fresh `ScanRun` row from a `ScanRecord`. `ScanStatus` is stored as its `.value`."""
    return ScanRun(
        scan_id=rec.scan_id,
        org_id=rec.org_id,
        project_id=rec.project_id,
        status=rec.status.value,
        progress=rec.progress,
        n_tests=rec.n_tests,
        n_completed=rec.n_completed,
        n_breaches=rec.n_breaches,
        top_attack=rec.top_attack,
        score=rec.score,
        cost_usd=rec.cost_usd,
        report_id=rec.report_id,
        error=rec.error,
        target=rec.target,
        pack=rec.pack,
        created_at=rec.created_at,
        started_at=rec.started_at,
        completed_at=rec.completed_at,
    )


def _orm_to_record(row: ScanRun) -> ScanRecord:
    """Project a `ScanRun` row back into a `ScanRecord`. The string status re-parses into the enum."""
    return ScanRecord(
        scan_id=row.scan_id,
        org_id=row.org_id,
        project_id=row.project_id,
        status=ScanStatus(row.status),
        progress=row.progress,
        n_tests=row.n_tests,
        n_completed=row.n_completed,
        n_breaches=row.n_breaches,
        top_attack=row.top_attack,
        score=row.score,
        cost_usd=row.cost_usd,
        report_id=row.report_id,
        error=row.error,
        target=row.target or {},
        pack=row.pack,
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


# --------------------------------------------------------------------------- #
# PostgresScanStore
# --------------------------------------------------------------------------- #


class PostgresScanStore(ScanStore):
    """SQLAlchemy-backed `ScanStore`. Construct with a `sessionmaker`; one short-lived session per call."""

    def __init__(self, session_factory: "sessionmaker") -> None:
        self._session_factory = session_factory

    async def create(self, record: ScanRecord) -> ScanRecord:
        with self._session_factory() as s:
            row = _record_to_orm(record)
            s.add(row)
            s.commit()
            s.refresh(row)
            return _orm_to_record(row)

    async def get(self, scan_id: str, *, org_id: str | None = None) -> ScanRecord | None:
        with self._session_factory() as s:
            row = s.get(ScanRun, scan_id)
            if row is None:
                return None
            # Cross-tenant read → not found (no existence leak), mirroring the in-memory store.
            if org_id is not None and row.org_id != org_id:
                return None
            return _orm_to_record(row)

    async def update(
        self, scan_id: str, *, expected_status: ScanStatus | None = None, **fields: Any
    ) -> ScanRecord:
        with self._session_factory() as s:
            row = s.get(ScanRun, scan_id)
            if row is None:
                raise KeyError(scan_id)
            # Compare-and-set guard. The session is already a transaction, so reading the current status
            # and (conditionally) writing within it is atomic for the single in-process worker. If the
            # caller pinned an `expected_status` and the row has since moved off it (e.g. CANCELED mid-run),
            # skip every setattr and return the unchanged record — the stale terminal write is dropped.
            if expected_status is not None and row.status != expected_status.value:
                return _orm_to_record(row)
            for key, value in fields.items():
                if key == "status" and isinstance(value, ScanStatus):
                    value = value.value
                setattr(row, key, value)
            s.commit()
            s.refresh(row)
            return _orm_to_record(row)

    async def list(
        self,
        *,
        org_id: str,
        project_id: str | None = None,
        status: ScanStatus | None = None,
        limit: int = 50,
    ) -> list[ScanRecord]:
        with self._session_factory() as s:
            stmt = select(ScanRun).where(ScanRun.org_id == org_id)
            if project_id is not None:
                stmt = stmt.where(ScanRun.project_id == project_id)
            if status is not None:
                stmt = stmt.where(ScanRun.status == status.value)
            # Newest-first. `created_at` may be NULL (record built before persist sets it); secondary
            # sort on `scan_id` keeps the order stable when timestamps tie.
            stmt = stmt.order_by(ScanRun.created_at.desc(), ScanRun.scan_id.desc()).limit(limit)
            return [_orm_to_record(row) for row in s.execute(stmt).scalars()]

    async def save_report(self, *, report_id: str, scan_id: str, payload: dict) -> None:
        with self._session_factory() as s:
            row = s.get(Report, report_id)
            if row is None:
                s.add(
                    Report(
                        report_id=report_id,
                        scan_id=scan_id,
                        payload=payload,
                        created_at=datetime.now(timezone.utc),
                    )
                )
            else:
                # Upsert: an existing report id re-points at this scan with the latest payload.
                row.scan_id = scan_id
                row.payload = payload
            s.commit()

    async def get_report(self, report_id: str) -> dict | None:
        with self._session_factory() as s:
            row = s.get(Report, report_id)
            return row.payload if row is not None else None


def build_postgres_scan_store(database_url: str | None = None) -> PostgresScanStore:
    """Build a `PostgresScanStore` over a fresh engine/sessionmaker.

    Defaults to `os.environ["DATABASE_URL"]`. Engine is hardened the same way as the API's pool
    (`pool_pre_ping`/`pool_recycle`/`pool_timeout`) so Neon's dropped idle connections don't wedge
    the store. `expire_on_commit=False` keeps refreshed rows readable after commit for the mapping.
    """
    url = database_url or os.environ["DATABASE_URL"]
    from sqlalchemy.orm import sessionmaker  # local import: keep module import zero-IO and light.

    engine = create_engine(url, pool_pre_ping=True, pool_recycle=300, pool_timeout=10)
    return PostgresScanStore(sessionmaker(bind=engine, expire_on_commit=False))


__all__ = [
    "PostgresScanStore",
    "build_postgres_scan_store",
    "_record_to_orm",
    "_orm_to_record",
]
