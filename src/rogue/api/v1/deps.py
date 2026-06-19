"""FastAPI dependency seam for the `/v1` routers.

Pins the dependency callables every router uses (`require_principal` for auth/tenant, and the four
service getters). Bodies are lazy / placeholder so this module imports before the concrete platform
services exist; the production graph is wired in `rogue.api.main` (assembly), and tests override these
via ``app.dependency_overrides``. The router code only ever sees ``Depends(require_principal)`` etc.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import Header, HTTPException

if TYPE_CHECKING:
    from rogue.platform.interfaces import (
        ReportService,
        ScanEngine,
        ScanService,
    )
    from rogue.platform.tenancy import Principal

# Set by the assembly wiring (rogue.api.main) at startup; overridden in tests.
_SERVICES: dict[str, Any] = {}


async def require_principal(authorization: str | None = Header(default=None)) -> Principal:
    """Authenticate the Bearer API key and return the caller's tenant principal. 401 otherwise."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail={"error": {"code": "invalid_token", "message": "missing bearer api key"}})
    token = authorization[7:].strip()
    from rogue.platform.tenancy import resolve_principal_from_token  # lazy

    principal = resolve_principal_from_token(token)
    if principal is None:
        raise HTTPException(status_code=401, detail={"error": {"code": "invalid_api_key", "message": "API key not recognized"}})
    return principal


def _require(name: str):
    svc = _SERVICES.get(name)
    if svc is None:
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "unavailable", "message": f"{name} not wired"}},
        )
    return svc


def get_scan_service() -> ScanService:
    return _require("scan_service")


def get_report_service() -> ReportService:
    return _require("report_service")


def get_scan_engine() -> ScanEngine:
    return _require("scan_engine")


def get_benchmark_service() -> Any:
    return _require("benchmark_service")


def get_attestation_service() -> Any:
    """The per-org append-only attestation chain service (v2 §2.5)."""
    return _require("attestation_service")


def get_attestation_service_optional() -> Any:
    """Like `get_attestation_service` but returns None when the chain isn't wired.

    For surfaces where a signed attestation is OPTIONAL evidence (e.g. the per-scan assurance
    report's honest "unattested" path) rather than a hard dependency — the route degrades to an
    unattested report instead of 503-ing when the chain service is absent."""
    return _SERVICES.get("attestation_service")


def get_scan_store() -> Any:
    """The durable ScanStore — used by the attestation replay route to resolve a
    `reproducibility_ref` (scan_id) back to the persisted report it reconstructs from."""
    return _require("store")


def wire(**services: Any) -> None:
    """Called by assembly to install the production service graph."""
    _SERVICES.update(services)


__all__ = [
    "require_principal",
    "get_scan_service",
    "get_report_service",
    "get_scan_engine",
    "get_benchmark_service",
    "get_attestation_service",
    "get_attestation_service_optional",
    "get_scan_store",
    "wire",
]
