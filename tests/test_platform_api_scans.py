"""Offline tests for the `/v1/scans` router — router wiring, serialization, and auth seam only.

No real services, DB, or network: we mount the router on a bare `FastAPI` app, override the three
dependencies (`require_principal`, `get_scan_service`, `get_report_service`) with fakes, and drive it
with a sync `TestClient`. The point is to prove the HTTP contract from
`docs/platform/api/scans-endpoints.md` — status codes, the {scan_id, status} 202 subset, ScanRecord
serialization, the error envelope, cross-tenant/not-ready 404s — NOT to re-test the service logic
(that lives in test_platform_scan_service.py). The service fake wraps the real `DefaultScanService`
over the in-memory store/queue, so the tenancy filtering it relies on is genuine.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rogue.api.v1.deps import (
    get_attestation_service_optional,
    get_report_service,
    get_scan_service,
    require_principal,
)
from rogue.api.v1.scans import router
from rogue.platform.memory import InMemoryJobQueue, InMemoryScanStore
from rogue.platform.scan_service import DefaultScanService
from rogue.platform.schemas import ScanStatus


# The router only ever reads `.org_id` and `.project_id` off the principal — a tiny stand-in is
# enough (the real tenancy.Principal is built by a sibling team and not importable here yet).
@dataclass
class FakePrincipal:
    org_id: str = "org_test"
    project_id: str | None = None
    role: str = "owner"
    scopes: list[str] = field(default_factory=lambda: ["scan:write"])
    key_id: str = "k"


# A fake ReportService — returns canned artifacts per format; never reads a DB.
class FakeReportService:
    async def build_json(self, scan_id: str) -> dict:
        return {"scan_id": scan_id, "report_id": "rep_test", "n_breaches": 1, "findings": []}

    async def build_html(self, scan_id: str) -> str:
        return f"<html><body>report for {scan_id}</body></html>"

    async def build_pdf(self, scan_id: str) -> bytes:
        return b"%PDF-1.4 fake"

    async def build_assurance_json(self, scan_id: str, *, attestation=None) -> dict:
        return {
            "report_type": "ai_red_team_assurance",
            "scope": {"config_id": scan_id},
            "attestation": ({"entry_hash": attestation.entry_hash} if attestation else None),
        }

    async def build_assurance_markdown(self, scan_id: str, *, attestation=None) -> str:
        return f"# AI Red-Team Assurance Report\n\nscan {scan_id}"


def _make_client(
    scan_service: DefaultScanService, attestation_service: object | None = None
) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_principal] = lambda: FakePrincipal()
    app.dependency_overrides[get_scan_service] = lambda: scan_service
    app.dependency_overrides[get_report_service] = lambda: FakeReportService()
    app.dependency_overrides[get_attestation_service_optional] = lambda: attestation_service
    return TestClient(app)


def _new_service() -> DefaultScanService:
    return DefaultScanService(InMemoryScanStore(), InMemoryJobQueue())


_BODY = {
    "provider": "openai",
    "model": "acme-support-bot",
    "system_prompt": "You are Acme's support assistant.",
    "pack": "default",
    "max_tests": 25,
    "n_trials": 3,
}


def test_create_scan_returns_202_with_scan_id_and_status() -> None:
    client = _make_client(_new_service())
    resp = client.post("/v1/scans", json=_BODY)
    assert resp.status_code == 202
    payload = resp.json()
    assert payload["scan_id"].startswith("scan_")
    assert payload["status"] == "queued"
    assert resp.headers["Location"] == f"/v1/scans/{payload['scan_id']}"


def test_create_scan_missing_target_is_422_envelope() -> None:
    client = _make_client(_new_service())
    resp = client.post("/v1/scans", json={"pack": "default"})  # neither endpoint nor provider
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"]["code"] == "invalid_request"


def test_get_scan_returns_full_record() -> None:
    service = _new_service()
    client = _make_client(service)
    scan_id = client.post("/v1/scans", json=_BODY).json()["scan_id"]

    resp = client.get(f"/v1/scans/{scan_id}")
    assert resp.status_code == 200
    record = resp.json()
    assert record["scan_id"] == scan_id
    assert record["org_id"] == "org_test"
    assert record["status"] == "queued"
    assert record["target"]["provider"] == "openai"  # redacted snapshot, no raw api_key
    assert "api_key" not in record["target"]


def test_get_unknown_scan_is_404_envelope() -> None:
    client = _make_client(_new_service())
    resp = client.get("/v1/scans/scan_does_not_exist")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"]["code"] == "not_found"


def test_cross_tenant_get_is_404() -> None:
    # A scan created under a different org must not be visible — the service filters on org_id and
    # returns None, which the router maps to 404 (not 403, so existence isn't leaked).
    service = _new_service()
    other = run_async(
        service.create_scan(
            _spec_from_body(), org_id="org_other", project_id=None, idempotency_key=None
        )
    )
    client = _make_client(service)  # principal is org_test
    resp = client.get(f"/v1/scans/{other.scan_id}")
    assert resp.status_code == 404


def test_list_scans_returns_scans_and_count() -> None:
    service = _new_service()
    client = _make_client(service)
    client.post("/v1/scans", json=_BODY)
    client.post("/v1/scans", json=_BODY)

    resp = client.get("/v1/scans")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert len(body["scans"]) == 2
    assert all(s["org_id"] == "org_test" for s in body["scans"])


def test_cancel_scan_transitions_to_canceled() -> None:
    service = _new_service()
    client = _make_client(service)
    scan_id = client.post("/v1/scans", json=_BODY).json()["scan_id"]

    resp = client.post(f"/v1/scans/{scan_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "canceled"


def test_cancel_unknown_scan_is_404() -> None:
    client = _make_client(_new_service())
    resp = client.post("/v1/scans/scan_nope/cancel")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"]["code"] == "not_found"


def test_report_before_complete_is_404_report_not_ready() -> None:
    service = _new_service()
    client = _make_client(service)
    scan_id = client.post("/v1/scans", json=_BODY).json()["scan_id"]  # still QUEUED

    resp = client.get(f"/v1/scans/{scan_id}/report?format=json")
    assert resp.status_code == 404
    err = resp.json()["detail"]["error"]
    assert err["code"] == "report_not_ready"
    assert err["details"]["status"] == "queued"


def test_report_json_html_pdf_on_completed_scan() -> None:
    service = _new_service()
    client = _make_client(service)
    scan_id = client.post("/v1/scans", json=_BODY).json()["scan_id"]
    # Drive the record to COMPLETED directly via the in-memory store (the worker's job in prod).
    run_async(service._store.update(scan_id, status=ScanStatus.COMPLETED))

    j = client.get(f"/v1/scans/{scan_id}/report?format=json")
    assert j.status_code == 200
    assert j.headers["content-type"].startswith("application/json")
    assert j.json()["scan_id"] == scan_id

    h = client.get(f"/v1/scans/{scan_id}/report?format=html")
    assert h.status_code == 200
    assert h.headers["content-type"].startswith("text/html")
    assert scan_id in h.text

    p = client.get(f"/v1/scans/{scan_id}/report?format=pdf")
    assert p.status_code == 200
    assert p.headers["content-type"] == "application/pdf"
    assert p.content.startswith(b"%PDF")


def test_report_bad_format_is_422() -> None:
    service = _new_service()
    client = _make_client(service)
    scan_id = client.post("/v1/scans", json=_BODY).json()["scan_id"]
    resp = client.get(f"/v1/scans/{scan_id}/report?format=xml")
    assert resp.status_code == 422  # FastAPI Literal validation on the query param


# ---------------------------------------------------------------------------------------------------
# Assurance endpoint — mirrors the report route's tenancy + readiness guards (json + markdown).
# ---------------------------------------------------------------------------------------------------
def test_assurance_before_complete_is_404_report_not_ready() -> None:
    service = _new_service()
    client = _make_client(service)
    # Seed a still-QUEUED scan via the store, not the rate-limited POST route (slowapi caps
    # /v1/scans at 10/min per client; a stray POST here trips the shared limiter and fails
    # an unrelated e2e test later in the same process window — same reason the completed-scan
    # tests use _seed_completed_scan).
    record = run_async(
        service.create_scan(
            _spec_from_body(), org_id="org_test", project_id=None, idempotency_key=None
        )
    )
    scan_id = record.scan_id  # still QUEUED

    resp = client.get(f"/v1/scans/{scan_id}/assurance")
    assert resp.status_code == 404
    err = resp.json()["detail"]["error"]
    assert err["code"] == "report_not_ready"
    assert err["details"]["status"] == "queued"


def test_assurance_unknown_scan_is_404() -> None:
    client = _make_client(_new_service())
    resp = client.get("/v1/scans/scan_does_not_exist/assurance")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"]["code"] == "not_found"


def test_assurance_cross_tenant_is_404() -> None:
    service = _new_service()
    other = run_async(
        service.create_scan(
            _spec_from_body(), org_id="org_other", project_id=None, idempotency_key=None
        )
    )
    run_async(service._store.update(other.scan_id, status=ScanStatus.COMPLETED))
    client = _make_client(service)  # principal is org_test
    resp = client.get(f"/v1/scans/{other.scan_id}/assurance")
    assert resp.status_code == 404


def _seed_completed_scan(service: DefaultScanService, org_id: str = "org_test") -> str:
    """Persist a COMPLETED scan directly via the store (bypasses the rate-limited POST route)."""
    record = run_async(
        service.create_scan(
            _spec_from_body(), org_id=org_id, project_id=None, idempotency_key=None
        )
    )
    run_async(service._store.update(record.scan_id, status=ScanStatus.COMPLETED))
    return record.scan_id


def test_assurance_json_and_markdown_on_completed_scan() -> None:
    service = _new_service()
    client = _make_client(service)
    scan_id = _seed_completed_scan(service)

    j = client.get(f"/v1/scans/{scan_id}/assurance")  # default json
    assert j.status_code == 200
    assert j.headers["content-type"].startswith("application/json")
    body = j.json()
    assert body["report_type"] == "ai_red_team_assurance"
    assert body["scope"]["config_id"] == scan_id
    assert body["attestation"] is None  # no attestation service wired

    for fmt in ("md", "markdown"):
        m = client.get(f"/v1/scans/{scan_id}/assurance?format={fmt}")
        assert m.status_code == 200
        assert m.headers["content-type"].startswith("text/markdown")
        assert "# AI Red-Team Assurance Report" in m.text


def test_assurance_references_attestation_head_when_wired() -> None:
    # A wired attestation chain with a head entry → the route resolves an AttestationRef and threads
    # it into the report. Cross-org isolation is the chain's job; the route passes principal.org_id.
    class _FakeAttestation:
        def head(self, org_id: str):
            assert org_id == "org_test"
            return {"entry_hash": "deadbeef", "signature": "", "seq": 3, "payload": {}}

    service = _new_service()
    client = _make_client(service, attestation_service=_FakeAttestation())
    scan_id = _seed_completed_scan(service)

    resp = client.get(f"/v1/scans/{scan_id}/assurance")
    assert resp.status_code == 200
    assert resp.json()["attestation"] == {"entry_hash": "deadbeef"}


def test_assurance_bad_format_is_422() -> None:
    service = _new_service()
    client = _make_client(service)
    scan_id = _seed_completed_scan(service)
    resp = client.get(f"/v1/scans/{scan_id}/assurance?format=pdf")
    assert resp.status_code == 422  # only json|md|markdown allowed


# ---------------------------------------------------------------------------------------------------
# Tiny helpers — a couple of tests need to call the async service directly to set up state the HTTP
# surface can't reach (a cross-tenant record, a completed scan).
# ---------------------------------------------------------------------------------------------------
def run_async(coro):
    import asyncio

    return asyncio.run(coro)


def _spec_from_body():
    from rogue.api.v1.scans import CreateScanRequest

    return CreateScanRequest(**_BODY).to_spec()
