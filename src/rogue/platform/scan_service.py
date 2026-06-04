"""Default `ScanService` — the single entry every surface (SDK/API/MCP/dashboard) calls.

The service is deliberately thin: it validates the request, persists a `ScanRecord` in the
QUEUED state, and hands the work to the `JobQueue`. It NEVER runs a scan inline — execution is
the worker's job (lease → `ScanEngine.run` → progress updates → ack). That separation is what
lets the API return immediately and the same path back the SDK, the dashboard, and the MCP server.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .interfaces import JobQueue, ScanService, ScanStore
from .memory import _new_id
from .schemas import ScanRecord, ScanSpec, ScanStatus


class DefaultScanService(ScanService):
    """Queue-backed `ScanService`. Owns no execution — it only writes records and enqueues jobs."""

    def __init__(self, store: ScanStore, queue: JobQueue, *, secret_store=None) -> None:
        self._store = store
        self._queue = queue
        # When wired (hosted path), a raw target api_key is encrypted into the secret store and the
        # enqueued spec carries only an `api_key_ref` handle — the raw key never lands in scan_jobs.
        # When None (SDK in-process / tests), the raw key passes through unchanged (no persistence
        # concern there).
        self._secret_store = secret_store
        # Process-local idempotency map keyed (org_id, idempotency_key) → scan_id. This is a
        # best-effort dedup for the in-memory single-process mode; the Postgres store enforces it
        # durably in prod via the scan_runs.idempotency_key column, so the pinned `ScanRecord`
        # carries no idempotency field.
        self._idem: dict[tuple[str, str], str] = {}

    async def create_scan(
        self,
        spec: ScanSpec,
        *,
        org_id: str,
        project_id: str | None = None,
        actor: str | None = None,
        idempotency_key: str | None = None,
    ) -> ScanRecord:
        # The spec arrives as an already-validated `ScanSpec` (TargetSpec's model_validator has
        # guaranteed endpoint-or-provider); re-assert the invariant defensively so a hand-built
        # spec can never slip a target-less scan onto the queue.
        target = spec.target
        if not target.endpoint and not target.provider:
            raise ValueError("ScanSpec.target needs either endpoint=... or provider=...")

        # Encrypt the raw target key into the secret store and swap it for a handle BEFORE anything is
        # persisted or enqueued, so the raw key never enters scan_runs/scan_jobs.
        if self._secret_store is not None and target.api_key and not target.api_key_ref:
            secref = self._secret_store.put(target.api_key, org_id=org_id)
            target = target.model_copy(update={"api_key": None, "api_key_ref": secref})
            spec = spec.model_copy(update={"target": target})

        # Idempotent replay: same (org, key) returns the original record, no new job enqueued.
        if idempotency_key is not None:
            existing_id = self._idem.get((org_id, idempotency_key))
            if existing_id is not None:
                existing = await self._store.get(existing_id, org_id=org_id)
                if existing is not None:
                    return existing

        record = ScanRecord(
            scan_id=_new_id("scan"),
            org_id=org_id,
            project_id=project_id,
            status=ScanStatus.QUEUED,
            target=target.redacted(),  # persist/log-safe snapshot — never the raw api_key
            pack=spec.pack,
            created_at=datetime.now(timezone.utc),
        )

        await self._store.create(record)
        await self._queue.enqueue(record.scan_id, spec, org_id=org_id)

        if idempotency_key is not None:
            self._idem[(org_id, idempotency_key)] = record.scan_id

        return record

    async def get_scan(self, scan_id: str, *, org_id: str) -> ScanRecord | None:
        return await self._store.get(scan_id, org_id=org_id)

    async def cancel_scan(self, scan_id: str, *, org_id: str) -> ScanRecord:
        record = await self._store.get(scan_id, org_id=org_id)
        if record is None:
            # Missing (or cross-tenant) → not found; surface as KeyError for the API layer to map.
            raise KeyError(scan_id)

        # Already finished: cancellation is a no-op — return the terminal record untouched.
        if record.status.is_terminal:
            return record

        updated = await self._store.update(
            scan_id,
            status=ScanStatus.CANCELED,
            completed_at=datetime.now(timezone.utc),
        )

        # Best-effort: drop the still-queued job so a worker never picks it up. The Postgres queue
        # cancels via a status column; the in-memory queue exposes a synchronous `.cancel` — guard
        # on its presence so the service stays agnostic to the concrete queue impl.
        cancel = getattr(self._queue, "cancel", None)
        if callable(cancel):
            cancel(scan_id)

        return updated

    async def list_scans(
        self,
        *,
        org_id: str,
        project_id: str | None = None,
        limit: int = 50,
    ) -> list[ScanRecord]:
        return await self._store.list(org_id=org_id, project_id=project_id, limit=limit)


__all__ = ["DefaultScanService"]
