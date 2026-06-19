"""`DefaultBenchmarkService` against a fake `ScanEngine` — fully offline, no DB, no spend.

Proves the contract: `create` persists a record and (in the MVP inline path) drives it to
COMPLETED with the report's ASR + derived fields; `get` is tenant-scoped (wrong org → not found);
and an engine/dataset failure lands a FAILED record carrying the error.
"""

from __future__ import annotations

import pytest

from rogue.platform.benchmark_service import DefaultBenchmarkService
from rogue.platform.schemas import ScanSpec, ScanStatus, TargetSpec
from rogue.report import BenchmarkReport


def _spec(**target_kw) -> ScanSpec:
    target_kw.setdefault("provider", "openai")
    target_kw.setdefault("model", "gpt-5.4-nano")
    return ScanSpec(target=TargetSpec(**target_kw))


class FakeEngine:
    """A `ScanEngine.benchmark` stub returning a fixed report (no network, no spend)."""

    def __init__(self, report: BenchmarkReport | None = None, exc: Exception | None = None):
        self._report = report
        self._exc = exc
        self.calls: list[dict] = []

    async def benchmark(self, spec, *, dataset, max_goals):
        self.calls.append({"dataset": dataset, "max_goals": max_goals})
        if self._exc is not None:
            raise self._exc
        return self._report


def _report() -> BenchmarkReport:
    return BenchmarkReport(
        dataset="advbench_100",
        target="openai/gpt-5.4-nano",
        n_goals=10,
        n_success=2,
        cost_usd=0.02,
        winner_rank=None,
    )


@pytest.mark.asyncio
async def test_create_runs_benchmark_to_completed():
    engine = FakeEngine(report=_report())
    svc = DefaultBenchmarkService(engine=engine)

    out = await svc.create(_spec(), dataset="advbench_100", max_goals=10, org_id="org_1")

    assert out["benchmark_id"].startswith("bench_")
    assert out["status"] is ScanStatus.COMPLETED

    # The engine was driven with the requested dataset + cap.
    assert engine.calls == [{"dataset": "advbench_100", "max_goals": 10}]

    record = await svc.get(out["benchmark_id"], org_id="org_1")
    assert record is not None
    assert record.status is ScanStatus.COMPLETED
    assert record.dataset == "advbench_100"
    assert record.n_goals == 10
    assert record.n_success == 2
    assert record.asr == pytest.approx(0.2)
    assert record.cost_usd == pytest.approx(0.02)
    assert record.cost_per_success == pytest.approx(0.01)
    assert record.winner_rank is None
    assert record.error is None
    assert record.created_at is not None
    assert record.completed_at is not None


@pytest.mark.asyncio
async def test_create_redacts_target():
    engine = FakeEngine(report=_report())
    svc = DefaultBenchmarkService(engine=engine)

    out = await svc.create(
        _spec(api_key="sk-secret"), dataset="advbench_100", max_goals=10, org_id="org_1"
    )
    record = await svc.get(out["benchmark_id"], org_id="org_1")
    # Only a redacted snapshot is persisted — never the raw credential.
    assert record.target["has_api_key"] is True
    assert "sk-secret" not in str(record.target)


@pytest.mark.asyncio
async def test_get_is_tenant_scoped():
    engine = FakeEngine(report=_report())
    svc = DefaultBenchmarkService(engine=engine)

    out = await svc.create(_spec(), dataset="advbench_100", max_goals=10, org_id="org_1")
    bid = out["benchmark_id"]

    assert await svc.get(bid, org_id="org_1") is not None
    # Cross-tenant read → not found (no existence leak).
    assert await svc.get(bid, org_id="org_2") is None
    # Unknown id → None.
    assert await svc.get("bench_does_not_exist", org_id="org_1") is None


@pytest.mark.asyncio
async def test_create_failure_marks_failed():
    engine = FakeEngine(exc=ValueError("unknown benchmark dataset 'nope'"))
    svc = DefaultBenchmarkService(engine=engine)

    out = await svc.create(_spec(), dataset="nope", max_goals=10, org_id="org_1")
    assert out["status"] is ScanStatus.FAILED

    record = await svc.get(out["benchmark_id"], org_id="org_1")
    assert record is not None
    assert record.status is ScanStatus.FAILED
    assert "unknown benchmark dataset" in record.error
    assert record.completed_at is not None
    # Result fields stay at their zero/None defaults on failure.
    assert record.n_goals == 0
    assert record.asr is None
