# API Authentication, Keys & Request Lifecycle

> Team A (API Platform), with Team C (Multi-Tenant). The doc that turns the open, single-tenant FastAPI app into an authenticated, tenant-scoped, rate-limited public API. It defines how a request proves who it is, gets resolved to an org/project, has its scopes enforced, gets rate-limited, and only then reaches a handler that hands `org_id` to `ScanService`. It does **not** redefine IDs, the error envelope, or tenancy vocabulary — those are owned by [../ARCHITECTURE.md](../ARCHITECTURE.md) §5 and Team C's [../tenancy/data-model.md](../tenancy/data-model.md) — it consumes them.

Status: **PARTIALLY BUILT (local).** What shipped: Bearer-key authentication on `/v1` — `require_principal` (`src/rogue/api/v1/deps.py`) parses `Authorization: Bearer rk_…`, `hash_key` (sha256) looks the key up via `resolve_principal_from_token`, and returns a `Principal` (`org_id`, `project_id`, `role`, `scopes`, `key_id`) the handlers pass into the services; an `api_keys` table (migration 0022) stores only the hash + a `[:16]` prefix; `generate_api_key(env)` mints `rk_{live|test}_…`. The scope model exists in `rogue.platform.tenancy` (`Principal.scopes`, `role`, `has_scope`). **What did NOT ship:** per-route scope *enforcement* (the `/v1` routers gate on auth only — `Depends(require_principal)` — not on `Security(..., scopes=[...])`); rate limiting; the `Idempotency-Key`-conflict (`409`) machinery (create only does best-effort same-key replay, no different-body conflict); the key-management endpoints (`POST/DELETE /v1/keys*`, rotation); and the audit-event stream. Sections below describing those are design, not current behavior — each is flagged inline. Also note: target/provider secrets live in a **Fernet secret store** (`platform/secrets.py`, migration 0023), not a Vault/KMS — see [../tenancy/secrets.md](../tenancy/secrets.md). Companion to [./overview.md](./overview.md), [./scans-endpoints.md](./scans-endpoints.md), [./validate-benchmark-endpoints.md](./validate-benchmark-endpoints.md); cross-cuts [../tenancy/isolation-and-rbac.md](../tenancy/isolation-and-rbac.md).

---

## 1. Where we are starting from

The FastAPI app exists today (`src/rogue/api/main.py`) and is deliberately open: its module docstring states the API is a "single-tenant demo, the dashboard runs on a different localhost port than the backend" (`src/rogue/api/main.py:16-18`), and CORS is wide open — `allow_origins=["*"]`, `allow_credentials=False` (`src/rogue/api/main.py:162-169`). Every existing route under `/api/*` is read-only (`list_attacks`, `attack_detail`, `breach_matrix`, `brief`, the SSE feed, the bandit/persona/escalation stats endpoints). There is no `Authorization` handling anywhere in the request path, and the only hard-coded tenant is the `"acme"` customer id passed to `ThreatBriefBuilder.build_diff(customer_id="acme", ...)` (`src/rogue/api/main.py:934`).

We do not touch any of that. **The legacy `/api/*` routes stay open and read-only** — the deployed dashboard at `https://rogue-eosin.vercel.app` reads them anonymously and must keep working. Authentication is introduced *only* on the new `/v1` routers (`POST /v1/scans`, `GET /v1/scans/{id}`, `POST /v1/benchmark`, …). This is an additive seam: the shipped dependency is **`require_principal`** (`src/rogue/api/v1/deps.py`), depended on by every `/v1` handler.

ROGUE already speaks the bearer-token convention on the *outbound* side — the Bright Data client sends `"Authorization": f"Bearer {self.api_key}"` (`src/rogue/harvest/bright_data_client.py:354`). The inbound `/v1` API mirrors that header shape, so the format is familiar in both directions.

## 2. Key format, issuance, rotation, revocation

### 2.1 Format (owned by ../ARCHITECTURE.md §5, not redefined here)

API keys are `rk_live_<rand>` and `rk_test_<rand>`, and **only a SHA-256 of the key is stored** (ARCHITECTURE.md §5, "IDs"). The prefix is the live/test mode discriminator: `rk_live_` keys bill, run real provider calls, and write durable scans; `rk_test_` keys exercise the same code path against fixtures and a sandbox quota, and never bill. The random tail is a high-entropy URL-safe token (≥ 32 bytes); the full string is shown to the user exactly once at creation and is unrecoverable thereafter, because the server keeps only its hash.

A key arrives over the wire as a bearer token:

```
Authorization: Bearer rk_live_8f3c…<rand>
```

### 2.2 Storage — the `api_keys` table (owned by ../tenancy/data-model.md)

The `api_keys` table shipped in migration **0022_platform_tables.py** (`src/rogue/platform/models.py`). Shipped columns: `key_id` (PK), `org_id` (FK), `project_id` (nullable FK), `key_hash` (sha256 hex, unique index — the lookup key), `prefix` (`rk_live_xxxx`, display only), `name`, `scopes` (JSON), `created_at`, `last_used_at`, `revoked_at`. **Not present:** `mode`, `expires_at`, and a `role` column (a key's role defaults to `member` via `tenancy._role_for_key`; the live/test distinction lives in the key string's `rk_live_`/`rk_test_` prefix, not a stored column). Key minting is `generate_api_key(env="live") -> (raw_key, key_hash, prefix)` with `prefix = raw_key[:16]`.

The server never stores, logs, or returns the raw key after creation. We compute `sha256(presented_key)` and look the row up; if the row's `revoked_at`/`expires_at` say it's dead, it's a `401`. We compare on the indexed hash (a single equality lookup, not a constant-time loop over candidates), so the only timing surface is the DB index — acceptable for a 32-byte random secret.

### 2.3 Issuance, rotation, revocation

- **Issuance** is an authenticated dashboard / admin-scope action (`POST /v1/keys`, body `{ name, scopes, project_id?, expires_at? }`): the server generates the random tail, prepends `rk_live_`/`rk_test_`, stores the row with `key_hash` only, and returns the **full key once** plus the `key_id`. This is the sole moment the plaintext exists server-side; it is never persisted.
- **Rotation** is "create new, revoke old, overlap": issue a replacement key, deploy it, then revoke the predecessor — no in-place mutation of a secret. Optionally `POST /v1/keys/{key_id}/rotate` does both atomically and returns the new plaintext, leaving the old key valid until a caller-supplied `grace_until` so a running deploy doesn't break mid-rotation.
- **Revocation** (`DELETE /v1/keys/{key_id}`) sets `revoked_at = now()`. Revocation is immediate at the next request — the dependency rejects any key whose row has `revoked_at IS NOT NULL` (see §5). Because auth resolves per-request against the row, there is no token cache to invalidate; a revoked key is dead on its next call. Expiry (`expires_at < now()`) is treated identically.

## 3. Scopes (per-key authorization)

Every key carries an explicit scope set; the dependency enforces the scope a route requires. Three scopes, least-privilege ordered:

| Scope | Grants | Typical key |
|---|---|---|
| `read` | `GET /v1/scans`, `GET /v1/scans/{id}`, `GET /v1/scans/{id}/report`, benchmark reads | CI badge fetch, read-only dashboards |
| `scan` | everything in `read` **plus** `POST /v1/scans`, `POST /v1/benchmark`, `POST /v1/validate`, cancel | the normal "run a scan" integration key |
| `admin` | everything in `scan` **plus** key management (`/v1/keys*`), project management, org settings | a tenant's owner/admin key |

Scopes are a coarse capability gate at the API edge; they are **not** the full RBAC model. *Role*-based access (who within an org can do what, project membership, owner vs member) is Team C's, specified in [../tenancy/isolation-and-rbac.md](../tenancy/isolation-and-rbac.md). The edge contract is: the key's scope must include the route's required scope **and** the resolved `org_id` must own the addressed resource. The dependency enforces the scope; row-level org ownership is enforced both here (resolution) and in `ScanService` (every method already takes `org_id` as a keyword-only argument — see ARCHITECTURE.md §4 — so a handler physically cannot query another tenant's scans without passing the wrong `org_id`).

## 4. The request lifecycle

A `/v1` request passes through an ordered chain before it reaches a handler. The chain is implemented as **one FastAPI dependency, `require_api_key`** (plus a thin Starlette middleware for the parts that must run for *all* `/v1` traffic, like the rate-limit headers on error responses). Order matters: cheap rejections first, the expensive scan last.

```
client ──Authorization: Bearer rk_live_…──▶  /v1 router
   │
   ▼  (1) authenticate        parse header → sha256(key) → SELECT … WHERE key_hash=:h
   │                          miss / revoked / expired ───────────────────────▶ 401 invalid_api_key
   ▼  (2) resolve tenancy     row → org_id, project_id, mode(live|test)
   │                          (mismatch: key's project vs URL path) ──────────▶ 403 project_mismatch
   ▼  (3) enforce scope       route.required_scope ∈ key.scopes ?
   │                          no ──────────────────────────────────────────────▶ 403 insufficient_scope
   ▼  (4) rate-limit          Redis token-bucket: per-key AND per-org
   │                          bucket empty ───────────────────────────────────▶ 429 rate_limited (+ Retry-After)
   ▼  (5) idempotency         Idempotency-Key present? replay stored response or reserve
   │                          reused key, different body ──────────────────────▶ 409 idempotency_conflict
   ▼  (6) handler             ScanService.create_scan(spec, org_id=…, project_id=…, actor=key_id)
   │                          (NEVER runs the scan in the request thread — enqueues; Team B)
   ▼  (7) audit               emit audit event (see §9), set last_used_at
   ▼  202 Accepted  { scan_id, status: "queued", … }
```

> **Shipped:** the chain is shorter — `require_principal` does steps (1) authenticate (parse Bearer, `resolve_principal_from_token`) and (2) resolve tenancy (returns a `Principal`), then the handler runs. Steps (3) scope-enforcement, (4) rate-limit, (5) idempotency-conflict, and (7) audit are **not** wired into the dependency. The returned type is `Principal` (not `AuthContext`); the dependency is `require_principal` (not `require_api_key`). The 401 codes are `invalid_token` (missing/malformed Bearer) and `invalid_api_key` (unrecognized). The original aspirational wiring follows:

### As FastAPI wiring (original design — see shipped note above)

```python
# src/rogue/api/auth.py  (new — Team A)
async def require_api_key(
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_session),
    required_scope: Scope = Scope.read,   # overridden per-router via Security(...)
) -> AuthContext:
    key = _parse_bearer(authorization)                 # (1) "Bearer rk_…" or 401
    row = _lookup_active_key(db, sha256_hex(key))      # (1) hash lookup; 401 if miss/revoked/expired
    _enforce_scope(row, required_scope)                # (3) 403 insufficient_scope
    await _rate_limit(row)                             # (4) Redis token-bucket; 429 + Retry-After
    return AuthContext(                                # (2) resolved tenancy handed to the handler
        org_id=row.org_id, project_id=row.project_id,
        scopes=row.scopes, mode=row.mode, key_id=row.key_id,
    )
```

```python
# src/rogue/api/v1/__init__.py  (new) — auth applies to the whole /v1 surface
v1 = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])
# legacy stays open:
app.include_router(legacy_api)   # the existing /api/* routes — NO dependency added
app.include_router(v1)
```

Per-route scope is declared with `Security(require_api_key, scopes=["scan"])` so OpenAPI documents the requirement and the dependency enforces it. The handler reads the resolved `AuthContext` and passes `org_id`/`project_id` straight into the service — it never re-parses the header and never sees the raw key.

## 5. Rate limiting

A **Redis token-bucket**, two buckets per request, both must pass:

- **Per-key** bucket — protects against a single leaked/misbehaving key. Key `rl:key:{key_id}`.
- **Per-org** bucket — the tenant's aggregate quota across all its keys. Key `rl:org:{org_id}`.

Each bucket has a sustained rate (tokens/sec refill) and a burst (bucket capacity); a request consumes one token (scan-create may cost more — a heavier op debits more tokens so a flood of expensive `POST /v1/scans` is throttled harder than cheap `GET`s). Refill is computed lazily on read (`now − last_refill × rate`, capped at capacity) in a small Lua script so check-and-decrement is atomic under concurrency. Limits are per-`mode`: `rk_test_` keys get a tiny sandbox bucket; `rk_live_` keys get the org's plan quota (the plan/quota source is Team C's org row).

On exhaustion the API returns **`429`** with a `Retry-After` header (seconds until the next token) and the standard error envelope (ARCHITECTURE.md §5). Redis being unavailable **fails open** (allow the request, log + alert) rather than taking the whole API down for a dependency that exists only to protect it — the same posture the codebase already takes elsewhere (e.g. the health endpoint never 500s, `src/rogue/api/main.py:330`).

## 6. Idempotency

`POST /v1/scans` (and any other create) accepts an optional `Idempotency-Key` header (a client-chosen unique string, ≤ 255 chars). On first sight we store `idem:{org_id}:{key}` → `{ request_fingerprint, status: "in_flight" }` in Redis (24 h TTL) and proceed; on completion we record the response (`scan_id` + status). A retry with the **same** key and the **same** request body replays the stored response (no second scan is enqueued — important because scans cost real money: a full reproduce ≈ $35). A retry with the same key but a **different** body is a **`409 idempotency_conflict`**. An in-flight duplicate (same key, request still processing) returns `409` with a `Retry-After`. The fingerprint is `sha256` of the canonicalized body so a byte-for-byte resend is recognized as identical. Scoping the idem key under `org_id` keeps one tenant's keys from colliding with another's.

## 7. Secret handling — what is NOT an API key

A ROGUE API key (`rk_live_`/`rk_test_`) authenticates the **caller to ROGUE**. It is categorically different from the **target/provider credentials** ROGUE needs to *reach the customer's model* (the OpenAI/Anthropic/etc. key behind a `TargetSpec`). Those are **never** sent as, stored as, or treated like API keys.

`TargetSpec.api_key_ref` is a secret-store handle (`secref_…`), never the raw secret. **Shipped:** the store is a **Fernet-encrypted `secrets` table** (`platform/secrets.py`, migration 0023) — not Vault/KMS. The API swaps the raw `target.api_key` for a `secref_` handle on the way in (`DefaultScanService` with a wired `secret_store`), and the worker resolves it just-in-time at run. The full lifecycle is in [../tenancy/secrets.md](../tenancy/secrets.md). Two distinct secrets, two distinct stores, one rule: ROGUE API keys are hashed-and-forgotten in `api_keys`; target keys live Fernet-encrypted in `secrets` and are referenced by handle.

## 8. Error envelope examples

All non-2xx responses use the single envelope from ARCHITECTURE.md §5: `{ "error": { "code", "message", "details"? } }`. The auth layer's canonical responses:

**401 — missing / invalid / revoked / expired key**

```json
{ "error": {
  "code": "invalid_api_key",
  "message": "The API key is missing, malformed, revoked, or expired. Pass a valid key as 'Authorization: Bearer rk_live_…'."
} }
```

`401` is intentionally uniform across missing/unknown/revoked/expired — we don't disclose *which*, so an attacker can't probe whether a key exists.

**403 — authenticated but not permitted (scope or project mismatch)**

```json
{ "error": {
  "code": "insufficient_scope",
  "message": "This key has scope 'read' but 'scan' is required for POST /v1/scans.",
  "details": { "required_scope": "scan", "key_scopes": ["read"] }
} }
```

**429 — rate limited** (also sets header `Retry-After: 12`)

```json
{ "error": {
  "code": "rate_limited",
  "message": "Per-org rate limit exceeded. Retry after 12s.",
  "details": { "scope": "org", "limit": 60, "window_s": 60, "retry_after_s": 12 }
} }
```

## 9. Audit

Every authenticated `/v1` request emits an audit event: `{ event_id, ts, org_id, project_id, key_id, actor, route, method, status, request_id }`. The `actor` of an API-driven action is the `key_id` (never the raw key). Mutating events — key issuance/rotation/revocation, scan create/cancel — are durable (a row, Team C's table); read traffic is logged. `last_used_at` on the key row is updated on each successful auth so an operator can spot dormant keys to revoke. The audit stream is the forensic record behind "who ran this scan / who created this key"; the RBAC/who-can-read-audit policy is [../tenancy/isolation-and-rbac.md](../tenancy/isolation-and-rbac.md).

## 10. Invariants (review checklist)

1. **Legacy stays open.** No `Depends(require_api_key)` is ever attached to a `/api/*` route. CORS on legacy is unchanged (`src/rogue/api/main.py:162-169`).
2. **Only the hash is stored.** The raw key exists server-side for exactly one response (creation) and is never logged.
3. **Tenancy is resolved at the edge and re-asserted in the service.** The handler passes the dependency-resolved `org_id` into `ScanService`; it never derives a tenant from request body or path alone.
4. **Cheap rejections precede expensive work.** Auth → scope → rate-limit → idempotency → enqueue. No scan runs in the request thread (ARCHITECTURE.md §4 / Team B).
5. **One envelope.** Every 401/403/409/429 uses `{ "error": { code, message, details? } }`; `429` always carries `Retry-After`.
6. **Two secrets, two stores.** ROGUE keys ≠ target/provider keys; target secrets go through Vault/KMS by handle ([../tenancy/secrets.md](../tenancy/secrets.md)), never the `api_keys` table.
