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
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from . import memory, scoring
from .schemas import ScanStatus

_log = logging.getLogger("rogue.platform.worker")

# How many idle poll-cycles between expired-lease recovery sweeps. At the default poll_interval the
# lease TTL (≈300s) is what gates how soon an orphan is reclaimable, so sweeping ~every 60s recovers a
# crashed/redeployed worker's scan promptly without hammering the DB.
_REAP_EVERY_IDLE_CYCLES = 30

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
        secret_store=None,
    ) -> None:
        self.store = store
        self.queue = queue
        self.engine = engine
        self.worker_id = worker_id
        # Resolves an `api_key_ref` handle back to the raw target key just-in-time (held only in memory
        # for the scan). When None, a spec's raw `api_key` is used as-is.
        self.secret_store = secret_store

    async def run_once(self) -> bool:
        """Lease and process a single job. Returns False only when the queue was empty (nothing leased);
        True once a job has been handled — whether it completed or failed (the failure is recorded, not
        propagated)."""
        job = await self.queue.lease(worker_id=self.worker_id)
        if job is None:
            return False

        # Redelivery guard. The queue is at-least-once: a job can be re-leased after its visibility
        # timeout (or because it was canceled). Re-read the record; if it's already terminal
        # (COMPLETED/FAILED/CANCELED) the scan must NOT run again — ack the (duplicate) job and return
        # without touching the engine, so a redelivery can't re-run finished work or revive a CANCELED scan.
        record = await self.store.get(job.scan_id, org_id=job.org_id)
        if record is not None and record.status.is_terminal:
            await self.queue.ack(job.job_id)
            return True

        # Flip the record to RUNNING before any work so a poller sees the scan has started. Guard on
        # QUEUED: if a racing transition (e.g. cancel) already moved it off QUEUED, this is a no-op.
        await self.store.update(
            job.scan_id, expected_status=ScanStatus.QUEUED, status=ScanStatus.RUNNING, started_at=_now()
        )

        # Progress callback the engine fires per primitive — keeps the record's live counters fresh.
        async def cb(n_completed: int, n_total: int, current: str | None) -> None:
            await self.store.update(
                job.scan_id,
                progress=int(100 * n_completed / max(1, n_total)),
                n_completed=n_completed,
                n_tests=n_total,
                top_attack=current,
            )

        # Resolve the encrypted target key just-in-time: the persisted/leased spec carries only a
        # `secref_` handle; turn it back into the raw key in memory for this run only.
        spec = job.spec
        if self.secret_store is not None and spec.target.api_key_ref and not spec.target.api_key:
            raw = self.secret_store.resolve(spec.target.api_key_ref, org_id=job.org_id)
            spec = spec.model_copy(update={"target": spec.target.model_copy(update={"api_key": raw})})

        try:
            report = await self.engine.run(spec, progress=cb)
        except Exception as e:  # noqa: BLE001 — any engine failure is recorded, never escapes the worker.
            # Guard on RUNNING: only finalize FAILED if the scan is still running. If it was CANCELED
            # mid-run the write is a no-op and the record stays CANCELED.
            await self.store.update(
                job.scan_id,
                expected_status=ScanStatus.RUNNING,
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
        # Guard on RUNNING: the terminal COMPLETED write applies ONLY if the scan is still running. If
        # `cancel_scan` flipped it to CANCELED while the engine ran, this is a no-op and the returned
        # record stays CANCELED — cancellation wins over the worker's completion.
        await self.store.update(
            job.scan_id,
            expected_status=ScanStatus.RUNNING,
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
        # Ack regardless of `finalized.status`: whether the scan finalized COMPLETED or was canceled
        # mid-run (in which case the guarded write above was a no-op and it stays CANCELED), the job is
        # done and must not be redelivered.
        await self.queue.ack(job.job_id)
        return True

    async def run_forever(
        self,
        *,
        poll_interval: float = 1.0,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """Loop ``run_once`` forever (or until ``stop_event`` is set), sleeping ``poll_interval`` seconds
        whenever the queue is empty so an idle worker doesn't spin.

        On startup and then periodically while idle, sweep for expired leases (`reap_expired`) so a scan
        orphaned by a previous worker's death — e.g. a redeploy that restarted this process mid-scan —
        is requeued and resumed instead of hanging in RUNNING forever."""
        self._reap()  # recover anything orphaned before this worker started (e.g. the last redeploy)
        idle = 0
        while stop_event is None or not stop_event.is_set():
            did_work = await self.run_once()
            if did_work:
                idle = 0
                continue
            idle += 1
            if idle % _REAP_EVERY_IDLE_CYCLES == 0:
                self._reap()
            await asyncio.sleep(poll_interval)

    def _reap(self) -> None:
        """Requeue jobs whose lease expired (crashed/redeployed worker). Never lets a sweep failure
        crash the worker loop."""
        try:
            n = self.queue.reap_expired()
        except Exception as e:  # noqa: BLE001 — recovery sweep is best-effort; a failure must not kill the loop.
            _log.warning("reap_expired sweep failed: %s", e)
            return
        if n:
            _log.info("recovered %d orphaned scan job(s) via expired-lease reap", n)


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
