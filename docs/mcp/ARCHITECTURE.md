# ROGUE MCP server — architecture & design doc

> The producer-side Model Context Protocol surface. Where `sdk/DESIGN.md` turns ROGUE into something a company installs with `pip`, this turns it into something an agent operates from inside the editor: ROGUE exposes its *own* MCP server, so Claude Desktop / Cursor / Windsurf can query the threat DB and run the whole scan lifecycle as tool calls — no dashboard, no context switch. This doc is the design rationale and the architecture; the usage walkthrough (connect, tool catalog, worked agent transcripts) lives in `docs/mcp.md`, and the per-tool input/output shapes live in the code's docstrings — this complements both rather than rehearsing them.

## Why this exists / first principles

1. **ROGUE is an MCP *producer*, not only a consumer.** ROGUE already uses MCP as a *consumer* in its harvest pipeline — the `DiscoveryAgent` calls Bright Data's MCP server to find novel attacks off the open web. The differentiator documented here is the *other* role: ROGUE runs its own `FastMCP("rogue")` server (`src/rogue/mcp_server/server.py:139`) so that any MCP-speaking IDE is the *client* and ROGUE is the *server*. The module docstring states this dual role verbatim (`src/rogue/mcp_server/server.py:1-21`). Consumer = ROGUE reaches out to Bright Data to harvest; producer = the world reaches into ROGUE to query and scan. This file is the producer side only; nothing here touches the harvest/consumer path.
2. **The agent operates the whole product from where it already lives.** The thesis is distribution: the customer's coding agent — the one they already work in — can validate a target, run a red-team scan, poll it to completion, read the report, summarize it for an exec, and file the tickets, all from one instruction. "Scan my staging endpoint, tell the team" answered in-IDE is the round trip that makes MCP more than a second API.
3. **One engine, four surfaces.** Every action tool is a thin client of the same `ScanService` / `ReportService` / `BenchmarkService` / `ScanEngine` that back the SDK, the `/v1` REST API, and the dashboard (`src/rogue/mcp_server/scan_tools.py:14-18`). The MCP layer defines no scan logic, no status enum, no record shape, and no score formula of its own — it builds a request, hands it to a service, and reshapes the result for the JSON-RPC wire. If an MCP scan and an API scan of the same target ever diverged, the architecture would have failed.
4. **The org is bound by the server, never by the model.** Tenancy is a server concern resolved out-of-band (today from `ROGUE_MCP_ORG_ID`; per-tenant auth in v2). No tool ever takes an `org_id` argument an LLM could supply or spoof (`src/rogue/mcp_server/scan_tools.py:20-24`).
5. **Secrets never pass through the model.** A target's API key is redacted before persistence; a Slack webhook or Jira token is registered once by an admin, encrypted at rest, and referenced by *name* — the LLM sees the name, never the credential.

## Architecture

```
FastMCP("rogue")                          src/rogue/mcp_server/server.py:139
 │  one instance, two tool families, two transports
 │
 ├─ Read / threat-intel tools             server.py  (direct lazy SQLAlchemy session)
 │   query_attacks · query_diff · query_threat_brief
 │   query_breaches_for_config · query_attack_detail · query_worst_attacks
 │      → _get_session() → harvest/reproduce DB (attack_primitives, breach_results, breach_matrix)
 │      read-only · global threat corpus · no customer target · spends no money
 │
 └─ Action tools                          scan_tools.py  (route through services)
     validate_target                      → ScanEngine.validate           (inline, near-zero cost)
     start_scan / get_scan_status / cancel_scan / list_scans
                                          → ScanService → JobQueue → ScanWorker → ScanEngine
     get_report / list_findings           → ReportService.build_json
     run_benchmark / get_benchmark        → BenchmarkService.create / get
     create_executive_summary             → ReportService.build_executive_summary   (Level-3)
     send_slack_alert / create_jira_ticket→ IntegrationStore + SecretStore           (Level-3)
     list_integrations                    → IntegrationStore.list                    (Level-3)

Transports                                one definition, run two ways
 ├─ streamable-http   mounted into FastAPI at app.mount("/mcp", _mcp_app)  api/main.py:211
 │                    stateless_http=True · DNS-rebind protection off · live on Render
 └─ stdio (default)   Claude Desktop spawns `python -m rogue.mcp_server.server`  server.py:622

Wiring                                    api/main.py:_wire_platform()  (231)
   register_scan_tools(rogue_mcp, scan_service=…, report_service=…, benchmark_service=…,
                       engine=…, integration_store=…, org_id=ROGUE_MCP_ORG_ID)   (275)
```

## The one-engine principle — every action tool routes through `ScanService`

The load-bearing design choice is that the MCP surface owns no execution. `src/rogue/mcp_server/scan_tools.py` is explicit (lines 14-18): "There is no scan logic here — every tool builds a request, hands it to a service, and reshapes the result for the MCP JSON-RPC layer. The one execution path stays singular." `register_scan_tools` (`scan_tools.py:170`) takes the *already-built* shared service graph as constructor arguments and closes over it; the tool callables are plain `async` functions that translate LLM-friendly arguments into a `ScanSpec`/`TargetSpec`, call a service, and JSON-clean the result. The `FastMCP` instance is passed in, never built here (`scan_tools.py:28`), so the module is decoupled from MCP and unit-testable with fake services and no network.

The request path for a scan is identical to `POST /v1/scans`:

```
MCP tool  start_scan(endpoint=…, api_key=…, mode="ladder")        scan_tools.py:264
   │  builds a validated ScanSpec(TargetSpec(...)) via _spec()    scan_tools.py:206
   ▼
ScanService.create_scan(spec, org_id=<server-bound>)             scan_service.py:34
   │  validates · encrypts the raw target key into the SecretStore (→ api_key_ref)
   │  persists a ScanRecord in QUEUED · enqueues a JobQueue job · returns in ms
   ▼  { scan_id, status: "queued" }                              ← returned to the model
   ⋮  (out of band)
ScanWorker  lease → mark RUNNING → ScanEngine.run (streaming progress) → save report → COMPLETED
   │  worker.py — the ONLY place a scan executes; many workers, one store+queue
   ▼
ReportService.build_json(scan_id)  ← get_report / list_findings / create_jira_ticket read this
```

`DefaultScanService` (`scan_service.py:18`) "owns no execution — it only writes records and enqueues jobs"; `DefaultScanEngine` (`engine.py:38`) is "a thin wrapper over the existing SDK reproduction pipeline … reimplements no scan logic of its own"; `ScanWorker` (`worker.py`) is "deliberately the *only* place a scan actually executes." MCP is a fourth caller of that one spine — the SDK is in-process, the API and dashboard go over HTTP, MCP goes over JSON-RPC, and all four mint the same `ScanRecord` on the same queue. This is also why the in-process worker started in the API's `_lifespan` (`api/main.py:165-174`, `ROGUE_INPROCESS_WORKER=1`) executes MCP-started scans for free on the single-service deploy: the MCP tool enqueues, the in-process worker drains the same queue.

## The tool surface

Two families on one `FastMCP("rogue")` instance. The **read tools** are registered at import time in `server.py` (decorated `@mcp.tool()` inline); the **action tools** are attached later by `register_scan_tools` during `_wire_platform()`. Below is the *design intent* per group — the full schemas are the source-of-truth docstrings in the two modules, and `docs/mcp.md` carries the human-readable catalog.

### Read · threat-intelligence (`server.py`, 6 tools, read-only)

These answer "what attacks exist / what's breaching / am I exposed?" against ROGUE's own continuously-harvested threat corpus. They take no customer target, spend no money, and read global already-computed data through a lazy direct session (`_get_session`, `server.py:92`) — never through `ScanService`, because there is no scan and no tenant to scope. The set:

- **`query_worst_attacks(model_family?, limit?)`** — the fast "am I exposed?" answer (`server.py:415`). The design subtlety: an assistant passes *its own* model identity and ROGUE maps it to the closest deployment config via a priority substring scan (`_MODEL_FAMILY_TOKENS`, `server.py:402`), so the user never has to name a model. Specific Claude tiers (`opus`/`sonnet`/`haiku`) win over the generic provider fallback.
- **`query_attacks` / `query_attack_detail`** — browse/filter the primitive corpus, and pull one primitive's full record plus its per-config breach histogram (`n_full`/`n_partial`/`n_refused`/`n_evaded`).
- **`query_diff` / `query_threat_brief`** — the day-over-day diff and the full CISO-readable brief, both routed through `ThreatBriefBuilder` with a disk-artifact-then-live-render fallback.
- **`query_breaches_for_config`** — per-trial breach results for one deployment config with judge rationale and response excerpts.

`list_integrations` (below) is the one read-only *action*-module tool that also belongs to this "takes no target, spends no money" class — it discovers integration names so the workflow tools can reference them.

### Validate (`scan_tools.py`, 1 tool)

- **`validate_target`** (`scan_tools.py:232`) — a cheap pre-flight probe delegating to `engine.validate(spec)`: reachable? credential authenticates? model responds? which modalities (image/audio)? No attacks run; near-zero cost. It exists so an agent confirms a `TargetSpec` is good *before* spending on a full scan, and it answers inline (it's a single round-trip, not a queued job).

### Scan (`scan_tools.py`, 4 tools)

- **`start_scan`** (264), **`get_scan_status`** (312, aliased **`get_scan`** at 687 for back-compat), **`cancel_scan`** (344), **`list_scans`** (363) — the async-job lifecycle. `start_scan` enqueues and returns `{scan_id, status:"queued"}`; the rest poll, cancel, and enumerate. `mode` chooses the run strategy (`"pack"` / `"repertoire"` / `"ladder"`), the deepest of which (`ladder`) is the full escalation arsenal. The target `api_key` is redacted before the scan is persisted (the redaction happens in `ScanService` via the `SecretStore`, not here).

### Report (`scan_tools.py`, 2 tools)

- **`get_report`** (389) and **`list_findings`** (415) — pure reads of an already-terminal scan's `ReportService.build_json` output. `get_report` renders a concise pasteable markdown summary by default (the `_markdown` helper, `scan_tools.py:115`, leads with the score, the "N/M breached" line, and the top findings each with its remediation) or returns the structured dict for `format="json"`. `list_findings` flattens the same payload to one row per reproduced attack.

### Benchmark (`scan_tools.py`, 2 tools)

- **`run_benchmark`** (433) / **`get_benchmark`** (466) — run a fixed public dataset (AdvBench / JailbreakBench) so the result is comparable to *published* numbers, unlike a scan which reproduces ROGUE's harvested corpus. Same start+poll shape as a scan, routed through `BenchmarkService.create` / `get`.

### Workflow · Level-3 (`scan_tools.py`, 4 tools)

- **`create_executive_summary`** (485), **`send_slack_alert`** (508), **`create_jira_ticket`** (559), **`list_integrations`** (670) — these turn a finished scan into the artifacts a security team acts on (covered in §"Level-3 workflow composition").

### Integrations-discovery

- **`list_integrations`** (670) — names + kinds of the org's stored Slack/Jira integrations, never a secret. It's the bridge between "the agent has a finished scan" and "the agent can deliver it": the agent discovers which `integration=` names exist, then references one in `send_slack_alert` / `create_jira_ticket`.

**The full action-tool registry** (the authoritative current set, from `scan_tools.py:691-707`): `validate_target`, `start_scan`, `get_scan_status`, `get_scan` (alias), `cancel_scan`, `list_scans`, `get_report`, `list_findings`, `run_benchmark`, `get_benchmark`, `create_executive_summary`, `send_slack_alert`, `create_jira_ticket`, `list_integrations` — 13 distinct tools plus one alias. Together with the 6 read tools that is **19 distinct tools** on the one server. (The superseded `docs/platform/integrations/mcp.md` design spec describes an earlier 5-tool action plan with a different naming/shape — it is stale; the registry above is what the code ships.)

## Async-job semantics over MCP — start + poll

A scan is a queued job, not a synchronous call. A full default-pack scan is dozens of customer-model round-trips plus judge calls — far longer than any MCP client holds a single tool call open, and the whole platform's load-bearing invariant is *never run a scan in the request thread*. So the MCP surface mirrors the API's async contract exactly:

- **`start_scan` enqueues and returns immediately** with `{scan_id, status:"queued"}` (`scan_tools.py:307-308`). No engine runs in the tool call — `ScanService.create_scan` writes a `ScanRecord` and an enqueued job, then returns in milliseconds.
- **`get_scan_status` is polled until terminal.** While running, `status` is `queued`/`running` and `_summarize` (`scan_tools.py:91`) reports `"Scan running — 40% complete"`; once `completed`, `n_breaches`/`top_attack`/`score` populate and `summary` reads `"7 vulnerabilities found, top: Crescendo"`. The terminal statuses are `completed | failed | canceled` (the `ScanStatus` enum — MCP echoes it, never redefines it).

A coding agent drives the loop itself: `start_scan` → poll `get_scan_status` until terminal → `get_report`. The model's only job is poll-until-terminal-then-narrate; all execution is server-side and identical to the SDK/API because it is literally the same `ScanService` call. There is no MCP-initiated server push — the mounted transport is `stateless_http=True` (`api/main.py:146`), each tool call is self-contained, so polling (not streaming) is the contract, and the endpoint survives a multi-worker/autoscaled host. `validate_target` and `get_report` are the exceptions that answer inline: `validate` is one cheap round-trip, and `get_report` is a pure read of an already-terminal artifact. `run_benchmark` follows the same start+poll shape as `start_scan`.

## Auth & tenancy

**The mounted endpoint is open today.** DNS-rebinding protection is deliberately disabled for the public host (`enable_dns_rebinding_protection=False`, `api/main.py:150-152` — it guards localhost servers from malicious web pages, not the threat model for a public read-only endpoint), and CORS is wide open (`allow_origins=["*"]`, `api/main.py:203-210`). Any client can connect and call the read tools anonymously. That is acceptable for read-only *global* threat data; per-tenant MCP auth is a v2 item (below).

**The org is server-bound, never an LLM argument.** `register_scan_tools(..., org_id=...)` (`scan_tools.py:177`) closes over the tenant the connection authenticated as; in the deployed product `_wire_platform` binds it from `ROGUE_MCP_ORG_ID` (defaulting to `"demo"`, `api/main.py:282`). Because `org_id` is captured in the closure, no tool callable takes it as a parameter — a model physically cannot address another tenant's scans (`scan_tools.py:20-24`, `192-194`). When per-tenant auth lands, the only change is *where* `org_id` comes from (the resolved API key's `AuthContext` instead of an env var); the invariant — org is never a tool arg — is unchanged.

**Stored integrations — the secref indirection.** A target's API key is redacted on persist by `ScanService`'s `SecretStore` (`secrets.py` — Fernet ciphertext in the `secrets` table, the queue carries only an `api_key_ref` handle). The *destination* credentials for Slack and Jira are handled the same way but registered ahead of time, not passed by the agent:

```
admin runs  scripts/add_integration.py --org <id> --kind slack --name slack-sec --webhook <url>
   │
   ▼
IntegrationStore.put(org_id, kind, name, config, secret)        integration_store.py:70
   │  config  (non-secret: jira base_url / project_key / email)  → integrations.config  (plaintext row)
   │  secret  (webhook URL / jira api_token) → SecretStore.put() → secrets.ciphertext   (Fernet)
   │                                                              → integrations.secret_ref (handle)
   ▼
agent calls  send_slack_alert(scan_id, integration="slack-sec")
   │  IntegrationStore.get(org_id, "slack-sec")  → resolves config + SecretStore.resolve(secret_ref)
   ▼  the raw webhook/token exists only in worker/tool memory at send time; the LLM saw only the NAME
```

The model never handles a webhook URL or an API token — it passes the integration's *name*, and ROGUE decrypts the secret server-side (`scan_tools.py:533-540` for Slack, `592-602` for Jira). `list_integrations` returns names + kinds only (`integration_store.py:108-113`). The integration store is only built when a `SecretStore` exists (i.e. `SECRET_ENCRYPTION_KEY` is set, `integration_store.py:116-126`); without it the tools fall back to the raw-args back-compat path and `list_integrations` reports nothing configured. Both `SecretStore.resolve` and `IntegrationStore.get` re-assert `org_id` on every call (`secrets.py:84`), so a cross-tenant resolve returns nothing — the stored-integration model is tenant-scoped by construction.

## Level-3 workflow composition — agent as security consultant

The action tools compose into a single agent-run consult: the user gives one instruction and the agent runs validate → scan → poll → read → summarize → *deliver*, never touching a dashboard or a credential. The three Level-3 tools are what close the loop from "I found vulnerabilities" to "I delivered the fix list":

- **`create_executive_summary(scan_id)`** — `ReportService.build_executive_summary` renders a CISO-ready markdown digest: headline score and risk band, the critical/high findings with remediation, and a business-impact line a non-engineer can act on.
- **`send_slack_alert(scan_id, integration="slack-sec")`** — builds a Block Kit summary from the scan record's aggregates and POSTs it to the resolved webhook. The destination swallows transport errors so a Slack outage never raises across the MCP boundary — it returns `{ok:false}` instead (`scan_tools.py:551-555`).
- **`create_jira_ticket(scan_id, integration="jira-prod")`** — files one ticket per breached critical/high finding (`_TICKETABLE_SEVERITIES`, `scan_tools.py:61`), *idempotently*: each finding gets a stable `finding_id` and an already-open `rogue-<fid>`-labelled ticket is skipped, so re-scans converge rather than spam the board (`scan_tools.py:645-666`). Returns `{created, skipped}`.

The composition is the differentiator: `list_integrations` → `validate_target` → `start_scan` → `get_scan_status` (poll) → `get_report` → `create_executive_summary` → `send_slack_alert` + `create_jira_ticket` is a complete security consult the customer's own agent runs in-IDE. That turns MCP from "a second API" into a distribution channel — the agent the customer already lives in does the whole job, from "test this" to "tickets filed." (The two worked transcripts are in `docs/mcp.md` §"Agentic workflows".)

## Transports & deployment

One server definition, two transports (`server.py:622` `main()`):

- **streamable-http — mounted, not a separate service.** In the deployed product the same `FastMCP("rogue")` instance is mounted into the FastAPI app: `rogue_mcp.streamable_http_path = "/"` then `app.mount("/mcp", _mcp_app)` (`api/main.py:142-211`), so it ships on the already-deployed API host with zero extra infrastructure. The mount is `stateless_http=True` (`api/main.py:146`) and DNS-rebind protection is off (150-152). The MCP session-manager lifespan is nested under the API's `_lifespan` (`api/main.py:178-180`) so the transport runs for the server's lifetime. The live endpoint is **`https://rogue-private.onrender.com/mcp`** (the platform service that has the action tools wired).
- **stdio — local default.** Claude Desktop spawns `python -m rogue.mcp_server.server` and talks over stdin/stdout; logs go to stderr so they never corrupt the JSON-RPC stream on stdout (`server.py:636-641`). `ROGUE_MCP_TRANSPORT` (`stdio` | `sse` | `streamable-http`) selects the standalone transport for a local HTTP run, with `ROGUE_MCP_HOST` / `ROGUE_MCP_PORT` overriding the default `127.0.0.1:8001` (a dedicated port that never collides with the dashboard backend on 8000).

The `mcpServers` client-config shapes (remote URL vs. local `command`/`args`) are in `docs/mcp.md` §"Connect" — that's the usage reference; this doc points at it rather than duplicating the snippets.

## Where it lives + invariants + what it must NOT do

**Module map.**

| File | Role |
|---|---|
| `src/rogue/mcp_server/server.py` | The `FastMCP("rogue")` instance, the 6 read tools, the `_get_session` lazy DB session, `main()` + transport selection. |
| `src/rogue/mcp_server/scan_tools.py` | `register_scan_tools` + all 13 action tools (closures over the service graph). Imports/instantiates no `FastMCP`. |
| `src/rogue/api/main.py` | Mounts `/mcp` (211), `_wire_platform` builds the service graph and calls `register_scan_tools` with the org binding (231-285). |
| `src/rogue/platform/{scan_service,engine,report_service,benchmark_service,worker}.py` | The one engine the action tools route through. |
| `src/rogue/platform/{integration_store,secrets}.py` | The stored-integration / SecretStore model behind the Level-3 tools. |

**Invariants (all inherited from the one-engine principle):**

1. **Org is never a tool argument.** It is server-bound via the `register_scan_tools` closure (`scan_tools.py:177`, bound from `ROGUE_MCP_ORG_ID` at `api/main.py:282`). A model cannot supply or spoof the tenant it scans under.
2. **Errors return `{error: …}`, never raise across the MCP boundary.** Every action tool maps a missing/cross-tenant scan, a not-yet-completed report, a `KeyError` on cancel, or a Slack/Jira transport failure to a clean error dict (e.g. `scan_tools.py:328-329`, `357-358`, `406-408`, `551-555`, `664-665`). The model gets a readable message, not an exception.
3. **No scan logic in the MCP layer.** Every action tool is a thin call into a service; if an MCP scan and an API scan of the same target+pack diverge, the architecture has failed (`scan_tools.py:14-18`).
4. **No scan runs in the tool call.** `start_scan` / `run_benchmark` enqueue and return; the worker runs the engine out of band.
5. **No new status enum, record shape, or score formula.** `ScanStatus`, `ScanRecord`, and the platform `score` are owned by the platform layer; MCP echoes them and JSON-cleans enums via `_status_str` / `_enum_str`.
6. **Secrets stay server-side.** Target keys are redacted on persist; Slack/Jira creds are referenced by name and decrypted server-side. The LLM never sees a raw credential.

**Test seams.** The Slack sender (`_SLACK_SENDER`, `scan_tools.py:58`) and the Jira client factory (`_JIRA_CLIENT_FACTORY`, `scan_tools.py:66`) are module-level injection points — `None` in production (real `httpx` / `JiraCloudClient`), a fake recorder in tests. They live at module scope deliberately so an LLM can never inject a transport via a tool argument, and so the full build-payload → notify / create-dedup paths run offline with no network.

## Versioning & roadmap

**v1 is stable.** The 19 tools above — including the Slack/Jira Level-3 workflow tools and the per-org stored-integration config — are shipped and the contract is frozen: tool names, inputs, and output shapes will not change underneath an integration. The two load-bearing v1 invariants are the **server-side org binding** (never a tool arg) and the **start+poll async shape** for scans/benchmarks; both will hold across v1.

**v2 (not yet shipped):**

- **Per-tenant MCP auth** — `rk_live_…` / `rk_test_…` bearer keys on the `/mcp` mount, resolved through the same authentication + tenancy chain as the `/v1` API, with read tools gated by `read` scope and action tools by `scan`. This turns the currently-open public endpoint into a multi-tenant one where each client runs and reads only its own org's scans. The org binding moves from `ROGUE_MCP_ORG_ID` to the resolved key's `AuthContext` — the never-a-tool-arg invariant is unchanged.
- **`list_projects` / `create_project`** — project-scoped organization of scans, blocked on a project service in the platform layer.
- **`download_report`** — binary PDF/HTML report artifacts. v1 surfaces only text renderings (`get_report` summary/json, `create_executive_summary` markdown) because MCP is a text protocol; binary delivery needs a separate mechanism (e.g. a signed URL the user opens in the dashboard).
- **Stored-integration UI** — a dashboard surface for registering Slack/Jira integrations, replacing today's admin-only `scripts/add_integration.py` CLI path.

## Out of scope for this layer (owned elsewhere)

- The consumer-side MCP — harvest's `DiscoveryAgent` calling Bright Data's MCP server — is the harvest layer, not this producer surface.
- `ScanService` / `ScanEngine` / worker semantics (validation, queue, lease, lifecycle, cancellation, tenant scoping) — `src/rogue/platform/` + `docs/platform/ARCHITECTURE.md`.
- The `score` formula and report artifacts (`get_report` renders, doesn't define) — `ReportService` / `rogue.report`.
- Benchmark datasets and scoring (`run_benchmark` transports them) — the benchmark layer.
- The SDK's customer object model and the `/v1` REST contract — `sdk/DESIGN.md`, `sdk/CONTRACT.md`.
