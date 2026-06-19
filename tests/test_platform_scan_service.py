"""`DefaultScanService` against the in-memory store + queue — fully offline, no DB, no spend.

Proves the service's contract: a scan is persisted QUEUED and a job lands on the queue (never run
inline); reads are tenant-scoped; an idempotency key replays the same scan with one enqueue; and
cancellation flips the record terminal AND removes the job so a worker won't pick it up.
"""

from __future__ import annotations

import pytest

from rogue.platform.memory import InMemoryJobQueue, InMemoryScanStore
from rogue.platform.scan_service import DefaultScanService, SecretStoreRequiredError
from rogue.platform.schemas import ScanSpec, ScanStatus, TargetSpec


def _spec(**target_kw) -> ScanSpec:
    # Minimal valid spec — TargetSpec requires endpoint or provider.
    target_kw.setdefault("provider", "openai")
    target_kw.setdefault("model", "gpt-4o-mini")
    return ScanSpec(target=TargetSpec(**target_kw))


@pytest.fixture
def service() -> tuple[DefaultScanService, InMemoryScanStore, InMemoryJobQueue]:
    store = InMemoryScanStore()
    queue = InMemoryJobQueue()
    return DefaultScanService(store, queue), store, queue


@pytest.mark.asyncio
async def test_create_scan_queues_record_and_job(service):
    svc, store, queue = service
    record = await svc.create_scan(_spec(), org_id="org_1")

    # The returned record is persisted and QUEUED — the service did not run anything inline.
    assert record.status is ScanStatus.QUEUED
    assert record.scan_id.startswith("scan_")
    assert record.org_id == "org_1"
    assert record.created_at is not None
    assert await store.get(record.scan_id, org_id="org_1") is not None

    # A job for that scan is now leasable.
    job = await queue.lease(worker_id="w1")
    assert job is not None
    assert job.scan_id == record.scan_id
    assert job.org_id == "org_1"


@pytest.mark.asyncio
async def test_create_scan_redacts_target(service):
    svc, _store, _queue = service
    record = await svc.create_scan(
        _spec(api_key="sk-secret", system_prompt="be helpful"), org_id="org_1"
    )
    # Only a redacted snapshot is persisted — never the raw credential.
    assert record.target["has_api_key"] is True
    assert "sk-secret" not in str(record.target)
    assert record.target["system_prompt_len"] == len("be helpful")


class _FakeSecretStore:
    """Minimal secret store: hands back a `secref_` handle, records what it was given."""

    def __init__(self) -> None:
        self.stored: list[tuple[str, str]] = []

    def put(self, raw: str, *, org_id: str) -> str:
        self.stored.append((org_id, raw))
        return f"secref_{len(self.stored)}"


@pytest.mark.asyncio
async def test_fail_closed_refuses_raw_key_without_secret_store():
    # Durable wiring (require_secret_store=True) with NO secret store must REFUSE a raw key —
    # never silently persist it. And nothing should be written or enqueued.
    store, queue = InMemoryScanStore(), InMemoryJobQueue()
    svc = DefaultScanService(store, queue, require_secret_store=True)

    with pytest.raises(SecretStoreRequiredError):
        await svc.create_scan(_spec(api_key="sk-secret"), org_id="org_1")

    assert await store.list(org_id="org_1") == []
    assert await queue.lease(worker_id="w1") is None


@pytest.mark.asyncio
async def test_fail_closed_allows_keyless_scan():
    # Fail-closed only gates KEY-bearing scans — a provider/keyless scan still runs without a store.
    store, queue = InMemoryScanStore(), InMemoryJobQueue()
    svc = DefaultScanService(store, queue, require_secret_store=True)

    record = await svc.create_scan(_spec(), org_id="org_1")  # provider only, no api_key
    assert record.status is ScanStatus.QUEUED
    assert await queue.lease(worker_id="w1") is not None


@pytest.mark.asyncio
async def test_require_secret_store_encrypts_raw_key():
    # With a secret store present, the raw key is encrypted to a handle and never enqueued raw.
    store, queue = InMemoryScanStore(), InMemoryJobQueue()
    secrets = _FakeSecretStore()
    svc = DefaultScanService(store, queue, secret_store=secrets, require_secret_store=True)

    await svc.create_scan(_spec(api_key="sk-secret"), org_id="org_1")

    assert secrets.stored == [("org_1", "sk-secret")]
    job = await queue.lease(worker_id="w1")
    assert job is not None
    assert job.spec.target.api_key is None
    assert job.spec.target.api_key_ref == "secref_1"


@pytest.mark.asyncio
async def test_in_process_default_passes_raw_key_through():
    # Default (require_secret_store=False) is the in-process SDK/test mode: a raw key passes through
    # (nothing is persisted durably), so it must NOT raise.
    store, queue = InMemoryScanStore(), InMemoryJobQueue()
    svc = DefaultScanService(store, queue)  # default: not durable, no store

    record = await svc.create_scan(_spec(api_key="sk-secret"), org_id="org_1")
    assert record.status is ScanStatus.QUEUED
    job = await queue.lease(worker_id="w1")
    assert job is not None and job.spec.target.api_key == "sk-secret"


@pytest.mark.asyncio
async def test_get_scan_is_tenant_scoped(service):
    svc, _store, _queue = service
    record = await svc.create_scan(_spec(), org_id="org_1")

    assert await svc.get_scan(record.scan_id, org_id="org_1") is not None
    # Cross-tenant read → not found (no existence leak).
    assert await svc.get_scan(record.scan_id, org_id="org_2") is None
    # Unknown id → None.
    assert await svc.get_scan("scan_does_not_exist", org_id="org_1") is None


@pytest.mark.asyncio
async def test_idempotency_key_replays_same_scan(service):
    svc, _store, queue = service
    first = await svc.create_scan(_spec(), org_id="org_1", idempotency_key="abc")
    second = await svc.create_scan(_spec(), org_id="org_1", idempotency_key="abc")

    # Same scan returned, no duplicate created.
    assert first.scan_id == second.scan_id

    # Exactly one job was enqueued: one lease yields it, the next yields nothing.
    job = await queue.lease(worker_id="w1")
    assert job is not None and job.scan_id == first.scan_id
    assert await queue.lease(worker_id="w1") is None


@pytest.mark.asyncio
async def test_idempotency_key_is_org_scoped(service):
    svc, _store, _queue = service
    a = await svc.create_scan(_spec(), org_id="org_1", idempotency_key="shared")
    b = await svc.create_scan(_spec(), org_id="org_2", idempotency_key="shared")
    # Same key under a different org is a different scan.
    assert a.scan_id != b.scan_id


@pytest.mark.asyncio
async def test_cancel_scan_flips_terminal_and_drops_job(service):
    svc, _store, queue = service
    record = await svc.create_scan(_spec(), org_id="org_1")

    canceled = await svc.cancel_scan(record.scan_id, org_id="org_1")
    assert canceled.status is ScanStatus.CANCELED
    assert canceled.completed_at is not None

    # The queued job is gone — a worker leasing now skips it.
    assert await queue.lease(worker_id="w1") is None


@pytest.mark.asyncio
async def test_cancel_scan_terminal_is_noop(service):
    svc, store, _queue = service
    record = await svc.create_scan(_spec(), org_id="org_1")
    await store.update(record.scan_id, status=ScanStatus.COMPLETED)

    out = await svc.cancel_scan(record.scan_id, org_id="org_1")
    # Already-terminal scan is returned untouched (still COMPLETED, not CANCELED).
    assert out.status is ScanStatus.COMPLETED


@pytest.mark.asyncio
async def test_cancel_scan_missing_raises(service):
    svc, _store, _queue = service
    with pytest.raises(KeyError):
        await svc.cancel_scan("scan_nope", org_id="org_1")


@pytest.mark.asyncio
async def test_cancel_scan_cross_tenant_raises(service):
    svc, _store, _queue = service
    record = await svc.create_scan(_spec(), org_id="org_1")
    # Another org cannot cancel — looks like a missing record.
    with pytest.raises(KeyError):
        await svc.cancel_scan(record.scan_id, org_id="org_2")


@pytest.mark.asyncio
async def test_list_scans_returns_org_scans(service):
    svc, _store, _queue = service
    s1 = await svc.create_scan(_spec(), org_id="org_1", project_id="p1")
    s2 = await svc.create_scan(_spec(), org_id="org_1", project_id="p2")
    await svc.create_scan(_spec(), org_id="org_2")

    rows = await svc.list_scans(org_id="org_1")
    ids = {r.scan_id for r in rows}
    assert ids == {s1.scan_id, s2.scan_id}

    # project_id filter narrows the list.
    only_p1 = await svc.list_scans(org_id="org_1", project_id="p1")
    assert {r.scan_id for r in only_p1} == {s1.scan_id}
