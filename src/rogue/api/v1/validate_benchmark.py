"""`/v1/validate` and `/v1/benchmark` — the two endpoints that bracket a scan.

`validate` is the cheap synchronous pre-flight ("can ROGUE reach this target, and what can it do?");
`benchmark` is the async standardized yardstick ("how does this target score against a known
dataset?"). Both are thin surfaces over the one `ScanEngine` (see
`docs/platform/api/validate-benchmark-endpoints.md`): they build a `ScanSpec` from the request's
`TargetSpec` and never run a scanning path of their own. This module owns only the HTTP contract —
the `TargetSpec` / `ValidationResult` / `BenchmarkReport` shapes are frozen elsewhere.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from rogue.platform.schemas import ScanSpec, TargetSpec

from .deps import get_benchmark_service, get_scan_engine, require_principal

if TYPE_CHECKING:
    from rogue.platform.interfaces import ScanEngine
    from rogue.platform.tenancy import Principal

router = APIRouter(prefix="/v1", tags=["validate", "benchmark"])


# --- request bodies -----------------------------------------------------------------------------


class ValidateRequest(BaseModel):
    """The `POST /v1/validate` body — a bare `TargetSpec` (no envelope), per the spec."""

    endpoint: str | None = None
    provider: str | None = None
    model: str | None = None
    api_key: str | None = Field(default=None, repr=False)
    system_prompt: str = ""


class BenchmarkRequest(BaseModel):
    """The `POST /v1/benchmark` body — a `TargetSpec` (inline, mirroring validate) plus job knobs."""

    endpoint: str | None = None
    provider: str | None = None
    model: str | None = None
    api_key: str | None = Field(default=None, repr=False)
    system_prompt: str = ""
    dataset: str = "advbench_100"
    max_goals: int = Field(default=25, ge=1, le=1000)


# --- helpers ------------------------------------------------------------------------------------


def _bad_request(message: str, code: str = "invalid_request") -> HTTPException:
    """A 400 in the platform's standard error envelope."""
    return HTTPException(status_code=400, detail={"error": {"code": code, "message": message}})


def _build_spec(*, endpoint, provider, model, api_key, system_prompt) -> ScanSpec:
    """Build the one `ScanSpec` both endpoints route through. A target missing both `endpoint`
    and `provider` is a request-level `400` (TargetSpec's validator rejects it), not an engine call."""
    try:
        target = TargetSpec(
            endpoint=endpoint,
            provider=provider,
            model=model,
            api_key=api_key,
            system_prompt=system_prompt,
        )
    except ValidationError as exc:
        # The only model-level rule is "endpoint or provider required" — surface it as a clean 400.
        raise _bad_request("target needs either endpoint=... or provider=...") from exc
    return ScanSpec(target=target)


# --- endpoints ----------------------------------------------------------------------------------


@router.post("/validate")
async def validate(
    body: ValidateRequest,
    principal: Principal = Depends(require_principal),
    scan_engine: ScanEngine = Depends(get_scan_engine),
) -> dict:
    """Synchronous spend-nothing pre-flight. One engine call; returns a `ValidationResult` as JSON
    with the computed `ok` boolean surfaced explicitly. A broken *target* is a `200` with bad-news
    booleans, not an API error — only request-level problems are non-2xx."""
    spec = _build_spec(
        endpoint=body.endpoint,
        provider=body.provider,
        model=body.model,
        api_key=body.api_key,
        system_prompt=body.system_prompt,
    )
    result = await scan_engine.validate(spec)
    return {
        "target": result.target,
        "reachable": result.reachable,
        "authenticated": result.authenticated,
        "model_responds": result.model_responds,
        "supports_image": result.supports_image,
        "supports_audio": result.supports_audio,
        "error": result.error,
        "ok": result.ok,
    }


@router.post("/benchmark", status_code=202)
async def create_benchmark(
    body: BenchmarkRequest,
    principal: Principal = Depends(require_principal),
    benchmark_service: Any = Depends(get_benchmark_service),
) -> dict:
    """Submit an async benchmark job. Returns `202 {benchmark_id, status}`; the caller polls
    `GET /v1/benchmark/{id}`. A bad dataset is rejected at submit time (before queueing) as a `400`,
    so it never costs a job slot."""
    spec = _build_spec(
        endpoint=body.endpoint,
        provider=body.provider,
        model=body.model,
        api_key=body.api_key,
        system_prompt=body.system_prompt,
    )
    try:
        created = await benchmark_service.create(
            spec,
            dataset=body.dataset,
            max_goals=body.max_goals,
            org_id=principal.org_id,
        )
    except ValueError as exc:
        # `run_benchmark` raises ValueError on an unknown dataset — map it to 400 at submit time.
        raise _bad_request(str(exc) or "unknown dataset") from exc
    return {"benchmark_id": created["benchmark_id"], "status": created["status"]}


@router.get("/benchmark/{benchmark_id}")
async def get_benchmark(
    benchmark_id: str,
    principal: Principal = Depends(require_principal),
    benchmark_service: Any = Depends(get_benchmark_service),
) -> dict:
    """Poll one benchmark job. Tenant-scoped: a `benchmark_id` belonging to another org is a `404`
    (not a `403`), per the scans isolation rule. While running, returns the status row; on
    `completed`, the row embeds the `BenchmarkReport` fields."""
    record = await benchmark_service.get(benchmark_id, org_id=principal.org_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": f"benchmark {benchmark_id} not found"}},
        )
    return record


__all__ = ["router"]
