"""In-memory `ScanStore` + `JobQueue` — the test substrate and a zero-infra single-process mode.

The Postgres-backed implementations (`store.py`, `queue.py`) are the production wiring; these let the
service/worker/API be built and tested with no database or Redis. Same interfaces, so swapping is a
one-line dependency change.
"""

from __future__ import annotations

import uuid
from collections import deque

from .interfaces import JobQueue, LeasedJob, ScanStore
from .schemas import ScanRecord, ScanSpec, ScanStatus


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


class InMemoryScanStore(ScanStore):
    def __init__(self) -> None:
        self._scans: dict[str, ScanRecord] = {}
        self._reports: dict[str, dict] = {}

    async def create(self, record: ScanRecord) -> ScanRecord:
        self._scans[record.scan_id] = record
        return record

    async def get(self, scan_id: str, *, org_id: str | None = None) -> ScanRecord | None:
        r = self._scans.get(scan_id)
        if r is None:
            return None
        if org_id is not None and r.org_id != org_id:
            return None  # cross-tenant read → not found (no existence leak)
        return r

    async def update(self, scan_id: str, **fields) -> ScanRecord:
        r = self._scans[scan_id]
        updated = r.model_copy(update=fields)
        self._scans[scan_id] = updated
        return updated

    async def list(self, *, org_id, project_id=None, status: ScanStatus | None = None, limit=50):
        rows = [
            r for r in self._scans.values()
            if r.org_id == org_id
            and (project_id is None or r.project_id == project_id)
            and (status is None or r.status == status)
        ]
        rows.sort(key=lambda r: (r.created_at or 0, r.scan_id), reverse=True)
        return rows[:limit]

    async def save_report(self, *, report_id: str, scan_id: str, payload: dict) -> None:
        self._reports[report_id] = {"scan_id": scan_id, "payload": payload}

    async def get_report(self, report_id: str) -> dict | None:
        return self._reports.get(report_id)


class InMemoryJobQueue(JobQueue):
    """FIFO in-memory queue. No real lease expiry (single process) — `lease` just pops the next job."""

    def __init__(self) -> None:
        self._jobs: dict[str, LeasedJob] = {}
        self._ready: deque[str] = deque()
        self._canceled: set[str] = set()

    async def enqueue(self, scan_id: str, spec: ScanSpec, *, org_id: str) -> str:
        job_id = _new_id("job")
        self._jobs[job_id] = LeasedJob(job_id=job_id, scan_id=scan_id, spec=spec, org_id=org_id)
        self._ready.append(job_id)
        return job_id

    async def lease(self, *, worker_id: str, lease_seconds: float = 300) -> LeasedJob | None:
        while self._ready:
            job_id = self._ready.popleft()
            job = self._jobs.get(job_id)
            if job is None or job.scan_id in self._canceled:
                continue
            return job
        return None

    async def ack(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)

    async def fail(self, job_id: str, *, error: str, retry: bool) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        if retry:
            job.attempts += 1
            if job.attempts < 3:
                self._ready.append(job_id)
                return
        self._jobs.pop(job_id, None)

    async def extend_lease(self, job_id: str, *, lease_seconds: float = 300) -> None:
        return None

    def cancel(self, scan_id: str) -> None:
        self._canceled.add(scan_id)


__all__ = ["InMemoryScanStore", "InMemoryJobQueue", "_new_id"]
