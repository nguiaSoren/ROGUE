"""Offline tests for the platform scan worker.

Uses the in-memory store + queue (the real impls from ``rogue.platform.memory``) plus a fake engine, so
the full lease → run → finalize lifecycle is exercised with no database, no network, and no API keys.
"""

from __future__ import annotations

import pytest

from rogue.platform.memory import InMemoryJobQueue, InMemoryScanStore, _new_id
from rogue.platform.schemas import ScanRecord, ScanSpec, ScanStatus, TargetSpec
from rogue.platform.worker import ScanWorker
from rogue.report import Finding, ScanReport


class FakeEngine:
    """An engine that fires two progress ticks then returns a real ScanReport with one breach."""

    async def run(self, spec, *, progress=None):
        if progress is not None:
            await progress(1, 2, "DAN")
            await progress(2, 2, "Crescendo")
        return ScanReport(
            target="t",
            n_tests=2,
            n_breaches=1,
            cost_usd=0.01,
            findings=[
                Finding(
                    family="dan_persona",
                    technique="DAN",
                    vector="user_turn",
                    severity="critical",
                    title="x",
                    success_rate=1.0,
                    n_trials=1,
                    n_breach=1,
                )
            ],
        )


class BoomEngine:
    """An engine whose run always raises — drives the failure path."""

    async def run(self, spec, *, progress=None):
        raise RuntimeError("engine exploded")


class SpyEngine:
    """Records whether `run` was invoked — used to prove the worker skips a redelivered terminal job."""

    def __init__(self) -> None:
        self.ran = False

    async def run(self, spec, *, progress=None):
        self.ran = True
        return ScanReport(target="t", n_tests=1, n_breaches=0, cost_usd=0.0, findings=[])


class CancelMidRunEngine:
    """An engine that cancels its own scan (via the store) before returning — simulates a cancel_scan
    landing while the engine is in-flight. Proves the worker's terminal write is guarded."""

    def __init__(self, store: InMemoryScanStore, scan_id: str) -> None:
        self._store = store
        self._scan_id = scan_id

    async def run(self, spec, *, progress=None):
        # Mirror what ScanService.cancel_scan does to the record while a scan is RUNNING.
        await self._store.update(self._scan_id, status=ScanStatus.CANCELED)
        return ScanReport(target="t", n_tests=1, n_breaches=0, cost_usd=0.0, findings=[])


def _spec() -> ScanSpec:
    return ScanSpec(target=TargetSpec(provider="openai", model="gpt-4o"))


async def _seed(store: InMemoryScanStore, queue: InMemoryJobQueue, spec: ScanSpec) -> str:
    """Mirror what ScanService.create_scan does: create the durable record, then enqueue a job."""
    scan_id = _new_id("scan")
    await store.create(ScanRecord(scan_id=scan_id, org_id="org-1", target=spec.target.redacted()))
    await queue.enqueue(scan_id, spec, org_id="org-1")
    return scan_id


@pytest.mark.asyncio
async def test_run_once_success_finalizes_completed():
    store, queue = InMemoryScanStore(), InMemoryJobQueue()
    spec = _spec()
    scan_id = await _seed(store, queue, spec)

    worker = ScanWorker(store, queue, FakeEngine())
    handled = await worker.run_once()

    assert handled is True
    rec = await store.get(scan_id, org_id="org-1")
    assert rec is not None
    assert rec.status == ScanStatus.COMPLETED
    assert rec.progress == 100
    assert rec.n_tests == 2
    assert rec.n_completed == 2
    assert rec.n_breaches == 1
    assert rec.top_attack == "DAN"
    assert rec.score is not None and rec.score > 0
    assert rec.cost_usd == 0.01
    assert rec.started_at is not None
    assert rec.completed_at is not None
    assert rec.report_id is not None

    # The report payload is retrievable and carries the engine's findings. `get_report` returns the
    # report payload dict DIRECTLY (the unified ScanStore contract — not a {"scan_id","payload"} wrapper).
    payload = await store.get_report(rec.report_id)
    assert payload is not None
    assert payload["n_tests"] == 2
    assert payload["n_breaches"] == 1
    assert payload["top_attack"] == "DAN"
    assert len(payload["findings"]) == 1


@pytest.mark.asyncio
async def test_run_once_failure_marks_failed_with_error():
    store, queue = InMemoryScanStore(), InMemoryJobQueue()
    spec = _spec()
    scan_id = await _seed(store, queue, spec)

    worker = ScanWorker(store, queue, BoomEngine())
    handled = await worker.run_once()

    # The job is considered handled — the failure is recorded, not propagated.
    assert handled is True
    rec = await store.get(scan_id, org_id="org-1")
    assert rec is not None
    assert rec.status == ScanStatus.FAILED
    assert rec.error is not None and "engine exploded" in rec.error
    assert rec.completed_at is not None
    assert rec.report_id is None


@pytest.mark.asyncio
async def test_run_once_empty_queue_returns_false():
    store, queue = InMemoryScanStore(), InMemoryJobQueue()
    worker = ScanWorker(store, queue, FakeEngine())
    assert await worker.run_once() is False


@pytest.mark.asyncio
async def test_run_once_marks_running_before_completion_state():
    # A successful run leaves a started_at earlier than completed_at — RUNNING was set before finalize.
    store, queue = InMemoryScanStore(), InMemoryJobQueue()
    scan_id = await _seed(store, queue, _spec())
    worker = ScanWorker(store, queue, FakeEngine())
    await worker.run_once()
    rec = await store.get(scan_id, org_id="org-1")
    assert rec.started_at <= rec.completed_at


@pytest.mark.asyncio
async def test_cancel_during_run_stays_canceled():
    # A cancel that lands while the engine is running must win: the worker's terminal COMPLETED write is
    # guarded on expected_status=RUNNING, so once the record is CANCELED the write is a no-op.
    store, queue = InMemoryScanStore(), InMemoryJobQueue()
    spec = _spec()
    scan_id = await _seed(store, queue, spec)

    worker = ScanWorker(store, queue, CancelMidRunEngine(store, scan_id))
    handled = await worker.run_once()

    assert handled is True
    rec = await store.get(scan_id, org_id="org-1")
    assert rec is not None
    # Cancellation survives — it is NOT clobbered back to COMPLETED.
    assert rec.status == ScanStatus.CANCELED
    # And the (now-finished) job is acked, not left for redelivery.
    assert queue._jobs == {}


@pytest.mark.asyncio
async def test_redelivered_terminal_job_acks_without_running_engine():
    # At-least-once redelivery: the leased job's scan is already terminal. run_once must ack the job and
    # NOT invoke the engine (no re-run of finished work, no reviving a canceled scan).
    store, queue = InMemoryScanStore(), InMemoryJobQueue()
    spec = _spec()
    scan_id = await _seed(store, queue, spec)
    # Drive the record to a terminal state before the worker leases the (redelivered) job.
    await store.update(scan_id, status=ScanStatus.COMPLETED)

    engine = SpyEngine()
    worker = ScanWorker(store, queue, engine)
    handled = await worker.run_once()

    assert handled is True
    assert engine.ran is False  # engine never invoked
    assert queue._jobs == {}  # job acked, won't be redelivered again
    rec = await store.get(scan_id, org_id="org-1")
    assert rec.status == ScanStatus.COMPLETED  # unchanged


@pytest.mark.asyncio
async def test_update_compare_and_set_noop_on_status_mismatch():
    # Direct unit check of the guard: an expected_status that doesn't match is a no-op returning the
    # unchanged record; a matching one applies.
    store = InMemoryScanStore()
    scan_id = _new_id("scan")
    await store.create(
        ScanRecord(scan_id=scan_id, org_id="org-1", status=ScanStatus.CANCELED, target=_spec().target.redacted())
    )

    # Mismatch (record is CANCELED, expected RUNNING) → no-op.
    out = await store.update(scan_id, expected_status=ScanStatus.RUNNING, status=ScanStatus.COMPLETED, progress=100)
    assert out.status == ScanStatus.CANCELED
    assert out.progress == 0

    # Match → applies.
    out = await store.update(scan_id, expected_status=ScanStatus.CANCELED, progress=42)
    assert out.progress == 42


class _ReapSpyQueue(InMemoryJobQueue):
    """Records reap_expired() calls so we can assert the worker sweeps for orphaned jobs."""

    def __init__(self) -> None:
        super().__init__()
        self.reaps = 0

    def reap_expired(self) -> int:
        self.reaps += 1
        return 0


def test_reap_invokes_queue_reap_expired() -> None:
    store, queue = InMemoryScanStore(), _ReapSpyQueue()
    ScanWorker(store, queue, FakeEngine())._reap()
    assert queue.reaps == 1


@pytest.mark.asyncio
async def test_run_forever_reaps_orphaned_jobs_on_startup() -> None:
    # A redeploy/crash mid-scan leaves a job leased; the worker must sweep expired leases on startup so
    # the orphaned scan is requeued and resumes instead of hanging in RUNNING forever.
    import asyncio

    store, queue = InMemoryScanStore(), _ReapSpyQueue()
    worker = ScanWorker(store, queue, FakeEngine())
    stop = asyncio.Event()
    stop.set()  # stop the loop immediately — we only want to observe the startup reap
    await worker.run_forever(poll_interval=0.01, stop_event=stop)
    assert queue.reaps >= 1
