"""Tenant secret store — the api_key_ref indirection that keeps raw target keys out of scan_jobs.

The load-bearing test is `test_create_scan_swaps_raw_key_for_ref_and_never_enqueues_raw`: it asserts
the audit-critical property that a hosted scan's enqueued payload contains NO raw credential.
"""

from __future__ import annotations

import json

import pytest

from rogue.platform.memory import InMemoryJobQueue, InMemoryScanStore
from rogue.platform.scan_service import DefaultScanService
from rogue.platform.schemas import ScanSpec, TargetSpec
from rogue.platform.secrets import InMemorySecretStore, PostgresSecretStore


def test_inmemory_secret_store_put_resolve_orgscoped():
    s = InMemorySecretStore()
    ref = s.put("sk-secret", org_id="org_1")
    assert ref.startswith("secref_")
    assert s.resolve(ref, org_id="org_1") == "sk-secret"
    assert s.resolve(ref, org_id="other") is None  # cross-tenant resolve → nothing
    s.delete(ref)
    assert s.resolve(ref, org_id="org_1") is None


def test_postgres_secret_store_encrypts_at_rest():
    from cryptography.fernet import Fernet
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from rogue.db.models import Base
    from rogue.platform.models import Secret

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Secret.__table__])
    store = PostgresSecretStore(sessionmaker(bind=engine), Fernet(Fernet.generate_key()))

    ref = store.put("sk-topsecret", org_id="org_1")
    with engine.connect() as c:
        ciphertext = c.execute(text("select ciphertext from secrets")).scalar()
    assert b"sk-topsecret" not in ciphertext  # stored encrypted, not plaintext
    assert store.resolve(ref, org_id="org_1") == "sk-topsecret"
    assert store.resolve(ref, org_id="nope") is None


@pytest.mark.asyncio
async def test_create_scan_swaps_raw_key_for_ref_and_never_enqueues_raw():
    store, queue, sec = InMemoryScanStore(), InMemoryJobQueue(), InMemorySecretStore()
    svc = DefaultScanService(store, queue, secret_store=sec)

    rec = await svc.create_scan(
        ScanSpec(target=TargetSpec(endpoint="https://api.company.com/v1", api_key="sk-RAWSECRET")),
        org_id="org_1",
    )

    job = await queue.lease(worker_id="w")
    assert job is not None
    assert job.spec.target.api_key is None  # raw key stripped from the enqueued spec
    assert job.spec.target.api_key_ref and job.spec.target.api_key_ref.startswith("secref_")
    # THE audit-critical assertion: the raw secret appears nowhere in the serialized queue payload.
    assert "sk-RAWSECRET" not in json.dumps(job.spec.model_dump(mode="json"))
    # the persisted record is redacted too (no raw key, but flagged as having one)
    assert rec.target.get("has_api_key") is True
    assert "sk-RAWSECRET" not in str(rec.target)
    # and the ref still resolves back to the raw key (org-scoped) for the worker
    assert sec.resolve(job.spec.target.api_key_ref, org_id="org_1") == "sk-RAWSECRET"


@pytest.mark.asyncio
async def test_no_secret_store_passes_raw_through():
    # SDK / test path: with no secret store wired, the raw key passes through (nothing is persisted
    # to a DB there, so there's no leak — and the engine still needs the key).
    store, queue = InMemoryScanStore(), InMemoryJobQueue()
    svc = DefaultScanService(store, queue)
    await svc.create_scan(ScanSpec(target=TargetSpec(provider="openai", api_key="sk-x")), org_id="o")
    job = await queue.lease(worker_id="w")
    assert job.spec.target.api_key == "sk-x"
    assert job.spec.target.api_key_ref is None


@pytest.mark.asyncio
async def test_worker_resolves_ref_to_raw_for_engine():
    from rogue.platform.worker import ScanWorker
    from rogue.report import ScanReport

    store, queue, sec = InMemoryScanStore(), InMemoryJobQueue(), InMemorySecretStore()
    svc = DefaultScanService(store, queue, secret_store=sec)
    seen: dict = {}

    class _FakeEngine:
        async def run(self, spec, *, progress=None):
            seen["key"] = spec.target.api_key  # what the engine actually receives
            return ScanReport(target="t", n_tests=0, n_breaches=0, cost_usd=0.0, findings=[])

        async def validate(self, spec):  # pragma: no cover
            raise NotImplementedError

        async def benchmark(self, spec, *, dataset, max_goals):  # pragma: no cover
            raise NotImplementedError

    await svc.create_scan(ScanSpec(target=TargetSpec(provider="openai", api_key="sk-RAW")), org_id="o1")
    worker = ScanWorker(store, queue, _FakeEngine(), secret_store=sec)
    assert await worker.run_once() is True
    assert seen["key"] == "sk-RAW"  # worker resolved the secref back to the raw key for the engine
