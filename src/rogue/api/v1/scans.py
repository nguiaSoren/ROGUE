"""`/v1/scans` — the platform's first write surface (create / poll / cancel / list / report).

These handlers are deliberately thin (docs/platform/api/scans-endpoints.md "Notes for implementers"):
resolve the tenant via `require_principal`, validate the request, `await` exactly one `ScanService`
coroutine (plus, on the report route, one `ReportService` coroutine), and serialize the result. No
SQL, no queue access, no engine calls live here — a scan never runs in the request thread.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from rogue.api.v1.deps import get_report_service, get_scan_service, require_principal
from rogue.platform.schemas import ScanRecord, ScanSpec, ScanStatus, TargetSpec

if TYPE_CHECKING:
    from rogue.platform.interfaces import ReportService, ScanService
    from rogue.platform.tenancy import Principal

router = APIRouter(prefix="/v1", tags=["scans"])


# ---------------------------------------------------------------------------------------------------
# Request body — the user-facing flat shape (docs §1). The SCOPE-level target fields (endpoint /
# provider / model / api_key / system_prompt) are folded into a `TargetSpec`; the rest map 1:1 onto
# `ScanSpec`. Tenant fields (org_id / project_id) are NEVER in the body — they come from the API key.
# ---------------------------------------------------------------------------------------------------
class CreateScanRequest(BaseModel):
    endpoint: str | None = None
    provider: str | None = None
    api_key: str | None = Field(default=None, repr=False)
    model: str | None = None
    mode: Literal["pack", "repertoire"] = "pack"
    pack: str = "default"
    attacks: list[str] | None = None
    max_tests: int = Field(default=50, ge=1, le=1000)
    n_trials: int = Field(default=1, ge=1, le=10)
    budget: float | None = Field(default=None, ge=0)
    system_prompt: str = ""

    def to_spec(self) -> ScanSpec:
        """Build the canonical `ScanSpec`. `TargetSpec`'s validator enforces endpoint-or-provider."""
        target = TargetSpec(
            endpoint=self.endpoint,
            provider=self.provider,
            model=self.model,
            api_key=self.api_key,
            system_prompt=self.system_prompt,
        )
        return ScanSpec(
            target=target,
            mode=self.mode,
            pack=self.pack,
            attacks=self.attacks,
            max_tests=self.max_tests,
            n_trials=self.n_trials,
            budget=self.budget,
        )


def _envelope(code: str, message: str, **details: object) -> dict:
    """The standard error-envelope body for HTTPException details (docs §"Shared shapes")."""
    err: dict = {"code": code, "message": message}
    if details:
        err["details"] = details
    return {"error": err}


# ---------------------------------------------------------------------------------------------------
# 1. POST /v1/scans — enqueue a scan, return immediately (202 + acknowledgement subset).
# ---------------------------------------------------------------------------------------------------
@router.post("/scans", status_code=202)
async def create_scan(
    body: CreateScanRequest,
    principal: Principal = Depends(require_principal),
    scan_service: ScanService = Depends(get_scan_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    # Folding the flat body into a ScanSpec can fail TargetSpec's endpoint-or-provider invariant;
    # surface that as a 422 invalid_request rather than a 500.
    try:
        spec = body.to_spec()
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=_envelope("invalid_request", str(exc), field="target"),
        ) from exc

    record = await scan_service.create_scan(
        spec,
        org_id=principal.org_id,
        project_id=principal.project_id,
        idempotency_key=idempotency_key,
    )
    status = record.status.value if isinstance(record.status, ScanStatus) else record.status
    return JSONResponse(
        status_code=202,
        content={"scan_id": record.scan_id, "status": status},
        headers={"Location": f"/v1/scans/{record.scan_id}"},
    )


# ---------------------------------------------------------------------------------------------------
# 2. GET /v1/scans/{scan_id} — poll. Cross-tenant reads are a clean 404 (no existence leak).
# ---------------------------------------------------------------------------------------------------
@router.get("/scans/{scan_id}")
async def get_scan(
    scan_id: str,
    principal: Principal = Depends(require_principal),
    scan_service: ScanService = Depends(get_scan_service),
) -> ScanRecord:
    record = await scan_service.get_scan(scan_id, org_id=principal.org_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=_envelope("not_found", f"scan not found: {scan_id}"),
        )
    return record


# ---------------------------------------------------------------------------------------------------
# 3. POST /v1/scans/{scan_id}/cancel — request cancellation (idempotent, best-effort).
# ---------------------------------------------------------------------------------------------------
@router.post("/scans/{scan_id}/cancel")
async def cancel_scan(
    scan_id: str,
    principal: Principal = Depends(require_principal),
    scan_service: ScanService = Depends(get_scan_service),
) -> ScanRecord:
    # The service raises KeyError for a missing/cross-tenant scan; map it to a 404.
    try:
        return await scan_service.cancel_scan(scan_id, org_id=principal.org_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=_envelope("not_found", f"scan not found: {scan_id}"),
        ) from exc


# ---------------------------------------------------------------------------------------------------
# 4. GET /v1/scans — list the org's scans (tenant-scoped by construction).
# ---------------------------------------------------------------------------------------------------
@router.get("/scans")
async def list_scans(
    principal: Principal = Depends(require_principal),
    scan_service: ScanService = Depends(get_scan_service),
    project_id: str | None = Query(default=None),
    status: ScanStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    scans = await scan_service.list_scans(
        org_id=principal.org_id,
        project_id=project_id,
        limit=limit,
    )
    # `status` filtering is applied by the service per the contract; the in-memory service's
    # list_scans signature takes no status arg, so filter here when asked (harmless when None).
    if status is not None:
        scans = [s for s in scans if s.status == status]
    return {"scans": scans, "count": len(scans)}


# ---------------------------------------------------------------------------------------------------
# 5. GET /v1/scans/{scan_id}/report — render the customer artifact for a COMPLETED scan.
# ---------------------------------------------------------------------------------------------------
@router.get("/scans/{scan_id}/report")
async def get_scan_report(
    scan_id: str,
    principal: Principal = Depends(require_principal),
    scan_service: ScanService = Depends(get_scan_service),
    report_service: ReportService = Depends(get_report_service),
    format: Literal["json", "html", "pdf"] = Query(default="json"),
) -> Response:
    # Resolve for tenancy + readiness first; never call the report layer for a non-completed scan.
    record = await scan_service.get_scan(scan_id, org_id=principal.org_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=_envelope("not_found", f"scan not found: {scan_id}"),
        )
    if record.status != ScanStatus.COMPLETED:
        status = record.status.value if isinstance(record.status, ScanStatus) else record.status
        raise HTTPException(
            status_code=404,
            detail=_envelope(
                "report_not_ready",
                "report not available until scan completes",
                status=status,
            ),
        )

    if format == "json":
        return JSONResponse(content=await report_service.build_json(scan_id))
    if format == "html":
        return HTMLResponse(content=await report_service.build_html(scan_id))
    return Response(
        content=await report_service.build_pdf(scan_id),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="rogue-scan-{scan_id}.pdf"'},
    )


__all__ = ["router", "CreateScanRequest"]
