"""Default `BenchmarkService` — the surface every caller hits to run a standard-dataset ASR
benchmark (AdvBench / JailbreakBench) against a target.

A benchmark is a long job, like a scan, but the orchestration is simpler: there is no per-trial
progress fan-out and no cancellation surface, so this MVP runs the work inline and marks the
record terminal in one step. Production routes a benchmark through the SAME queue/worker path as
scans (enqueue → lease → `ScanEngine.benchmark` → ack) so it never ties up the request thread;
the durable `BenchmarkRun` persistence (a Postgres table mirroring `BenchmarkRecord`) is the
documented follow-up — today the records live in a process-local dict, matching the in-memory
`ScanStore` substrate.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from .interfaces import ScanEngine
from .memory import _new_id
from .schemas import ScanSpec, ScanStatus


class BenchmarkRecord(BaseModel):
    """The persisted status+result of a benchmark — what a GET /v1/benchmarks/{id} would return.

    `target` is the redacted `TargetSpec` snapshot (never the raw api_key), mirroring `ScanRecord`.
    The numeric result fields are populated from the engine's `BenchmarkReport` on completion.
    """

    benchmark_id: str
    org_id: str
    dataset: str
    target: dict = Field(default_factory=dict)  # redacted TargetSpec snapshot
    status: ScanStatus = ScanStatus.QUEUED
    n_goals: int = 0
    n_success: int = 0
    asr: float | None = None
    cost_usd: float = 0.0
    cost_per_success: float | None = None
    winner_rank: int | None = None
    error: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"use_enum_values": False}


class DefaultBenchmarkService:
    """Runs and tracks dataset benchmarks. Holds an in-memory record map; delegates execution to a
    `ScanEngine.benchmark` (the one path that wraps `rogue.benchmark.run_benchmark`)."""

    def __init__(self, *, engine: ScanEngine | None = None, store=None) -> None:
        # `engine` runs the benchmark; `store` is reserved for the future durable BenchmarkRun
        # persistence (see module docstring) — accepted now so the constructor signature is stable
        # when the Postgres-backed store lands.
        self._engine = engine
        self._store = store
        self._records: dict[str, BenchmarkRecord] = {}

    async def create(
        self,
        spec: ScanSpec,
        *,
        dataset: str,
        max_goals: int,
        org_id: str,
    ) -> dict:
        # Re-assert the target invariant defensively (the `TargetSpec` validator already guarantees
        # it, but a hand-built spec must never start a benchmark with no target).
        target = spec.target
        if not target.endpoint and not target.provider:
            raise ValueError("ScanSpec.target needs either endpoint=... or provider=...")

        benchmark_id = _new_id("bench")
        record = BenchmarkRecord(
            benchmark_id=benchmark_id,
            org_id=org_id,
            dataset=dataset,
            target=target.redacted(),  # persist/log-safe snapshot — never the raw api_key
            status=ScanStatus.QUEUED,
            created_at=datetime.now(timezone.utc),
        )
        self._records[benchmark_id] = record

        # MVP: run inline, then mark terminal. Production enqueues onto the same JobQueue scans use
        # and a worker leases it — the request never blocks on the (multi-minute) benchmark run.
        try:
            report = await self._engine.benchmark(spec, dataset=dataset, max_goals=max_goals)
        except Exception as exc:  # noqa: BLE001 — any engine/dataset failure → FAILED record
            self._records[benchmark_id] = record.model_copy(
                update={
                    "status": ScanStatus.FAILED,
                    "error": str(exc),
                    "completed_at": datetime.now(timezone.utc),
                }
            )
            return {"benchmark_id": benchmark_id, "status": ScanStatus.FAILED}

        completed = record.model_copy(
            update={
                "status": ScanStatus.COMPLETED,
                "n_goals": report.n_goals,
                "n_success": report.n_success,
                "asr": report.asr,
                "cost_usd": report.cost_usd,
                "cost_per_success": report.cost_per_success,
                "winner_rank": report.winner_rank,
                "completed_at": datetime.now(timezone.utc),
            }
        )
        self._records[benchmark_id] = completed
        return {"benchmark_id": benchmark_id, "status": ScanStatus.COMPLETED}

    async def get(self, benchmark_id: str, *, org_id: str) -> BenchmarkRecord | None:
        record = self._records.get(benchmark_id)
        if record is None:
            return None
        if record.org_id != org_id:
            return None  # cross-tenant read → not found (no existence leak)
        return record


__all__ = ["BenchmarkRecord", "DefaultBenchmarkService"]
