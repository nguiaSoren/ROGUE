# Public API — Team A Overview

> The design principles for ROGUE's public REST API. Team A builds this **on top of the existing FastAPI app** — it does not stand up a new service, and it adds **no scan logic**. Every endpoint is a thin shell over `ScanService` / `ReportService` (the contracts in [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §4). If a request handler ever computes a breach, renders a payload, or talks to a customer model directly, the layering has been violated — that work belongs to the **one** scan engine, `rogue.scan.run_scan`, reached only through `ScanService`.

Status: **design spec, not yet built.** The app we extend is live today; the `/v1` surface below is Team A's Week-1–3 deliverable. This doc owns the cross-cutting API conventions (versioning, error envelope, async-job pattern, pagination, idempotency, OpenAPI, router organization, CORS). The two detail docs own the per-route request/response schemas: scan lifecycle in [`./scans-endpoints.md`](./scans-endpoints.md), validate + benchmark in [`./validate-benchmark-endpoints.md`](./validate-benchmark-endpoints.md), and auth + keys + rate limiting in [`./auth-and-keys.md`](./auth-and-keys.md).

## 1. What exists today — the app we extend

The deployed app is `src/rogue/api/main.py`. Three facts about it shape everything Team A does:

- The `app` object is constructed at `src/rogue/api/main.py:151` as a `FastAPI` instance titled *"ROGUE Dashboard API"*. It is **read-only** (its own docstring at `:18–20` states "no POST/PUT/DELETE"), **no-auth**, and **single-tenant** (hard-coded `customer_id="acme"`, e.g. `src/rogue/api/main.py:934`). Today it has **zero POST routes** — the `/v1/scans` write surface below is the first POST this codebase will serve.
- CORS is wide-open: `allow_origins=["*"]` at `src/rogue/api/main.py:162–169`, `allow_credentials=False`. The MCP server is mounted at `/mcp` (`src/rogue/api/main.py:170`) and rides the same app/lifespan; Team A must not disturb that mount.
- It is deployed via `docker/backend.Dockerfile:47` as `uvicorn rogue.api.main:app` — so whatever Team A adds to this `app` object ships on the existing Render service. There is no second process to deploy.

The existing `/api/*` routes (`/api/livez`, `/api/health`, `/api/attacks`, `/api/breaches/matrix`, …) are the **dashboard read layer**. They stay exactly as they are. The public product API is a **new, parallel surface under `/v1`** added to the same `app`. We do not retrofit `/api/*` into `/v1`, and we do not route the dashboard through `/v1`; the dashboard keeps its bespoke read endpoints, the public API gets the clean versioned contract.

## 2. Base URL and versioning

- Production base URL: `https://rogue-api-mr5w.onrender.com` (the Render service from §1). All public product routes live under the `/v1` prefix: `https://rogue-api-mr5w.onrender.com/v1/...`.
- `/v1` is the contract boundary. Within `v1` we only make **additive** changes — new optional fields, new endpoints, new enum members are non-breaking and ship without a version bump. A breaking change (removing a field, changing a status meaning, renaming a path) is a new prefix (`/v2`) mounted beside `/v1`; the two coexist until `/v1` is sunset on an announced date. `ScanStatus` and the IDs in [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §5 are part of the `/v1` contract — they cannot change under it.
- The `/api/*` dashboard routes and the `/mcp` mount are **not** versioned and are out of scope for `/v1` guarantees.

## 3. Endpoint catalog

The full public surface. Every row is a thin shell: the handler authenticates + resolves the tenant (Team C, [`../tenancy/isolation-and-rbac.md`](../tenancy/isolation-and-rbac.md)), validates the request body into the canonical schema (§5 of the architecture), calls exactly one `ScanService` / `ReportService` method, and serializes the returned `ScanRecord` / report. No handler contains scan logic.

| Method + path | Purpose | Calls | Sync/async | Detail doc |
|---|---|---|---|---|
| `POST /v1/scans` | Create a scan from a `ScanSpec`; enqueue it. | `ScanService.create_scan(spec, org_id, project_id, actor)` | **async-job** → `202` | [`./scans-endpoints.md`](./scans-endpoints.md) |
| `GET /v1/scans/{scan_id}` | Fetch one scan's status/result row. | `ScanService.get_scan(scan_id, org_id)` | `200` | [`./scans-endpoints.md`](./scans-endpoints.md) |
| `GET /v1/scans/{scan_id}/report` | Fetch the rendered report (JSON; HTML/PDF via `Accept`). | `ReportService.build_json/html/pdf(scan_id)` | `200` (or `409` if not `completed`) | [`./scans-endpoints.md`](./scans-endpoints.md) |
| `POST /v1/scans/{scan_id}/cancel` | Request cancellation of a queued/running scan. | `ScanService.cancel_scan(scan_id, org_id)` | `200` (terminal-state aware) | [`./scans-endpoints.md`](./scans-endpoints.md) |
| `GET /v1/scans` | List scans for the tenant, paginated, newest-first. | `ScanService.list_scans(org_id, project_id, limit)` | `200` | [`./scans-endpoints.md`](./scans-endpoints.md) |
| `POST /v1/validate` | Reachability/credential check on a target before scanning. | `ScanService` → `ScanEngine.validate(target)` | **async-job** → `202` | [`./validate-benchmark-endpoints.md`](./validate-benchmark-endpoints.md) |
| `POST /v1/benchmark` | Run a target against a named dataset; trended score. | `ScanService` → `ScanEngine.benchmark(target, dataset, max_goals)` | **async-job** → `202` | [`./validate-benchmark-endpoints.md`](./validate-benchmark-endpoints.md) |

`POST /v1/scans` returns the freshly-created `ScanRecord` (status `queued`) with HTTP `202`; the other writes (`validate`, `benchmark`) follow the same async-job pattern (§5) — they enqueue work and return a record to poll. `validate` and `benchmark` go through `ScanService` too (so they get the same queue, tenancy, and idempotency), and `ScanService` dispatches them to the matching `ScanEngine` method; see [`../orchestration/scan-service.md`](../orchestration/scan-service.md). The `score` and the report body are owned by Team F ([`../reports/report-service.md`](../reports/report-service.md)); the API only relays them.

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

Scans, validations, and benchmarks are **queued, never run in the request thread** — this is the spine principle ([`../ARCHITECTURE.md`](../ARCHITECTURE.md) §2: `ScanService` "NEVER runs a scan in the request thread"). A `run_scan` call drives many LLM panel + judge round-trips and can take minutes; holding an HTTP worker thread for that would starve the pool and trip the deploy platform's request timeout (the same class of failure the DB-free `/api/livez` probe at `src/rogue/api/main.py:280` was added to avoid). So the write endpoints follow accepted-then-poll:

1. `POST /v1/scans` validates the `ScanSpec`, calls `ScanService.create_scan(...)`, which **enqueues** a job and persists a `ScanRecord` with `status: queued`. The handler returns immediately.
2. Response is **`202 Accepted`**, body is the `ScanRecord` (so the client gets `scan_id` + initial `progress: 0`), and a `Location: /v1/scans/{scan_id}` header points at the poll endpoint.
3. The client polls `GET /v1/scans/{scan_id}`; `progress` (0–100), `n_completed`, and `status` advance as the worker runs ([`../orchestration/worker.md`](../orchestration/worker.md)). Terminal states are `completed`, `failed`, `canceled`.
4. On `completed`, `report_id` is populated and `GET /v1/scans/{scan_id}/report` returns the rendered report. Requesting the report before `completed` is a `409 scan_not_completed`.

The API layer never blocks on the queue and never opens a streaming connection to the worker. (Live progress UX for the dashboard — SSE/websocket — is Team D's concern, [`../dashboard/live-scan-ux.md`](../dashboard/live-scan-ux.md), and reads the same `ScanRecord.progress`; the public API stays poll-based for simplicity and cacheability.)

## 6. Pagination and idempotency

**Pagination (`GET /v1/scans`).** Cursor-based, opaque, stable under inserts. Query params: `limit` (default `50`, max `200`, mirroring `ScanService.list_scans`' `limit`), `cursor` (opaque token; omit for the first page), and the optional tenant-scoping `project_id`. Response wraps the list:

```json
{ "data": [ /* ScanRecord… newest-first */ ], "next_cursor": "eyJ…" | null }
```

`next_cursor` is `null` on the last page. The cursor encodes `(created_at, scan_id)` so ties break deterministically and a scan created mid-pagination never duplicates or skips. The handler passes `limit` through to `ScanService.list_scans` and translates the cursor into the service's offset/keyset args — it adds no filtering logic of its own beyond what the service exposes.

**Idempotency (all POSTs).** Clients may send an `Idempotency-Key: <opaque>` header on `POST /v1/scans`, `/v1/validate`, `/v1/benchmark`. The key is scoped to `(org_id, route)` and stored with the resulting `scan_id`. A replay with the same key + same body returns the **original** `ScanRecord` and a `202` (or `200` if it already advanced) — no second job is enqueued. A replay with the same key but a **different** body is a `409 idempotency_key_reuse`. Keys expire after 24h. This protects against client retries on the `202` path (a timeout on the create call must not silently launch two paid scans, given a full reproduce ≈ $35). Enqueue + idempotency-record write happen in one transaction so a crash can't leave a key without its job.

## 7. OpenAPI and `/docs`

FastAPI generates the OpenAPI schema from the route signatures and Pydantic models for free; the `/v1` request/response models (`ScanSpec`, `TargetSpec`, `ScanRecord`, the error envelope, the paginated list wrapper) are declared as Pydantic v2 models so they appear in the schema with descriptions and examples. The public, versioned schema is served at `/v1/openapi.json` with interactive docs at `/docs` (Swagger) and `/redoc`. We tag every public operation with `tags=["scans"]` / `["validate"]` / `["benchmark"]` so the rendered docs group cleanly, and we set a `summary` + `operation_id` per route (stable `operation_id`s let us generate typed client SDKs). The existing dashboard `/api/*` routes are tagged `["dashboard-internal"]` so the public docs page reads as a product API, not an internal grab-bag. The app `title`/`version` at `src/rogue/api/main.py:151–160` are updated to reflect the platform API (the version string tracks the API contract, distinct from the package version).

## 8. Router organization

New write surfaces are added as **FastAPI `APIRouter`s**, one per resource group, mounted onto the existing `app` — not by appending more `@app.post(...)` decorators inline next to the dashboard routes. `src/rogue/api/main.py` currently declares every route directly on `app`; for the public API we introduce a package:

```
src/rogue/api/
  main.py            # builds `app`, mounts /mcp, includes the v1 routers (this file stays the entrypoint)
  v1/
    __init__.py      # router = APIRouter(prefix="/v1"); error-envelope handlers; auth dependency wiring
    scans.py         # APIRouter — POST /scans, GET /scans, GET /scans/{id}, POST /scans/{id}/cancel, GET /scans/{id}/report
    validate.py      # APIRouter — POST /validate
    benchmark.py     # APIRouter — POST /benchmark
    deps.py          # shared dependencies: get_api_key (Team C), get_scan_service, get_report_service, pagination
    errors.py        # the error envelope + exception handlers registered on the app
```

`main.py` does `from rogue.api.v1 import router as v1_router; app.include_router(v1_router)` after the CORS middleware and the `/mcp` mount, so the deploy command at `docker/backend.Dockerfile:47` (`uvicorn rogue.api.main:app`) is unchanged. Each router declares the shared dependencies (`Depends(get_api_key)`, `Depends(get_scan_service)`) at the router level so every `/v1` route is authenticated and tenant-scoped by construction — there is no unauthenticated public route and no place to forget the check. `ScanService` / `ReportService` are obtained from the dependency layer (not constructed in the handler) so tests can inject fakes and the queue connection is shared.

## 9. CORS and rate-limit posture

- **CORS.** The wide-open `allow_origins=["*"]` at `src/rogue/api/main.py:162–169` is correct for the read-only, credential-less dashboard API and for the `/mcp` mount, and it stays. The `/v1` product API is **key-authenticated, not cookie-authenticated** — credentials travel in an `Authorization` header, not a browser cookie — so it does not rely on CORS for security and the existing `*` policy is acceptable for it too (a malicious page cannot read a response it has no API key to authorize in the first place; `allow_credentials` stays `False`, which is what keeps `*` safe). If Team C later issues browser-session cookies for the dashboard's own first-party calls, those calls use the `/api/*` surface or a tightened origin list — not `/v1` — so the public API's CORS stance never needs to narrow.
- **Rate limiting.** The `/v1` API is rate-limited per API key, returning `429 rate_limited` with a `Retry-After` header and the standard error envelope. The limiter is keyed off the resolved key/org from the auth dependency, so it composes with tenancy. The concrete tiers, burst allowances, quota accounting, and the `Retry-After` semantics are owned by Team C and specified in [`./auth-and-keys.md`](./auth-and-keys.md); this doc only fixes that the response shape is the standard envelope and the status is `429`.

## 10. Non-goals for Team A

To keep the "thin shell" boundary from eroding: Team A does **not** implement scan execution, judging, target adapters, the `score` formula, report rendering, the queue, the worker, or the tenancy/secrets layer. Those are Teams B ([`../orchestration/scan-service.md`](../orchestration/scan-service.md), [`../orchestration/scan-engine-adapter.md`](../orchestration/scan-engine-adapter.md)), F ([`../reports/report-service.md`](../reports/report-service.md)), and C ([`../tenancy/data-model.md`](../tenancy/data-model.md), [`../tenancy/secrets.md`](../tenancy/secrets.md)). Team A owns: the `/v1` routers and their request/response Pydantic models, the error envelope + handlers, the async-job HTTP semantics (`202`/poll), pagination, idempotency, OpenAPI presentation, and CORS. Where the API needs a value it does not own (the `score`, a report body, a tenant identity), it asks the owning service for it and relays the result verbatim.
