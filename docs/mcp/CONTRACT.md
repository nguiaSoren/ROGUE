# ROGUE MCP server — frozen `v1` tool contract

This is the **single source of truth** for ROGUE's producer-side MCP tool surface — the tools a Claude Desktop / Cursor / Windsurf / hosted MCP client sees when it connects to the ROGUE MCP server. It is the MCP equivalent of `sdk/CONTRACT.md`: where that document freezes the SDK ⇄ Hosted-API *wire* protocol, this one freezes the MCP *tool* protocol (tool names, input parameters, and output shapes). An integrator builds against this; the code in `src/rogue/mcp_server/` implements it.

The surface is two layers on one `FastMCP` instance (`src/rogue/mcp_server/server.py`):

- **Read tools** (6) — query ROGUE's own continuously-harvested threat-intelligence DB. Read-only, global, take no customer target, spend no money. Registered as module-level `@mcp.tool()` functions in `server.py`.
- **Action tools** (14, of which one is a back-compat alias) — run and report the whole scan/benchmark/integration lifecycle against the *caller's* endpoint. Registered by `register_scan_tools(...)` in `src/rogue/mcp_server/scan_tools.py`, routed through the same `ScanService` / `ReportService` / `ScanEngine` / `BenchmarkService` that back the SDK, the HTTP API, and the dashboard. They cost real money and write per-tenant records.

## What `v1` promises

- **Tool names are stable.** Every tool name listed here remains callable for the life of `v1`. A tool is never renamed in place and never removed in `v1`.
- **Input shapes are stable.** A tool's parameter names, types, and defaults listed here do not change in `v1`. New parameters may be added only if they are **optional with a default** that preserves the current behavior (additive-only). No existing parameter is renamed, retyped, made required, or removed in `v1`.
- **Output keys are stable.** The keys this contract documents for each tool's success payload are always present with the documented type. New keys may be **added** to an output object in `v1`; existing keys are never removed or repurposed. Clients must tolerate unknown keys (forward-compatible parsing).
- **Breaking changes bump the tool name to a `v2` form** (e.g. a hypothetical `start_scan_v2`), introduced alongside the `v1` tool, not in place of it. `v1` clients keep working.

### Hard contract rule — org is never a tool argument

Tenancy is bound at the **server**, never passed by the model. For the HTTP transport the org is resolved from the per-tenant API key (`rk_live_…` → `org_<ulid>`); for stdio it comes from the connection's auth context / `ROGUE_API_KEY`. The server binds it once via `register_scan_tools(..., org_id=...)` (a closure). **No tool in this contract takes an `org_id` (or `customer_id`, or tenant) parameter** — by construction, so an LLM can never supply, spoof, or escalate the org it scans, reads, or bills under. Every action tool is implicitly scoped to the bound org; an unknown id (a scan from another org) reads back as "not found". This rule is permanent across all versions.

Likewise, the secret-handling seams (`_SLACK_SENDER`, `_JIRA_CLIENT_FACTORY` in `scan_tools.py`) are module-level test seams, **not** tool parameters — a model can never inject a transport or client.

## Conventions

- **Transport.** stdio by default (Claude Desktop spawns the process). Set `ROGUE_MCP_TRANSPORT=streamable-http` (or legacy `sse`) to serve over HTTP on `ROGUE_MCP_PORT` (default `8001`) / `ROGUE_MCP_HOST` (default `127.0.0.1`). Valid transports: `stdio` | `sse` | `streamable-http`.
- **Run:** `uv run python -m rogue.mcp_server.server`.
- **Result encoding.** Every tool returns JSON-clean values — enums are coerced to their string `.value`, datetimes to ISO-8601 strings. A tool result is a JSON object (`dict`) unless explicitly noted as a string or list.
- **Error shape.** The two layers differ deliberately and this difference is part of the contract:
  - **Read tools raise.** A bad input (unknown primitive id, bad `format`) raises a Python exception that the MCP runtime surfaces as a JSON-RPC tool error. They do **not** return an `{"error": ...}` body.
  - **Action tools never raise across the MCP boundary.** A recoverable failure (unknown/cross-org scan id, scan not completed, unresolved integration, missing credentials, transport failure) returns a plain `{"error": "<human message>"}` object (or, for `create_jira_ticket`, `{"error": ..., "created": [...], "skipped": [...]}`). The model reads the `error` string and reacts.
- **Vocabularies are imported, never redefined here.** Severity / verdict / status / family / vector values come from the schemas (see *Vocabularies* below). This contract references them; it does not own them.

---

## Read tools

Six read-only tools over the harvested threat DB (`server.py`). They take no target and no org. Filters are optional. They raise on bad input rather than returning an `error` object.

### `query_attacks(family=None, vector=None, since_days=7, limit=20)`
Browse/filter the attack-primitive corpus by family, vector, and recency.
- **Params:** `family: str | None`, `vector: str | None`, `since_days: int = 7` (use `999` for all-time), `limit: int = 20` (clamped to `1..100`).
- **Returns:** `list` of attack-primitive dicts, newest first. Each dict: `{primitive_id: str, title: str, family: str, vector: str, base_severity: str, short_description: str, payload_template: str` (truncated to 500 chars + `"...[truncated]"`)`, payload_slots: dict, reproducibility_score: float, canonical: bool, cluster_id: str | null, discovered_at: str | null` (ISO)`, requires_multi_turn: bool, requires_system_prompt_access: bool, requires_tools: list[str], sources: [{url, source_type, bright_data_product, author, fetched_at}]}`.

### `query_diff(date_str=None)`
Today's threat-brief diff vs the day before — what is newly breaching / newly defended.
- **Params:** `date_str: str | None` — ISO `"YYYY-MM-DD"`. Default resolves to the **most-recent run day with breach data** (falls back to today UTC if the matrix is empty), not a bare "today".
- **Returns:** the JSON form of `ThreatBriefBuilder.render_json`: `{summary: {new_critical, new_high, new_medium, new_low, newly_defended, total_today, total_yesterday, net_delta}, new_critical: [...], new_high: [...], new_medium: [...], new_low: [...], ...}`. Internally scoped to the demo `customer_id="acme"` (server-bound, not a parameter).

### `query_threat_brief(date_str=None, format="markdown")`
The full daily threat brief for a date.
- **Params:** `date_str: str | None` (ISO, default = most-recent run day, as in `query_diff`); `format: str = "markdown"` — `"markdown"` | `"json"`.
- **Returns:** a **string** — the brief file's contents (`data/threat_briefs/<date>.{md,json}`), or a live render from the DB if the artifact isn't on disk yet. Raises `ValueError` if `format` is neither `markdown` nor `json`.

### `query_breaches_for_config(deployment_config_id, since_days=7, limit=50)`
Per-trial breach results for one customer deployment config (model × system prompt × tools), with judge rationale + model-response excerpts.
- **Params:** `deployment_config_id: str` (e.g. `"acme-claudehaiku-20260526"`); `since_days: int = 7`; `limit: int = 50` (clamped to `1..200`).
- **Returns:** `list` of breach dicts, most recent first. Each: `{breach_id: str, primitive_id: str, primitive_title: str, deployment_config_id: str, trial_index: int, verdict: str, judge_confidence: float | null, judge_rationale: str` (truncated 500)`, model_response_excerpt: str` (truncated 500)`, ran_at: str | null` (ISO)`}`.

### `query_attack_detail(primitive_id)`
One attack's full record (untruncated payload) + its per-config breach aggregates.
- **Params:** `primitive_id: str` (ULID-shaped). **Raises** `ValueError` if the primitive is not found.
- **Returns:** `{primitive: <full primitive dict, same keys as query_attacks but with the full untruncated payload_template>, breaches: [{deployment_config_id, config_name, target_model, n_trials, n_full_breach, n_partial_breach, n_refused, n_evaded, n_error, avg_confidence: float | null, last_ran_at: str | null}]}`.

### `query_worst_attacks(model_family=None, limit=10)`
The fast "am I exposed?" answer — the hardest-breaching attacks, optionally scoped to the config closest to a given model. An assistant answering "what would hit a model like me?" passes its own model identity.
- **Params:** `model_family: str | None` — a full id (`"claude-opus-4-8"`), tier (`"opus"`/`"sonnet"`/`"haiku"`), or provider (`"gpt"`/`"openai"`, `"gemini"`/`"google"`, `"llama"`/`"meta"`, `"mistral"`, `"claude"`/`"anthropic"`); specific tiers win over providers; `None` = worst across all configs. `limit: int = 10` (clamped to `1..50`).
- **Returns:** `{matched_config: {config_id, config_name, target_model} | null, note: str, attacks: [{primitive_id, title, family, vector, config_name, target_model, any_breach_rate: float, full_breach_rate: float, n_trials: int}]}`, sorted any-breach desc then full-breach desc. An unmappable `model_family` returns `{matched_config: null, note: <explanation>, attacks: []}` (a clean empty result, not an error).

---

## Action tools

Fourteen tools from `register_scan_tools(...)` (one is a back-compat alias of another). All are `async`. All are org-scoped to the server-bound org. None raises across the MCP boundary — a recoverable failure returns `{"error": "<message>"}`.

The four target tools (`validate_target`, `start_scan`, `run_benchmark`) share the same target inputs: provide **either** `endpoint` (a custom OpenAI-compatible URL) **or** `provider` (a hosted provider name); `model` and `api_key` are optional. `api_key` is the *target's* credential — it is redacted before any record is persisted and never logged or stored raw. Supplying neither `endpoint` nor `provider` raises a validation error from `TargetSpec` that surfaces as the tool's error.

### Validate

#### `validate_target(endpoint=None, provider=None, api_key=None, model=None)`
Cheap pre-flight on a target before spending on a scan — checks reachability, auth, model response, and supported modalities. Near-zero cost; runs no attacks.
- **Returns:** `{target: str, reachable: bool, authenticated: bool, model_responds: bool, supports_image: bool, supports_audio: bool, error: str | null, ok: bool}`. `ok` is `true` only when `reachable and authenticated and model_responds`.
- **Credentials/destinations:** `api_key` (target credential; used live, not stored).

### Scan

#### `start_scan(endpoint=None, provider=None, api_key=None, model=None, pack="default", mode="pack", max_tests=20, budget=None)`
Start a red-team scan against your endpoint. Returns immediately; poll `get_scan_status`.
- **Params:** target inputs (above) plus `pack: str = "default"`; `mode: str = "pack"` — `"pack"` (curated pack) | `"repertoire"` (live harvested corpus) | `"ladder"` (full escalation arsenal — deepest + most expensive); `max_tests: int = 20`; `budget: float | None` (optional USD cap).
- **Returns:** `{scan_id: str, status: str}` (status `"queued"`).
- **Credentials/destinations:** `api_key` (target credential; redacted on persist).

#### `get_scan_status(scan_id)`
Poll a scan's status and results by id. While running, `summary` reports progress; once `"completed"`, the result fields populate.
- **Returns:** `{scan_id: str, status: str, progress: int` (0–100)`, n_tests: int, n_completed: int, n_breaches: int, top_attack: str | null, score: float | null, summary: str}`. Unknown/cross-org id → `{error: "scan not found: <id>"}`.

#### `get_scan(scan_id)`
**Back-compat alias of `get_scan_status`** — the original tool name before the catalog grew. Identical signature and output. Retained for life of `v1`.

#### `cancel_scan(scan_id)`
Cancel a queued or running scan (no-op on a finished scan).
- **Returns:** `{scan_id: str, status: str}` (`"canceled"` once stopped). Unknown/cross-org id → `{error: "scan not found: <id>"}`.

#### `list_scans(limit=20)`
List this org's recent scans, newest first.
- **Params:** `limit: int = 20`.
- **Returns:** `{scans: [{scan_id: str, status: str, target: str | null` (the redacted endpoint or provider — never a raw key)`, score: float | null, n_breaches: int, created_at: str | null` (ISO)`}], count: int}`.

### Report

#### `get_report(scan_id, format="summary")`
Fetch a completed scan's report.
- **Params:** `scan_id: str` (must be COMPLETED); `format: str = "summary"` — `"summary"` | `"json"`.
- **Returns:**
  - `format="summary"` → a **markdown string** (headline `risk N/100 (level)`, the `N/M attacks breached` line, and top findings each with technique, severity, success %, and remediation) — pasteable to a user.
  - `format="json"` → the **full report dict**: the `ReportService.build_json` payload = `{target: str, n_tests: int, n_breaches: int, breach_rate: float, top_attack: str | null, cost_usd: float, findings: [<finding>], score: float` (0–100)`, risk_level: str, score_methodology: str}`. Each `<finding>`: `{family: str, technique: str` (humanized)`, vector: str` (humanized)`, severity: str, title: str, success_rate: float, n_trials: int, n_breach: int, breached` is derived `n_breach > 0`, `example_attack: str | null, example_response: str | null, remediation: str}`.
  - Unknown / not-completed / no-report → `{error: <message>}`.

#### `list_findings(scan_id)`
A completed scan's findings as flat rows (one per reproduced attack).
- **Returns:** `{findings: [{family: str | null, technique: str | null, vector: str | null, severity: str | null, breached: bool, success_rate: float | null, remediation: str | null}]}`. Unknown / not-completed → `{error: <message>}`. (A projection of the `get_report(format="json")` findings — the `_finding_row` subset.)

#### `create_executive_summary(scan_id)`
A CISO-ready executive summary of a completed scan, as markdown (headline risk, breach ratio, critical & high findings with remediation, one-line business framing).
- **Returns:** `{summary: <markdown string>}`. Unknown / not-completed → `{error: <message>}`.

### Benchmark

#### `run_benchmark(endpoint=None, provider=None, api_key=None, model=None, dataset="advbench_100", max_goals=25)`
Run a standard-dataset ASR benchmark (e.g. AdvBench / JailbreakBench) against a target so a result is comparable to published numbers. Async; poll `get_benchmark`.
- **Params:** target inputs (above) plus `dataset: str = "advbench_100"`; `max_goals: int = 25`.
- **Returns:** `{benchmark_id: str, status: str}` (status `"queued"`).
- **Credentials/destinations:** `api_key` (target credential; redacted on persist).

#### `get_benchmark(benchmark_id)`
Fetch a benchmark's status + result by id.
- **Returns:** the `BenchmarkRecord` dict (`model_dump(mode="json")` with `status` coerced to its string): `{benchmark_id: str, org_id: str, dataset: str, target: dict` (redacted snapshot)`, status: str, n_goals: int, n_success: int, asr: float | null, cost_usd: float, cost_per_success: float | null, winner_rank: int | null, error: str | null, created_at: str | null, completed_at: str | null}`. Unknown/cross-org id → `{error: "benchmark not found: <id>"}`.

### Workflow / Integrations

The two destination tools support **two credential paths**. The **preferred** form passes `integration=<name>` — the NAME of a Slack/Jira integration the org stored once (discover names via `list_integrations`); ROGUE resolves the secret server-side and the model never handles it. The **back-compat** form passes the raw credentials/destination directly. The `integration=` path requires the server to have been built with an `integration_store`; without one, only the raw-args path works and `list_integrations` reports nothing is configured.

#### `list_integrations()`
Discover the org's stored Slack/Jira integrations by name + kind — **never any secret**.
- **Returns:** `{integrations: [{kind: str, name: str}]}` — or `{integrations: [], note: "no stored integrations configured"}` when no store is bound.

#### `send_slack_alert(scan_id, integration=None, webhook_url=None)`
Post a scan's result (Block Kit summary: score / breach ratio / top attack) to a Slack channel via an incoming webhook. Transport errors are logged+swallowed (a Slack outage never raises).
- **Params:** `scan_id: str`; **destination** — `integration: str | None` (preferred; the NAME of a stored Slack integration) **or** `webhook_url: str | None` (back-compat; the raw incoming-webhook URL).
- **Returns:** `{ok: bool, status: str}` — `{ok: true, status: "sent"}` on success; `{ok: false, status: "send failed: <exc>"}` if delivery failed. Error cases → `{error: <message>}`: unknown scan id, unknown integration name, an integration whose `kind` isn't `slack`, or neither `integration` nor `webhook_url` given.
- **Credentials/destinations:** `webhook_url` (a secret); or `integration` (a name resolving to one server-side).

#### `create_jira_ticket(scan_id, integration=None, base_url=None, project_key=None, email=None, api_token=None)`
File a Jira ticket for each **critical/high breached** finding of a scan, **idempotently** — a finding already carrying its stable `rogue-<finding_id>` label on an open ticket is skipped, so re-scans converge rather than spam the board.
- **Params:** `scan_id: str` (must be COMPLETED); **destination/creds** — preferred `integration: str | None` (the NAME of a stored Jira integration; resolves `base_url`/`project_key`/`email`/`api_token` server-side) **or** the back-compat raw set, all four required together: `base_url: str | None` (e.g. `"https://acme.atlassian.net"`), `project_key: str | None` (e.g. `"SEC"`), `email: str | None` (Basic-auth user), `api_token: str | None` (Basic-auth secret).
- **Returns:** `{created: [issue_key, ...], skipped: [finding_id, ...]}`. Error cases → `{error: <message>}` (and, when a Jira call fails mid-loop, `{error: "jira: <exc>", created: [...], skipped: [...]}` carrying partial progress): unknown/not-completed scan, unknown integration name, an integration whose `kind` isn't `jira`, or an incomplete raw cred set.
- **Credentials/destinations:** `api_token` (a secret) + `base_url`/`project_key`/`email`; or `integration` (a name resolving to them server-side).

---

## Vocabularies (source of truth, not redefined here)

The string values that appear in tool outputs are owned by the schemas — this contract references them so they can never drift:

- **`severity` / `base_severity`** — `low` | `medium` | `high` | `critical`. Source: `rogue.schemas.attack_primitive.Severity`.
- **`risk_level`** (report headline) — `low` | `medium` | `high` | `critical`, banded from the 0–100 `score`. Source: `rogue.platform.report_service` scoring (`SCORE_METHODOLOGY`).
- **`verdict`** (breach results, and the `n_full`/`n_partial`/`n_refused`/`n_evaded`/`n_error` aggregate buckets) — `refused` | `evaded` | `partial_breach` | `full_breach` | `error`. "Breached" = `partial_breach` ∪ `full_breach`. Source: `rogue.schemas.breach_result.JudgeVerdict` (+ `BREACH_VERDICTS`).
- **`status`** (scans and benchmarks) — `queued` | `running` | `completed` | `failed` | `canceled`. Source: `rogue.platform.schemas.ScanStatus`.
- **`family`** — ROGUE's 15-family taxonomy (`jailbreak`, `indirect_prompt_injection`, `multimodal_injection`, …). Source: `rogue.schemas.attack_primitive.AttackFamily`.
- **`vector`** — the injection vector (`user_turn`, `rag_document`, `tool_output`, `system_prompt`, …). Source: `rogue.schemas.attack_primitive.AttackVector`.

`mode` (`pack` | `repertoire` | `ladder`) is owned by `rogue.platform.schemas.ScanSpec`; `source_type` / `bright_data_product` (in primitive `sources`) are owned by `rogue.schemas` `Literal` types.

---

## Versioning rules

**The `v1` stable set is exactly the 20 tools above** — 6 read tools + 14 action tools (`get_scan` being the alias of `get_scan_status`). These names, their documented inputs, and their documented output keys are frozen for `v1` under the promises at the top of this document. Additive evolution (new optional params with safe defaults; new output keys) is allowed in `v1`; renames/removals/retypes/required-additions are not.

**Not in the `v1` contract** (roadmap; will arrive as new tools / new optional params, never as breaking changes to the above):

- **Project tools** — `list_projects` / `create_project`. Scans already carry an optional `project_id` on the record, but no MCP tool exposes project CRUD in `v1`.
- **`download_report` (PDF/HTML)** — `get_report` ships `summary` (markdown) and `json` only in `v1`; a PDF/HTML artifact path is a v2 addition.
- **Per-tenant MCP auth** — the HTTP transport is currently unauthenticated for the read tools and binds a single org for the action tools; the per-tenant `rk_live_…` → `org_<ulid>` bearer auth on the `/mcp` mount (matching the `/v1` API) is roadmap, not part of this tool contract.
- **Stored-integration management UI / tools** — `list_integrations` is read-only; creating/updating/deleting integrations happens out-of-band (dashboard / API), not via an MCP tool in `v1`.
