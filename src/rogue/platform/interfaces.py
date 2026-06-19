"""Pinned platform interfaces (ABCs). Every concrete module implements one of these.

The orchestration is built around two storage abstractions — :class:`ScanStore` (durable records)
and :class:`JobQueue` (dispatch) — each with an in-memory impl (tests + single-process mode) and a
Postgres impl (production). The three services (:class:`ScanEngine`, :class:`ScanService`,
:class:`ReportService`) are the boxes from ``docs/platform/ARCHITECTURE.md`` §4. Implementors must
match these signatures exactly; if a signature must change, it changes here first.
"""

from __future__ import annotations

import abc
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from .schemas import ScanRecord, ScanSpec, ScanStatus

if TYPE_CHECKING:
    from rogue.report import BenchmarkReport, ScanReport, ValidationResult

# (n_completed, n_total, current_attack) — the worker wires this into the engine to update progress.
ProgressCallback = Callable[[int, int, str | None], Awaitable[None]]


class LeasedJob:
    """A job handed to a worker: the scan to run + the lease bookkeeping."""

    def __init__(self, job_id: str, scan_id: str, spec: ScanSpec, org_id: str, attempts: int = 0):
        self.job_id = job_id
        self.scan_id = scan_id
        self.spec = spec
        self.org_id = org_id
        self.attempts = attempts


class ScanStore(abc.ABC):
    """Durable scan records + reports (Postgres in prod; in-memory for tests)."""

    @abc.abstractmethod
    async def create(self, record: ScanRecord) -> ScanRecord: ...

    @abc.abstractmethod
    async def get(self, scan_id: str, *, org_id: str | None = None) -> ScanRecord | None: ...

    @abc.abstractmethod
    async def update(
        self, scan_id: str, *, expected_status: ScanStatus | None = None, **fields: Any
    ) -> ScanRecord: ...
    # Compare-and-set: when `expected_status` is given the update applies ONLY if the record's CURRENT
    # status equals it; otherwise the call is a no-op and returns the record UNCHANGED. This is the guard
    # the worker uses so a CANCELED scan (set mid-run by `cancel_scan`) is never clobbered back to
    # COMPLETED, and a redelivered job's terminal write can't overwrite an already-finalized record.

    @abc.abstractmethod
    async def list(self, *, org_id: str, project_id: str | None = None, status: ScanStatus | None = None,
                   limit: int = 50) -> list[ScanRecord]: ...

    @abc.abstractmethod
    async def save_report(self, *, report_id: str, scan_id: str, payload: dict) -> None: ...

    @abc.abstractmethod
    async def get_report(self, report_id: str) -> dict | None: ...


class JobQueue(abc.ABC):
    """Scan-job dispatch with a visibility-timeout lease (so a crashed worker's job is reclaimed)."""

    @abc.abstractmethod
    async def enqueue(self, scan_id: str, spec: ScanSpec, *, org_id: str) -> str: ...

    @abc.abstractmethod
    async def lease(self, *, worker_id: str, lease_seconds: float = 300) -> LeasedJob | None: ...

    @abc.abstractmethod
    async def ack(self, job_id: str) -> None: ...

    @abc.abstractmethod
    async def fail(self, job_id: str, *, error: str, retry: bool) -> None: ...

    @abc.abstractmethod
    async def extend_lease(self, job_id: str, *, lease_seconds: float = 300) -> None: ...

    def reap_expired(self) -> int:
        """Crash recovery: requeue every job whose lease has expired (its worker died / was redeployed
        mid-scan), so the scan resumes instead of hanging forever. Returns the count reclaimed. Default
        no-op for single-process queues (`InMemoryJobQueue`); `PostgresJobQueue` overrides it."""
        return 0


class ScanEngine(abc.ABC):
    """The ONE execution path — a thin wrapper over the existing `rogue.scan.run_scan`."""

    @abc.abstractmethod
    async def run(self, spec: ScanSpec, *, progress: ProgressCallback | None = None) -> ScanReport: ...

    @abc.abstractmethod
    async def validate(self, spec: ScanSpec) -> ValidationResult: ...

    @abc.abstractmethod
    async def benchmark(self, spec: ScanSpec, *, dataset: str, max_goals: int) -> BenchmarkReport: ...


class ScanService(abc.ABC):
    """The single entry every surface (SDK/API/MCP/dashboard) calls. Queue-backed; never runs a scan
    in the calling thread."""

    @abc.abstractmethod
    async def create_scan(self, spec: ScanSpec, *, org_id: str, project_id: str | None = None,
                          actor: str | None = None, idempotency_key: str | None = None) -> ScanRecord: ...

    @abc.abstractmethod
    async def get_scan(self, scan_id: str, *, org_id: str) -> ScanRecord | None: ...

    @abc.abstractmethod
    async def cancel_scan(self, scan_id: str, *, org_id: str) -> ScanRecord: ...

    @abc.abstractmethod
    async def list_scans(self, *, org_id: str, project_id: str | None = None, limit: int = 50) -> list[ScanRecord]: ...


class ReportService(abc.ABC):
    """Renders a persisted scan into customer artifacts."""

    @abc.abstractmethod
    async def build_json(self, scan_id: str) -> dict: ...

    @abc.abstractmethod
    async def build_html(self, scan_id: str) -> str: ...

    @abc.abstractmethod
    async def build_pdf(self, scan_id: str) -> bytes: ...

    @abc.abstractmethod
    async def build_executive_summary(self, scan_id: str) -> str: ...


__all__ = [
    "ProgressCallback", "LeasedJob",
    "ScanStore", "JobQueue", "ScanEngine", "ScanService", "ReportService",
]
