# Job Queue & the `ScanJob` Model — Team B

> Where a scan *waits*. [`ScanService`](./scan-service.md) accepts a `ScanSpec` in the request thread, persists a `ScanRecord`, and hands the work off here; the [`ScanWorker`](./worker.md) pulls from here and runs it through the engine. This doc owns the seam between those two: the durable `scan_jobs` dispatch table. It does **not** redefine the [`ScanStatus`](../ARCHITECTURE.md) enum (`queued | running | completed | failed | canceled`) or the `scan_<ulid>` / `org_<ulid>` / `proj_<ulid>` IDs — those are canonical in [`ARCHITECTURE.md §5`](../ARCHITECTURE.md) and are imported, never restated.

Status: **BUILT (local).** Shipped as `PostgresJobQueue` (`src/rogue/platform/queue.py`) against the `JobQueue` ABC (`src/rogue/platform/interfaces.py`), with an `InMemoryJobQueue` twin in `memory.py` for tests / single-process mode. The `scan_jobs` table shipped in migration `0022_platform_tables.py`.

**Major deviation from the original design below: there is NO Redis.** The shipped queue is **Postgres-only** — a `SELECT … FOR UPDATE SKIP LOCKED` lease on the `scan_jobs` table, exactly the "fallback / rebuild path" §7 once described as a degraded mode. Postgres is both the durable record *and* the dispatch layer; the single-box deployment (one Neon Postgres, no service mesh, no Redis) is the whole reason. Everything below that talks about `LPUSH`/`BRPOP`/`ZADD`/`rogue:q:*` lists, priority bands drained by `BRPOP`, per-tenant fairness lists, or a Redis delayed-set reaper is **the original aspirational design and is not built** — `SKIP LOCKED` is the concurrency guard, `available_at` (a timestamp column) schedules retry backoff, and a `reap_expired()` sweep reclaims dead-worker leases. The `priority` column exists but is only an `ORDER BY` key; there is no cross-tenant fairness layer.

---

## 1. One store, two roles

- **Durability — Postgres (Neon).** A `ScanRecord` (the customer-facing status row, returned by `GET /v1/scans/{id}`) lives in `scan_runs`. Its execution backing — the unit of work a worker leases — lives in the `scan_jobs` table. Both are the source of truth, and because dispatch is *also* Postgres, there is no second store to keep in sync.
- **Dispatch — Postgres `SKIP LOCKED`.** `lease()` claims the oldest available `queued` job with `SELECT … ORDER BY priority DESC, created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED`, so N concurrent workers never get the same row. (SQLite ignores `with_for_update`, which is why offline tests are single-threaded and exercise the state machine, not the locking.)

`scan_runs` is the [`ScanRecord`](../ARCHITECTURE.md) (status, progress, score, report_id) — owned jointly with [`../tenancy/data-model.md`](../tenancy/data-model.md). `scan_jobs` carries `org_id` as its own indexed column (not read through the FK). One scan row → one job row.

The split is the whole point of [ARCHITECTURE.md §4](../ARCHITECTURE.md)'s "NEVER runs a scan in the request thread": the API call returns the instant the job is durably enqueued, and a long red-team run (multi-minute, multi-dollar, `full reproduce ≈ $35` per CLAUDE.md) happens out-of-band.

## 2. Why Postgres-only, not Kafka or Redis — and why a queue at all

The deployment is a **single Neon Postgres** and a **3 GB / 2 CPU Docker box** (per CLAUDE.md's footprint note). That budget rules out Kafka/RabbitMQ/a broker cluster. The original design (below) reached for a small Redis as a dispatch cache, keeping `SELECT … FOR UPDATE SKIP LOCKED` only as a fallback. **What actually shipped inverted that: Postgres `SKIP LOCKED` *is* the queue, and there is no Redis at all** — one fewer moving part to run, monitor, and keep durable, consistent with the "one Postgres, no service mesh, no Redis" rule. A worker polls `lease()` on a poll interval (`run_forever(poll_interval=1.0)`); `SKIP LOCKED` keeps concurrent workers from colliding without any external broker.

## 3. The leased-job shape

The object a worker dequeues is `LeasedJob` (`src/rogue/platform/interfaces.py`), built from a `scan_jobs` row:

```python
class LeasedJob:
    job_id: str          # job_<ulid>
    scan_id: str         # scan_<ulid>  → scan_runs.scan_id
    spec: ScanSpec       # the frozen ScanSpec (rehydrated from the row's `payload` JSON)
    org_id: str          # org_<ulid>
    attempts: int        # delivery count so far (retry / backoff, §6)
```

The `payload` column is the [`ScanSpec`](../ARCHITECTURE.md) captured at create time (`spec.model_dump(mode="json")`), frozen into the row so a replay runs the *exact* spec the customer submitted even if defaults later change. The worker rehydrates it with `ScanSpec.model_validate(...)` and calls `ScanEngine.run(spec, ...)` (the [worker doc](./worker.md) owns that hand-off; the [scan-engine adapter](./scan-engine-adapter.md) owns the engine wrapper).

## 4. The `scan_jobs` table (migration `0022_platform_tables.py`)

The shipped ORM (`src/rogue/platform/models.py`, in the new `platform` model module — *not* the legacy `src/rogue/db/models.py`):

```python
class ScanJob(Base):
    """Durable dispatch record (the queue's source of truth). Postgres SKIP-LOCKED lease."""

    __tablename__ = "scan_jobs"
    job_id: Mapped[str] = mapped_column(String(48), primary_key=True)              # job_<ulid>
    scan_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.scan_id"), index=True)
    org_id: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)  # queued|leased|running|done|failed|canceled
    payload: Mapped[dict] = mapped_column(JSON, default=dict)                       # frozen ScanSpec
    priority: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    locked_by: Mapped[str | None] = mapped_column(String(80), nullable=True)        # worker id holding lease
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)  # retry-backoff gate
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

Notes on the columns. The PK is the `job_id` string itself (no surrogate `BigInteger`). `status` carries `queued|leased|running|done|failed|canceled` as a plain `String(20)` (`done` is the queue's ack state; the canonical customer-facing `ScanStatus` lives on `scan_runs`). The `scan_id` FK points at `scan_runs.scan_id`; **`org_id` is a direct indexed column on this table**, not read through the FK (no fairness layer needs it routed). The `locked_by` / `locked_at` / `lease_expires_at` triple is the visibility-timeout lease (§5). **`available_at`** is the shipped retry mechanism: a failed job is re-queued with `available_at = now + backoff`, and `lease()` only considers rows with `available_at <= now` — this replaces the design's Redis delayed-set. There is no `updated_at` and no `project_id` column on `scan_jobs`.

### The migration file — `0022_platform_tables.py`

`scan_jobs` did **not** ship as a standalone `0022_add_scan_jobs.py`. It landed in `0022_platform_tables.py`, the single migration that creates the whole multi-tenant platform schema at once (`organizations`, `users`, `memberships`, `projects`, `api_keys`, `scan_runs`, `scan_jobs`, `reports`). The `secrets` table came later in `0023_secrets.py` and `integrations` in `0024_integrations.py`. Applied the standard way (per CLAUDE.md's Database section): `uv run alembic upgrade head`.

## 5. Enqueue / lease with a visibility-timeout lease (shipped)

The shipped `PostgresJobQueue` methods (`src/rogue/platform/queue.py`), all Postgres, no Redis:

**`enqueue(scan_id, spec, *, org_id) -> job_id`** — a single `INSERT scan_jobs (status='queued', payload=spec.model_dump(mode="json"), available_at=now, …)`. The Postgres commit is the durable enqueue. `ScanService` calls this right after persisting the `scan_runs` row (row-then-enqueue ordering, [scan-service §11](./scan-service.md)).

**`lease(*, worker_id, lease_seconds=300) -> LeasedJob | None`** — one statement claims the oldest ready job:

```sql
SELECT * FROM scan_jobs
 WHERE status='queued' AND available_at <= now()
 ORDER BY priority DESC, created_at ASC
 LIMIT 1 FOR UPDATE SKIP LOCKED;
```

then sets `status='leased'`, `locked_by=worker_id`, `locked_at=now()`, `lease_expires_at=now()+lease_seconds` and commits. `SKIP LOCKED` is the whole concurrency story: two workers leasing at once skip each other's locked row, so no job is double-leased. Returns `None` when nothing is ready (the worker then sleeps `poll_interval`).

**`ack(job_id)`** — `status='done'`. **`extend_lease(job_id, *, lease_seconds=300)`** — pushes `lease_expires_at` out so a legitimately long scan isn't reclaimed (the worker's lease heartbeat).

**`fail(job_id, *, error, retry)`** — records `error`; if `retry` and `attempts + 1 < max_attempts`, bumps `attempts`, sets `status='queued'` and `available_at = now + backoff(attempts)` (clearing the lease columns) so the row becomes leasable again only after the delay; otherwise `status='failed'` (dead-letter). Backoff is `min(5 · 5^(attempts-1), 600)` seconds — i.e. 5s → 25s → 125s, capped at 600s.

**The crashed-worker reclaim.** `reap_expired()` is a periodic sweep (run by a supervisor): `UPDATE scan_jobs SET status='queued', available_at=now(), locked_by=NULL … WHERE status='leased' AND lease_expires_at < now()`. A worker that died mid-lease never acked, so its job sits in `leased` until its `lease_expires_at` passes and this hands it back to the pool. The visibility timeout (`lease_seconds`, default 300s) is the single knob governing how fast a dead worker's work is rescued.

## 6. At-least-once delivery + idempotency

The lease model gives **at-least-once** delivery: a worker that crashes after leasing but before acking has its job reclaimed by `reap_expired()` and re-run. That is the correct trade — we never want a paid scan to silently vanish — but it means a job can execute more than once.

**Shipped caveat:** the worker does *not* check `scan_runs.status` before running, and the result-write (`ScanStore.update`) is **not** a conditional `WHERE status='running'`. So a redelivered job re-runs the scan and overwrites the record. Re-execution is bounded by `attempts`/`max_attempts` (default 3) but not deduplicated against an already-terminal scan. (The conditional-write / terminal-state guard the original design describes is not built — flag if exactly-once result semantics become a requirement.)

## 7. Postgres is the only store

There is no Redis to rebuild from — the durable `scan_jobs` table *is* the queue. On worker startup nothing needs reconstructing: `lease()` simply queries `scan_jobs` for the next ready `queued` row. Stuck `leased` rows from a dead worker are recovered by `reap_expired()` (§5).

## 8. Priority & fairness

The `scan_jobs.priority` column exists and `lease()` orders by `priority DESC, created_at ASC`, so a higher-priority job is leased first. **Cross-tenant fairness (per-`org_id` round-robin / weighted-fair-queuing) is NOT built** — the design below was Redis-list-based and did not ship. For the current single-worker deployment this is latent; a fairness layer would be a future addition over the same `org_id` column.

## 9. The job state machine

`status` advances through one queue-internal phase (`leased`) bracketed by the canonical `ScanStatus` values. The `scan_jobs.status` and the `scan_runs.status` (`ScanRecord.status`) move together: when the job goes `running`, the `ScanRecord` goes `running`; the job's terminal state mirrors the scan's `completed | failed | canceled`.

```
                          enqueue (API thread)
                                  │
                                  ▼
                            ┌──────────┐
            reclaim ───────▶│  queued  │◀────── rebuild from Postgres (§7)
          (lease expired)   └────┬─────┘
                                 │ BRPOP + ZADD lease + UPDATE (§5)
                                 ▼
                            ┌──────────┐   lease expires, no heartbeat
                            │  leased  │───────────────────────────────┐
                            └────┬─────┘                                │
                                 │ worker starts engine                 │
                                 ▼                                      │
                            ┌──────────┐   crash / lease expiry         │
                            │ running  │────────────────────────────────┤
                            └────┬─────┘                                │
            cancel_scan ────────┤                                       │
          (ScanService)         │                                       ▼
              ┌─────────────────┼─────────────────┐            attempts < max?
              ▼                 ▼                 ▼              │           │
        ┌───────────┐    ┌───────────┐    ┌───────────┐    yes  │           │ no
        │ completed │    │  failed   │    │ canceled  │◀─────────┘           │
        └───────────┘    └─────┬─────┘    └───────────┘    re-queue          ▼
         (terminal)            │ attempts ≥ max_attempts            ┌──────────────────┐
                               └───────────────────────────────────│  dead-letter     │
                                                                    │ (rogue:q:dlq +   │
                                                                    │  status='failed',│
                                                                    │  error set)      │
                                                                    └──────────────────┘
```

**Retry & backoff.** When the worker calls `fail(job_id, retry=…)`, a retry happens iff `attempts + 1 < max_attempts`: the row goes back to `queued` with `available_at = now + backoff`, where `backoff = min(5 · 5^(attempts-1), 600)` seconds (5s → 25s → 125s, capped at 600s). There is no Redis delayed-set — the `available_at` timestamp column gates re-leasing (a row is only leasable once `available_at <= now()`). (Note: the *shipped* worker calls `fail(retry=False)`, so engine exceptions currently dead-letter immediately; the retry path exists in the queue but the worker does not yet opt into it — flag if automatic retry of transient adapter/429 failures is wanted.)

**Dead-letter.** When retries are exhausted (or `retry=False`), the job goes `status='failed'` with `error` set to the last exception, and the worker also marks the `ScanRecord` `failed` with the same `error` (surfaced to the customer via the [error envelope](../ARCHITECTURE.md)). There is no separate DLQ list — a `failed` `scan_jobs` row *is* the dead letter. Re-driving is a deliberate `status='queued', attempts=0, available_at=now()` reset.

**Cancel.** [`ScanService.cancel_scan`](./scan-service.md) sets `scan_runs.status='canceled'` and best-effort cancels the queued job (`PostgresJobQueue` has no `.cancel`; the in-memory queue does — so on Postgres a still-`queued` job's record is marked canceled but the job row may still be leasable; see the scan-service §8 caveat). **There is no mid-run cancel checkpoint** — the worker does not poll `scan_runs.status` between attacks. The DLQ / cooperative-cancel boxes in the diagram below are original-design, not shipped.

---

## See also

- [`./scan-service.md`](./scan-service.md) — the `ScanService` facade that enqueues here and reads `scan_runs` back.
- [`./worker.md`](./worker.md) — the `ScanWorker` dequeue loop, lease heartbeat, and engine hand-off.
- [`../tenancy/data-model.md`](../tenancy/data-model.md) — `scan_runs` / `ScanRecord` columns, `org_id` / `project_id` FKs, and the tenant model that drives §8 fairness.
- [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — canonical `ScanStatus`, IDs, `ScanSpec` / `ScanRecord` shapes (§5), and the one-engine principle this queue protects.
