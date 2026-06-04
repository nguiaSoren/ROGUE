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

    # The report payload is retrievable and carries the engine's findings.
    stored = await store.get_report(rec.report_id)
    assert stored is not None
    assert stored["scan_id"] == scan_id
    payload = stored["payload"]
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
