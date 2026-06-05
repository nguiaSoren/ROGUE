# Slack / GitHub / Jira Integrations (Team G)

> Distribution into where teams already work. A scan completing is an *event*; this doc specifies the single event that fires when it does, the per-org fan-out that delivers it to whichever destinations a tenant has configured, and the three first-party destinations — Slack notifications + slash command, a GitHub Action that gates CI, and Jira tickets per critical finding. It builds on what already ships: the `_maybe_post_to_slack` webhook in [`src/rogue/diff/threat_brief.py:470`](../../../src/rogue/diff/threat_brief.py) is the *precedent* this generalizes from a single env-var webhook into a per-tenant, multi-destination event bus. Like the MCP doc ([`./mcp.md`](./mcp.md)), every surface here is a thin client of `ScanService` (inbound) or a reader of the persisted `ScanRecord` / report (outbound). Nothing redefines a contract — `ScanRecord`, `score`, `ScanStatus`, `Finding`, `ScanService`, `ReportService` come verbatim from [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md) §4–§5.

Status: **PARTIALLY BUILT (local).** What shipped: a per-org **`integrations` store** (`src/rogue/platform/integration_store.py` + the `integrations` table, migration 0024) holding `{kind, name, config, secret_ref}` with the credential Fernet-encrypted via the `SecretStore`; **Slack** and **Jira** destinations (`src/rogue/platform/integrations/{slack,jira}.py`) plus a `dispatcher.py` with a `ScanCompletedEvent` (`from_record`) fan-out core; and the **MCP action tools** `send_slack_alert` / `create_jira_ticket` / `list_integrations` (in `mcp_server/scan_tools.py`) that resolve a stored integration by name and deliver. **Key deviations from this doc:**
- **There is no `GitHub` *destination* in code** — GitHub integration is only a packaged **GitHub Action** shell under `.github/actions/rogue-scan/` that calls the public API (the "shift-left" §4 story is real but is a client of `/v1/scans`, not a server-side `GitHubReporter`). No Check-Run/PR-comment writer ships.
- **Delivery is MCP-tool-driven, not an automatic worker event bus.** The `ScanWorker` does **not** emit `scan.completed` and the dispatcher is **not** subscribed to it; instead an MCP client (or caller) invokes `send_slack_alert(scan_id, integration=…)` / `create_jira_ticket(...)`. The `scan.completed`/`finding.critical` event taxonomy and auto-fan-out below are the intended design.
- The shipped `Integration` row is `{integration_id, org_id, kind ('slack'|'jira'), name, config, secret_ref, created_at}` with `UNIQUE(org_id, name)` — **no `project_id`, `enabled`, or `events` columns**, and `secret_ref` is a Fernet `secref_` handle (not `vault://`).

The threat-brief single-tenant Slack hook still exists alongside this. Sections below are the original generalized design; reconcile against the shipped facts above.

## Where this sits

These integrations are pure **edges** of the platform. They never run a scan and never render a report themselves — outbound flows read a finished `ScanRecord` (ARCHITECTURE §5) and delegate formatting to `ReportService` ([`../reports/report-service.md`](../reports/report-service.md)); inbound flows call `ScanService.create_scan` exactly as the public API does ([`../api/scans-endpoints.md`](../api/scans-endpoints.md) route 1). Two directions:

- **Outbound** (notification / ticket): the platform tells a destination something happened — a scan finished, a critical finding appeared. Slack messages, GitHub status checks, Jira tickets.
- **Inbound** (command / trigger): a destination tells the platform to do something — `/rogue scan`, a GitHub Action step. These resolve a tenant, then call `ScanService` and (for the synchronous gating story) poll the resulting `ScanRecord`.

The same `score` (0–100, Team-F formula, ARCHITECTURE §5) and the same `Finding` fields (`family`, `technique`, `vector`, `severity`, `title`, `success_rate`, `n_breach`; [`src/rogue/report.py:54`](../../../src/rogue/report.py)) drive every destination's formatting, so a Slack card, a GitHub check, and a Jira ticket for one scan can never disagree.

## 1. The common event + fan-out architecture

Everything outbound hangs off one event. When the worker (Team B) drives a `ScanRecord` to a terminal state, it emits a `scan.completed` event; the integration layer subscribes once and fans it out to whichever destinations the org has configured. There is no per-integration polling of the scan table — the event is the single trigger, mirroring how the existing brief writer fires Slack exactly once per brief at the tail of `write_outputs` ([`src/rogue/diff/threat_brief.py:464`](../../../src/rogue/diff/threat_brief.py)) rather than on a loop.

```
ScanWorker (Team B)
   │  scan reaches completed | failed
   ▼
emit scan.completed  ──►  IntegrationDispatcher
                              │  load org's enabled integrations (Team C config)
              ┌───────────────┼────────────────────┐
              ▼               ▼                     ▼
        SlackNotifier   GitHubReporter         JiraSync
        (chat.post)     (status + comment)     (create/close issues)
```

Event taxonomy (org-scoped; the dispatcher filters per destination's subscription):

- **`scan.completed`** — terminal success. Carries the full `ScanRecord`. Drives the Slack "scan finished" message, the GitHub check conclusion, and the Jira reconciliation pass.
- **`scan.failed`** — terminal failure. Drives an error notification (Slack/GitHub) so a CI run doesn't hang; never creates tickets.
- **`finding.critical`** — derived: emitted (once per finding identity, see §5) when a `completed` scan contains a `Finding` with `severity == "critical"`. This is the generalized successor to today's "new HIGH/CRITICAL" Slack trigger ([`src/rogue/diff/threat_brief.py:482`](../../../src/rogue/diff/threat_brief.py)). Drives the new-critical Slack alert and the Jira ticket-per-finding flow.

The dispatcher derives `finding.critical` events from the `scan.completed` payload (it does not re-scan); it reads the report once via `ReportService.build_json(scan_id)` to get the structured `findings[]`.

### Event payload schema

`scan.completed` (and `scan.failed`, with `status: "failed"` and `error` set) carries the `ScanRecord` plus delivery envelope. No new vocabulary — `scan_id`/`org_id`/`project_id`/`status`/`score` are the ARCHITECTURE §5 fields:

```json
{
  "event": "scan.completed",
  "event_id": "evt_01J9ZD0000000000000000001",
  "delivered_at": "2026-06-04T12:07:42Z",
  "org_id": "org_01J9Z0000000000000000ACME",
  "project_id": "proj_01J9Z000000000000000SUPPORT",
  "data": {
    "scan_id": "scan_01J9ZC4M0K8Q2R3S4T5U6V7W8X",
    "status": "completed",
    "score": 73.0,
    "n_tests": 50,
    "n_breaches": 6,
    "top_attack": "Crescendo",
    "cost_usd": 0.214902,
    "report_id": "rep_01J9ZC9XY00000000000RPT001",
    "report_url": "https://app.rogue.dev/o/acme/scans/scan_01J9ZC4M0K8Q2R3S4T5U6V7W8X"
  }
}
```

`finding.critical` carries the offending `Finding` (verbatim `Finding` fields from [`src/rogue/report.py:54`](../../../src/rogue/report.py)) plus a stable `finding_id` for dedup (§5):

```json
{
  "event": "finding.critical",
  "event_id": "evt_01J9ZD0000000000000000002",
  "org_id": "org_01J9Z0000000000000000ACME",
  "project_id": "proj_01J9Z000000000000000SUPPORT",
  "data": {
    "scan_id": "scan_01J9ZC4M0K8Q2R3S4T5U6V7W8X",
    "report_id": "rep_01J9ZC9XY00000000000RPT001",
    "finding_id": "fnd_acme_support_multi-turn-gradient_conversational",
    "family": "multi_turn_gradient",
    "technique": "Crescendo",
    "vector": "conversational",
    "severity": "critical",
    "title": "Gradual policy erosion over 3 turns",
    "success_rate": 0.8,
    "n_trials": 5,
    "n_breach": 4,
    "report_url": "https://app.rogue.dev/o/acme/scans/scan_01J9ZC4M0K8Q2R3S4T5U6V7W8X#finding-fnd_acme_support_multi-turn-gradient_conversational"
  }
}
```

The dispatcher itself is fire-and-forget per destination with the brief writer's failure semantics ([`src/rogue/diff/threat_brief.py:514`](../../../src/rogue/diff/threat_brief.py)): a destination outage logs a WARNING and does not block the other destinations or the worker, and the event is retried (§6). One slow Slack post must never wedge the Jira sync.

## 2. Per-tenant integration config + secrets

Today the Slack target is a single process-wide env var, `SLACK_WEBHOOK_URL`, read directly inside `_maybe_post_to_slack` ([`src/rogue/diff/threat_brief.py:479`](../../../src/rogue/diff/threat_brief.py)). That is correct for the single-tenant `acme` world (ARCHITECTURE §3) and exactly what we generalize: in the platform, each **org** configures its own destinations, and the credential for each is a Vault/KMS handle — never a raw secret in a row — resolved through Team C's secrets layer ([`../tenancy/secrets.md`](../tenancy/secrets.md)), the same `api_key_ref` discipline `TargetSpec` already uses (ARCHITECTURE §5).

**Shipped `integrations` table** (migration 0024, `src/rogue/platform/models.py`):

```
integrations(
  integration_id   String(48) pk,      -- secref-family ulid
  org_id           String(40) idx,     -- tenant scope
  kind             String(20),         -- 'slack' | 'jira'   (no 'github')
  name             String(80),         -- the handle MCP tools reference; UNIQUE(org_id, name)
  config           JSON,               -- kind-specific, non-secret (slack: nothing; jira: base_url/email/project_key)
  secret_ref       String(48) null,    -- secref_ handle into the Fernet `secrets` table; never the raw token
  created_at       timestamptz
)
```

There is **no `project_id`, `enabled`, or `events` column** — selection is by `(org_id, name)`, and "which events" / per-project scoping from the design below did not ship. `config` holds the non-secret knobs (Jira `base_url`/`email`/`project_key`; Slack stores its webhook URL as the *secret*). `secret_ref` resolves at delivery time through the `SecretStore` to the Slack webhook URL / Jira API token. `IntegrationStore.list(org_id)` returns `[{kind, name}]` only — never secrets.

## 3. Slack

> **Shipped:** `SlackDestination` (`integrations/slack.py`) posts a Block-Kit payload to a **stored incoming-webhook URL** (the org's `secret_ref`), via `build_payload(event)` → an httpx POST — not `chat.postMessage` with a bot token, and there is **no `/rogue scan` slash-command handler** (`POST /v1/integrations/slack/commands` does not exist). Delivery is triggered by the `send_slack_alert` MCP tool, not an automatic `scan.completed` subscription. The bot-token + slash-command design below is unrealized.

Two outbound notifications + one inbound slash command. All three reuse the message body builder so the bot post, the alert, and the slash-command reply are formatted identically.

**Outbound — scan complete.** On `scan.completed` for an org subscribed to it, `SlackNotifier` posts via `chat.postMessage` (the bot-token successor to today's incoming-webhook `httpx.post`, [`src/rogue/diff/threat_brief.py:508`](../../../src/rogue/diff/threat_brief.py)) to the configured channel. The message leads with the `score`, the breach count, and the `top_attack` from the `ScanRecord`, and links to the hosted report (`report_url`).

**Outbound — new critical.** On `finding.critical`, a higher-urgency message (`:rotating_light:`) naming the finding — the direct generalization of the current per-CRITICAL/HIGH bullet loop ([`src/rogue/diff/threat_brief.py:493`](../../../src/rogue/diff/threat_brief.py)), now keyed off `Finding.severity == "critical"` instead of the brief's tiering. Deduped by `finding_id` (§5) so a re-scan that re-breaches the same cell does not re-ping.

**Inbound — `/rogue scan <endpoint>`.** Registered as a Slack slash command pointing at `POST /v1/integrations/slack/commands`. The handler verifies the Slack request signature (timestamp + HMAC over the raw body, using the app signing secret from `secret_ref`), maps the Slack `team_id` → ROGUE `org_id` via the `integrations` row, parses `<endpoint>` (and optional `pack=`), and calls the **same** `ScanService.create_scan` the API uses (ARCHITECTURE §4; [`../api/scans-endpoints.md`](../api/scans-endpoints.md) route 1). Because a scan is queue-backed and never runs in the request thread (ARCHITECTURE §2), the handler returns an immediate ephemeral ack (`"Scan scan_… queued — I'll post the result here"`) inside Slack's 3-second window, and the eventual `scan.completed` event closes the loop by posting the result to the same channel (the slash command's `project_id`/`channel` are stamped onto the scan so the dispatcher routes the completion back). The slash command is thus pure sugar over create + the standard completion fan-out — no second execution path.

### Example Slack message (`scan.completed`)

Block Kit, built from the `ScanRecord` (`score` 73, `n_breaches` 6, `top_attack` Crescendo):

```json
{
  "channel": "C0ACMESEC",
  "blocks": [
    { "type": "header", "text": { "type": "plain_text", "text": ":shield: ROGUE scan complete — score 73/100" } },
    { "type": "section", "fields": [
      { "type": "mrkdwn", "text": "*Target:*\nopenai/acme-support-bot" },
      { "type": "mrkdwn", "text": "*Breaches:*\n6 / 50 tests" },
      { "type": "mrkdwn", "text": "*Top attack:*\nCrescendo" },
      { "type": "mrkdwn", "text": "*Cost:*\n$0.21" }
    ]},
    { "type": "section", "text": { "type": "mrkdwn",
      "text": ":rotating_light: *1 critical* · :warning: *2 high* · 3 medium" } },
    { "type": "actions", "elements": [
      { "type": "button", "text": { "type": "plain_text", "text": "View full report" },
        "url": "https://app.rogue.dev/o/acme/scans/scan_01J9ZC4M0K8Q2R3S4T5U6V7W8X" } ]}
  ]
}
```

## 4. GitHub — CI gating ("shift-left")

> **Shipped:** only the **GitHub Action** half exists — a packaged Action under `.github/actions/rogue-scan/` that calls the public `/v1` API with a `ROGUE_API_KEY` and fails the job on threshold. There is **no GitHub App, no `GitHubReporter`, no Check-Run/PR-comment writer, and no `kind='github'` integration row** in the shipped code. The outbound Check-Run/comment design below is unrealized; treat GitHub as a pure API client, not a server-side destination.

A GitHub App (installed per org; its installation id + private-key `secret_ref` live in the `integrations` row) plus a thin **GitHub Action** customers drop into a workflow. The story: a scan runs on a pull request — or on a push that touches a model/prompt file — and the build **fails** when the result crosses the org's threshold, so a regression in safety posture blocks merge the same way a failing unit test does.

**Inbound — the Action.** `rogue/scan-action@v1` runs in the customer's CI. It needs only an **org API key** stored as a GitHub repo/org secret (`ROGUE_API_KEY`, a `rk_live_…` key — auth-and-keys derives `org_id`/`project_id` from it, [`../api/scans-endpoints.md`](../api/scans-endpoints.md) §"Tenant context"). The Action calls the public API exactly as any client would — `POST /v1/scans` with a `ScanSpec`, then polls `GET /v1/scans/{id}` until terminal (the create→poll loop from scans-endpoints' worked example). No GitHub-specific scan path exists; the Action is just a packaged API client. On completion it compares the `ScanRecord.score` / critical count against `fail_on` (from `config`, or overridable as an Action input) and sets its exit code — non-zero fails the job and therefore the required check.

**Outbound — status check + PR comment.** Independently, on `scan.completed` for a scan tagged with a GitHub commit SHA (the Action passes `head_sha` through as scan metadata), `GitHubReporter` uses the App installation token to: (a) create a **Check Run** on that SHA with `conclusion = success | failure` per the threshold and a summary built from the report; and (b) post/update a single PR comment (upserted by a hidden marker so re-runs edit in place, not pile up — same dedup spirit as §5). The check is what a branch-protection rule keys off; the comment is the human-readable detail. Both read the persisted scan/report — no re-execution.

Threshold precedence: an explicit `with: fail-on-score` on the Action step wins; else the org's `integrations.config.fail_on`; else the default (`score >= 70` **or** any `critical`).

### Example GitHub Check Run

What `GitHubReporter` sends to `POST /repos/{owner}/{repo}/check-runs`:

```json
{
  "name": "ROGUE security scan",
  "head_sha": "9f3a1c2e7b...",
  "status": "completed",
  "conclusion": "failure",
  "details_url": "https://app.rogue.dev/o/acme/scans/scan_01J9ZC4M0K8Q2R3S4T5U6V7W8X",
  "output": {
    "title": "Risk score 73/100 — exceeds threshold 70",
    "summary": "6 breaches across 50 tests. **1 critical**, 2 high.\n\n| Severity | Technique | Success |\n|---|---|---|\n| critical | Crescendo | 80% |\n| high | System-Prompt Leak | 33% |\n\nFull report → details_url",
    "annotations": []
  }
}
```

A passing run sends `conclusion: "success"` with `title: "Risk score 48/100 — within threshold"`. A `scan.failed` event sets `conclusion: "neutral"` with the `error` in the summary, so CI surfaces the infra failure rather than silently passing.

## 5. Jira — ticket per critical finding, with dedup + auto-close

`JiraSync` turns the engineering view of a scan into tracked work. On each `scan.completed`, it reconciles the scan's critical findings against open ROGUE-created issues in the configured Jira project:

- **Create.** For every `finding.critical`, create an issue: summary = `Finding.title`, priority mapped from `severity` (`critical → Highest`), description = the engineering detail from `ReportService` — the offending `family`/`technique`/`vector`, `success_rate` over `n_trials`, the `example_attack`/`example_response` excerpts, and **remediation** text (the engineering report's per-finding guidance, [`../reports/report-service.md`](../reports/report-service.md) — `ReportService.build_executive_summary` / the engineering report are the source, never re-derived here).
- **Dedup by finding identity.** A finding's identity is stable across scans of the same target: `finding_id = hash(org_id, project_id, target, family, vector)` — *not* the `scan_id` (a new scan must not open a duplicate). The `finding_id` is stored on the Jira issue (a label or a custom field) so a re-occurrence of the same vulnerability updates the existing ticket (refreshing the latest `success_rate` and example) rather than filing a new one. This is the same identity used to dedup the §3 Slack critical alert and the §4 PR comment.
- **Auto-close.** During reconciliation, any open ROGUE issue whose `finding_id` is **not** present in the latest completed scan's breaching findings — i.e. a re-scan no longer breaches that cell — is transitioned to Done with a comment ("Re-scan scan_… no longer breaches this cell"). This closes the loop: ROGUE both opens the ticket and verifies the fix.

Reconciliation runs against the *latest* completed scan per (project, target), so a project that scans nightly converges: new criticals open tickets, fixed ones close, unchanged ones get a touch. Jira writes go through `secret_ref` (API token) and are scoped to the org's project key from `config`.

## 6. Idempotency + dedup (cross-cutting)

Every edge here is at-least-once and must be safe to replay:

- **Event delivery.** Each event carries an `event_id` (`evt_<ulid>`). The dispatcher persists per `(integration_id, event_id)` delivery attempts; a redelivery (worker retry, dispatcher restart) is a no-op if already succeeded. Failed deliveries retry with backoff and never block sibling destinations — the brief writer's "log WARNING, don't raise" rule ([`src/rogue/diff/threat_brief.py:514`](../../../src/rogue/diff/threat_brief.py)) generalized across all three kinds.
- **Slack.** Completion/critical messages are keyed by `(scan_id, event)` / `finding_id`; a duplicate event edits the existing message (or no-ops) rather than double-posting.
- **GitHub.** The Check Run is keyed by `(head_sha, name)` and the PR comment by a hidden marker — both upsert, so a re-delivered `scan.completed` updates in place.
- **Jira.** Dedup is the `finding_id` identity above; reconciliation is idempotent by construction (create-if-absent, close-if-resolved, touch-if-unchanged), so running it twice on the same scan changes nothing the second time.

The shared rule: identity is derived from the *finding* (stable across scans) or the *event* (stable across retries), never from the `scan_id` alone — that is what keeps a nightly cadence from drowning a channel, a PR, or a backlog in duplicates.

## Notes for implementers

- **No new execution path.** Inbound flows (`/rogue scan`, the Action) call `ScanService.create_scan` and poll `GET /v1/scans/{id}` — the same contract the API and SDK use (ARCHITECTURE §2, §4). If an integration grows its own scan logic, the "one scan engine" invariant is broken.
- **Outbound reads, never re-runs.** Notifications/tickets read a persisted `ScanRecord` and call `ReportService` for detail; they must not recompute `score` or re-judge findings.
- **Secrets via Team C only.** Tokens are `secret_ref` handles resolved at delivery time ([`../tenancy/secrets.md`](../tenancy/secrets.md)); no integration row stores a raw credential, matching `TargetSpec.api_key_ref` (ARCHITECTURE §5).
- **The brief Slack hook stays** as the single-tenant `acme` path until this layer ships; when it does, `acme`'s webhook becomes one `integrations` row of `kind="slack"`, and `_maybe_post_to_slack` ([`src/rogue/diff/threat_brief.py:470`](../../../src/rogue/diff/threat_brief.py)) is retired in favor of `SlackNotifier` driven by `finding.critical`.
- See [`./mcp.md`](./mcp.md) for the other half of Team G's surface (the in-IDE scan/query tools), [`../api/scans-endpoints.md`](../api/scans-endpoints.md) for the API the inbound flows are clients of, and [`../reports/report-service.md`](../reports/report-service.md) for the report/remediation text the outbound flows render.
