"""The scan worker — the single process that turns queued jobs into finished scan records.

The worker is deliberately the *only* place a scan actually executes: every surface (SDK / API / MCP /
dashboard) enqueues through :class:`ScanService`, and one or more workers lease those jobs and drive the
:class:`ScanEngine`. This keeps the request path cheap (never runs a scan in the calling thread) and lets
us scale execution horizontally by running more worker processes against the same store + queue.

Lifecycle of one job: lease → mark RUNNING → run the engine (streaming progress back into the record) →
on success persist the report + finalize COMPLETED + ack; on failure record the error + mark FAILED +
fail the job. A worker never lets an engine exception escape ``run_once`` — the job is always resolved.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from . import memory, scoring
from .schemas import ScanStatus

_log = logging.getLogger("rogue.platform.worker")

# How many idle poll-cycles between expired-lease recovery sweeps. At the default poll_interval the
# lease TTL (≈300s) is what gates how soon an orphan is reclaimable, so sweeping ~every 60s recovers a
# crashed/redeployed worker's scan promptly without hammering the DB.
_REAP_EVERY_IDLE_CYCLES = 30

if TYPE_CHECKING:
    from .interfaces import JobQueue, ScanEngine, ScanStore


def _now() -> datetime:
    # UTC, timezone-aware — every persisted timestamp on a scan record is in the same clock.
    return datetime.now(timezone.utc)


class ScanWorker:
    """Leases scan jobs and runs them through the engine, finalizing the durable record."""

    def __init__(
        self,
        store: ScanStore,
        queue: JobQueue,
        engine: ScanEngine,
        *,
        worker_id: str = "worker-1",
        secret_store=None,
        attestation_service=None,
        slack_delivery=None,
    ) -> None:
        self.store = store
        self.queue = queue
        self.engine = engine
        self.worker_id = worker_id
        # Resolves an `api_key_ref` handle back to the raw target key just-in-time (held only in memory
        # for the scan). When None, a spec's raw `api_key` is used as-is.
        self.secret_store = secret_store
        # Appends one signed `scan` attestation entry per COMPLETED scan (v2 §2.5). Injected (not
        # import-coupled) and OPTIONAL: when None, scans run exactly as before with no attestation.
        # FAILED/CANCELED scans are NOT attested — there is no verdict to attest (honest completeness).
        self.attestation_service = attestation_service
        # Optional Surface-1 auto-post: after a COMPLETED scan, post the §4 breach diff to the
        # agent's Slack security channel. Injected (not import-coupled) and OPTIONAL — when None,
        # scans run exactly as before with no Slack delivery. Best-effort by contract: a delivery
        # hiccup is swallowed and can never fail or lose a completed scan (see _deliver_slack_surface1).
        self._slack_delivery = slack_delivery

    async def run_once(self) -> bool:
        """Lease and process a single job. Returns False only when the queue was empty (nothing leased);
        True once a job has been handled — whether it completed or failed (the failure is recorded, not
        propagated)."""
        job = await self.queue.lease(worker_id=self.worker_id)
        if job is None:
            return False

        # Redelivery guard. The queue is at-least-once: a job can be re-leased after its visibility
        # timeout (or because it was canceled). Re-read the record; if it's already terminal
        # (COMPLETED/FAILED/CANCELED) the scan must NOT run again — ack the (duplicate) job and return
        # without touching the engine, so a redelivery can't re-run finished work or revive a CANCELED scan.
        record = await self.store.get(job.scan_id, org_id=job.org_id)
        if record is not None and record.status.is_terminal:
            await self.queue.ack(job.job_id)
            return True

        # Flip the record to RUNNING before any work so a poller sees the scan has started. Guard on
        # QUEUED: if a racing transition (e.g. cancel) already moved it off QUEUED, this is a no-op.
        await self.store.update(
            job.scan_id, expected_status=ScanStatus.QUEUED, status=ScanStatus.RUNNING, started_at=_now()
        )

        # Progress callback the engine fires per primitive — keeps the record's live counters fresh.
        async def cb(n_completed: int, n_total: int, current: str | None) -> None:
            await self.store.update(
                job.scan_id,
                progress=int(100 * n_completed / max(1, n_total)),
                n_completed=n_completed,
                n_tests=n_total,
                top_attack=current,
            )

        # Resolve the encrypted target key just-in-time: the persisted/leased spec carries only a
        # `secref_` handle; turn it back into the raw key in memory for this run only.
        spec = job.spec
        if self.secret_store is not None and spec.target.api_key_ref and not spec.target.api_key:
            raw = self.secret_store.resolve(spec.target.api_key_ref, org_id=job.org_id)
            spec = spec.model_copy(update={"target": spec.target.model_copy(update={"api_key": raw})})

        try:
            report = await self.engine.run(spec, progress=cb)
        except Exception as e:  # noqa: BLE001 — any engine failure is recorded, never escapes the worker.
            # Guard on RUNNING: only finalize FAILED if the scan is still running. If it was CANCELED
            # mid-run the write is a no-op and the record stays CANCELED.
            await self.store.update(
                job.scan_id,
                expected_status=ScanStatus.RUNNING,
                status=ScanStatus.FAILED,
                error=str(e)[:500],
                completed_at=_now(),
            )
            await self.queue.fail(job.job_id, error=str(e), retry=False)
            return True

        # Success: score, persist the full report payload, finalize the record, and ack the job.
        score = scoring.score_for(report)
        report_id = memory._new_id("rep")
        await self.store.save_report(report_id=report_id, scan_id=job.scan_id, payload=report.to_dict())
        # Guard on RUNNING: the terminal COMPLETED write applies ONLY if the scan is still running. If
        # `cancel_scan` flipped it to CANCELED while the engine ran, this is a no-op and the returned
        # record stays CANCELED — cancellation wins over the worker's completion.
        await self.store.update(
            job.scan_id,
            expected_status=ScanStatus.RUNNING,
            status=ScanStatus.COMPLETED,
            progress=100,
            n_tests=report.n_tests,
            n_completed=report.n_tests,
            n_breaches=report.n_breaches,
            top_attack=report.top_attack,
            score=score,
            cost_usd=report.cost_usd,
            report_id=report_id,
            completed_at=_now(),
        )
        # Signed attestation: append exactly ONE `scan` entry to the org's hash chain (v2 §2.5).
        # Additive and best-effort — a chain hiccup must NEVER lose a paid scan result, so this is
        # wrapped to log-and-continue (mirrors the "never crash a run" rule in the cost logs). The
        # append is idempotent on `reproducibility_ref=scan_id`, so a redelivered/retried job can't
        # double-append. corpus_as_of = scan-completion time (the moment we tested against the current
        # open-web corpus); a true harvest cutoff replaces this when the harvest layer threads it through.
        self._attest_completed_scan(job, report)

        # Surface-1 auto-fire: post the §4 breach diff to the agent's Slack security channel.
        # Additive + gated + best-effort — a no-op for any non-Slack scan and for an unconfigured
        # worker; a delivery failure is swallowed and can never affect the (already-finalized) scan
        # or the ack below.
        await self._deliver_slack_surface1(job, report)

        # Ack regardless of `finalized.status`: whether the scan finalized COMPLETED or was canceled
        # mid-run (in which case the guarded write above was a no-op and it stays CANCELED), the job is
        # done and must not be redelivered.
        await self.queue.ack(job.job_id)
        return True

    def _attest_completed_scan(self, job, report) -> None:
        """Append one `scan` attestation entry for a COMPLETED scan. Never raises.

        Best-effort by contract: any failure here is logged and swallowed so a chain problem can
        never fail (or lose) the paid scan that just completed. No-op when no attestation service is
        wired. Synchronous (the service uses short-lived blocking DB sessions like the store/queue)."""
        if self.attestation_service is None:
            return
        try:
            from rogue.attestation import emit  # local import: keep module import light

            corpus_as_of = _now()
            payload = emit.payload_for_scan(
                report.to_dict(), {"scan_id": job.scan_id}, corpus_as_of=corpus_as_of
            )
            self.attestation_service.append(
                org_id=job.org_id,
                entry_type="scan",
                payload=payload,
                reproducibility_ref=job.scan_id,
                # Additive: populate the entry's ground_truth_ref column from the payload's derived
                # pointer (set only on Surface-1/Slack policy scans, ADR-0011). Absent ⇒ None ⇒
                # identical to before for every other scan.
                ground_truth_ref=payload.get("ground_truth_ref"),
                corpus_as_of=corpus_as_of,
            )
        except Exception as e:  # noqa: BLE001 — attestation is additive; never fail a completed scan.
            _log.warning("attestation append failed for scan %s (scan result preserved): %s", job.scan_id, e)

    async def _deliver_slack_surface1(self, job, report) -> None:
        """Auto-post a COMPLETED Surface-1 policy scan's breach diff to its Slack security channel.

        Best-effort by contract: any failure here is logged and swallowed so a Slack hiccup can
        never fail (or lose) the scan that just completed. No-op when no Slack delivery is wired,
        and the delivery itself is a no-op for any scan without a `surface1_context`."""
        if self._slack_delivery is None:
            return
        try:
            await self._slack_delivery.deliver(
                report.to_dict(), org_id=job.org_id, scan_id=job.scan_id
            )
        except Exception as e:  # noqa: BLE001 — auto-fire is additive; never fail a completed scan.
            _log.warning(
                "slack surface-1 delivery failed for scan %s (scan result preserved): %s",
                job.scan_id,
                e,
            )

    async def run_forever(
        self,
        *,
        poll_interval: float = 1.0,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """Loop ``run_once`` forever (or until ``stop_event`` is set), sleeping ``poll_interval`` seconds
        whenever the queue is empty so an idle worker doesn't spin.

        On startup and then periodically while idle, sweep for expired leases (`reap_expired`) so a scan
        orphaned by a previous worker's death — e.g. a redeploy that restarted this process mid-scan —
        is requeued and resumed instead of hanging in RUNNING forever."""
        self._reap()  # recover anything orphaned before this worker started (e.g. the last redeploy)
        idle = 0
        while stop_event is None or not stop_event.is_set():
            did_work = await self.run_once()
            if did_work:
                idle = 0
                continue
            idle += 1
            if idle % _REAP_EVERY_IDLE_CYCLES == 0:
                self._reap()
            await asyncio.sleep(poll_interval)

    def _reap(self) -> None:
        """Requeue jobs whose lease expired (crashed/redeployed worker). Never lets a sweep failure
        crash the worker loop."""
        try:
            n = self.queue.reap_expired()
        except Exception as e:  # noqa: BLE001 — recovery sweep is best-effort; a failure must not kill the loop.
            _log.warning("reap_expired sweep failed: %s", e)
            return
        if n:
            _log.info("recovered %d orphaned scan job(s) via expired-lease reap", n)


def main() -> None:
    """Process entrypoint: ``python -m rogue.platform.worker``.

    Deployed as a separate process from the API. It wires the Postgres-backed store + queue and the real
    engine, then runs forever. The production impls are imported lazily so merely importing this module
    (e.g. in offline tests) never requires a database or those classes to exist yet."""
    try:
        from .engine import DefaultScanEngine
        from .queue import build_postgres_job_queue
        from .store import build_postgres_scan_store
    except ImportError as e:  # pragma: no cover — exercised only in a real deployment.
        raise RuntimeError(
            "rogue.platform.worker.main() requires the Postgres store/queue and DefaultScanEngine; "
            f"a production dependency is missing: {e}"
        ) from e

    store = build_postgres_scan_store()
    queue = build_postgres_job_queue()
    engine = DefaultScanEngine()
    # Attestation: share the store's hardened engine/sessionmaker so each completed scan appends one
    # signed entry to its org's hash chain (v2 §2.5). Best-effort — see ScanWorker._attest_completed_scan.
    from rogue.attestation.service import AttestationService

    attestation_service = AttestationService(store._session_factory)

    # Surface-1 auto-fire: build the Slack delivery only when a bot token is configured. Lazy +
    # guarded, mirroring the attestation wiring above — an unset/empty token leaves slack_delivery
    # None, so the worker behaves exactly as before (no Slack post).
    from rogue.config import get_settings

    slack_delivery = None
    token = get_settings().slack_bot_token
    if token and token.get_secret_value():
        from rogue.integrations.slack import (
            SlackSurface1Delivery,
            build_postgres_slack_agent_store,
            make_slack_channel_sender,
        )
        from rogue.platform.secrets import build_postgres_secret_store
        from rogue.platform.snapshot_store import build_postgres_snapshot_store

        # Secret store (may be None when SECRET_ENCRYPTION_KEY isn't set) so a registration whose
        # system prompt was encrypted can be resolved on lookup; None ⇒ inline-prompt fallback.
        secret_store = build_postgres_secret_store()
        slack_delivery = SlackSurface1Delivery(
            agent_store=build_postgres_slack_agent_store(secret_store),
            sender=make_slack_channel_sender(token.get_secret_value()),
            snapshot_store=build_postgres_snapshot_store(),
        )

    worker = ScanWorker(
        store,
        queue,
        engine,
        attestation_service=attestation_service,
        slack_delivery=slack_delivery,
    )
    asyncio.run(worker.run_forever())


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["ScanWorker", "main"]
