"""Offline tests for the `/v1/attestation` router — wiring, serialization, tenancy.

No real DB/network: mount the router on a bare app, override `require_principal`
with a fake, back `get_attestation_service` with a real `AttestationService` over
SQLite, and back `get_scan_store` with a fake store for the replay route. Proves
the HTTP contract (list/verify/entry/replay shapes, the framing line on every
entry, cross-org 404) — not the service logic (that's test_service.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from rogue.api.v1.attestation import router
from rogue.api.v1.deps import (
    get_attestation_service,
    get_scan_store,
    require_principal,
)
from rogue.attestation import emit
from rogue.attestation.service import AttestationService
from rogue.db.models import Base
from rogue.platform.models import AttestationEntry, Organization  # noqa: F401  (register tables)

_AS_OF = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)


@dataclass
class FakePrincipal:
    org_id: str = "org_test"
    project_id: str | None = None
    role: str = "owner"
    scopes: list[str] = field(default_factory=lambda: ["scan:read"])
    key_id: str = "k"


@dataclass
class _FakeRecord:
    scan_id: str
    org_id: str
    report_id: str | None


class FakeStore:
    """Minimal ScanStore stand-in for the replay route's report resolution."""

    def __init__(self, reports: dict[str, dict]):
        self._reports = reports  # report_id -> payload
        self._records = {
            "scan_1": _FakeRecord("scan_1", "org_test", "rep_1"),
        }

    async def get(self, scan_id: str, *, org_id: str | None = None):
        rec = self._records.get(scan_id)
        if rec is None or (org_id is not None and rec.org_id != org_id):
            return None
        return rec

    async def get_report(self, report_id: str):
        return self._reports.get(report_id)


def _report() -> dict:
    return {
        "target": "gpt-4o",
        "n_tests": 4,
        "n_breaches": 1,
        "breach_rate": 0.25,
        "findings": [
            {
                "family": "roleplay",
                "technique": "DAN",
                "severity": "high",
                "success_rate": 0.5,
                "n_trials": 2,
                "n_breach": 1,
                "explanation": "roleplay attack",
            }
        ],
    }


def _make_service() -> AttestationService:
    # StaticPool + a single shared connection: the TestClient drives the app on a
    # worker thread, so a fresh-per-checkout in-memory SQLite would see an empty DB.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine, tables=[Organization.__table__, AttestationEntry.__table__]
    )
    return AttestationService(sessionmaker(bind=engine, expire_on_commit=False))


def _make_client(service: AttestationService, store: FakeStore, principal=None) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_principal] = lambda: principal or FakePrincipal()
    app.dependency_overrides[get_attestation_service] = lambda: service
    app.dependency_overrides[get_scan_store] = lambda: store
    return TestClient(app)


def _seed_scan_entry(service: AttestationService):
    payload = emit.payload_for_scan(_report(), {"scan_id": "scan_1"}, corpus_as_of=_AS_OF)
    return service.append(
        "org_test", "scan", payload, reproducibility_ref="scan_1", corpus_as_of=_AS_OF
    )


def test_list_entries_carries_framing():
    service = _make_service()
    _seed_scan_entry(service)
    client = _make_client(service, FakeStore({"rep_1": _report()}))

    resp = client.get("/v1/attestation/entries")
    assert resp.status_code == 200
    body = resp.json()
    # genesis (seq 0) + scan (seq 1).
    assert body["count"] == 2
    for entry in body["entries"]:
        assert "threat-informed assurance" in entry["framing"]
        assert "not a safety guarantee" in entry["framing"]


def test_list_filter_by_entry_type():
    service = _make_service()
    _seed_scan_entry(service)
    client = _make_client(service, FakeStore({"rep_1": _report()}))
    resp = client.get("/v1/attestation/entries", params={"entry_type": "scan"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["entries"][0]["entry_type"] == "scan"


def test_verify_ok():
    service = _make_service()
    _seed_scan_entry(service)
    client = _make_client(service, FakeStore({"rep_1": _report()}))
    resp = client.get("/v1/attestation/verify")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_get_entry_and_cross_org_404():
    service = _make_service()
    entry = _seed_scan_entry(service)
    store = FakeStore({"rep_1": _report()})

    # Caller's org → 200.
    client = _make_client(service, store)
    resp = client.get(f"/v1/attestation/entries/{entry.entry_id}")
    assert resp.status_code == 200
    assert resp.json()["entry_id"] == entry.entry_id

    # Another org → clean 404 (no existence leak).
    other = _make_client(service, store, principal=FakePrincipal(org_id="org_other"))
    resp = other.get(f"/v1/attestation/entries/{entry.entry_id}")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"]["code"] == "not_found"


def test_replay_route_reproducible():
    service = _make_service()
    entry = _seed_scan_entry(service)
    client = _make_client(service, FakeStore({"rep_1": _report()}))
    resp = client.get(f"/v1/attestation/entries/{entry.entry_id}/replay")
    assert resp.status_code == 200
    body = resp.json()
    assert body["reproducible"] is True
    assert body["recomputed_hash"] == body["stored_hash"]


def test_replay_route_cross_org_404():
    service = _make_service()
    entry = _seed_scan_entry(service)
    store = FakeStore({"rep_1": _report()})
    other = _make_client(service, store, principal=FakePrincipal(org_id="org_other"))
    resp = other.get(f"/v1/attestation/entries/{entry.entry_id}/replay")
    assert resp.status_code == 404
