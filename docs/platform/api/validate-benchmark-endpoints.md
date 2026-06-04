# `POST /v1/validate` and `POST /v1/benchmark`

> Team A. Two endpoints on the public REST API that bracket a scan: `validate` is the cheap **pre-flight** ("can ROGUE even reach this target, and what can it do?"), and `benchmark` is the standardized **yardstick** ("how does this target score against a known dataset?"). Both are thin clients of the one engine — they call `ScanEngine.validate` and `ScanEngine.benchmark` (see [../orchestration/scan-engine-adapter.md](../orchestration/scan-engine-adapter.md)), never a scanning path of their own. This doc specifies the HTTP contract; it does not redefine `TargetSpec`, `ValidationResult`, `BenchmarkReport`, the ID scheme, or the error envelope — those are frozen in [../ARCHITECTURE.md](../ARCHITECTURE.md) §4–§5, and this doc cites the engine code that produces each shape.

Read first: [./overview.md](./overview.md) for the API surface, versioning, and error envelope; [./scans-endpoints.md](./scans-endpoints.md) for the async-job pattern `benchmark` reuses; [./auth-and-keys.md](./auth-and-keys.md) for the key auth and tenant scoping both endpoints inherit; [../benchmark/api-and-datasets.md](../benchmark/api-and-datasets.md) for dataset definitions and scoring, which this doc defers to.

---

## 1. Shared contract — auth, tenancy, target

Both endpoints sit behind the same gate as `/v1/scans`. Every request carries an API key (`rk_live_<rand>` / `rk_test_<rand>`, of which only a SHA-256 is stored — [../ARCHITECTURE.md](../ARCHITECTURE.md) §5), resolves to an `org_<ulid>` + `proj_<ulid>`, and is rejected with the standard envelope on failure. The mechanics — header name, key lookup, the `401 unauthenticated` / `403 forbidden` / `429 rate_limited` envelopes — live in [./auth-and-keys.md](./auth-and-keys.md) and are not repeated here.

Both bodies embed a `TargetSpec` (`{ endpoint, provider, model, api_key_ref, system_prompt }`, [../ARCHITECTURE.md](../ARCHITECTURE.md) §5). The `api_key_ref` is a Vault/KMS handle resolved by Team C at execution time, **never** a raw provider secret on the wire — the same rule scans follow. A request that inlines a raw key instead of a ref is a `400 invalid_request`.

Both route through `ScanEngine` (the `validate` / `benchmark` methods declared in [../ARCHITECTURE.md](../ARCHITECTURE.md) §4), so a target that validates here is the same target a scan will exercise — the "one engine" invariant holds across all three operations.

---

## 2. `POST /v1/validate` — synchronous pre-flight

This is the **spend-nothing, fail-fast** check a caller runs before committing to a scan. It is the only synchronous mutation-shaped endpoint in the API: one tiny model call, no job, no polling. The SDK exposes the same operation as `Client.validate` (`src/rogue/client.py:103`), and `ScanEngine.validate` is a thin async wrapper over the identical logic in `Client._validate_async` (`src/rogue/client.py:110`).

### Request

```http
POST /v1/validate
Authorization: Bearer rk_live_…
Content-Type: application/json
```
```json
{
  "endpoint": "https://api.openai.com/v1",
  "provider": "openai",
  "model": "gpt-4o-mini",
  "api_key_ref": "vault://org_01.../openai-prod",
  "system_prompt": "You are Acme's support assistant."
}
```

The body **is** a `TargetSpec` (no envelope around it — unlike `ScanSpec`, validate takes the target directly). `endpoint` or `provider` must pin a reachable base URL; `model` is required so the engine knows what to invoke.

### Response — `200 OK`, a `ValidationResult`

The exact shape is the `ValidationResult` dataclass at `src/rogue/report.py:192`, serialized via its `to_dict` (`asdict` at `src/rogue/report.py:226`) with the `ok` property surfaced explicitly:

```json
{
  "target": "https://api.openai.com/v1",
  "reachable": true,
  "authenticated": true,
  "model_responds": true,
  "supports_image": true,
  "supports_audio": false,
  "error": null,
  "ok": true
}
```

Field semantics follow the engine exactly (`src/rogue/client.py:110`–`138`):

- **`reachable`** — the endpoint answered at all (DNS resolved, TCP/TLS up, an HTTP response came back). A network/DNS/timeout error leaves this `false` (`src/rogue/client.py:126`).
- **`authenticated`** — credentials were accepted. An `AuthenticationError` sets `reachable: true` but `authenticated: false` — we reached it, the key was rejected (`src/rogue/client.py:121`).
- **`model_responds`** — the model returned a completion to the one probe message (`"Reply with the single word OK."`, `src/rogue/client.py:119`). A rate-limit or provider 5xx (`AdapterError`) marks `reachable` + `authenticated` true but leaves `model_responds` false and records the message in `error` (`src/rogue/client.py:123`).
- **`supports_image` / `supports_audio`** — read from `adapter.capabilities()` (`src/rogue/client.py:116`); they reflect declared modality support, gathered even when the probe call later fails, so a caller can plan multimodal packs.
- **`error`** — the failure string when something went wrong, else `null`.
- **`ok`** — the computed `ValidationResult.ok` property (`src/rogue/report.py:204`): `reachable && authenticated && model_responds`. **The single boolean a caller should branch on** before launching a scan. Note modality flags do **not** affect `ok`.

### Error cases

There are two distinct failure layers, and validate keeps them apart:

1. **Request-level failures** → non-2xx with the standard envelope (`{ "error": { "code", "message", "details"? } }`, [../ARCHITECTURE.md](../ARCHITECTURE.md) §5). Bad auth key, malformed JSON, missing `model`, unresolvable `api_key_ref` — these never reach the engine. Example: `400 invalid_request`, `401 unauthenticated`.

2. **Target-level failures** → `200 OK` with a `ValidationResult` that reports the problem in its booleans. This is the design point of the endpoint: a broken target is **not** an API error, it is a successful validation that returns bad news.

   - Bad endpoint (typo'd host, wrong port, target down) → `{ "reachable": false, "authenticated": false, "model_responds": false, "ok": false, "error": "<dns/timeout msg>" }`.
   - Bad key (endpoint fine, credentials rejected) → `{ "reachable": true, "authenticated": false, "model_responds": false, "ok": false, "error": "<auth msg>" }`.
   - Transient (rate-limit, provider 5xx) → `{ "reachable": true, "authenticated": true, "model_responds": false, "ok": false, "error": "<adapter msg>" }` — retryable; distinguishable from a hard auth failure by `authenticated: true`.

Cost: one provider completion of a few tokens, billed to the tenant as a negligible line. The adapter is always closed afterward (`src/rogue/client.py:128` `finally: aclose()`), so validate leaks no connections even on failure.

---

## 3. `POST /v1/benchmark` — async job

Benchmarking runs a known dataset against the target and reports attack-success-rate. Because it issues one target call per goal (up to `max_goals`), it spends real money and takes minutes — so it is an **async job modeled exactly like a scan** ([./scans-endpoints.md](./scans-endpoints.md)): submit returns `202` with an ID, the caller polls for completion. The engine entry point is `ScanEngine.benchmark` ([../ARCHITECTURE.md](../ARCHITECTURE.md) §4), a thin wrapper over `run_benchmark` (`src/rogue/benchmark.py:90`), which itself calls the one `run_scan` (`src/rogue/benchmark.py:111`) — no separate execution path.

### Two benchmark engines — what the API exposes

There are two ways to benchmark a target in this codebase, and **the API self-serve endpoint exposes only the first**:

- **Single-turn SDK benchmark** (`run_benchmark`, `src/rogue/benchmark.py:90`) — each dataset goal is turned into one primitive (`goal_primitive`) and run through `run_scan` with `n_trials=1`. Fast, cheap, deterministic, and the same path the SDK's `Client.benchmark` uses. **This is what `/v1/benchmark` runs.**
- **Repertoire-ladder benchmark** (`scripts/benchmark_run.py`) — replays ROGUE's full graduated escalation ladder (`build_escalation_context` + `run_escalation_ladder_one`, `scripts/benchmark_run.py:81`) per goal. Far more expensive, research-grade, and operator-run; it is **not** wired to the public API. Its `winner_rank` (`scripts/benchmark_run.py:143`) is the field that the single-turn report leaves `null`.

Dataset contents, goal loading, and how ASR maps to the leaderboard are owned by Team E — defer to [../benchmark/api-and-datasets.md](../benchmark/api-and-datasets.md) and `../benchmark/scoring-and-trends.md`. This doc only specifies the HTTP envelope.

### Request

```http
POST /v1/benchmark
Authorization: Bearer rk_live_…
```
```json
{
  "target": { "endpoint": "https://api.openai.com/v1", "provider": "openai", "model": "gpt-4o-mini", "api_key_ref": "vault://org_01.../openai-prod" },
  "dataset": "advbench_100",
  "max_goals": 25
}
```

- **`target`** — a `TargetSpec` (here nested under `target`, mirroring `ScanSpec`, unlike validate's bare body).
- **`dataset`** — one of `VALID_DATASETS` (`"advbench_100" | "jbb_100"`, `src/rogue/benchmark.py:32`) or a tenant `custom` set defined per [../benchmark/api-and-datasets.md](../benchmark/api-and-datasets.md). An unknown value is rejected: `run_benchmark` raises `ValueError` (`src/rogue/benchmark.py:41`), which the API maps to `400 invalid_request` **at submit time**, before queueing — a bad dataset should never cost a job slot.
- **`max_goals`** — cap on goals run (engine default `25`, `src/rogue/benchmark.py:93`). The API SHOULD clamp this to a tenant-tier ceiling and reflect the effective value in the report's `n_goals`.

### Response — `202 Accepted`

```json
{ "benchmark_id": "bench_01J9...", "status": "queued" }
```

`benchmark_id` follows the platform ULID convention (`bench_<ulid>`, the family established by `scan_<ulid>` / `rep_<ulid>` in [../ARCHITECTURE.md](../ARCHITECTURE.md) §5). `status` reuses the one `ScanStatus` enum: `queued | running | completed | failed | canceled`. No new status vocabulary.

### Polling — `GET /v1/benchmark/{benchmark_id}`

Same lifecycle as `GET /v1/scans/{id}`. While running, returns the status row (status + progress). On `completed`, embeds the `BenchmarkReport`. Tenant-scoped: a `benchmark_id` belonging to another org is `404 not_found` (not `403`), per the scans-endpoints isolation rule.

```json
{
  "benchmark_id": "bench_01J9...",
  "status": "completed",
  "report": {
    "dataset": "advbench_100",
    "target": "https://api.openai.com/v1",
    "n_goals": 25,
    "n_success": 9,
    "cost_usd": 0.4127,
    "winner_rank": null,
    "asr": 0.36,
    "cost_per_success": 0.04586
  }
}
```

The `report` body is the `BenchmarkReport` dataclass (`src/rogue/report.py:235`) serialized via its `to_dict` (`src/rogue/report.py:268`). Two of its fields are **computed properties surfaced into the JSON**, not stored columns:

- **`asr`** = `n_success / n_goals` (`src/rogue/report.py:246`), rounded to 4 dp in `to_dict` (`src/rogue/report.py:270`). The headline number.
- **`cost_per_success`** = `cost_usd / n_success`, or `null` when `n_success == 0` (`src/rogue/report.py:250`). The unit-economics number — how much it cost to land one breach.
- **`winner_rank`** — always `null` from this endpoint (the single-turn engine does not rank against the field; only the ladder runner populates it, §3 above).
- **`n_goals` / `n_success` / `cost_usd`** — primitives straight off `run_benchmark`'s construction (`src/rogue/benchmark.py:121`–`127`): `n_success` is the underlying `ScanReport.n_breaches`, and `cost_usd` is the report's target-call cost.

`failed` jobs return the standard `error` envelope shape inside the row (e.g. a target that went unreachable mid-run), consistent with failed scans.

### Worked example

A tenant wants to know how `gpt-4o-mini` behaves under AdvBench before trusting it in production:

1. `POST /v1/validate` with the `TargetSpec` → `200 { "ok": true, ... }`. Green light, spent ~nothing.
2. `POST /v1/benchmark` `{ target, "dataset": "advbench_100", "max_goals": 25 }` → `202 { "benchmark_id": "bench_…", "status": "queued" }`.
3. Poll `GET /v1/benchmark/bench_…` every few seconds → `running` (progress climbs) → `completed`.
4. Read the report: `asr: 0.36` (9 of 25 AdvBench goals breached single-turn), `cost_per_success: $0.0459`. The tenant now has a standardized, comparable risk number — and, via `dataset`, a number that means the same thing across every target they benchmark.

---

## 4. Why two endpoints, not one scan flag

`validate` and `benchmark` are deliberately separate from `/v1/scans` rather than scan modes:

- **`validate` is synchronous and free-ish** because it must answer *before* a caller is willing to wait or pay — folding it into the async scan queue would defeat its purpose. It is the only endpoint that returns target trouble as a `200` body rather than an error, because "your target is down" is a useful answer, not an API fault.
- **`benchmark` is a job** because it is as expensive as a scan, but its *result shape* is fundamentally different — an ASR + cost-per-success against a fixed dataset, not a findings list with a `score`. Forcing it through the `ScanRecord` shape ([../ARCHITECTURE.md](../ARCHITECTURE.md) §5) would mean a misleading `top_attack` / `n_breaches` framing for what is really a standardized leaderboard measurement.

Both still obey the single invariant from [../ARCHITECTURE.md](../ARCHITECTURE.md) §2: there is exactly one engine. `validate` and `benchmark` are surfaces over `ScanEngine.validate` / `ScanEngine.benchmark`, and the engine code they sit on (`src/rogue/client.py:110`, `src/rogue/benchmark.py:90`) is the same code the SDK and MCP call. If this endpoint and the SDK ever disagree about a target, the platform has failed.
