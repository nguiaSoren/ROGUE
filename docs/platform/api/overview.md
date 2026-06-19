# Public API — Team A Overview

> The design principles for ROGUE's public REST API. Team A builds this **on top of the existing FastAPI app** — it does not stand up a new service, and it adds **no scan logic**. Every endpoint is a thin shell over `ScanService` / `ReportService` (the contracts in [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §4). If a request handler ever computes a breach, renders a payload, or talks to a customer model directly, the layering has been violated — that work belongs to the **one** scan engine, `rogue.scan.run_scan`, reached only through `ScanService`.

Status: **BUILT (local).** The `/v1` surface shipped — routers in `src/rogue/api/v1/` (`scans.py`, `validate_benchmark.py`, `deps.py`), mounted on the live `src/rogue/api/main.py` app. A few details below diverge from this spec and are corrected inline: the create response is a small `{scan_id, status}` ack (not the full `ScanRecord`); `GET /v1/scans` returns `{scans, count}` with `limit`+`status` filtering (no cursor pagination shipped); the report format is a `?format=json|html|pdf` query param (not `Accept`); a report on a non-completed scan is `404 report_not_ready` (not `409`); `validate` is **synchronous** (`200`, straight to `ScanEngine.validate` — it does NOT enqueue); and `benchmark` is async via a dedicated `benchmark_service` polled at `GET /v1/benchmark/{id}`, not via `ScanService`. This doc owns the cross-cutting API conventions; the two detail docs own per-route schemas: scan lifecycle in [`./scans-endpoints.md`](./scans-endpoints.md), validate + benchmark in [`./validate-benchmark-endpoints.md`](./validate-benchmark-endpoints.md), and auth + keys in [`./auth-and-keys.md`](./auth-and-keys.md).

## 1. What exists today — the app we extend

The deployed app is `src/rogue/api/main.py`. Three facts about it shape everything Team A does:

- The `app` object is constructed around `src/rogue/api/main.py:192` as a `FastAPI` instance titled *"ROGUE Dashboard API"* (`version="0.1.0"`). Its **legacy** `/api/*` surface is read-only, no-auth, and single-tenant (the dashboard diff still uses `customer_id="acme"`, e.g. `src/rogue/api/main.py:1052`). The `/v1` routers (`app.include_router(_v1_scans.router)` / `_v1_vb.router`, ~`:228-229`) now add the first **authenticated, multi-tenant POST routes** on top of this same app — so the old "zero POST routes / read-only" description applies only to the legacy `/api/*` layer.
- CORS is wide-open: `allow_origins=["*"]` at `src/rogue/api/main.py:203-209`, `allow_credentials=False`. The MCP server is mounted at `/mcp` (`src/rogue/api/main.py:211`) and rides the same app/lifespan; Team A must not disturb that mount.
- It is deployed as `uvicorn rogue.api.main:app` — so whatever is added to this `app` object ships on the existing Render service. There is no second process to deploy (the **worker** is a separate process — see [`../orchestration/worker.md`](../orchestration/worker.md)).

The existing `/api/*` routes (`/api/livez`, `/api/health`, `/api/attacks`, `/api/breaches/matrix`, …) are the **dashboard read layer**. They stay exactly as they are. The public product API is a **parallel surface under `/v1`** on the same `app`. We do not retrofit `/api/*` into `/v1`, and we do not route the dashboard through `/v1`.

## 2. Base URL and versioning

- Production base URL: `https://rogue-private.onrender.com` (the Render service from §1). All public product routes live under the `/v1` prefix: `https://rogue-private.onrender.com/v1/...`.
- `/v1` is the contract boundary. Within `v1` we only make **additive** changes — new optional fields, new endpoints, new enum members are non-breaking and ship without a version bump. A breaking change (removing a field, changing a status meaning, renaming a path) is a new prefix (`/v2`) mounted beside `/v1`; the two coexist until `/v1` is sunset on an announced date. `ScanStatus` and the IDs in [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §5 are part of the `/v1` contract — they cannot change under it.
- The `/api/*` dashboard routes and the `/mcp` mount are **not** versioned and are out of scope for `/v1` guarantees.

## 3. Endpoint catalog

The full public surface. Every row is a thin shell: the handler authenticates + resolves the tenant (Team C, [`../tenancy/isolation-and-rbac.md`](../tenancy/isolation-and-rbac.md)), validates the request body into the canonical schema (§5 of the architecture), calls exactly one `ScanService` / `ReportService` method, and serializes the returned `ScanRecord` / report. No handler contains scan logic.

| Method + path | Purpose | Calls | Sync/async | Detail doc |
|---|---|---|---|---|
| `POST /v1/scans` | Create a scan from a `ScanSpec`; enqueue it. | `ScanService.create_scan(spec, org_id, project_id, idempotency_key)` | **async-job** → `202` `{scan_id, status}` | [`./scans-endpoints.md`](./scans-endpoints.md) |
| `GET /v1/scans/{scan_id}` | Fetch one scan's status/result row. | `ScanService.get_scan(scan_id, org_id)` | `200` (full `ScanRecord`) | [`./scans-endpoints.md`](./scans-endpoints.md) |
| `GET /v1/scans/{scan_id}/report` | Fetch the rendered report. Format via `?format=json\|html\|pdf`. | `ReportService.build_json/html/pdf(scan_id)` | `200` (or `404 report_not_ready` if not `completed`) | [`./scans-endpoints.md`](./scans-endpoints.md) |
| `POST /v1/scans/{scan_id}/cancel` | Request cancellation of a queued/running scan. | `ScanService.cancel_scan(scan_id, org_id)` | `200` (terminal-state aware; `404` if unknown) | [`./scans-endpoints.md`](./scans-endpoints.md) |
| `GET /v1/scans` | List scans for the tenant, newest-first (`limit`, optional `status`/`project_id`). | `ScanService.list_scans(org_id, project_id, limit)` | `200` `{scans, count}` | [`./scans-endpoints.md`](./scans-endpoints.md) |
| `POST /v1/validate` | Reachability/credential check on a target before scanning. | `ScanEngine.validate(spec)` **directly** | **synchronous** → `200` | [`./validate-benchmark-endpoints.md`](./validate-benchmark-endpoints.md) |
| `POST /v1/benchmark` | Run a target against a named dataset; trended score. | `benchmark_service.create(spec, dataset, max_goals, org_id)` | **async-job** → `202` `{benchmark_id, status}` | [`./validate-benchmark-endpoints.md`](./validate-benchmark-endpoints.md) |
| `GET /v1/benchmark/{benchmark_id}` | Poll one benchmark job (embeds `BenchmarkReport` when complete). | `benchmark_service.get(benchmark_id, org_id)` | `200` (or `404`) | [`./validate-benchmark-endpoints.md`](./validate-benchmark-endpoints.md) |

`POST /v1/scans` returns a small `202 {scan_id, status}` acknowledgement (not the full `ScanRecord`) with a `Location: /v1/scans/{id}` header; the client then polls `GET /v1/scans/{id}` for the full record. **`validate` is the one synchronous write — it does NOT enqueue and does NOT go through `ScanService`; it calls `ScanEngine.validate(spec)` directly and returns the `ValidationResult` fields (plus an `ok`) as `200`.** `benchmark` is async but rides a **dedicated `benchmark_service`** (not `ScanService`), polled at its own `GET /v1/benchmark/{id}`. The `score` and report body are produced downstream (the worker computes `score`; [`../reports/report-service.md`](../reports/report-service.md) renders the report); the API only relays them.

## 4. Error envelope and HTTP status mapping

Every non-2xx response uses the single envelope from [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §5, with no other top-level shape:

```json
{ "error": { "code": "scan_not_found", "message": "No scan scan_01J… in this org.", "details": { "scan_id": "scan_01J…" } } }
```

`code` is a stable machine-readable string (clients branch on it; we never repurpose a code). `message` is human-readable and may change. `details` is optional and structured. This replaces FastAPI's default `{"detail": ...}` shape: Team A registers an exception handler on the `app` that converts `HTTPException` and `RequestValidationError` into the envelope, so existing `raise HTTPException(...)` call sites in the dashboard routes are unaffected (they keep `{"detail": ...}`) while every `/v1` route emits the envelope. The standard mapping:

| Status | When | `code` examples |
|---|---|---|
| `400` | malformed body / bad query param | `invalid_request` |
| `401` | missing/invalid API key | `unauthenticated` (see [`./auth-and-keys.md`](./auth-and-keys.md)) |
| `403` | key valid but not entitled to this org/project | `forbidden` |
| `404` | scan/report not found **within the tenant** | `scan_not_found`, `report_not_found` |
| `409` | state conflict (e.g. report requested before `completed`; cancel on terminal scan) | `scan_not_completed`, `scan_not_cancelable` |
| `422` | semantically invalid `ScanSpec` (e.g. neither `endpoint` nor `provider` set) | `invalid_target`, `invalid_spec` |
| `429` | rate / quota limit hit | `rate_limited` (detail in [`./auth-and-keys.md`](./auth-and-keys.md)) |
| `500` | unexpected server error (never leaks internals) | `internal_error` |
| `503` | queue/DB transiently unavailable | `service_unavailable` |

A scan whose **execution** fails is **not** an HTTP error: the job runs, the worker records `status: failed` with a populated `error` field on the `ScanRecord`, and `GET /v1/scans/{id}` returns `200` with that record. HTTP errors describe API-call failures (auth, validation, not-found, conflict); `ScanStatus.failed` describes scan-run failures. Keeping these separate is what lets a client poll one endpoint and always get a `200` until the job reaches a terminal state.

## 5. Async-job pattern (202 + poll)

**Scans and benchmarks** are queued, never run in the request thread — this is the spine principle ([`../ARCHITECTURE.md`](../ARCHITECTURE.md) §2). A `run_scan` call drives many LLM panel + judge round-trips and can take minutes; holding an HTTP worker thread for that would starve the pool and trip the deploy platform's request timeout (the same class of failure the DB-free `/api/livez` probe at `src/rogue/api/main.py:398` was added to avoid). So those write endpoints follow accepted-then-poll. **`validate` is the exception: it is a cheap synchronous pre-flight that returns `200` inline** (one tiny model call, no queue).

1. `POST /v1/scans` folds the flat body into a `ScanSpec`, calls `ScanService.create_scan(...)`, which **enqueues** a job and persists a `ScanRecord` with `status: queued`. The handler returns immediately.
2. Response is **`202 Accepted`**, body is the small ack `{scan_id, status}`, and a `Location: /v1/scans/{scan_id}` header points at the poll endpoint.
3. The client polls `GET /v1/scans/{scan_id}`; `progress` (0–100), `n_completed`, and `status` advance as the worker runs ([`../orchestration/worker.md`](../orchestration/worker.md)). Terminal states are `completed`, `failed`, `canceled`.
4. On `completed`, `report_id` is populated and `GET /v1/scans/{scan_id}/report` returns the rendered report. Requesting the report before `completed` is a **`404 report_not_ready`** (the shipped code uses 404, not 409).

The API layer never blocks on the queue and never opens a streaming connection to the worker. (Live progress UX for the dashboard — SSE/websocket — is Team D's concern, [`../dashboard/live-scan-ux.md`](../dashboard/live-scan-ux.md), and reads the same `ScanRecord.progress`; the public API stays poll-based for simplicity and cacheability.)

## 6. Pagination and idempotency

**Listing (`GET /v1/scans`).** **Cursor pagination was not built.** The shipped endpoint takes `limit` (default `50`, max `200`), an optional `status` filter, and the optional tenant-scoping `project_id`, and returns a simple count-wrapped list, newest-first:

```json
{ "scans": [ /* ScanRecord… newest-first */ ], "count": 12 }
```

There is no `cursor` / `next_cursor`. The handler passes `limit`/`project_id` through to `ScanService.list_scans` and applies the `status` filter in-handler. (Cursor-based keyset pagination remains a clean future addition if list sizes grow.)

**Idempotency.** `POST /v1/scans` accepts an `Idempotency-Key` header, threaded into `ScanService.create_scan(idempotency_key=…)`. A replay with the same `(org_id, key)` returns the **original** record — no second job enqueued. **Shipped caveat:** dedup is a best-effort process-local map in the in-memory service (durable via the `scan_runs.idempotency_key` column in Postgres); there is no same-key-different-body `409` check and no 24h-expiry logic in the shipped service. `validate`/`benchmark` do not take an idempotency key. This still protects against the dangerous case (a timeout on create silently launching two paid scans, given a full reproduce ≈ $35).

## 7. OpenAPI and `/docs`

FastAPI generates the OpenAPI schema from the route signatures and Pydantic models for free; the `/v1` request/response models (`CreateScanRequest`/`ScanSpec`/`TargetSpec`/`ScanRecord`, the `ValidateRequest`/`BenchmarkRequest` bodies) are Pydantic v2 models so they appear in the schema. **Shipped reality:** the schema is the app-wide default at `/openapi.json` with docs at `/docs` and `/redoc` (there is no separate `/v1/openapi.json`). The `/v1` operations carry router-level `tags=["scans"]` and `tags=["validate","benchmark"]`, but the legacy `/api/*` routes are **not** retagged `dashboard-internal`, and the app `title` is still *"ROGUE Dashboard API"* (`version="0.1.0"`) — the title/version retitling and the per-route `operation_id` polish in the original plan were not done.

## 8. Router organization

New write surfaces are added as **FastAPI `APIRouter`s**, one per resource group, mounted onto the existing `app` — not by appending more `@app.post(...)` decorators inline next to the dashboard routes. `src/rogue/api/main.py` currently declares every route directly on `app`; for the public API we introduce a package:

**Shipped layout** (`src/rogue/api/v1/`):

```
src/rogue/api/
  main.py                  # builds `app`, mounts /mcp, includes the v1 routers (the entrypoint)
  v1/
    __init__.py
    scans.py               # APIRouter(prefix="/v1") — POST /scans, GET /scans, GET /scans/{id},
                           #   POST /scans/{id}/cancel, GET /scans/{id}/report
    validate_benchmark.py  # APIRouter(prefix="/v1") — POST /validate, POST /benchmark, GET /benchmark/{id}
    deps.py                # require_principal (auth), get_scan_service / get_report_service /
                           #   get_scan_engine / get_benchmark_service, and a wire(**services) injector
```

There is no `validate.py` / `benchmark.py` / `errors.py` split — `validate` and `benchmark` share `validate_benchmark.py`, and the error envelope is built inline per-handler (a small `_envelope(...)` helper) rather than via app-level exception handlers. `main.py` includes both routers (`app.include_router(_v1_scans.router)` / `_v1_vb.router`) after the CORS middleware and `/mcp` mount. Each handler depends on `require_principal` (auth → `Principal` carrying `org_id`/`project_id`) and pulls the service via `Depends(get_scan_service)` etc., so the services are injectable for tests (`wire(...)` swaps in fakes).

## 9. CORS and rate-limit posture

- **CORS.** The wide-open `allow_origins=["*"]` at `src/rogue/api/main.py:162–169` is correct for the read-only, credential-less dashboard API and for the `/mcp` mount, and it stays. The `/v1` product API is **key-authenticated, not cookie-authenticated** — credentials travel in an `Authorization` header, not a browser cookie — so it does not rely on CORS for security and the existing `*` policy is acceptable for it too (a malicious page cannot read a response it has no API key to authorize in the first place; `allow_credentials` stays `False`, which is what keeps `*` safe). If Team C later issues browser-session cookies for the dashboard's own first-party calls, those calls use the `/api/*` surface or a tightened origin list — not `/v1` — so the public API's CORS stance never needs to narrow.
- **Rate limiting.** *Not built.* The original plan was a per-API-key limiter returning `429 rate_limited`; the shipped `/v1` routers have no rate-limit dependency. If/when added it should key off the resolved principal and use the standard envelope; see [`./auth-and-keys.md`](./auth-and-keys.md) for the intended posture.

## 10. Non-goals for Team A

To keep the "thin shell" boundary from eroding: Team A does **not** implement scan execution, judging, target adapters, the `score` formula, report rendering, the queue, the worker, or the tenancy/secrets layer. Those are Teams B ([`../orchestration/scan-service.md`](../orchestration/scan-service.md), [`../orchestration/scan-engine-adapter.md`](../orchestration/scan-engine-adapter.md)), F ([`../reports/report-service.md`](../reports/report-service.md)), and C ([`../tenancy/data-model.md`](../tenancy/data-model.md), [`../tenancy/secrets.md`](../tenancy/secrets.md)). Team A owns: the `/v1` routers and their request/response Pydantic models, the error envelope + handlers, the async-job HTTP semantics (`202`/poll), pagination, idempotency, OpenAPI presentation, and CORS. Where the API needs a value it does not own (the `score`, a report body, a tenant identity), it asks the owning service for it and relays the result verbatim.
