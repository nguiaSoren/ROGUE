# Job Queue & the `ScanJob` Model — Team B

> Where a scan *waits*. [`ScanService`](./scan-service.md) accepts a `ScanSpec` in the request thread, persists a `ScanRecord`, and hands the work off here; the [`ScanWorker`](./worker.md) pulls from here and runs it through the engine. This doc owns the seam between those two: the Redis dispatch queue and the durable `scan_jobs` table. It does **not** redefine the [`ScanStatus`](../ARCHITECTURE.md) enum (`queued | running | completed | failed | canceled`) or the `scan_<ulid>` / `org_<ulid>` / `proj_<ulid>` IDs — those are canonical in [`ARCHITECTURE.md §5`](../ARCHITECTURE.md) and are imported, never restated.

Status: **design spec, not yet built.** Targets migration `0022` (see below); the engine it ultimately feeds (`rogue.scan.run_scan`, `src/rogue/scan.py:24`) already exists.

---

## 1. Two stores, two jobs

A scan has two distinct persistence needs and we split them deliberately:

- **Durability — Postgres (Neon).** A `ScanRecord` (the customer-facing status row, returned by `GET /v1/scans/{id}`) lives in `scan_runs`. Its execution backing — the unit of work a worker leases — lives in a new `scan_jobs` table. These are the **source of truth**: if Redis is wiped, no scan is lost; the queue can be rebuilt from `scan_jobs WHERE status IN (queued, leased, running)`.
- **Dispatch — Redis.** A lightweight list/stream that answers exactly one question fast: *which job should a free worker pick up next, and has anyone else already grabbed it?* The Redis state is **ephemeral and reconstructable** — it is a cache of "what's pending," never the record of "what happened."

`scan_runs` is the [`ScanRecord`](../ARCHITECTURE.md) (status, progress, score, report_id) — owned jointly with [`../tenancy/data-model.md`](../tenancy/data-model.md), which adds the `org_id` / `project_id` FK columns and the tenant-scoping indexes. `scan_jobs` is the queue's own durable mirror, owned entirely by Team B. One scan row → one job row (1:1 today; the column shape leaves room for fan-out later without a schema change).

The split is the whole point of [ARCHITECTURE.md §4](../ARCHITECTURE.md)'s "NEVER runs a scan in the request thread": the API call returns the instant the job is durably enqueued, and a long red-team run (multi-minute, multi-dollar, `full reproduce ≈ $35` per CLAUDE.md) happens out-of-band.

## 2. Why Redis-for-dispatch, not Kafka — and why a queue at all

The deployment is a **single Neon Postgres** and a **3 GB / 2 CPU Docker box** (per CLAUDE.md's footprint note). That budget rules out Kafka/RabbitMQ/a broker cluster: they want partitions, ZooKeeper/KRaft, multi-GB heaps, and an ops surface a solo dev can't carry. A single small Redis (`redis:7-alpine`, `maxmemory ~128mb`, `--appendonly no` since the durable copy is in Postgres) fits the box and gives us the two primitives we actually need: an atomic blocking pop and a sorted-set for visibility timeouts.

We could have used **Postgres alone** as the queue (`SELECT … FOR UPDATE SKIP LOCKED`). That works and we keep it as the **fallback / rebuild path** (§7). But a hot `SKIP LOCKED` poll against the *one* Neon instance competes with every read the dashboard and API issue, and Neon's serverless connection ceiling is already a known constraint (`reference_neon_serverless_resilience.md`). Redis absorbs the high-frequency "anything for me?" polling so Postgres only sees a write when a job's **state actually changes**. Redis dispatches; Postgres remembers.

## 3. The `ScanJob` shape

The in-memory/wire object the worker dequeues. It is the `payload` JSON of a `scan_jobs` row plus its envelope columns:

```python
@dataclass(frozen=True)
class ScanJob:
    job_id: str          # job_<ulid>
    scan_id: str         # scan_<ulid>  → scan_runs.scan_id
    org_id: str          # org_<ulid>   (tenant; drives fairness, §8)
    project_id: str      # proj_<ulid>
    payload: dict        # the frozen ScanSpec: {target, pack, attacks, max_tests, n_trials, budget}
    priority: int        # 0 = normal; higher = sooner (§8)
    attempts: int        # delivery count so far (idempotency / retry, §6)
    max_attempts: int    # default 3, then → dead-letter
```

`payload` is the [`ScanSpec`](../ARCHITECTURE.md) captured at create time, frozen into the row so a replay runs the *exact* spec the customer submitted even if defaults later change. The worker reconstructs a `TargetSpec` from it and calls `ScanEngine.run` (the [worker doc](./worker.md) owns that hand-off; the [scan-engine adapter](./scan-engine-adapter.md) owns the engine wrapper).

## 4. The `scan_jobs` table (migration `0022`)

Modeled on the existing run-record precedent `BenchmarkRun` (`src/rogue/db/models.py:728`) — an append-style durable row with `BigInteger` surrogate PK, indexed string business keys, a `JSON` detail blob, and `DateTime(timezone=True)` timestamps. New ORM class in `src/rogue/db/models.py` (added to `__all__` alongside `BenchmarkRun`), enums imported from `rogue.schemas` per the no-duplication rule (`models.py:38`):

```python
class ScanJob(Base):
    """Durable queue record — the unit of work a ScanWorker leases. Redis holds
    the *dispatch* copy (ephemeral); this row is the source of truth. status uses
    the canonical ScanStatus vocabulary plus the queue-internal 'leased' phase.
    """
    __tablename__ = "scan_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)      # job_<ulid>
    scan_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.scan_id"), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True, server_default="queued")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)                     # frozen ScanSpec
    priority: Mapped[int] = mapped_column(Integer, server_default="0", index=True)
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, server_default="3")
    locked_by: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)   # worker id holding lease
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc))
```

Notes on the columns. `status` reuses the canonical `ScanStatus` *values* plus the one queue-internal phase `leased` (§5) — stored as a CHECK-constrained `String(20)` rather than a native PG enum, because `leased` is a queue concept that does not belong in the customer-facing `ScanStatus` enum (the same `String` + values-from-`Literal` discipline `SourceType`/`BrightDataProduct` use at `models.py:62`). The `scan_id` FK points at `scan_runs.scan_id` (the [`ScanRecord`](../ARCHITECTURE.md) table that [`../tenancy/data-model.md`](../tenancy/data-model.md) defines); `org_id`/`project_id` are read through that FK for fairness rather than duplicated here. The `locked_by` / `locked_at` / `lease_expires_at` triple is the visibility-timeout lease (§5). `error` mirrors the `ScanRecord.error` field for the terminal-failure case.

### The migration file — `0022_add_scan_jobs.py`

A new revision under `src/rogue/db/migrations/versions/`, continuing the linear chain. The latest is `0021_add_benchmark_runs.py` (`revision = "0021"`, `down_revision = "0020"`), so:

```python
# 0022_add_scan_jobs.py
revision: str = "0022"
down_revision: Union[str, Sequence[str], None] = "0021"   # chains onto benchmark_runs
```

It is `op.create_table("scan_jobs", …)` with the columns above, the `ForeignKey("scan_runs.scan_id")` constraint (so `scan_runs` from the tenancy migration must land first — coordinate the chain so the `scan_runs` revision is an ancestor), plus the dispatch indexes: a composite `(status, priority, created_at)` for the rebuild scan (§7) and `ix_scan_jobs_lease_expires_at` on `lease_expires_at` for the reaper sweep (§5). `downgrade()` drops the indexes then the table. No data migration — `scan_jobs` is born empty.

Applied the standard way (per CLAUDE.md's Database section): `uv run alembic upgrade head`. The alembic `env.py` overrides `sqlalchemy.url` from `DATABASE_URL` via `dotenv.load_dotenv()` at runtime (`src/rogue/db/migrations/env.py:8-21`) — so `0022` runs against whatever DB `DATABASE_URL` points at (local Docker Postgres or Neon), with no hard-coded connection string in the migration.

## 5. Enqueue / dequeue with a visibility-timeout lease

**Enqueue** (in the API request thread, transactionally with the `scan_runs` insert):

1. `INSERT scan_jobs (status='queued', priority, payload, …)`.
2. `LPUSH rogue:q:{priority} <job_id>` — push the job id onto the Redis list for its priority band.

The Postgres write is the commit point. If step 2 fails (Redis down), the row still exists as `queued`; the reaper/rebuild (§7) re-pushes it. This ordering is what makes the queue **rebuildable** — Redis never holds a job Postgres doesn't.

**Dequeue** (in the worker loop — detail in [`worker.md`](./worker.md)):

1. `BRPOP rogue:q:{high} rogue:q:{normal} … <timeout>` — atomic blocking pop across priority bands (highest first). Blocking means no busy-poll against Redis or Neon.
2. **Lease, don't delete.** In one Redis transaction add the job to a `ZADD rogue:leased <now+visibility_timeout> <job_id>` sorted set keyed by lease expiry. The job is now invisible to other workers but *not gone*.
3. `UPDATE scan_jobs SET status='leased', locked_by=:worker_id, locked_at=now(), lease_expires_at=now()+:vt, attempts=attempts+1 WHERE job_id=:id AND status='queued'`. The `AND status='queued'` guard makes the claim atomic at the DB level too — a double-delivered id can't be claimed twice.
4. Worker transitions the row to `running` and starts the engine; it `ZADD`s a fresh expiry periodically (a **lease heartbeat**) so a legitimately long scan isn't reclaimed mid-flight.

**The crashed-worker reclaim.** A reaper (a periodic sweep, can be a `0` background coroutine in the worker or a tiny cron) does `ZRANGEBYSCORE rogue:leased -inf <now>` to find leases whose `lease_expires_at` has passed with no heartbeat — i.e. the worker holding them died. For each: `UPDATE scan_jobs SET status='queued', locked_by=NULL WHERE job_id=:id AND status IN ('leased','running')`, remove from `rogue:leased`, and `LPUSH` it back onto its priority list. The job is redelivered. The visibility timeout (start at ~5 min, longer than a normal scan's slow step, refreshed by heartbeat) is the single knob governing how fast a dead worker's work is rescued.

## 6. At-least-once delivery + idempotency

The lease model gives **at-least-once** delivery: a worker that crashes after starting a scan but before recording the result will have its job reclaimed and re-run. That is the correct trade — we never want a paid scan to silently vanish — but it means a job can execute more than once, so every consumer must be **idempotent**.

The idempotency key is `(scan_id, attempt)` is *not* used; instead the worker is idempotent on `scan_id`: before running, it checks `scan_runs.status` — if the scan already reached a terminal `ScanStatus` (`completed`/`failed`/`canceled`), the redelivered job is a **no-op ack** (pop the lease, mark the job `completed`, write no second report). The result-write itself is an `UPDATE scan_runs … WHERE scan_id=:id AND status='running'` so two racing executions can't both commit a result. `attempts`/`max_attempts` bound how many times we'll redeliver before giving up (§ dead-letter).

## 7. Postgres as the rebuild / fallback path

Redis is allowed to disappear. On worker startup, or on a Redis flush, the queue is reconstructed from the durable table:

```sql
SELECT job_id, priority FROM scan_jobs
 WHERE status IN ('queued','leased','running')
 ORDER BY priority DESC, created_at ASC;        -- uses ix (status,priority,created_at)
```

Every `queued`/`leased`/`running` job is re-`LPUSH`ed (leased/running ones are treated as expired-lease reclaims). This is also the **degraded mode**: if Redis is unreachable, the worker falls back to polling this exact query with `FOR UPDATE SKIP LOCKED` — slower and heavier on Neon, but correct, and acceptable for a single-box deployment that rarely loses Redis. The durable table is what makes "lightweight ephemeral Redis" a safe choice rather than a single point of data loss.

## 8. Priority & cross-tenant fairness

Two levers, both cheap on a single small Redis:

- **Priority bands.** A fixed set of Redis lists — `rogue:q:high`, `rogue:q:normal`, `rogue:q:low` — drained in order by the `BRPOP` key list. `priority` on the row maps to a band; an interactive dashboard scan can outrank a bulk benchmark sweep without a real priority-queue data structure.
- **Per-tenant fairness within a band.** A single noisy `org_id` must not starve others sharing its band. The dequeue applies **round-robin over `org_id`**: rather than one list per band, key the lists per tenant (`rogue:q:{band}:{org_id}`) and keep a Redis list of *active tenant queues* per band; the worker pops one job, then rotates that tenant to the back. This is weighted-fair-queuing-lite — O(1) per dequeue, no global scan — and bounds any one tenant's share of worker time. The `org_id` for routing is read off the job's `scan_runs` row at enqueue (see [`../tenancy/data-model.md`](../tenancy/data-model.md) for the tenant model). A per-tenant in-flight cap (e.g. ≤ N `running` jobs per `org_id`) is the natural extension when concurrency grows.

For the Week-1 single-worker deployment ([ARCHITECTURE.md §7](../ARCHITECTURE.md)) fairness is mostly latent, but the band + per-tenant-list shape is in from the start so turning on a second worker needs no schema or protocol change.

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

**Retry & backoff.** A `failed` execution (engine exception, adapter timeout) is retried iff `attempts < max_attempts`: the row goes back to `queued` and is re-`LPUSH`ed after an **exponential backoff** delay (`base · 2^attempts`, e.g. 5s → 10s → 20s, jittered). The delay is implemented with a Redis **delayed set** — `ZADD rogue:q:delayed <ready_at> <job_id>` — that the reaper promotes to the live list once `ready_at` passes (same sweep that reclaims expired leases). Provider rate-limit errors (HTTP 429 from the customer's model) use a longer floor.

**Dead-letter.** When `attempts ≥ max_attempts` (default 3), the job stops retrying: `status='failed'`, `error` set to the last exception, pushed to `rogue:q:dlq`, and the `ScanRecord` goes `failed` with the same `error` (the [`ScanRecord.error`](../ARCHITECTURE.md) field surfaces it to the customer via the [error envelope](../ARCHITECTURE.md)). The DLQ is inspected manually — a poisoned job (bad target, malformed spec) should never silently loop and burn budget. Re-driving a DLQ job is a deliberate `status='queued', attempts=0` reset + re-push.

**Cancel.** [`ScanService.cancel_scan`](./scan-service.md) sets `scan_runs.status='canceled'`; the worker checks the scan's status at each safe checkpoint (between attacks) and, seeing `canceled`, stops the engine cleanly and marks the job `canceled`. A still-`queued` job is canceled by removing it from its Redis list and setting both rows terminal — no worker ever picks it up.

---

## See also

- [`./scan-service.md`](./scan-service.md) — the `ScanService` facade that enqueues here and reads `scan_runs` back.
- [`./worker.md`](./worker.md) — the `ScanWorker` dequeue loop, lease heartbeat, and engine hand-off.
- [`../tenancy/data-model.md`](../tenancy/data-model.md) — `scan_runs` / `ScanRecord` columns, `org_id` / `project_id` FKs, and the tenant model that drives §8 fairness.
- [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — canonical `ScanStatus`, IDs, `ScanSpec` / `ScanRecord` shapes (§5), and the one-engine principle this queue protects.
