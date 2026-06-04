# ScanWorker — the process that runs a scan

> Team B (Scan Orchestration). The `ScanWorker` is the consumer side of the orchestration triangle: it leases a job off the queue, executes the scan through the single `ScanEngine` execution path, streams progress, persists results, and releases the job. It is the only process that ever calls `ScanEngine.run`. The web dyno enqueues and reads status; it never scans. This document specifies the worker loop, its progress-reporting mechanism, its concurrency and rate-limit model, and how it is deployed. It uses the `ScanStatus` / `ScanRecord` / `ScanSpec` / `TargetSpec` vocabulary and the `ScanEngine` / `ScanService` contracts defined in [../ARCHITECTURE.md](../ARCHITECTURE.md) §4–§5 verbatim — nothing here redefines them.

Status: **design spec, not yet built.** The engine it drives (`rogue.scan.run_scan` at `src/rogue/scan.py:24`, `TargetPanel.run_attack` at `src/rogue/reproduce/target_panel.py:170`) exists today; the worker is the new Week-1 layer that turns it into a hosted, queue-backed service.

Lives at `src/rogue/platform/worker.py`. Related docs: the queue it leases from is [./job-queue.md](./job-queue.md); the engine wrapper it calls is [./scan-engine-adapter.md](./scan-engine-adapter.md); the service that enqueues the jobs and serves their status is [./scan-service.md](./scan-service.md); the live progress it writes is consumed by [../dashboard/live-scan-ux.md](../dashboard/live-scan-ux.md).

---

## 1. Responsibility boundary

The worker owns exactly one verb: **run a leased job to a terminal `ScanStatus`.** Everything around that verb belongs to a neighbour:

- **It does not enqueue.** `ScanService.create_scan` writes the `scan_runs` row in `queued` and pushes the job id ([./scan-service.md](./scan-service.md), [./job-queue.md](./job-queue.md)).
- **It does not scan.** The actual render → dispatch → judge → aggregate loop is `run_scan` (`src/rogue/scan.py:56`–`110`), reached only through `ScanEngine.run` ([./scan-engine-adapter.md](./scan-engine-adapter.md)). The worker never imports `run_scan` or `TargetPanel` directly — it holds a `ScanEngine` and calls `.run(...)`.
- **It does not render reports.** It persists the raw `ScanReport`; `ReportService` (Team F) turns it into HTML/PDF later, keyed by `report_id`.
- **It does not authorize.** Tenancy/RBAC is enforced at the API edge (Team C); a leased job is already authorized. The worker still threads `org_id` through every DB write so isolation is defence-in-depth, never trusting the job body alone.

So the worker is small and almost entirely orchestration glue. Its hard parts are not scanning — they are **liveness** (progress, heartbeats, crash recovery) and **politeness** (the outer concurrency cap so a wide scan does not 429-cascade a provider).

## 2. The worker loop

One worker process runs a pool of `concurrency` async loop tasks (§5). Each task runs this cycle forever:

```
loop forever:
    job = await queue.lease(worker_id, lease_ttl=LEASE_TTL)      # blocking pop + visibility timeout
    if job is None: continue                                     # lease() blocked then timed out

    run = await store.load_run(job.scan_id)                      # scan_runs row, ScanRecord shape
    if run.status != queued:                                     # already terminal / re-leased late
        await queue.ack(job); continue                           # idempotent: drop the duplicate

    if run.canceled_requested:                                   # canceled while still queued
        await mark(run, status=canceled); await queue.ack(job); continue

    await mark(run, status=running, started_at=now())           # scan_runs + Redis ScanRecord

    heartbeat = spawn(_heartbeat(job, run))                      # extends the lease every LEASE_TTL/3
    try:
        engine = ScanEngine()                                    # thin wrapper, no per-job state
        report = await engine.run(
            target = run.spec.target,                            # TargetSpec
            pack   = run.spec.pack,
            config = ScanConfig(                                 # from ScanSpec: attacks, max_tests,
                attacks=run.spec.attacks,                        #   n_trials, budget
                max_tests=run.spec.max_tests,
                n_trials=run.spec.n_trials,
                budget=run.spec.budget,
            ),
            progress = lambda ev: _on_progress(run, ev),         # §3 — drives ScanRecord.progress
        )
    except CancelledScan:                                        # cooperative cancel raised between primitives
        await mark(run, status=canceled, completed_at=now())
    except Exception as exc:
        await mark(run, status=failed, error=str(exc)[:500], completed_at=now())
    else:
        report_id = await store.persist_report(run, report)     # ScanReport → rows; returns rep_<ulid>
        await mark(run, status=completed, report_id=report_id,
                   n_tests=report.n_tests, n_breaches=report.n_breaches,
                   cost_usd=report.cost_usd, progress=100, completed_at=now())
    finally:
        heartbeat.cancel()
        await queue.ack(job)                                     # remove from in-flight; loop again
```

`mark(...)` is a single helper that writes both sinks atomically-enough for our needs: it updates the durable `scan_runs` row (Postgres, the audit/recovery truth) **and** the volatile `ScanRecord` snapshot in Redis (the fast read path for `GET /v1/scans/{id}`). The two can briefly disagree on `progress` during a scan — that is fine; only the terminal transition must hit Postgres before `ack`, so a crash after `ack` can never lose a completed result (§7).

`ScanStatus` transitions are exactly the five from ARCHITECTURE.md §5: `queued → running → {completed | failed | canceled}`. The worker only ever performs `queued→running`, `running→completed`, `running→failed`, and the two `→canceled` edges. It never moves a job back to `queued` itself — that is the queue's lease-expiry job (§7).

## 3. Progress reporting

`ScanRecord` carries `progress: int (0-100)` and the worker also surfaces a current-attack label, both of which the dashboard polls live (ARCHITECTURE.md §5; [../dashboard/live-scan-ux.md](../dashboard/live-scan-ux.md)). The engine produces this for free because `run_scan` is a flat loop over primitives (`src/rogue/scan.py:57`) — one iteration per attack primitive. The mechanism:

1. **The seam.** `ScanEngine.run` accepts `progress: ProgressCallback | None` (ARCHITECTURE.md §4). The worker passes a closure bound to the `run`. The engine wrapper ([./scan-engine-adapter.md](./scan-engine-adapter.md)) is responsible for invoking it once per completed primitive — i.e. just after the `responses = await panel.run_attack(...)` / judge step for each `prim` in the `run_scan` loop. `run_scan` itself has no callback today; the wrapper adds it by injecting a `panel`/`judge` pair (it already accepts injected `panel`/`judge` at `src/rogue/scan.py:32`–`33`) or by iterating primitives in the wrapper and calling the engine per-slice. Either way **no scanning logic is reimplemented** — the callback is a side-channel, not a fork of the loop.

2. **The event.** Each callback delivers `ProgressEvent { completed: int, total: int, current_attack: str, n_breaches_so_far: int, cost_usd_so_far: float }`. `total` is `min(max_tests, len(primitives))`; `current_attack` is the human `technique_label(prim.family.value)` already computed in the finding (`src/rogue/scan.py:90`).

3. **The write.** `_on_progress` maps the event to `ScanRecord` fields and writes only to **Redis** — `progress = round(100 * completed / total)`, `n_completed = completed`, `top_attack = current_attack`, `n_breaches`, `cost_usd`. It deliberately does **not** touch Postgres on every primitive: a 50-attack scan would otherwise issue 50 row updates of throwaway intermediate state. Postgres is written only on status transitions (§2). Redis is the live mirror; if it is evicted the dashboard simply shows the last `scan_runs` snapshot until the next transition.

4. **The read.** `GET /v1/scans/{id}` (Team A) reads the `ScanRecord` straight from Redis when the status is `running`, falling back to Postgres for terminal states. The dashboard polls that endpoint (or an SSE bridge over it) — see [../dashboard/live-scan-ux.md](../dashboard/live-scan-ux.md). The worker never talks to the dashboard; the contract is purely `ScanRecord` in Redis.

Progress is **monotonic and best-effort**: a dropped callback write loses one tick, never corrupts state, because `completed` is absolute (not a delta) so the next tick self-heals.

## 4. Persisting results

On the `completed` branch the worker turns the in-memory `ScanReport` (`target, n_tests, n_breaches, cost_usd, findings[]`, `src/rogue/report.py:75`) into durable rows via `store.persist_report`, which returns a `rep_<ulid>`. That id goes onto the `scan_runs` row as `report_id`; `ReportService` (Team F) later reads those rows to render JSON/HTML/PDF. The worker computes the headline `score` only if Team F's `compute_risk_score` is import-cheap; otherwise it stores `findings` raw and leaves `score` for the report layer (ARCHITECTURE.md §5 names Team F as the formula owner — the worker must not invent a second score).

The terminal `mark(...)` and `persist_report` must both land in Postgres **before** `queue.ack` (§2/§7). Ordering: persist report rows → write terminal `scan_runs` → `ack`. A crash between persist and ack re-leases the job; the loop's `run.status != queued` guard (§2) then sees a non-`queued`/already-`completed` row and acks the duplicate without re-running.

## 5. Concurrency model — two nested levels, the outer one is the worker's job

There are two independent fan-outs, and conflating them is the classic 429-cascade bug. ARCHITECTURE.md §7 and the §11.3 note in the engine both call the outer cap the worker's responsibility.

- **Inner (already solved, do not touch).** Within a single attack, `TargetPanel.run_attack` fires `n_trials` provider calls in parallel via `asyncio.gather` (`src/rogue/reproduce/target_panel.py:202`–`210`). That fan-out is bounded by `n_trials` (small, e.g. 5) and is the engine's concern. The panel's own comment is explicit that it does **not** own the outer cap (`target_panel.py:207`–`208`).

- **Outer (the worker owns this).** A scan sweeps `primitives × configs`. `scripts/reproduce_once.py` already demonstrates the pattern the worker must adopt: a single `asyncio.Semaphore(concurrency)` wrapping each `(primitive, config)` panel dispatch (`scripts/reproduce_once.py:442`, `:445`). The worker holds **one process-wide semaphore** sized to the provider's tolerable in-flight request count (config: `ROGUE_PROVIDER_CONCURRENCY`, default ~5), shared across **all** loop tasks in the pool — not per-scan, because ten concurrent small scans hitting the same OpenAI key must respect the same ceiling as one big scan. The engine wrapper acquires it around each primitive dispatch; the worker injects it.

- **Pool size.** The worker runs `WORKER_CONCURRENCY` loop tasks (default ~4) so several scans progress at once. Pool size governs *job* parallelism; the provider semaphore governs *request* parallelism. They are deliberately separate knobs: you scale the pool to keep many tenants' scans moving, and scale the provider semaphore to whatever the provider tolerates. The product of the two is naturally capped because every in-flight request, from whatever loop task, takes a slot in the same provider semaphore.

This is the single most important worker invariant: **no provider sees more than `ROGUE_PROVIDER_CONCURRENCY` concurrent requests, regardless of how many scans or trials are live.**

## 6. Rate limits, retries, and budget

- **Transient errors are already handled below the worker.** Each adapter wraps its provider call in `with_provider_retry` — 3 attempts, exponential backoff 1→10s, retrying only network transients / provider `RateLimitError` / 429 / 5xx, reraising on exhaustion (`src/rogue/adapters/_provider_errors.py:79`–`85`, retry predicate at `:60`–`75`). A 4xx that is not 429 (auth, bad request, content-policy) is **not** retried — it is deterministic. The worker adds **no** retry layer of its own; double-retrying would amplify a rate-limit storm.

- **Exhausted rate limits are recorded, not fatal.** When retries are exhausted the panel projects the failure to a `ModelResponse` with `error="rate_limit_exhausted: …"` (`target_panel.py:278`–`279`), and `run_scan` simply skips that trial (`src/rogue/scan.py:68`–`69`). One throttled primitive degrades that finding's sample size; it never fails the scan. The worker therefore treats a returned `ScanReport` as success even if some trials errored — `failed` status is reserved for an exception escaping `engine.run` (e.g. auth misconfig, an unrouted provider — `target_panel.py:98`).

- **Budget stops the sweep early, the worker doesn't.** `run_scan`'s `budget` parameter halts the loop once accumulated target-call cost reaches it (`src/rogue/scan.py:58`–`59`). The worker passes `ScanSpec.budget` straight through; a budget-truncated scan still completes normally with a partial `findings[]` and the real `cost_usd`. The worker does not separately meter spend — that would duplicate the engine's authoritative figure.

## 7. Timeouts, heartbeats, and crash recovery

- **Lease + heartbeat.** A leased job carries a visibility timeout `LEASE_TTL` (e.g. 120s). The `_heartbeat` task (§2) extends the lease every `LEASE_TTL/3` while the scan runs, so a legitimately long scan (many primitives × trials) keeps its lease. This is the only thing the heartbeat does — it is liveness, not progress (progress is §3). Heartbeat and the scan share the loop task; if the event loop wedges, the heartbeat stops, the lease lapses, and recovery kicks in.

- **Crash recovery via lease expiry.** If a worker dies mid-scan (OOM, deploy, kill), it never `ack`s and never heartbeats. The lease expires and the queue makes the job visible again; another worker leases it and re-runs from scratch (scans are idempotent — re-running produces a fresh `ScanReport`; there is no partial-result resume, by design, because a half-judged matrix is not a meaningful report). The re-run overwrites the same `scan_runs` row. Lease-expiry re-queue mechanics belong to [./job-queue.md](./job-queue.md); the worker's only obligation is to heartbeat while alive and to `ack` exactly once on a terminal outcome.

- **Poison-job guard.** A job that crashes the worker every time would re-lease forever. The queue tracks a delivery count; past `MAX_DELIVERIES` (e.g. 3) the worker (or the queue) moves the job to `failed` with `error="exceeded max deliveries"` and stops re-queueing. See [./job-queue.md](./job-queue.md) for where the counter lives.

- **Per-scan wall-clock ceiling.** Independent of the lease, the worker wraps `engine.run` in an `asyncio.timeout(SCAN_MAX_SECONDS)` (e.g. 1800s). On timeout it marks `failed` with `error="scan exceeded time budget"`. This protects against a provider that accepts connections but never responds — the adapter retry/backoff bounds a single call, but a 200-primitive sweep of slow-but-not-failing calls needs a top-level cap.

## 8. Cooperative cancellation

`ScanService.cancel_scan` (ARCHITECTURE.md §4) sets a cancel flag — `canceled_requested=true` on the `scan_runs` row plus a fast Redis flag for the running case. The worker honours it **cooperatively, between primitives**:

- The `progress` callback (§3) is the natural checkpoint — it already fires once per completed primitive. Inside `_on_progress` (or in the engine wrapper's per-primitive step) the worker checks the Redis cancel flag for this `scan_id`; if set, it raises `CancelledScan`, which unwinds out of `engine.run` to the `except CancelledScan` branch (§2) and marks `canceled`. The in-flight primitive's `n_trials` calls are allowed to finish (they are cheap and already issued) — we cancel at the primitive boundary, not mid-`gather`, to avoid leaking half-closed provider connections.
- A job canceled **while still `queued`** never starts: the loop's pre-`running` guard (§2) catches `canceled_requested` and marks `canceled` without leasing engine work.
- Cancellation is therefore bounded by one primitive's latency, not the whole scan — good enough, and far simpler than hard task cancellation across the `asyncio.gather` fan-out.

## 9. Deployment

The worker is a **separate Render service**, distinct from the web dyno that serves the FastAPI app (`src/rogue/api/main.py`). Same image and codebase, different entrypoint:

```
# web service (Render):     uvicorn rogue.api.main:app --host 0.0.0.0 --port $PORT
# worker service (Render):  python -m rogue.platform.worker
```

`src/rogue/platform/worker.py` exposes a `__main__` that reads `WORKER_CONCURRENCY`, `ROGUE_PROVIDER_CONCURRENCY`, `LEASE_TTL`, `SCAN_MAX_SECONDS`, the `DATABASE_URL`, the Redis URL, and the provider API keys from the environment, builds the pool, and runs the loop. Rationale for the split:

- **Resource isolation.** A wide scan is CPU/IO-heavy and long-lived; running it in the web dyno would block request threads and starve `GET /v1/scans/{id}` — which is exactly the polling endpoint that needs to stay snappy *during* a scan. ARCHITECTURE.md §2/§7 mandate "scans run in a worker, never the request thread."
- **Independent scaling.** Worker replicas scale on queue depth; web replicas scale on request rate. They share Redis (queue + `ScanRecord` mirror) and Postgres (`scan_runs`, report rows) but nothing else. Multiple worker replicas are safe: the queue lease guarantees exactly-one active processor per job, and the shared provider semaphore is per-process — so the global provider concurrency ceiling is `replicas × ROGUE_PROVIDER_CONCURRENCY`, which the operator must size against the provider's account limit (a documented multi-replica caveat, not a bug).
- **Health.** The worker has no HTTP surface; Render health-checks it via a liveness file or a tiny background ping it writes to Redis each loop. A worker that stops heartbeating its *own* liveness key is restarted by the platform; in-flight jobs recover via §7 lease expiry.

## 10. Open questions (resolve before Week-1 build)

- **Per-primitive progress granularity vs. the wrapper.** §3 assumes the engine wrapper can invoke `progress` once per primitive without forking `run_scan`. If injecting a progress-aware `panel`/`judge` proves too indirect, the alternative is for the wrapper to iterate primitives and call a per-slice engine method — decided in [./scan-engine-adapter.md](./scan-engine-adapter.md), not here.
- **Multi-replica provider ceiling.** Whether to centralize the provider semaphore in Redis (a true global token bucket) or accept the `replicas × N` per-process ceiling. Per-process is simpler and ships first; a Redis token bucket is the upgrade path if we run many worker replicas against one provider key.
- **Cancel-flag transport.** Whether the running-scan cancel flag rides the existing `ScanRecord` Redis key or a dedicated pub/sub channel. Polling the key in `_on_progress` (§8) is adequate at our primitive cadence; pub/sub is only worth it if we want sub-primitive cancel latency.
