"""Durable Postgres `JobQueue` — the production dispatch backed by the `scan_jobs` table.

The in-memory sibling (`memory.InMemoryJobQueue`) is the single-process / test substrate; this one
is the source of truth in Postgres, so a crashed worker's job is reclaimed via a visibility-timeout
lease. The lease is implemented with `SELECT ... FOR UPDATE SKIP LOCKED` so N concurrent workers can
poll the same queue without ever handing the same row to two of them — that SKIP-LOCKED clause is the
Postgres-only concurrency guard (SQLite silently drops `with_for_update`, which is why the offline
tests are single-threaded and exercise the state machine, not the locking).

Same `JobQueue` interface as the in-memory impl, so swapping production wiring is a one-line change.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from .interfaces import JobQueue, LeasedJob
from .memory import _new_id
from .models import ScanJob
from .schemas import ScanSpec

# Exponential retry backoff, in seconds, keyed by the post-increment attempt count (1, 2, 3, ...).
# attempt 1 → 5s, attempt 2 → 25s, attempt 3 → 125s, capped so a hot-looping failure can't park a job
# for hours.
_BACKOFF_BASE_SECONDS = 5
_BACKOFF_CAP_SECONDS = 600

DEFAULT_DATABASE_URL = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _backoff(attempts: int) -> timedelta:
    """Exponential backoff for the next retry of an `attempts`-times-failed job (capped)."""
    seconds = _BACKOFF_BASE_SECONDS * (5 ** max(attempts - 1, 0))
    return timedelta(seconds=min(seconds, _BACKOFF_CAP_SECONDS))


class PostgresJobQueue(JobQueue):
    """Durable scan-job dispatch over the `ScanJob` ORM. `session_factory` is a SQLAlchemy
    `sessionmaker` (or any zero-arg callable returning a `Session` usable as a context manager)."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    async def enqueue(self, scan_id: str, spec: ScanSpec, *, org_id: str) -> str:
        job_id = _new_id("job")
        now = _now()
        with self._session_factory() as session:
            session.add(
                ScanJob(
                    job_id=job_id,
                    scan_id=scan_id,
                    org_id=org_id,
                    status="queued",
                    payload=spec.model_dump(mode="json"),
                    available_at=now,
                    created_at=now,
                )
            )
            session.commit()
        return job_id

    async def lease(self, *, worker_id: str, lease_seconds: float = 300) -> LeasedJob | None:
        now = _now()
        with self._session_factory() as session:
            # Claim the oldest available queued job. FOR UPDATE SKIP LOCKED makes this safe for N
            # concurrent workers on Postgres; SQLite ignores the clause (single-threaded tests).
            stmt = (
                select(ScanJob)
                .where(ScanJob.status == "queued", ScanJob.available_at <= now)
                .order_by(ScanJob.priority.desc(), ScanJob.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            job = session.execute(stmt).scalar_one_or_none()
            if job is None:
                return None
            job.status = "leased"
            job.locked_by = worker_id
            job.locked_at = now
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            # Snapshot the fields we need before commit expires the instance attributes.
            leased = LeasedJob(
                job_id=job.job_id,
                scan_id=job.scan_id,
                spec=ScanSpec.model_validate(job.payload),
                org_id=job.org_id,
                attempts=job.attempts,
            )
            session.commit()
        return leased

    async def ack(self, job_id: str) -> None:
        with self._session_factory() as session:
            job = session.get(ScanJob, job_id)
            if job is None:
                return
            job.status = "done"
            session.commit()

    async def fail(self, job_id: str, *, error: str, retry: bool) -> None:
        with self._session_factory() as session:
            job = session.get(ScanJob, job_id)
            if job is None:
                return
            job.error = error
            if retry and job.attempts + 1 < job.max_attempts:
                # Re-queue with exponential backoff; the bumped attempt count drives the delay.
                job.attempts += 1
                job.status = "queued"
                job.available_at = _now() + _backoff(job.attempts)
                job.locked_by = None
                job.locked_at = None
                job.lease_expires_at = None
            else:
                # Exhausted retries (or caller opted out) → dead-letter.
                job.status = "failed"
            session.commit()

    async def extend_lease(self, job_id: str, *, lease_seconds: float = 300) -> None:
        with self._session_factory() as session:
            job = session.get(ScanJob, job_id)
            if job is None:
                return
            job.lease_expires_at = _now() + timedelta(seconds=lease_seconds)
            session.commit()

    def reap_expired(self) -> int:
        """Crash-recovery sweep: requeue every leased job whose lease has expired. Returns the count
        requeued. Run periodically by a supervisor — a worker that died mid-lease never acked, so its
        job sits in `leased` until its `lease_expires_at` passes and this hands it back to the pool."""
        now = _now()
        with self._session_factory() as session:
            stmt = select(ScanJob).where(
                ScanJob.status == "leased", ScanJob.lease_expires_at < now
            )
            jobs = session.execute(stmt).scalars().all()
            for job in jobs:
                job.status = "queued"
                job.available_at = now
                job.locked_by = None
                job.locked_at = None
                job.lease_expires_at = None
            session.commit()
            return len(jobs)


def build_postgres_job_queue(database_url: str | None = None) -> PostgresJobQueue:
    """Convenience constructor: wire a `PostgresJobQueue` to `database_url` (or `$DATABASE_URL`)."""
    url = database_url or os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    engine = create_engine(url, pool_pre_ping=True, pool_recycle=300, pool_timeout=10)
    session_factory = sessionmaker(bind=engine)
    return PostgresJobQueue(session_factory)


__all__ = ["PostgresJobQueue", "build_postgres_job_queue"]
