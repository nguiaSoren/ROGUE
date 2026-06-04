"""The scan worker — the single process that turns queued jobs into finished scan records.

The worker is deliberately the *only* place a scan actually executes: every surface (SDK / API / MCP /
dashboard) enqueues through :class:`ScanService`, and one or more workers lease those jobs and drive the
:class:`ScanEngine`. This keeps the request path cheap (never runs a scan in the calling thread) and lets
us scale execution horizontally by running more worker processes against the same store + queue.

Lifecycle of one job: lease → mark RUNNING → run the engine (streaming progress back into the record) →
on success persist the report + finalize COMPLETED + ack; on failure record the error + mark FAILED +
fail the job. A worker never lets an engine exception escape ``run_once`` — the job is always resolved.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from . import memory, scoring
from .schemas import ScanStatus

if TYPE_CHECKING:
    from .interfaces import JobQueue, ScanEngine, ScanStore


def _now() -> datetime:
    # UTC, timezone-aware — every persisted timestamp on a scan record is in the same clock.
    return datetime.now(timezone.utc)


class ScanWorker:
    """Leases scan jobs and runs them through the engine, finalizing the durable record."""

    def __init__(
        self,
        store: ScanStore,
        queue: JobQueue,
        engine: ScanEngine,
        *,
        worker_id: str = "worker-1",
    ) -> None:
        self.store = store
        self.queue = queue
        self.engine = engine
        self.worker_id = worker_id

    async def run_once(self) -> bool:
        """Lease and process a single job. Returns False only when the queue was empty (nothing leased);
        True once a job has been handled — whether it completed or failed (the failure is recorded, not
        propagated)."""
        job = await self.queue.lease(worker_id=self.worker_id)
        if job is None:
            return False

        # Flip the record to RUNNING before any work so a poller sees the scan has started.
        await self.store.update(job.scan_id, status=ScanStatus.RUNNING, started_at=_now())

        # Progress callback the engine fires per primitive — keeps the record's live counters fresh.
        async def cb(n_completed: int, n_total: int, current: str | None) -> None:
            await self.store.update(
                job.scan_id,
                progress=int(100 * n_completed / max(1, n_total)),
                n_completed=n_completed,
                n_tests=n_total,
                top_attack=current,
            )

        try:
            report = await self.engine.run(job.spec, progress=cb)
        except Exception as e:  # noqa: BLE001 — any engine failure is recorded, never escapes the worker.
            await self.store.update(
                job.scan_id,
                status=ScanStatus.FAILED,
                error=str(e)[:500],
                completed_at=_now(),
            )
            await self.queue.fail(job.job_id, error=str(e), retry=False)
            return True

        # Success: score, persist the full report payload, finalize the record, and ack the job.
        score = scoring.score_for(report)
        report_id = memory._new_id("rep")
        await self.store.save_report(report_id=report_id, scan_id=job.scan_id, payload=report.to_dict())
        await self.store.update(
            job.scan_id,
            status=ScanStatus.COMPLETED,
            progress=100,
            n_tests=report.n_tests,
            n_completed=report.n_tests,
            n_breaches=report.n_breaches,
            top_attack=report.top_attack,
            score=score,
            cost_usd=report.cost_usd,
            report_id=report_id,
            completed_at=_now(),
        )
        await self.queue.ack(job.job_id)
        return True

    async def run_forever(
        self,
        *,
        poll_interval: float = 1.0,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """Loop ``run_once`` forever (or until ``stop_event`` is set), sleeping ``poll_interval`` seconds
        whenever the queue is empty so an idle worker doesn't spin."""
        while stop_event is None or not stop_event.is_set():
            did_work = await self.run_once()
            if not did_work:
                await asyncio.sleep(poll_interval)


def main() -> None:
    """Process entrypoint: ``python -m rogue.platform.worker``.

    Deployed as a separate process from the API. It wires the Postgres-backed store + queue and the real
    engine, then runs forever. The production impls are imported lazily so merely importing this module
    (e.g. in offline tests) never requires a database or those classes to exist yet."""
    try:
        from .engine import DefaultScanEngine
        from .queue import PostgresJobQueue  # type: ignore[attr-defined]
        from .store import PostgresScanStore
    except ImportError as e:  # pragma: no cover — exercised only in a real deployment.
        raise RuntimeError(
            "rogue.platform.worker.main() requires the Postgres store/queue and DefaultScanEngine; "
            f"a production dependency is missing: {e}"
        ) from e

    store = PostgresScanStore()
    queue = PostgresJobQueue()
    engine = DefaultScanEngine()
    worker = ScanWorker(store, queue, engine)
    asyncio.run(worker.run_forever())


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["ScanWorker", "main"]
