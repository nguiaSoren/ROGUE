"""Offline tests for the `/v1/validate` + `/v1/benchmark` router.

Pure TestClient + `dependency_overrides` + fakes — no network, no DB, no real engine. We mount the
router on a bare `FastAPI` app and swap `require_principal` / `get_scan_engine` /
`get_benchmark_service` for in-memory fakes, so we exercise the HTTP contract (status codes, request
validation, response shapes) without any of the parallel-built services existing yet.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rogue.api.v1.deps import (
    get_benchmark_service,
    get_scan_engine,
    require_principal,
)
from rogue.api.v1.validate_benchmark import router
from rogue.report import ValidationResult


# --- fakes --------------------------------------------------------------------------------------


@dataclass
class FakePrincipal:
    """Stands in for `rogue.platform.tenancy.Principal` — the router only reads `org_id`."""

    org_id: str = "org_test"
    project_id: str | None = "proj_test"


class FakeScanEngine:
    """A `ScanEngine` stub whose `validate` returns a fixed, fully-reachable `ValidationResult`."""

    def __init__(self) -> None:
        self.last_spec = None

    async def validate(self, spec) -> ValidationResult:
        self.last_spec = spec
        return ValidationResult(
            target="openai/gpt-5.4-nano",
            reachable=True,
            authenticated=True,
            model_responds=True,
            supports_image=True,
            supports_audio=False,
        )


class FakeBenchmarkService:
    """Minimal benchmark-service interface: async `create` → {benchmark_id, status}, async `get` →
    a record (or None for a cross-tenant / unknown id). `bad_dataset` makes `create` raise like the
    real `run_benchmark` does on an unknown dataset."""

    def __init__(self, *, bad_dataset: str | None = None) -> None:
        self.bad_dataset = bad_dataset
        self.created: list[dict] = []

    async def create(self, spec, *, dataset, max_goals, org_id) -> dict:
        if self.bad_dataset is not None and dataset == self.bad_dataset:
            raise ValueError(f"unknown dataset: {dataset}")
        self.created.append({"dataset": dataset, "max_goals": max_goals, "org_id": org_id})
        return {"benchmark_id": "bench_01TEST", "status": "queued"}

    async def get(self, benchmark_id, *, org_id) -> dict | None:
        if benchmark_id != "bench_01TEST":
            return None
        return {
            "benchmark_id": "bench_01TEST",
            "status": "completed",
            "report": {
                "dataset": "advbench_100",
                "target": "openai/gpt-5.4-nano",
                "n_goals": 25,
                "n_success": 9,
                "cost_usd": 0.4127,
                "winner_rank": None,
                "asr": 0.36,
                "cost_per_success": 0.04586,
            },
        }


# --- fixtures -----------------------------------------------------------------------------------


def _make_client(*, benchmark_service: FakeBenchmarkService | None = None) -> tuple[TestClient, FakeScanEngine, FakeBenchmarkService]:
    app = FastAPI()
    app.include_router(router)
    engine = FakeScanEngine()
    bench = benchmark_service or FakeBenchmarkService()
    app.dependency_overrides[require_principal] = lambda: FakePrincipal()
    app.dependency_overrides[get_scan_engine] = lambda: engine
    app.dependency_overrides[get_benchmark_service] = lambda: bench
    return TestClient(app), engine, bench


@pytest.fixture
def client() -> TestClient:
    c, _, _ = _make_client()
    return c


# --- POST /v1/validate --------------------------------------------------------------------------


def test_validate_returns_result_fields_and_ok(client: TestClient) -> None:
    resp = client.post("/v1/validate", json={"provider": "openai", "model": "gpt-5.4-nano"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["target"] == "openai/gpt-5.4-nano"
    assert body["reachable"] is True
    assert body["authenticated"] is True
    assert body["model_responds"] is True
    assert body["supports_image"] is True
    assert body["supports_audio"] is False
    assert body["error"] is None
    # `ok` is the computed property — reachable && authenticated && model_responds.
    assert body["ok"] is True


def test_validate_accepts_endpoint_only() -> None:
    c, engine, _ = _make_client()
    resp = c.post("/v1/validate", json={"endpoint": "https://api.openai.com/v1", "model": "gpt-4o-mini"})
    assert resp.status_code == 200
    # The engine saw a ScanSpec whose target carried the endpoint we sent.
    assert engine.last_spec is not None
    assert engine.last_spec.target.endpoint == "https://api.openai.com/v1"


def test_validate_missing_endpoint_and_provider_is_rejected(client: TestClient) -> None:
    resp = client.post("/v1/validate", json={"model": "gpt-4o-mini"})
    assert resp.status_code in (400, 422)
    if resp.status_code == 400:
        assert resp.json()["detail"]["error"]["code"] == "invalid_request"


def test_validate_requires_auth() -> None:
    # No principal override → the real `require_principal` runs and rejects a missing bearer key.
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_scan_engine] = lambda: FakeScanEngine()
    app.dependency_overrides[get_benchmark_service] = lambda: FakeBenchmarkService()
    resp = TestClient(app).post("/v1/validate", json={"provider": "openai", "model": "x"})
    assert resp.status_code == 401


# --- POST /v1/benchmark -------------------------------------------------------------------------


def test_benchmark_submit_returns_202_with_id(client: TestClient) -> None:
    resp = client.post(
        "/v1/benchmark",
        json={"provider": "openai", "model": "gpt-5.4-nano", "dataset": "advbench_100", "max_goals": 25},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["benchmark_id"] == "bench_01TEST"
    assert body["status"] == "queued"


def test_benchmark_passes_org_and_knobs_to_service() -> None:
    c, _, bench = _make_client()
    c.post("/v1/benchmark", json={"provider": "openai", "model": "m", "dataset": "jbb_100", "max_goals": 10})
    assert bench.created == [{"dataset": "jbb_100", "max_goals": 10, "org_id": "org_test"}]


def test_benchmark_defaults_dataset_and_max_goals() -> None:
    c, _, bench = _make_client()
    c.post("/v1/benchmark", json={"provider": "openai", "model": "m"})
    assert bench.created[0]["dataset"] == "advbench_100"
    assert bench.created[0]["max_goals"] == 25


def test_benchmark_bad_target_rejected() -> None:
    c, _, _ = _make_client()
    resp = c.post("/v1/benchmark", json={"model": "m", "dataset": "advbench_100"})
    assert resp.status_code in (400, 422)


def test_benchmark_unknown_dataset_is_400() -> None:
    c, _, _ = _make_client(benchmark_service=FakeBenchmarkService(bad_dataset="nope_999"))
    resp = c.post("/v1/benchmark", json={"provider": "openai", "model": "m", "dataset": "nope_999"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["code"] == "invalid_request"


# --- GET /v1/benchmark/{id} ---------------------------------------------------------------------


def test_get_benchmark_returns_record(client: TestClient) -> None:
    resp = client.get("/v1/benchmark/bench_01TEST")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    report = body["report"]
    assert report["asr"] == 0.36
    assert report["n_goals"] == 25
    assert report["n_success"] == 9
    assert report["cost_per_success"] == 0.04586
    assert report["winner_rank"] is None


def test_get_benchmark_unknown_id_is_404(client: TestClient) -> None:
    resp = client.get("/v1/benchmark/bench_DOESNOTEXIST")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"]["code"] == "not_found"
