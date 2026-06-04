# ScanService — the single entry every surface calls

> Team B, Scan Orchestration. This doc specs `ScanService`, the one façade the SDK, the public API ([../api/scans-endpoints.md](../api/scans-endpoints.md)), MCP ([../integrations/mcp.md](../integrations/mcp.md)), and the dashboard all call to start, read, cancel, and list scans. It is the box labelled *Scan Orchestrator* in [../ARCHITECTURE.md](../ARCHITECTURE.md) §2, sitting above `ScanEngine` and in front of the queue. It owns the `scan_runs` lifecycle and nothing below it. The contract here is the one frozen in [../ARCHITECTURE.md](../ARCHITECTURE.md) §4 — this doc elaborates it, it does not redefine it.

Status: design spec, not yet built. The engine it wraps (`rogue.scan.run_scan`, `src/rogue/scan.py:24`) ships today; `ScanService`, the queue ([./job-queue.md](./job-queue.md)), the worker ([./worker.md](./worker.md)), and the engine adapter ([./scan-engine-adapter.md](./scan-engine-adapter.md)) are the layers being added in Week 1 of the [../ARCHITECTURE.md](../ARCHITECTURE.md) §7 roadmap.

## 1. Responsibility — and the one rule

`ScanService` is the *control plane* for a scan: it validates a request, persists intent, enqueues work, and reads status back. It is emphatically **not** the *data plane* — it never fires an attack, never calls a customer model, never runs `ScanEngine.run`. That happens in [./worker.md](./worker.md), out of band.

The load-bearing rule, stated once in [../ARCHITECTURE.md](../ARCHITECTURE.md) §4 and §7 and enforced here: **NEVER run a scan in the request thread.** `create_scan` does a row insert plus a queue push and returns — on the order of single-digit milliseconds — with a `ScanRecord` in `status=queued`. A full default-pack scan is dozens of customer-model round-trips plus judge calls (the `for prim in primitives` loop at `src/rogue/scan.py:57`); that work belongs to a worker process draining the queue, never to the HTTP handler that accepted `POST /v1/scans`. If `create_scan` ever blocks on `run_scan`, the architecture has failed exactly the way [../ARCHITECTURE.md](../ARCHITECTURE.md) §2 warns against.

## 2. Where it lives

```
src/rogue/platform/
  scan_service.py      ← ScanService (this doc)
  scan_engine.py       ← ScanEngine wrapper            (./scan-engine-adapter.md)
  queue.py             ← JobQueue protocol + Redis impl (./job-queue.md)
  worker.py            ← ScanWorker drain loop          (./worker.md)
```

`src/rogue/platform/` is a new package — the platform layer above the existing engine. It depends *downward* on `rogue.scan`, `rogue.packs`, `rogue.schemas`, and `rogue.db.models`, and is depended on *upward* by `src/rogue/api/main.py` (Team A) and the SDK. Nothing in `src/rogue/scan.py` or `src/rogue/reproduce/` imports back up into `platform/`; the dependency arrow points one way, matching the §2 diagram.

## 3. The contract (verbatim from [../ARCHITECTURE.md](../ARCHITECTURE.md) §4)

```python
class ScanService:
    async def create_scan(self, spec: ScanSpec, *, org_id: str, project_id: str, actor: str) -> ScanRecord: ...
    async def get_scan(self, scan_id: str, *, org_id: str) -> ScanRecord: ...
    async def cancel_scan(self, scan_id: str, *, org_id: str) -> ScanRecord: ...
    async def list_scans(self, *, org_id: str, project_id: str | None = None, limit: int = 50) -> list[ScanRecord]: ...
```

Every method takes `org_id` and enforces it (§6). All four are `async` — they touch Postgres (`scan_runs`), Redis (queue + live progress), and the secrets layer, never CPU-bound work. `ScanSpec`, `TargetSpec`, `ScanRecord`, and the `ScanStatus` enum are the canonical types from [../ARCHITECTURE.md](../ARCHITECTURE.md) §5; this service constructs `ScanRecord`s and consumes `ScanSpec`s but defines none of them. `actor` (the API key id or user id that initiated the scan) is recorded for audit and is not part of the read shape.

## 4. `create_scan` — validate → persist → enqueue → return

The whole method is four steps, in order, and returns in milliseconds.

**Step 1 — validate the `ScanSpec` *before* anything is persisted or enqueued.** A bad `TargetSpec` must be rejected synchronously so the caller gets a `400`-class error, not a scan that fails in a worker minutes later. Reject before enqueue when: neither `target.endpoint` nor `target.provider` is set (the SDK's own constructor enforces exactly this at `src/rogue/client.py:79–80` — `"Client needs either endpoint=... or provider=..."` — and the service mirrors it); `provider` is set but unknown to `rogue.adapters.registry`; `pack` is not a known pack name (`load_pack` would `KeyError`); `attacks` names that filter to zero primitives; `max_tests`, `n_trials`, or `budget` out of range. `api_key_ref` is validated as a *handle* — that it resolves in the secrets layer (Team C, [../tenancy/secrets.md](../tenancy/secrets.md)) — never as a raw secret; per [../ARCHITECTURE.md](../ARCHITECTURE.md) §5 the raw key never reaches this service. Validation failures raise a typed error that Team A maps to the §5 error envelope (`{"error": {"code", "message", "details"}}`); they leave no `scan_runs` row behind.

**Step 2 — persist a `scan_runs` row in `status=queued`.** Mint `scan_id = "scan_" + ulid()` ([../ARCHITECTURE.md](../ARCHITECTURE.md) §5 ID grammar), insert one row scoped to `org_id`/`project_id` with `actor`, `created_at`, the resolved spec, and `status=queued`, `progress=0`, all counters null. This row is the durable record of intent and the thing `get_scan`/`list_scans` read. Schema, columns, indexes, and the `0022+` migration are owned by [../tenancy/data-model.md](../tenancy/data-model.md) (the latest shipped migration is `0021_add_benchmark_runs.py`; `scan_runs` lands next). `ScanService` is the *only* writer that creates these rows and the *only* writer that sets `queued`.

**Step 3 — enqueue a job.** Push a job (`scan_id`, `org_id`, the resolved spec, `idempotency_key` if any) onto the queue via the `JobQueue` interface from [./job-queue.md](./job-queue.md). The insert (step 2) and the enqueue (step 3) must not drift: if the enqueue fails, the row is left `queued` and a reconciler/visibility-timeout re-enqueues it — the queue is the at-least-once delivery layer, so the worker tolerates a redelivered job (idempotent transition `queued→running`, §7). We never enqueue *before* the row exists, so a worker can never dequeue a `scan_id` it can't find.

**Step 4 — return the `ScanRecord`.** Build it from the row just written: `status=queued`, `progress=0`. The caller now has a `scan_id` to poll. No engine has run.

### Validation rules (step 1, in full)

These are the checks `create_scan` runs synchronously; each maps to a stable error `code` in the [../ARCHITECTURE.md](../ARCHITECTURE.md) §5 envelope so callers can branch on it.

| Condition | `error.code` | Notes |
|---|---|---|
| Neither `target.endpoint` nor `target.provider` set | `invalid_target` | Mirrors `src/rogue/client.py:79–80`. |
| `provider` set but not in `rogue.adapters.registry` | `unknown_provider` | `details.known` lists supported providers. |
| `pack` not a known pack name | `unknown_pack` | `load_pack(pack)` would `KeyError`; known packs are `default`/`aggressive`/`compliance` ([../ARCHITECTURE.md](../ARCHITECTURE.md) §3). |
| `attacks` filters to zero primitives | `empty_attack_set` | `filter_attacks(load_pack(pack), attacks)` (`src/rogue/client.py:161`) returns `[]`. |
| `max_tests` ≤ 0 or above the org's per-scan cap | `invalid_max_tests` | Cap is a tenant policy ([../tenancy/data-model.md](../tenancy/data-model.md)). |
| `n_trials` ≤ 0 or above cap | `invalid_n_trials` | More trials = more cost; capped. |
| `budget` ≤ 0 (when set) | `invalid_budget` | `budget` is the USD stop in `run_scan` (`src/rogue/scan.py:38`). |
| `api_key_ref` does not resolve in the secrets layer | `unresolvable_key_ref` | Handle is checked for existence, not dereferenced here. |

Validation is pure and side-effect-free: no DB row, no queue push, no secret dereference. The service never *holds* a raw target credential — it only confirms the `api_key_ref` handle resolves; the worker dereferences it at run time inside the engine adapter ([./scan-engine-adapter.md](./scan-engine-adapter.md)).

### Idempotency

`create_scan` accepts an `Idempotency-Key` (threaded from the `POST /v1/scans` header by Team A, see [../api/scans-endpoints.md](../api/scans-endpoints.md)). The key is stored on the `scan_runs` row under a unique constraint scoped to `(org_id, idempotency_key)`. On a replay with the same key, `create_scan` short-circuits *before* step 2 and returns the existing `ScanRecord` for the already-minted `scan_id` — same scan, no second row, no second enqueue. This makes client retries (network blip after the row was written but before the response landed) safe: one key maps to exactly one `scan_id` forever. Keys are scoped per org so two tenants' keys can never collide or cross-resolve.

## 5. `get_scan` — row + live progress

`get_scan` answers `GET /v1/scans/{id}` ([../api/scans-endpoints.md](../api/scans-endpoints.md)). It reads the `scan_runs` row scoped to `org_id`, then **merges live progress from Redis**. The durable row is authoritative for `status` and the final counters; while a scan is `running`, the worker writes a fast-moving heartbeat to a Redis key (`scan:progress:{scan_id}` → `progress`, `n_completed`, running `n_breaches`, `top_attack` so far) on every trial, far more often than it would touch Postgres. `get_scan` overlays that heartbeat onto the row so a polling dashboard sees a smoothly climbing `progress: 0–100` instead of stepping only at terminal write. The Redis overlay is *advisory*: if the key is absent (worker hasn't started, or scan already terminal) the row's persisted values stand. On a terminal `status` (`completed`/`failed`/`canceled`) the row alone is returned and the Redis key is irrelevant (and TTL'd away by the worker). The `ScanRecord` shape returned is exactly [../ARCHITECTURE.md](../ARCHITECTURE.md) §5: `score` and `report_id` are populated only once terminal (`report_id = "rep_" + ulid()`, set by the worker after [../reports/report-service.md](../reports/report-service.md) persists the report).

## 6. Tenant scoping — every method, no exceptions

Every method signature carries `org_id`, and every read/write is filtered by it. `get_scan(scan_id, *, org_id)` is `WHERE scan_id = :scan_id AND org_id = :org_id` — a `scan_id` belonging to another org returns *not found*, never the row (no existence oracle, no cross-tenant read). `list_scans` is `WHERE org_id = :org_id` with the optional `project_id` narrowing, `ORDER BY created_at DESC LIMIT :limit`. `cancel_scan` checks `org_id` before transitioning. The service treats `org_id` as already-authenticated — Team A's key-auth middleware ([../api/auth-and-keys.md](../api/auth-and-keys.md)) resolves `rk_live_*`/`rk_test_*` to an `org_<ulid>` and passes it in; `ScanService` trusts that boundary and enforces the filter unconditionally. The hard-coded single-tenant `acme` of the current `src/rogue/api/main.py` is gone the moment this service is the entry point (kills the §7 Week-2 tech debt). RBAC (who within an org may scan/cancel) is layered above by [../tenancy/isolation-and-rbac.md](../tenancy/isolation-and-rbac.md); `ScanService` enforces the org *boundary*, not intra-org roles.

## 7. The `scan_runs` lifecycle this service owns

```
            create_scan                worker picks up            run_scan returns
   (none) ───────────────▶ queued ───────────────────▶ running ──────────────────▶ completed
                              │                            │                            
                              │ cancel_scan                │ run_scan raises            
                              │ (before pickup)            ▼                            
                              ▼                          failed                         
                           canceled ◀─── cancel_scan (cooperative, while running) ──────┘
```

`ScanStatus` is the single enum from [../ARCHITECTURE.md](../ARCHITECTURE.md) §5: `queued | running | completed | failed | canceled`. Who transitions each:

- **`→ queued`** — `ScanService.create_scan`, and only it (§4 step 2).
- **`queued → running`** — the worker on pickup ([./worker.md](./worker.md)); idempotent so a redelivered job (§4 step 3) is a no-op if already `running`.
- **`running → completed`** — the worker when `run_scan` returns a `ScanReport`; it writes `n_tests`, `n_breaches`, `cost_usd` from the report (`ScanReport`, `src/rogue/report.py:75`), the Team-F `score`, and `report_id`.
- **`running → failed`** — the worker when `run_scan` raises (adapter/auth/budget error); it writes the `error` string.
- **`→ canceled`** — `ScanService.cancel_scan` (§8), from either `queued` or `running`.

`ScanService` writes the `queued` and `canceled` transitions; the worker writes `running`/`completed`/`failed`. Terminal states (`completed`/`failed`/`canceled`) are absorbing — no transition leaves them.

### `ScanRecord` field population across the lifecycle

The §5 [../ARCHITECTURE.md](../ARCHITECTURE.md) `ScanRecord` shape is filled progressively; this table is the contract for what is set when, so the dashboard ([../dashboard/live-scan-ux.md](../dashboard/live-scan-ux.md)) and API ([../api/scans-endpoints.md](../api/scans-endpoints.md)) know which fields to expect null.

| Field | Set at `queued` | During `running` | At terminal |
|---|---|---|---|
| `scan_id`, `org_id`, `project_id` | yes (create) | — | — |
| `status` | `queued` | `running` | `completed`/`failed`/`canceled` |
| `progress` (0–100) | `0` | Redis overlay, climbing | `100` (completed) or last value |
| `n_tests` | resolved spec cap | — | final from `ScanReport.n_tests` |
| `n_completed` | `0` | Redis overlay | final count |
| `n_breaches` | null | running tally (advisory) | `ScanReport.n_breaches` |
| `top_attack` | null | best-so-far (advisory) | `ScanReport.top_attack` (`src/rogue/report.py:103`) |
| `score` (0–100) | null | null | Team F formula over findings |
| `cost_usd` | null | null | `ScanReport.cost_usd` (target-call cost; `src/rogue/scan.py:39`) |
| `report_id` | null | null | `rep_<ulid>` once report persisted |
| `error` | null | null | set only on `failed` |
| `created_at` | yes | — | — |
| `started_at` | null | set on `queued → running` | — |
| `completed_at` | null | null | set on terminal transition |

The `running`-column "advisory" values come from the Redis overlay (§5) and are absent in `list_scans` results (§8); the terminal column is the persisted source of truth.

## 8. `cancel_scan` and `list_scans`

**`cancel_scan(scan_id, *, org_id)`** — org-scoped lookup, then: if `queued`, mark `canceled` and tombstone the queued job so the worker skips it on pickup (cheap, no engine ever ran). If `running`, set a cancel flag (a Redis key `scan:cancel:{scan_id}` the worker checks between trials) and mark the row `canceling`/`canceled` cooperatively — the in-flight trial finishes, the worker sees the flag at the top of the next `for prim in primitives` iteration (`src/rogue/scan.py:57`) and stops, writing `canceled` with partial counters. If already terminal, `cancel_scan` is a no-op returning the existing `ScanRecord` (idempotent). Cancellation is cooperative because `run_scan` is a long loop, not a killable subprocess; we never hard-kill mid customer-model call.

**`list_scans(*, org_id, project_id=None, limit=50)`** — the dashboard's and `GET /v1/scans`' backing query: org-scoped, optional project filter, newest first, capped at `limit`. Returns lightweight `ScanRecord`s straight from `scan_runs` (no Redis overlay — list views show last-persisted state, not live heartbeats; live progress is a per-scan concern handled by `get_scan`).

## 9. Refactoring the SDK `Client.scan` for hosted mode

Today `Client.scan` (`src/rogue/client.py:142`) runs the scan *in-process*: it `load_pack`s, `filter_attacks`, and `asyncio.run(run_scan(...))` synchronously (`src/rogue/client.py:158–172`), blocking until the `ScanReport` is built. That is the local/single-machine path and stays the default — it is the §2 promise that the same engine runs everywhere, just co-located.

Hosted mode adds an *optional* branch: a `Client` constructed against the ROGUE platform (e.g. `Client(hosted=True, api_key="rk_live_…")`, exact ctor signature owned by the SDK doc) routes `scan()` through `POST /v1/scans` instead of `run_scan`. In hosted mode `scan()` builds a `ScanSpec` from the same args it takes today (`attacks`, `max_tests`, `budget`, `pack`, `n_trials` → `ScanSpec`; the ctor's `endpoint`/`provider`/`model`/`system_prompt` → `TargetSpec`), calls the API, and either polls `GET /v1/scans/{id}` to completion (blocking façade, returns a `ScanReport` reconstructed from the persisted report — preserving today's return type) or returns the `ScanRecord` for async callers. The `api_key` becomes an `api_key_ref` handle on the way in: the SDK hands the target credential to the secrets layer, never inlines it into the `ScanSpec` ([../tenancy/secrets.md](../tenancy/secrets.md), [../ARCHITECTURE.md](../ARCHITECTURE.md) §5). Crucially, hosted `scan()` does **not** import `rogue.scan` — it is a pure HTTP client of `ScanService` via Team A's API, so the same scan runs in the hosted worker, satisfying §2's "one engine" invariant. The local and hosted paths converge on identical engine behavior because both ultimately reach `run_scan`; only *where* it runs differs.

## 10. Sequence — create → queue → worker → done

```
SDK/API          ScanService           Postgres            JobQueue            ScanWorker          ScanEngine
  │                   │                 (scan_runs)         (Redis)               │              (run_scan)
  │  create_scan(spec)│                     │                  │                  │                  │
  │──────────────────▶│                     │                  │                  │                  │
  │                   │ validate spec       │                  │                  │                  │
  │                   │ (reject if bad ◀─── 400, no row)        │                  │                  │
  │                   │ INSERT status=queued│                  │                  │                  │
  │                   │────────────────────▶│                  │                  │                  │
  │                   │ enqueue(scan_id)    │                  │                  │                  │
  │                   │───────────────────────────────────────▶│                  │                  │
  │  ScanRecord(queued)│ (returns in ms)    │                  │                  │                  │
  │◀──────────────────│                     │                  │                  │                  │
  │                   │                     │                  │  dequeue         │                  │
  │                   │                     │                  │◀─────────────────│                  │
  │                   │                     │  UPDATE running   │                  │                  │
  │                   │                     │◀─────────────────────────────────────│                  │
  │                   │                     │                  │  heartbeat       │   run(target,…)  │
  │                   │                     │                  │◀────progress─────│─────────────────▶│
  │  get_scan(id)     │                     │                  │   (per trial)    │   ScanReport     │
  │──────────────────▶│ read row + overlay  │                  │                  │◀─────────────────│
  │  ScanRecord(running, progress=N) ◀──────│◀─────────────────┤                  │                  │
  │◀──────────────────│                     │                  │  UPDATE completed│                  │
  │                   │                     │◀─────────────────────────────────────│ (+report_id,score)
  │  get_scan(id)     │                     │                  │                  │                  │
  │──────────────────▶│ read row (terminal) │                  │                  │                  │
  │  ScanRecord(completed, report_id) ◀─────│                  │                  │                  │
```

The customer never blocks on the engine: `create_scan` returns at the third row of the diagram; everything below it is the worker draining the queue out of band, exactly as [../ARCHITECTURE.md](../ARCHITECTURE.md) §2 and §7 require.

## 11. Concurrency, races, and failure modes

The control plane is small but the seams between Postgres, Redis, and the queue have to be reasoned about explicitly, because the §1 rule means state lives in three places at once.

- **Row-then-enqueue ordering.** The row insert (§4 step 2) commits before the enqueue (§4 step 3). The window between them is the only place a `scan_runs` row can be `queued` with no live job; a reconciler (the worker's responsibility, [./worker.md](./worker.md)) re-enqueues any row stuck in `queued` past a grace period. The reverse window — a job for a non-existent row — is structurally impossible, which is why the order is fixed.
- **At-least-once delivery.** The queue is at-least-once, so the same `scan_id` can be delivered twice (e.g. worker crash after `running` before ack). The `queued → running` transition is a conditional update (`UPDATE … SET status='running' WHERE scan_id=:id AND status='queued'`) so the second delivery's update affects zero rows and the worker drops the duplicate. This is why §7 calls the pickup transition idempotent.
- **Cancel ↔ completion race.** `cancel_scan` on a `running` scan and the worker's `running → completed` write can race. The worker's terminal write is also conditional (`WHERE status='running'`); if `cancel_scan` already moved the row to `canceled`, the worker's `completed` write affects zero rows and the worker discards the report. Terminal states are absorbing (§7), so whichever conditional update lands first wins and the loser is a no-op — never a flip-flop.
- **Redis as advisory only.** Progress heartbeats and the cancel flag live in Redis, which can be lost (eviction, restart). Loss degrades gracefully: a missing progress key means `get_scan` falls back to the row (§5); a missing cancel flag means a cancel may not take effect until the worker re-reads the row's `canceled` status at the next trial boundary. Correctness lives in Postgres; Redis only makes the experience smoother.
- **Stuck `running` scans.** A worker that dies mid-scan leaves the row `running` with a stale Redis heartbeat (TTL'd) and an unacked queue job. The queue's visibility timeout redelivers the job; the conditional `queued → running` will *not* match (row is already `running`), so reconciliation here is by a watchdog that fails or re-queues rows whose heartbeat has gone silent past a threshold — owned by [./worker.md](./worker.md), surfaced to the customer as `failed` with an `error` of `worker_lost`.

## 12. Out of scope (owned elsewhere)

- Queue mechanics, delivery guarantees, visibility timeout, dead-letter — [./job-queue.md](./job-queue.md).
- The drain loop, heartbeat cadence, cancel-flag polling, retry-on-crash — [./worker.md](./worker.md).
- Building `DeploymentConfig` from `TargetSpec`, wiring `run_scan`, progress callback — [./scan-engine-adapter.md](./scan-engine-adapter.md).
- HTTP surface, status codes, error-envelope mapping, `Idempotency-Key` header parsing — [../api/scans-endpoints.md](../api/scans-endpoints.md).
- `scan_runs` columns/indexes/migration, org/project FKs, key→org resolution — [../tenancy/data-model.md](../tenancy/data-model.md).
- The `score` formula and `report_id` artifact — Team F ([../ARCHITECTURE.md](../ARCHITECTURE.md) §5).
