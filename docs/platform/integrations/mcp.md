# MCP Scan Tools — action over the producer server

> **⚠️ SUPERSEDED (2026-06-05) — historical design spec.** This was the Team-G *design* for the action tools, written when only 5 were planned (`start_scan`/`get_scan`/`validate`/`benchmark`/`get_report`) and marked "not yet built." The action surface shipped and grew well beyond this: the live server now exposes **19 tools** (6 read + 13 action), some renamed (`validate`→`validate_target`, `benchmark`→`run_benchmark`, `get_scan`→`get_scan_status` with `get_scan` kept as an alias) plus the Level-3 workflow tools (`create_executive_summary`/`send_slack_alert`/`create_jira_ticket`) and stored integrations (`list_integrations`). **For current, accurate docs use [`docs/mcp/ARCHITECTURE.md`](../../mcp/ARCHITECTURE.md) (design), [`docs/mcp/CONTRACT.md`](../../mcp/CONTRACT.md) (frozen v1 tool contract), and [`docs/mcp.md`](../../mcp.md) (usage).** The sections below are kept only for the original design rationale — do not trust their tool list.

> Team G (MCP & Integrations). This doc specs the *action* half of ROGUE's producer-side MCP server: the new `start_scan` / `get_scan` / `validate` / `benchmark` / `get_report` tools that let an MCP client (Cursor, ChatGPT, Claude Desktop, Windsurf) start a hosted scan and read its result. Every one of these tools is a thin client of `ScanService` ([../orchestration/scan-service.md](../orchestration/scan-service.md)) and `ScanEngine` — the SAME engine the SDK, the public API ([../api/scans-endpoints.md](../api/scans-endpoints.md)), and the dashboard use ([../ARCHITECTURE.md](../ARCHITECTURE.md) §2). MCP is just a fourth surface on the one-engine spine; it defines no scanning logic, no status enum, and no record shape of its own. It consumes `ScanSpec` / `TargetSpec` / `ScanRecord` / `ScanStatus` verbatim from [../ARCHITECTURE.md](../ARCHITECTURE.md) §5. The integrations sibling — Slack/GitHub/Jira event sinks — is [./slack-github-jira.md](./slack-github-jira.md).

Status: design spec, not yet built. The producer MCP server it extends ships today (`src/rogue/mcp_server/server.py`, 6 read-only tools); the action tools are the [../ARCHITECTURE.md](../ARCHITECTURE.md) §7 Week-4 "distribution" layer, and they cannot land before `ScanService` (Week 1) and per-tenant key auth (Week 2) exist, because they route through the former and are gated by the latter.

---

## 1. Consumer vs producer — two MCP roles, this doc is the producer

ROGUE uses MCP on both sides of its pipeline, and the distinction matters for scoping this work. As a **consumer**, the harvest layer's `DiscoveryAgent` calls *Bright Data's* MCP server to discover novel attacks off the open web — ROGUE is the client there. As a **producer** (this file), ROGUE exposes its *own* MCP server so any MCP-speaking IDE can query the threat DB and now run scans — ROGUE is the server. The module docstring at `src/rogue/mcp_server/server.py:5-12` states exactly this dual role. Team G owns only the producer side. Nothing here touches the consumer/harvest path.

The producer server is `FastMCP("rogue")` at `src/rogue/mcp_server/server.py:139`. It runs two ways from one definition: **stdio** by default (Claude Desktop spawns the process and talks over stdin/stdout — `main()` at `src/rogue/mcp_server/server.py:622`), and **streamable-http** for remote IDE clients. In the deployed product the HTTP transport is not a separate service — the same `FastMCP` instance is **mounted into the FastAPI app** at `app.mount("/mcp", _mcp_app)` (`src/rogue/api/main.py:170`), so it ships on the already-deployed API host (Render) at `<api-host>/mcp`. `ROGUE_MCP_TRANSPORT` (`stdio | sse | streamable-http`) selects the standalone transport for local runs.

## 2. What exists today, and how the action tools coexist with it

Six tools live on the server today, all **read-only**, all querying the harvest/reproduce DB directly through a lazy SQLAlchemy session (`_get_session`, `src/rogue/mcp_server/server.py:92`): `query_attacks`, `query_diff`, `query_threat_brief`, `query_breaches_for_config`, `query_attack_detail`, `query_worst_attacks` (`src/rogue/mcp_server/server.py:151-525`). These answer "*what attacks exist / what's breaching / am I exposed?*" against ROGUE's own continuously-harvested threat intelligence. They are **threat-DB queries**, not customer scans — they read global, already-computed data, take no customer target, spend no money, and are unchanged by this work.

The five new tools answer a different question — "*scan MY endpoint and tell me what breaks*" — and have a fundamentally different shape: they take a customer `TargetSpec`, cost real money (a full reproduce ≈ $35, [../api/auth-and-keys.md](../api/auth-and-keys.md) §6), write durable per-tenant `scan_runs` rows, and **must not run in the request thread** ([../orchestration/scan-service.md](../orchestration/scan-service.md) §1). They route through `ScanService`/`ScanEngine`; the read tools route through `_get_session`. The two families coexist on the same `FastMCP` instance with no interference: read tools keep their direct DB session, action tools get their `ScanService` handle (§7), and the auth boundary (§5) decides which a given client may call.

The split is also a tenancy split. The read tools surface ROGUE's *global* threat DB (today scoped to the demo `customer_id="acme"` in `query_diff`, `src/rogue/mcp_server/server.py:219`) and remain readable to any authenticated MCP client. The action tools operate on a *specific tenant's* scans and are strictly org-scoped (§5). A client authenticated as `org_X` can read the global threat corpus and run/read **only `org_X`'s** scans — never another tenant's.

## 3. The headline flow — "scan my staging endpoint" in Cursor

```
  User (in Cursor / ChatGPT):  "Scan my staging chatbot at https://staging.acme.com/chat"
        │
        ▼  model calls
  start_scan(target={endpoint:"https://staging.acme.com/chat", api_key_ref:"vault://acme/staging"})
        │   → ScanService.create_scan(spec, org_id=<from key>, project_id, actor)
        ▼
  { scan_id: "scan_01J…", status: "queued", poll_after_s: 2 }
        │
        ▼  model polls (start + poll, because scans are queued — §4)
  get_scan("scan_01J…")  → { status: "running", progress: 40, n_completed: 20, … }
  get_scan("scan_01J…")  → { status: "running", progress: 85, … }
  get_scan("scan_01J…")  → { status: "completed", n_breaches: 7, top_attack: "Crescendo",
                              score: 62, report_id: "rep_01J…" }
        │
        ▼  model summarizes to the user
  "7 vulnerabilities found across 50 tests. Top attack: Crescendo (multi-turn escalation).
   Risk score 62/100. Full report: get_report(\"scan_01J…\")."
```

The model drives the loop itself — `start_scan` returns a `scan_id`, the model polls `get_scan` until terminal, then narrates the result. This is the exact path [../ARCHITECTURE.md](../ARCHITECTURE.md) §7 Week-4 names ("the 'scan staging endpoint' in Cursor flow"). The model's only job is poll-until-terminal-then-summarize; all scan logic is server-side, identical to the SDK and API because it is literally the same `ScanService` call.

## 4. Async-job semantics over MCP — start + poll

A scan is a queued job, not a synchronous call (`ScanService.create_scan` returns in milliseconds with `status=queued`; the engine runs out of band in a worker — [../orchestration/scan-service.md](../orchestration/scan-service.md) §1, §4). MCP tools are request/response, and a full default-pack scan is dozens of customer-model round-trips plus judge calls — far longer than any MCP client will hold a single tool call open. So the MCP surface mirrors the API's async contract: **`start_scan` enqueues and returns a `scan_id`; `get_scan` is polled until a terminal `ScanStatus`.** There is no long-running blocking tool. This keeps the load-bearing invariant — *never run a scan in the request thread* — true for the MCP surface exactly as it is for the API ([../orchestration/scan-service.md](../orchestration/scan-service.md) §1).

`start_scan` returns a `poll_after_s` hint (a suggested seconds-to-wait before the first `get_scan`) so a well-behaved model paces its polling instead of busy-looping; the worker's progress heartbeat ([../orchestration/scan-service.md](../orchestration/scan-service.md) §5) means each `get_scan` returns a smoothly climbing `progress: 0–100` rather than a binary done/not-done. `ScanStatus` is the single enum `queued | running | completed | failed | canceled` ([../ARCHITECTURE.md](../ARCHITECTURE.md) §5); the model treats `completed | failed | canceled` as terminal and stops polling. There is no MCP-initiated server push — the mounted transport is configured `stateless_http=True` (`src/rogue/api/main.py:133`), so each tool call is self-contained and survives a multi-worker host; polling, not streaming, is the contract.

`validate` and `benchmark` follow the SAME async shape as `start_scan` where they touch the engine. `validate` (a single reachability probe — `ScanEngine.validate`, [../ARCHITECTURE.md](../ARCHITECTURE.md) §4) is fast enough to answer inline, so it may return its `ValidationResult` synchronously. `benchmark` is a long multi-goal run (`ScanEngine.benchmark`) and is start+poll like `start_scan`, returning a `scan_id`-shaped handle that `get_scan` reads. `get_report` is a pure read of an already-terminal scan's persisted artifact (no engine), so it answers synchronously.

## 5. Auth — the mounted MCP is currently open; scope it per tenant

Today the mounted MCP endpoint has **no authentication**: DNS-rebinding protection is deliberately disabled for the public host (`enable_dns_rebinding_protection=False`, `src/rogue/api/main.py:137-139`), CORS is wide open (`allow_origins=["*"]`, `src/rogue/api/main.py:162-169`), and any client can call the six read tools anonymously. That is acceptable for read-only global threat data; it is **not** acceptable for action tools that spend a tenant's money and read a tenant's scans. The action tools therefore require the same per-tenant API key the public API uses — `rk_live_…` / `rk_test_…`, resolved to an `org_<ulid>` ([../api/auth-and-keys.md](../api/auth-and-keys.md) §2).

**How the key arrives.** MCP clients authenticate the HTTP transport with a bearer header on the mounted `/mcp` endpoint — the identical `Authorization: Bearer rk_live_…` convention the `/v1` API uses ([../api/auth-and-keys.md](../api/auth-and-keys.md) §1, §2.1). Because the MCP app is mounted into the same FastAPI app as the `/v1` router, the natural implementation is a Starlette middleware on the `/mcp` mount that runs the same authentication and tenancy-resolution chain as `require_api_key` ([../api/auth-and-keys.md](../api/auth-and-keys.md) §4 steps 1–4): parse bearer → `sha256(key)` → `SELECT … WHERE key_hash=:h` → reject miss/revoked/expired with `401`, resolve `org_id` / `project_id` / `mode`, enforce scope, rate-limit. The resolved `AuthContext` is stashed on the request so the action tools read `org_id` from it (FastMCP exposes the request context to tools via its app context). For the stdio transport (local Claude Desktop) the key comes from a `ROGUE_API_KEY` env var the spawned process reads, resolved through the same path.

**Scopes map straight onto the existing scope ladder** ([../api/auth-and-keys.md](../api/auth-and-keys.md) §3): the read tools require `read`, `start_scan` / `validate` / `benchmark` require `scan`, `get_scan` / `get_report` require `read`. A key with only `read` may query the threat DB and read scans but cannot start one. Rate limiting and idempotency reuse the API's machinery: `start_scan` accepts an optional idempotency key so a model that retries after a dropped MCP response does not enqueue (and bill for) a second scan ([../api/auth-and-keys.md](../api/auth-and-keys.md) §6).

**The read tools' anonymity is a deliberate, separable policy.** During rollout the six read tools MAY stay open (global, read-only, no tenant data) while the five action tools require auth — the middleware can gate by tool name / required scope rather than blanket-rejecting the mount. The end-state, once tenancy is the norm, is that an unauthenticated client sees only the read tools and an authenticated one additionally gets the action tools scoped to its org. Two distinct secrets remain distinct throughout: the ROGUE API key authenticates the *caller*; the customer's provider/target credential is a `TargetSpec.api_key_ref` Vault/KMS handle, never sent inline and never logged ([../api/auth-and-keys.md](../api/auth-and-keys.md) §7, [../ARCHITECTURE.md](../ARCHITECTURE.md) §5).

## 6. Tool schemas

Inputs/outputs below are the MCP tool surface; every type name is the [../ARCHITECTURE.md](../ARCHITECTURE.md) §5 vocabulary. `org_id` is **never** a tool input — it is resolved from the authenticated key (§5) and injected server-side, so a model physically cannot address another tenant's scans.

### `start_scan` — enqueue a hosted scan (scope: `scan`)

Inputs (a flattened `ScanSpec` so a model can fill it from natural language):

| Field | Type | Notes |
|---|---|---|
| `target` | object | `TargetSpec`: `{ endpoint?, provider?, model?, api_key_ref, system_prompt? }` ([../ARCHITECTURE.md](../ARCHITECTURE.md) §5). One of `endpoint` / `provider` required. |
| `pack` | str = `"default"` | `default` / `aggressive` / `compliance` ([../ARCHITECTURE.md](../ARCHITECTURE.md) §3). |
| `attacks` | list[str] \| null | Optional attack-name filter. |
| `max_tests` | int = 50 | Per-scan cap; org policy may lower it. |
| `n_trials` | int = 1 | Trials per attack. |
| `budget` | float \| null | USD stop. |
| `idempotency_key` | str \| null | Replay-safe create ([../api/auth-and-keys.md](../api/auth-and-keys.md) §6). |

Output: `{ scan_id, status: ScanStatus ("queued"), poll_after_s: int }`. Implementation: build a `ScanSpec`/`TargetSpec`, call `ScanService.create_scan(spec, org_id=<auth>, project_id=<auth>, actor=<key_id>)`, return the minted `scan_id`. No engine runs here (§4).

### `get_scan` — poll status / progress (scope: `read`)

Input: `{ scan_id: str }`. Output: the full `ScanRecord` ([../ARCHITECTURE.md](../ARCHITECTURE.md) §5) — `{ scan_id, status, progress (0–100), n_tests, n_completed, n_breaches, top_attack, score (0–100), cost_usd, report_id, error, created_at, started_at, completed_at }`. Implementation: `ScanService.get_scan(scan_id, org_id=<auth>)`, which merges the durable row with the live Redis progress heartbeat ([../orchestration/scan-service.md](../orchestration/scan-service.md) §5). A `scan_id` belonging to another org returns *not found*, never the row (§5; [../orchestration/scan-service.md](../orchestration/scan-service.md) §6). This is the tool the model loops on until `status` is terminal.

### `validate` — reachability + auth probe (scope: `scan`)

Input: `{ target: TargetSpec }`. Output: a `ValidationResult` — `{ reachable: bool, latency_ms?: int, model_echo?: str, error?: str }` (shape owned by `ScanEngine.validate`, [../ARCHITECTURE.md](../ARCHITECTURE.md) §4). Answered inline (§4) — a single round-trip, no queued job. The model uses this to confirm a `TargetSpec` is good *before* spending money on a full `start_scan`.

### `benchmark` — dataset run (scope: `scan`)

Inputs: `{ target: TargetSpec, dataset: str, max_goals: int = 50 }`. Output: `{ scan_id, status: ScanStatus ("queued"), poll_after_s: int }` — start+poll like `start_scan` (§4), read back via `get_scan`; the terminal record carries the benchmark `score`/trend. Implementation routes through `ScanService` to `ScanEngine.benchmark(target, dataset, max_goals=…)` ([../ARCHITECTURE.md](../ARCHITECTURE.md) §4). Datasets/scoring are Team E's ([../api/validate-benchmark-endpoints.md](../api/validate-benchmark-endpoints.md)); this tool is a transport over them.

### `get_report` — fetch the finished report (scope: `read`)

Inputs: `{ scan_id: str, format: str = "summary" }` where `format ∈ { "summary", "json", "markdown" }`. Output: `{ report_id, format, content: str | object }` — a model-readable rendering of the persisted report (`summary` is a short prose digest the model can relay; `json` is the structured `ReportService.build_json` shape). Implementation reads the already-terminal scan's `report_id` and asks `ReportService` ([../ARCHITECTURE.md](../ARCHITECTURE.md) §4 — Team F) for the rendering; a pure read, answered synchronously, `404`-class if the scan is not yet `completed`. PDF/HTML binary artifacts are out of MCP scope (a text protocol) — the report URL is surfaced instead so the user opens it in the dashboard.

## 7. Where it lives, and what it must not do

The action tools are added to the existing `src/rogue/mcp_server/server.py` alongside the six read tools — same `FastMCP("rogue")` instance, registered with `@mcp.tool()` exactly like the current six. The one structural change: action tools need a `ScanService` handle, not a raw DB session. They acquire it the way the API handlers do — through the platform layer (`src/rogue/platform/scan_service.py`, [../orchestration/scan-service.md](../orchestration/scan-service.md) §2) — and read `org_id` from the request's resolved `AuthContext` (§5). The read tools' `_get_session` (`src/rogue/mcp_server/server.py:92`) is untouched.

Hard boundaries, all inherited from the one-engine principle:

1. **No scanning logic here.** Every action tool is a thin call into `ScanService` / `ScanEngine`. If an MCP scan and an API scan of the same target+pack ever diverge, the architecture has failed ([../ARCHITECTURE.md](../ARCHITECTURE.md) §2).
2. **No scan in the tool call.** `start_scan` / `benchmark` enqueue and return; the worker runs the engine out of band ([../orchestration/scan-service.md](../orchestration/scan-service.md) §1). MCP tool calls are short.
3. **No new status enum, record, or score formula.** `ScanStatus`, `ScanRecord`, and `score` are [../ARCHITECTURE.md](../ARCHITECTURE.md) §5 / Team F; MCP echoes them.
4. **No cross-tenant reach.** `org_id` is auth-resolved, never a tool input; `ScanService` re-asserts it on every call ([../orchestration/scan-service.md](../orchestration/scan-service.md) §6).
5. **Two secrets, two stores.** The ROGUE key authenticates the caller; the target credential is a Vault/KMS handle in `TargetSpec.api_key_ref` ([../api/auth-and-keys.md](../api/auth-and-keys.md) §7).

## 8. Out of scope (owned elsewhere)

- `ScanService` semantics — validation, queue, lifecycle, cancellation, tenant scoping — [../orchestration/scan-service.md](../orchestration/scan-service.md).
- Key format, hashing, scopes, rate limit, idempotency, the `require_api_key` chain the MCP middleware reuses — [../api/auth-and-keys.md](../api/auth-and-keys.md).
- `score` formula and report artifacts (`get_report` renders, doesn't define) — Team F ([../ARCHITECTURE.md](../ARCHITECTURE.md) §4–§5).
- Benchmark datasets and scoring (`benchmark` transports them) — Team E ([../api/validate-benchmark-endpoints.md](../api/validate-benchmark-endpoints.md)).
- Slack/GitHub/Jira event sinks (the other half of Team G) — [./slack-github-jira.md](./slack-github-jira.md).
- The consumer-side MCP (harvest's `DiscoveryAgent` calling Bright Data) — harvest layer, not the platform.
