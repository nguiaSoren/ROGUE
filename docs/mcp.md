# ROGUE MCP — the threat DB and the scan lifecycle, as a tool surface

> **This is the usage/integration guide.** For the design/architecture see [`docs/mcp/ARCHITECTURE.md`](mcp/ARCHITECTURE.md); for the frozen per-tool v1 interface see [`docs/mcp/CONTRACT.md`](mcp/CONTRACT.md).

## What it is

ROGUE exposes its **own** Model Context Protocol server. This is the producer role: ROGUE is the server, and any MCP-speaking client — Claude Desktop, Cursor, ChatGPT, Windsurf, or anything that speaks the protocol — is the client. (ROGUE also uses MCP as a *consumer* inside its harvest pipeline, where the `DiscoveryAgent` calls Bright Data's MCP server to find novel attacks off the open web; that path is internal and is not what this document covers.) The producer server is the `FastMCP("rogue")` instance defined in `src/rogue/mcp_server/server.py`, and it is the piece that lets a coding agent work with ROGUE without ever opening the dashboard.

Two things live behind that one surface. The first is **threat intelligence**: an agent can query ROGUE's live breach matrix — the real jailbreaks and prompt-injection attacks ROGUE harvests from 15+ open-web sources, reproduces against deployment configs, and grades with an independent judge — and ask questions like "what's breaching hardest against a model like me?" or "what changed today?". The second is the **full scan lifecycle**: an agent can point ROGUE at a customer's own endpoint, validate it, run a red-team scan, poll it to completion, pull the report, and benchmark it — the same engine the SDK, the HTTP API, and the dashboard run, reached as a fourth surface. An agent can drive a real security workflow end to end from inside the editor. That round trip — "scan my staging endpoint" answered in-IDE, no console, no context switch — is the differentiator.

## Connect

The server runs from a single definition over two transports.

**Remote (streamable-http).** In the deployed product the HTTP transport is not a separate service: the same `FastMCP("rogue")` instance is mounted into the FastAPI app at `app.mount("/mcp", _mcp_app)` (`src/rogue/api/main.py:170`), so it ships on the already-deployed API host. The live endpoint is:

```
https://rogue-private.onrender.com/mcp
```

The mount is configured `stateless_http=True` (`src/rogue/api/main.py:146`), so every tool call is self-contained and the endpoint survives a multi-worker, autoscaled host. There is no server-initiated streaming — the contract is request/response (and, for scans, poll; see below).

**Local (stdio).** For a local Claude Desktop setup the client spawns the server as a subprocess and talks to it over stdin/stdout. Run it directly:

```bash
ROGUE_MCP_TRANSPORT=stdio uv run python -m rogue.mcp_server.server
```

`ROGUE_MCP_TRANSPORT` accepts `stdio` (the default) | `sse` | `streamable-http`; `ROGUE_MCP_HOST` / `ROGUE_MCP_PORT` override the HTTP bind address (default `127.0.0.1:8001` for a standalone local HTTP run).

**Client config.** For a remote (hosted) connection, point the client's `mcpServers` block at the live URL:

```json
{
  "mcpServers": {
    "rogue": {
      "url": "https://rogue-private.onrender.com/mcp",
      "transport": "streamable-http"
    }
  }
}
```

For a local stdio connection, have the client spawn the process instead:

```json
{
  "mcpServers": {
    "rogue": {
      "command": "uv",
      "args": ["--directory", "/path/to/ROGUE", "run", "python", "-m", "rogue.mcp_server.server"]
    }
  }
}
```

**Auth, honestly.** Today the mounted public MCP endpoint is **open**: DNS-rebinding protection is deliberately disabled for the public host (`enable_dns_rebinding_protection=False`, `src/rogue/api/main.py:150`) and CORS is wide open, so any client can connect and call the read tools anonymously. That is acceptable for read-only global threat data. The org a scan runs under is **bound by the server**, never passed as a tool argument — for the HTTP transport it derives from the connection's auth context; for stdio it derives from the spawning environment. Per-tenant MCP auth with `rk_live_…` keys — so an authenticated client can run and read *only its own* org's scans, with the same key, scope ladder, and rate limits as the `/v1` API — is a **v2 item** (see Versioning). Until then, treat the action tools as operating under a single server-bound org.

## Tool catalog (v1)

Every tool below is on the one `FastMCP("rogue")` instance. The `org` a tool operates under is resolved and bound by the server; it is **never** a tool argument, so a model can neither supply nor spoof the tenant it scans. The read tools query the harvested threat DB through a direct SQLAlchemy session; the action tools route through the shared `ScanService` / `ScanEngine` — the same one-engine spine behind the SDK, the API, and the dashboard, so an MCP scan and an API scan of the same target are identical by construction.

### Read — threat intelligence

These read ROGUE's global, already-computed threat data. They take no customer target and spend no money.

- **`query_worst_attacks(model_family?, limit?)`** — the fast "am I exposed?" answer: the hardest-breaching attacks, all-time. Pass your own model identity (`"claude-opus-4-8"`, a tier like `"opus"`, or a provider like `"openai"`) to scope to the closest deployment config; omit it for the worst across all configs. Returns `{matched_config, note, attacks:[{primitive_id, title, family, vector, config_name, target_model, any_breach_rate, full_breach_rate, n_trials}]}`, sorted worst-first.
- **`query_attacks(family?, vector?, since_days?, limit?)`** — browse/filter the attack-primitive corpus by family, injection vector, or recency. Returns a list of primitives (newest first), each with `primitive_id, title, family, vector, base_severity, short_description, payload_template (truncated), reproducibility_score, discovered_at, canonical, sources[]`.
- **`query_diff(date?)`** — what changed on a date versus the day before: newly-breaching and newly-defended cells with per-severity counts. Returns `{summary:{new_critical, new_high, new_medium, new_low, newly_defended, total_today, total_yesterday, net_delta}, new_critical:[…], new_high:[…], …}`.
- **`query_threat_brief(date?, format?)`** — the full daily CISO-readable threat brief for a date, as a string. `format` is `"markdown"` (default) or `"json"`. Falls back to a live DB render if the artifact file isn't on disk yet.
- **`query_breaches_for_config(deployment_config_id, since_days?, limit?)`** — per-trial breach results for one deployment config, with judge rationale and model-response excerpts. Returns a list of `{breach_id, primitive_id, primitive_title, deployment_config_id, trial_index, verdict, judge_confidence, judge_rationale (truncated), model_response_excerpt (truncated), ran_at}`.
- **`query_attack_detail(primitive_id)`** — one attack's full record plus its per-config breach aggregates. Returns `{primitive:{…full payload + slots…}, breaches:[{deployment_config_id, config_name, target_model, n_trials, n_full_breach, n_partial_breach, n_refused, n_evaded, n_error, avg_confidence, last_ran_at}]}`.
- **`list_integrations()`** — discover the org's stored Slack/Jira integrations by name + kind, so an agent knows which `integration=` names it can pass to `send_slack_alert` / `create_jira_ticket`. Returns `{integrations:[{kind, name}]}` — **names and kinds only, never a secret**; webhook URLs and API tokens stay encrypted server-side. Returns an empty list with a note when no integration store is configured. Takes no customer target and spends no money.

### Validate

- **`validate_target(endpoint?, provider?, api_key?, model?)`** — a cheap pre-flight probe on a target before spending on a scan: confirms the endpoint is reachable, the credential authenticates, the model responds, and which modalities (image/audio) it supports. No attacks run; near-zero cost. Provide either `endpoint` (a custom OpenAI-compatible URL) or `provider`. Returns `{target, reachable, authenticated, model_responds, supports_image, supports_audio, ok, error}` — `ok` is true only when reachable, authenticated, and the model responds. Run this first when a user hands you a target.

### Scan

These take a customer `TargetSpec`, cost real money, and write durable per-tenant scan rows. A scan is a queued job, not a synchronous call: `start_scan` enqueues and returns immediately; the agent then polls `get_scan_status` until the scan reaches a terminal status. There is no long-running blocking tool.

- **`start_scan(endpoint?, provider?, api_key?, model?, pack, mode, max_tests, budget?)`** — enqueue a red-team scan against the target. Provide either `endpoint` or `provider`; `api_key` is the *target's* credential (redacted before persistence, never logged); `model` defaults per provider. `pack` selects the attack pack (`default` / `aggressive` / `compliance`), `mode` selects the run strategy (e.g. `"ladder"` for escalating multi-turn), `max_tests` caps attacks attempted, and `budget` is an optional USD stop. Returns `{scan_id, status}` (status `"queued"`).
- **`get_scan_status(scan_id)`** — poll a scan by id. While running, `status` is `queued`/`running` and `summary` reports progress; once `completed`, `n_breaches` / `top_attack` / `score` are populated and `summary` reads like "7 vulnerabilities found, top: Crescendo". Returns `{scan_id, status, progress, n_tests, n_completed, n_breaches, top_attack, score, summary}`. Terminal statuses are `completed | failed | canceled`.
- **`cancel_scan(scan_id)`** — request cancellation of an in-flight scan. Returns the scan's updated `{scan_id, status}`.
- **`list_scans(limit?)`** — list the org's recent scans (most recent first) with their status and headline metrics, so an agent can find a prior `scan_id` to read or resume.

### Report

- **`get_report(scan_id, format=summary|json)`** — fetch the finished report for a terminal scan. `format="summary"` returns a short prose digest the agent can relay to the user; `format="json"` returns the structured report shape. A pure read; errors if the scan is not yet completed.
- **`list_findings(scan_id, ...)`** — list the individual breach findings for a completed scan (attack, verdict, severity, judge rationale), for an agent that wants to walk the results rather than read the rolled-up report.

### Benchmark

- **`run_benchmark(endpoint?/provider?, dataset, max_goals?, ...)`** — run the target against a standard benchmark dataset (e.g. AdvBench / JailbreakBench). Start+poll like `start_scan` — returns `{benchmark_id, status}` (status `"queued"`); read it back with `get_benchmark`.
- **`get_benchmark(benchmark_id)`** — read a benchmark run's status and, when terminal, its result (`dataset`, `n_goals`, `n_success`, `asr`, `cost_per_success`, `winner_rank`, …) against the dataset.

### Workflow

These are the **Level-3** tools — they turn a finished scan into the artifacts and notifications a security team actually acts on, so the agent doesn't just report a result, it delivers the consult. Each takes a terminal `scan_id` and reads that scan's stored findings; the summary tool is a pure read, while the alert/ticket tools fan the result out to an external destination. The **preferred** way to reach that destination is a *stored integration*: an admin registers the org's Slack workspace or Jira site once with `scripts/ops/add_integration.py`, and the agent then passes only the integration *name* — the secret is decrypted server-side and never reaches the model (see Versioning). Each tool also accepts the raw destination credentials as arguments for a quick/demo run, and `list_integrations` lets an agent discover the names available to it.

- **`create_executive_summary(scan_id)`** — render a CISO-ready markdown executive summary for a completed scan: the headline score and risk band, the critical and high findings with concrete remediation, and business framing a non-engineer can act on. Returns `{summary}` (the markdown string). A pure read; errors if the scan is not terminal.
- **`send_slack_alert(scan_id, integration?, webhook_url?)`** — post the scan result — score, breach count, and the top attack — to Slack. **Preferred:** pass `integration` — the *name* of a Slack integration the org registered once (e.g. `"slack-sec"`); ROGUE resolves the stored webhook server-side and the agent never handles the raw URL (discover the available names with `list_integrations`). Back-compat: pass `webhook_url` directly (an `https://hooks.slack.com/services/…` URL the calling user authorizes the agent with) for a quick/demo post; it is used once and not persisted. Returns `{ok, status}` — `ok` is true when Slack accepts the post.
- **`create_jira_ticket(scan_id, integration?, base_url?, project_key?, email?, api_token?)`** — file a Jira issue per breached critical/high finding, deduped so re-running the tool against the same scan won't refile a finding already ticketed. **Preferred:** pass `integration` — the *name* of a Jira integration the org registered once (e.g. `"jira-prod"`); ROGUE resolves the stored `base_url` / `project_key` / `email` plus the encrypted API token server-side and the agent never handles a credential. Back-compat: pass all four raw args (`base_url`, e.g. `https://acme.atlassian.net`; `project_key`, e.g. `SEC`; `email`; `api_token`) for a quick/demo run; they are used for the API calls and not persisted. Returns `{created, skipped}` — the lists of finding keys ticketed this call and those skipped as already-filed.

## Agentic workflows (the real value)

The point of the action tools is that a coding agent can run a complete security task on its own — the model drives the loop, ROGUE does the work server-side. Two worked sequences.

### (a) "Scan staging-api.company.com"

```
User (in Cursor):  "Scan my staging API at https://staging-api.company.com/v1"

  → validate_target(endpoint="https://staging-api.company.com/v1", api_key="sk-…")
        ← { reachable: true, authenticated: true, model_responds: true,
            supports_image: false, supports_audio: false, ok: true }

  → start_scan(endpoint="https://staging-api.company.com/v1", api_key="sk-…",
               pack="default", mode="ladder", max_tests=50)
        ← { scan_id: "scan_01J…", status: "queued" }

  → get_scan_status("scan_01J…")   ← { status: "running",  progress: 40, … }
  → get_scan_status("scan_01J…")   ← { status: "running",  progress: 85, … }
  → get_scan_status("scan_01J…")   ← { status: "completed", n_breaches: 7,
                                       top_attack: "Crescendo", score: 62,
                                       summary: "7 vulnerabilities found, top: Crescendo" }

  → get_report("scan_01J…", format="summary")
        ← { content: "7 of 50 attacks broke through. The model is most exposed to
            multi-turn escalation (Crescendo) and RAG-document injection. Risk 62/100." }

Agent → user:  "Your staging API failed 7 of 50 red-team attacks (risk 62/100).
                The biggest weakness is multi-turn escalation — the model gives
                up its guardrails when an attacker ramps up gradually over several
                turns. I'd prioritize a turn-aware refusal check next."
```

The agent validates first (cheap, catches a bad endpoint before spending), starts the scan, paces its polling until the status is terminal, then reads the summary and narrates it. No dashboard involved.

### (b) Agent as security consultant — the full Level-3 flow

This is the whole point: the user asks one question and the agent runs the entire consult — validate, scan, read, summarize, and *deliver* — without the user touching a dashboard or a ticket queue. The Workflow tools are what close that loop.

```
User:  "Test our staging endpoint and tell the team. It's at
        https://staging-api.company.com/v1, here's the key. Post to Slack and
        file Jira for the critical/high findings."

  → list_integrations()
        ← { integrations: [ { kind: "slack", name: "slack-sec" },
                            { kind: "jira",  name: "jira-prod" } ] }

  → validate_target(endpoint="https://staging-api.company.com/v1", api_key="sk-…")
        ← { ok: true, model_responds: true, supports_image: false }

  → start_scan(endpoint="https://staging-api.company.com/v1", api_key="sk-…",
               pack="default", mode="ladder", max_tests=50)
        ← { scan_id: "scan_03L…", status: "queued" }

  → get_scan_status("scan_03L…")   ← { status: "running",   progress: 55, … }
  → get_scan_status("scan_03L…")   ← { status: "completed", n_breaches: 7,
                                       top_attack: "Crescendo", score: 62,
                                       summary: "7 vulnerabilities found, top: Crescendo" }

  → get_report("scan_03L…", format="summary")
        ← { content: "7 of 50 attacks broke through. Most exposed to multi-turn
            escalation (Crescendo) and RAG-document injection. Risk 62/100." }

  → create_executive_summary("scan_03L…")
        ← { summary: "## Staging API — red-team summary\n**Risk: 62/100 (elevated).**
            7 of 50 attacks succeeded. **Critical:** RAG-document injection — an
            attacker-controlled document can override instructions… **Remediation:**
            …\n**Business impact:** a support-bot deployment could be steered to
            leak internal docs; recommend gating before GA." }

  → send_slack_alert("scan_03L…", integration="slack-sec")
        ← { ok: true, status: "sent" }

  → create_jira_ticket("scan_03L…", integration="jira-prod")
        ← { created: ["SEC-412", "SEC-413", "SEC-414"], skipped: [] }

Agent → user:  "Scanned staging: risk 62/100, 7 of 50 attacks landed (worst is
                multi-turn Crescendo escalation, plus a critical RAG-injection).
                I filed 3 Jira tickets in SEC for the critical/high findings and
                posted the summary to #security. I'd gate this before GA — the
                RAG-injection is the one to fix first."
```

The agent ran the consultant loop end to end: discover the org's registered destinations with `list_integrations`, validate the target, scan it under a ladder, pace its polling to terminal, read the report, turn it into a CISO-ready summary, and then *deliver* — push to Slack and open the right tickets by integration name, never touching a raw credential — finally narrating what it did. The user gave one instruction; ROGUE did the work and the agent closed every loop. **This is what makes MCP more than an API: it turns ROGUE into a distribution channel — the agent the customer already lives in runs the whole security consult, from "test this" to "tickets filed."**

## Versioning

The tools above are **v1** — including the Slack and Jira Workflow tools, which graduate the "push findings onward" capability out of the roadmap and into the shipped surface, and **per-tenant stored integration config**, which has now shipped (see below). The v1 contract is **stable**: tool names, their inputs, and their output shapes will not change underneath an integration. The `org` binding (server-side, never a tool argument) and the start+poll async shape for scans are load-bearing invariants of v1 and will hold.

**A note on how credentials flow.** The **preferred** path is a *stored per-org integration*. An admin registers the org's Slack workspace or Jira site **once**, server-side, with `scripts/ops/add_integration.py` — `--org <id> --kind slack --name slack-sec --webhook <url>` for Slack, or `--kind jira --name jira-prod --base-url … --project … --email … --token …` for Jira. The secret (the webhook URL, the Jira API token) is encrypted into the `secrets` table (Fernet) and referenced by a `secret_ref`; the non-secret config (Jira base_url / project / email) sits in plaintext on the integration row. Thereafter the agent passes only the integration **name** — `send_slack_alert(scan_id, integration="slack-sec")`, `create_jira_ticket(scan_id, integration="jira-prod")` — and ROGUE resolves the config and decrypts the secret server-side, so the raw credential **never reaches the LLM** and never appears in the conversation. `list_integrations()` lets the agent discover the configured names (kind + name only, never a secret). The Workflow tools still accept the raw destination credentials as arguments (`webhook_url`; or `base_url` / `project_key` / `email` / `api_token`) for a zero-setup quick/demo run, but the stored integration is the enterprise default.

**v2 roadmap** (not yet shipped):

- **`list_projects` / `create_project`** — project-scoped organization of scans, blocked on a project service existing in the platform layer.
- **`download_report`** — binary PDF/HTML report artifacts over MCP. v1 deliberately surfaces only text renderings (`get_report` summary/json, `create_executive_summary` markdown) because MCP is a text protocol; binary delivery needs a separate mechanism (e.g. a signed URL the user opens in the dashboard).
- **Per-tenant MCP auth** — `rk_live_…` / `rk_test_…` bearer keys on the `/mcp` mount, resolved through the same authentication and tenancy chain as the `/v1` API, with the read tools gated by `read` scope and the action tools by `scan`. This is what turns the currently-open public endpoint into a multi-tenant one where each client runs and reads only its own org's scans with its own key.
