"""The in-process worker — the $0 single-service path.

Verifies that `ScanWorker.run_forever` (the loop started inside the API process when
ROGUE_INPROCESS_WORKER=1) drains a queued scan to completion and then exits cleanly when its
stop_event is set. Offline: in-memory store/queue + a fake engine, no DB/network/money.
"""

from __future__ import annotations

import asyncio

import pytest

from rogue.platform.memory import InMemoryJobQueue, InMemoryScanStore
from rogue.platform.scan_service import DefaultScanService
from rogue.platform.schemas import ScanSpec, ScanStatus, TargetSpec
from rogue.platform.worker import ScanWorker
from rogue.report import Finding, ScanReport


class _FakeEngine:
    async def run(self, spec, *, progress=None):
        if progress is not None:
            await progress(1, 1, "DAN")
        return ScanReport(
            target="t",
            n_tests=1,
            n_breaches=1,
            cost_usd=0.001,
            findings=[
                Finding(
                    family="dan_persona", technique="DAN", vector="user_turn", severity="critical",
                    title="x", success_rate=1.0, n_trials=1, n_breach=1,
                )
            ],
        )

    async def validate(self, spec):  # pragma: no cover - unused here
        raise NotImplementedError

    async def benchmark(self, spec, *, dataset, max_goals):  # pragma: no cover - unused here
        raise NotImplementedError


@pytest.mark.asyncio
async def test_inprocess_worker_drains_queue_then_stops():
    store = InMemoryScanStore()
    queue = InMemoryJobQueue()
    service = DefaultScanService(store, queue)
    worker = ScanWorker(store, queue, _FakeEngine(), worker_id="inprocess-test")

    stop = asyncio.Event()
    task = asyncio.create_task(worker.run_forever(poll_interval=0.01, stop_event=stop))
    try:
        rec = await service.create_scan(
            ScanSpec(target=TargetSpec(provider="openai"), pack="default", max_tests=1), org_id="o1"
        )
        cur = None
        for _ in range(500):  # ≤5s
            cur = await store.get(rec.scan_id, org_id="o1")
            if cur.status == ScanStatus.COMPLETED:
                break
            await asyncio.sleep(0.01)
        assert cur is not None and cur.status == ScanStatus.COMPLETED
        assert cur.n_breaches == 1
        assert cur.score is not None and cur.score > 0
        assert cur.report_id is not None
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=2.0)  # run_forever must exit once stop_event is set
    assert task.done()


def test_inprocess_flag_off_by_default(monkeypatch):
    from rogue.api.main import _inprocess_worker_enabled

    monkeypatch.delenv("ROGUE_INPROCESS_WORKER", raising=False)
    assert _inprocess_worker_enabled() is False
    monkeypatch.setenv("ROGUE_INPROCESS_WORKER", "1")
    assert _inprocess_worker_enabled() is True
    monkeypatch.setenv("ROGUE_INPROCESS_WORKER", "off")
    assert _inprocess_worker_enabled() is False
