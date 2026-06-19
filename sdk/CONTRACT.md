# ROGUE SDK ⇄ Hosted API — frozen `v1` wire contract

This is the **single source of truth** for the wire protocol between the `rogue` Python SDK
(this package) and the ROGUE Hosted API. The SDK client codes to it; `MockTransport` serves it
faithfully in-memory; the (future) Hosted API team **builds the server to match this exact shape**.

Status of each endpoint against the *currently deployed* API (`https://rogue-private.onrender.com`):

| Area | Endpoint | Server today |
|---|---|---|
| Auth | `POST /v1/auth/token`, `POST /v1/auth/refresh` | ❌ token endpoints not built — but the hosted API **is** key-authenticated today (`rk_live_` bearer), not unauthenticated. |
| Deployments | `POST/GET/PATCH/DELETE /v1/deployments` | ❌ `/v1/deployments` not built — (the hosted API is no longer read-only; it ships `/v1/scans`, `/v1/validate`, `/v1/benchmark`, `/v1/attestation/*`). |
| Scans | `POST /v1/scans`, `GET /v1/scans/{id}`, cancel | ⚠️ **live + key-auth'd, but queues only** — the endpoints are deployed and enqueue a job; no hosted worker drains the queue yet, so a scan does not complete on the host. A real graded scan = offline `reproduce_once.py` (Mode 1). |
| Reports | `GET /v1/reports/{id}`, `GET /v1/scans/{id}/report` | ⚠️ partial — `/api/brief` returns the diff today; needs per-scan shaping |

`MockTransport` implements **all** of the above so the SDK is fully usable and testable offline today.
The HTTPTransport targets these paths for when the server catches up.

---

## Conventions

- Base URL carries no path; the SDK prepends `/v1/...`. (e.g. `https://api.rogue.dev` → `https://api.rogue.dev/v1/scans`).
- All request/response bodies are JSON. Timestamps are ISO-8601 UTC strings (`...Z`).
- **Auth:** every endpoint except `POST /v1/auth/*` requires `Authorization: Bearer <access_token>`.
- **Versioning:** the SDK sends `X-Rogue-Api-Version: v1` and `User-Agent: rogue-python/<sdk-version>`.
- **Errors:** any non-2xx returns `{"error": {"code": "<machine_code>", "message": "<human>", "details": {...}?}}`.
  The SDK maps `code`/HTTP-status → a typed exception (see `rogue.exceptions`).

### Error codes → SDK exception

| HTTP | `error.code` | SDK exception |
|---|---|---|
| 400 | `invalid_request` / `validation_error` | `ValidationError` |
| 401 | `invalid_api_key` / `invalid_token` / `token_expired` | `AuthenticationError` |
| 403 | `forbidden` | `AuthorizationError` |
| 404 | `not_found` | `NotFoundError` |
| 409 | `conflict` | `ConflictError` |
| 429 | `rate_limited` (+ `Retry-After`) | `RateLimitError` |
| 5xx | `internal` / `unavailable` | `APIError` |
| — | (network/timeout/DNS) | `APIConnectionError` |

---

## Auth

### `POST /v1/auth/token`
Exchange a long-lived API key for a short-lived access token.
```jsonc
// request
{ "api_key": "rk_live_..." }
// 200
{ "access_token": "...", "refresh_token": "...", "expires_in": 3600, "token_type": "bearer" }
// 401 -> { "error": { "code": "invalid_api_key", "message": "API key not recognized" } }
```

### `POST /v1/auth/refresh`
```jsonc
// request
{ "refresh_token": "..." }
// 200
{ "access_token": "...", "expires_in": 3600 }
```

---

## Deployments

A **deployment** is the customer's deployed LLM config under test: `(model × system_prompt × tools)`.

`deployment` object:
```jsonc
{
  "id": "dep_01J...",
  "name": "Customer Support Agent",
  "model": "openai/gpt-5",
  "system_prompt": "You are a helpful support agent...",
  "tools": ["web_fetch", "order_lookup"],
  "forbidden_topics": ["refund policy internals"],
  "provider": "openai",            // null if not declared
  "created_at": "2026-06-04T09:00:00Z",
  "updated_at": "2026-06-04T09:00:00Z"
}
```

- `POST /v1/deployments` — body `{name, model, system_prompt?, tools?, forbidden_topics?, provider?}` → `201 {deployment}`. `name` + `model` required.
- `GET /v1/deployments/{id}` → `200 {deployment}` | `404`.
- `PATCH /v1/deployments/{id}` — body = any subset of the writable fields → `200 {deployment}` (bumps `updated_at`).
- `GET /v1/deployments?limit=50&cursor=` → `200 {"deployments": [deployment...], "next_cursor": null}`.
- `DELETE /v1/deployments/{id}` → `204`.

---

## Scans

A **scan** runs ROGUE's attack repertoire against one deployment. It is a **server-side async job**
(minutes to tens of minutes, real LLM spend) — the SDK starts it and polls.

`scan` object:
```jsonc
{
  "id": "scan_01J...",
  "deployment_id": "dep_01J...",
  "status": "running",            // queued | running | completed | failed | canceled
  "created_at": "2026-06-04T09:00:00Z",
  "started_at": "2026-06-04T09:00:01Z",
  "completed_at": null,
  "progress": 0.42,               // 0.0..1.0
  "n_attacks": 333,               // total attack primitives in this scan (null until known)
  "n_completed": 140,
  "report_id": null,              // set when status == completed
  "error": null                   // human message when status == failed
}
```

- `POST /v1/scans` — body `{deployment_id, n_trials?: 5, options?: {...}}` → `202 {scan}` (status `queued`/`running`).
- `GET /v1/scans/{id}` → `200 {scan}` | `404`. (Poll this for status/progress.)
- `GET /v1/scans?deployment_id=&limit=50` → `200 {"scans": [scan...], "next_cursor": null}`.
- `POST /v1/scans/{id}/cancel` → `200 {scan}` (status → `canceled`).

---

## Reports

A **report** is the customer-facing result of a completed scan: an overall risk score plus findings.
(Internally derived from the breach matrix + threat-brief diff; remediation text is synthesized.)

`report` object:
```jsonc
{
  "id": "rep_01J...",
  "scan_id": "scan_01J...",
  "deployment_id": "dep_01J...",
  "generated_at": "2026-06-04T09:20:00Z",
  "risk_score": 73.5,             // 0..100, higher = more exposed
  "risk_level": "high",           // low | medium | high | critical (banded from risk_score)
  "stats": { "n_findings": 12, "n_critical": 2, "n_high": 4, "n_medium": 5, "n_low": 1 },
  "findings": [ finding... ]      // sorted: severity desc, then success_rate desc
}
```

`finding` object:
```jsonc
{
  "id": "find_01J...",
  "severity": "critical",                       // low | medium | high | critical
  "family": "indirect_prompt_injection",        // ROGUE taxonomy slug
  "technique": "Indirect Prompt Injection",     // human display label
  "vector": "rag_document",                     // where the payload enters
  "title": "Hidden instruction in fetched web page overrides system prompt",
  "description": "...",
  "success_rate": 0.81,                          // any-breach rate over n_trials, 0..1
  "n_trials": 5,
  "confidence": 0.92,                            // judge confidence, nullable
  "example_attack": "Ignore previous...",        // rendered payload excerpt, nullable
  "example_response": "Sure, here is...",         // model response excerpt, nullable
  "explanation": "An attacker hides instructions in content the model fetches...", // plain-language "what this is + why it matters", synthesized by family
  "remediation": "Treat retrieved content as untrusted data...", // "how to fix", synthesized by family
  "source_url": "https://...",                   // provenance, nullable
  "first_seen": "2026-05-28T19:47:35Z"            // nullable
}
```

- `GET /v1/reports/{id}` → `200 {report}` | `404`.
- `GET /v1/scans/{id}/report` → `200 {report}` | `404` (scan not completed / no report).

---

## Providers

Registers the credentials ROGUE uses to reach the customer's model provider when scanning. Secrets
are write-only — they are **never echoed back**; responses carry only non-secret metadata.

`provider` object (response):
```jsonc
{ "id": "prov_01J...", "provider": "openai", "label": "default", "created_at": "...Z" }
```

- `POST /v1/providers` — body `{provider, credentials: {...}, label?}` → `201 {provider}` (no secrets).
  `credentials` shape is provider-specific (see `adapters/`): openai/anthropic → `{api_key}`,
  vertex → `{project, location, credentials_json?}`, custom → `{base_url, api_key?, headers?}`.
- `GET /v1/providers` → `200 {"providers": [provider...]}`.

---

## Internal → customer mapping (for the API team)

| Customer (this contract) | Internal ROGUE |
|---|---|
| `Deployment` | `schemas.DeploymentConfig` (`customer_id` from auth context; `model`→`target_model`, `tools`→`declared_tools`) |
| `Scan` | a `run_reproduction(...)` job over the deployment's config, scoped to that customer |
| `Report.findings[]` | breaching `AttackPrimitive`s for the config (the threat-brief diff's per-tier arrays) |
| `Finding.success_rate` | the cell `any_breach_rate` |
| `Finding.severity` | `severity_tier` (from `severity_score`) |
| `Report.risk_score` | **synthesized** (no internal equivalent — formula in `models/report.py`) |
| `Finding.explanation` | **synthesized** by family (plain-language "what this is + why it matters"; no internal equivalent) |
| `Finding.remediation` | **synthesized** by family (no internal equivalent) |
