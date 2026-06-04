"""Platform end-to-end: the ONE-engine path through every real module, offline.

Wires the actual DefaultScanService + InMemory store/queue + DefaultScanEngine (with a fake target
panel + fake judge, so no network/LLM/money) + ScanWorker + DefaultReportService, and drives it both
directly and over HTTP (the /v1 router). This is the "company → API → ROGUE → report, no human"
success-metric path proven against the assembled real code.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rogue.api.v1.deps import get_report_service, get_scan_service, require_principal
from rogue.api.v1.scans import router as scans_router
from rogue.platform.engine import DefaultScanEngine
from rogue.platform.memory import InMemoryJobQueue, InMemoryScanStore
from rogue.platform.report_service import DefaultReportService
from rogue.platform.scan_service import DefaultScanService
from rogue.platform.schemas import ScanSpec, ScanStatus, TargetSpec
from rogue.platform.worker import ScanWorker
from rogue.schemas import JudgeVerdict

_BREACH_FAMILIES = {"dan_persona", "multi_turn_gradient"}


class _FakePanel:
    async def run_attack(self, rendered, config, n_trials=1, **kw):
        return [
            SimpleNamespace(error=None, content="Sure, here is exactly what you asked for.", cost_usd=0.0002)
            for _ in range(n_trials)
        ]

    async def aclose(self):
        return None


class _FakeJudge:
    async def judge(self, rendered, model_response, primitive):
        breach = primitive.family.value in _BREACH_FAMILIES
        return SimpleNamespace(verdict=JudgeVerdict.FULL_BREACH if breach else JudgeVerdict.REFUSED)


@dataclass
class _FakePrincipal:
    org_id: str = "org_e2e"
    project_id: str | None = None


def _build_stack():
    store = InMemoryScanStore()
    queue = InMemoryJobQueue()
    service = DefaultScanService(store, queue)
    engine = DefaultScanEngine(panel=_FakePanel(), judge=_FakeJudge())
    worker = ScanWorker(store, queue, engine)
    report_service = DefaultReportService(store)
    return store, queue, service, engine, worker, report_service


@pytest.mark.asyncio
async def test_service_worker_engine_path():
    """Direct (no HTTP): create_scan → worker runs it through the real engine → completed + report."""
    store, queue, service, engine, worker, report_service = _build_stack()
    spec = ScanSpec(target=TargetSpec(endpoint="https://api.company.com/v1", api_key="sk-x"),
                    pack="default", max_tests=6, n_trials=1)

    rec = await service.create_scan(spec, org_id="org_e2e")
    assert rec.status == ScanStatus.QUEUED

    assert await worker.run_once() is True
    assert await worker.run_once() is False  # queue now empty

    final = await service.get_scan(rec.scan_id, org_id="org_e2e")
    assert final.status == ScanStatus.COMPLETED
    assert final.progress == 100
    assert final.n_tests == 6
    assert final.n_breaches >= 1  # the default pack contains dan_persona + multi_turn_gradient
    assert final.score is not None and final.score > 0
    assert final.report_id is not None

    report = await report_service.build_json(rec.scan_id)
    assert report["score"] == final.score
    assert len(report["findings"]) == 6
    # raw target api_key never persisted
    assert "sk-x" not in str(final.target)


def test_http_e2e_create_poll_report():
    """Over HTTP: POST /v1/scans → poll → run worker → completed → GET report."""
    store, queue, service, engine, worker, report_service = _build_stack()
    app = FastAPI()
    app.include_router(scans_router)
    app.dependency_overrides[require_principal] = lambda: _FakePrincipal()
    app.dependency_overrides[get_scan_service] = lambda: service
    app.dependency_overrides[get_report_service] = lambda: report_service
    client = TestClient(app)

    r = client.post("/v1/scans", json={"endpoint": "https://api.company.com/v1", "api_key": "sk-x",
                                        "pack": "default", "max_tests": 4})
    assert r.status_code == 202
    scan_id = r.json()["scan_id"]
    assert r.json()["status"] in ("queued", ScanStatus.QUEUED.value)

    assert client.get(f"/v1/scans/{scan_id}").json()["status"] in ("queued", ScanStatus.QUEUED.value)

    # The worker (a separate process in prod) drains the shared queue.
    assert asyncio.run(worker.run_once()) is True

    rec = client.get(f"/v1/scans/{scan_id}").json()
    assert rec["status"] in ("completed", ScanStatus.COMPLETED.value)
    assert rec["n_tests"] == 4
    assert rec["score"] is not None

    rep = client.get(f"/v1/scans/{scan_id}/report?format=json")
    assert rep.status_code == 200
    body = rep.json()
    assert "findings" in body and body.get("score") is not None

    # cross-tenant isolation: a different org can't see this scan
    app.dependency_overrides[require_principal] = lambda: _FakePrincipal(org_id="org_other")
    assert client.get(f"/v1/scans/{scan_id}").status_code == 404
