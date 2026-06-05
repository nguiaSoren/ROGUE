# ROGUE — Product Capabilities: Scanning, Reporting & MCP

An exhaustive catalog of what a ROGUE customer actually *does* — the operable surface of the product, from "I have a key" to "I just filed Jira tickets for every critical finding without leaving Cursor." Where the journey doc (`03_app_and_scan_journey.md`) narrates the funnel as one story, this document breaks it into discrete, marketable capabilities. Each entry is a beat: a thing the customer can do, where it lives in the code, what it does on screen, why it matters, and how you'd shoot it. Everything is anchored to real code under `frontend/src/app/`, `frontend/src/lib/platform-api.ts`, and the frozen MCP contract at `docs/mcp/CONTRACT.md`.

The product is two operable surfaces over one engine. The **dashboard** is the human surface — a deliberately small linear funnel of four routes (sign in → scans → new scan → watch → report). The **MCP server** is the agent surface — 20 frozen `v1` tools that let an LLM in your editor drive the same scan/report/integration lifecycle through tool calls. Both route through the same `ScanService` / `ReportService` / `ScanEngine` that backs the SDK and the HTTP API, so a scan is a scan no matter who launched it.

---

## A. The dashboard — the human surface

### 1. Sign in with a key, not a password — and the key never touches the browser

**Where:** `/sign-in` (`frontend/src/app/sign-in/page.tsx`) → `POST /api/session` (`frontend/src/app/api/session/route.ts`).

**What it does / on screen:** A spare screen — heading "Sign in to ROGUE," one line of copy, a single password-masked input that reads `rk_live_…`, and a **Sign in** button (disabled until you type, shows "Verifying…" in flight). There is no username, no password, no user table: the API key *is* the session. The client POSTs `{ api_key }` once over HTTPS to the same-origin `/api/session` route. That route doesn't trust the key on its face — it *validates* it by making a real authenticated call against the live platform (`GET /v1/scans?limit=1` with the key as bearer). Only if the platform answers does it write the key into an `httpOnly`, `secure` cookie (`rogue_key`). From then on the browser holds a cookie its own JavaScript cannot read back. A rejected key surfaces as "That API key was not recognized." (401); an unreachable platform surfaces as a distinct 502 with the upstream message, so "wrong key" reads differently from "service is waking up." A prospect without a key gets a "Request access" `mailto:` to the founder rather than a dead end.

**Marketing hook:** "Your key never lives in the browser. One paste over HTTPS, validated against the live platform, then parked in a server-only cookie no script — not even an XSS payload — can read."

**Video idea:** Paste `rk_live_…` into the masked field, hit Sign in, button flips to "Verifying…" and lands on the scans list — then cut to dev-tools showing the cookie is `httpOnly` and unreadable from `document.cookie`.

---

### 2. Your scans dashboard — every red-team your org has ever run, newest first

**Where:** `/scans` (`frontend/src/app/(app)/scans/page.tsx`), server component, `force-dynamic`.

**What it does / on screen:** The landing page after sign-in. A table of every scan the org has launched, newest first (up to 50), with columns **Scan** (the id, linking to the live detail page), **Target** (a redacted label — model, else provider, else endpoint), **Status** (a tinted `StatusBadge`), **Breaches** (red if non-zero), **Score** (a banded `ScoreBadge`), and **Created**. Click any row to either watch it run or open its report. The data is strictly per-tenant — `no-store`, never the public corpus's ISR — and a failed fetch renders an explicit red error card rather than silently serving another tenant's stale HTML. A brand-new org sees a friendly empty state pointing at "New scan." A "New scan" button sits in the header.

**Marketing hook:** "Every red-team you've run, in one ledger — status, breach count, and a 0–100 risk score per scan, scoped hard to your org and never cached across tenants."

**Video idea:** Scroll the scans table — a mix of green "completed," a pulsing "running," and one red high-breach row — then click the running one to dive into the live view.

---

### 3. Launch a scan — point ROGUE at any model in one form

**Where:** `/scans/new` (`frontend/src/app/(app)/scans/new/page.tsx`) → `POST /api/scans` → `POST /v1/scans`.

**What it does / on screen:** The launch form. First toggle: **Known provider** vs **Custom endpoint**. "Known provider" gives a dropdown — `openai`, `anthropic`, `openrouter`, `groq`, `gemini` — and the model field is optional (the provider default is used). "Custom endpoint" swaps in a free-text field for any OpenAI-compatible base URL (e.g. `https://gateway.company.ai/v1`), so you can scan your own gateway, a self-hosted model, or a staging deployment. An optional **Target API key** field (password-masked) lets you supply the target's own credential — left blank, the server key is used; supplied, it's redacted before any record is persisted and never logged raw. Below the target: the attack-corpus mode picker (next three entries), a **Pack** dropdown, and **Max tests** (1–1000). Submit fires with an `Idempotency-Key` (a fresh UUID) so a double-click can't launch two paid scans, then routes straight to the live detail page.

**Marketing hook:** "Scan any LLM you can reach — a hosted provider by name, or your own OpenAI-compatible endpoint by URL. One form, one click, and a double-submit guard so you never pay twice."

**Video idea:** Toggle from "Known provider / openai" to "Custom endpoint," paste a company gateway URL, type a model name, hit Launch — and land on the live progress screen mid-animation.

---

### 4. Scan mode: Curated pack — a fast, cheap first look

**Where:** `/scans/new`, the **Curated pack** corpus button (`mode: "pack"`), with the **Pack** dropdown (`default` / `aggressive` / `compliance`).

**What it does / on screen:** The default mode. Fires a small curated sample of ROGUE's threat library against the target — a quick, bounded, inexpensive read on exposure. The **Pack** dropdown selects which curated set runs (`default`, `aggressive`, `compliance`), letting you tune for a quick smoke test versus a harder pass versus a compliance-flavored sweep. This is the "is anything obviously broken?" mode — low cost, fast turnaround, good for CI and for a first impression.

**Marketing hook:** "Start cheap. A curated pack of ROGUE's nastiest known attacks gives you a fast exposure read before you commit to a deep run."

**Video idea:** Pick "Curated pack → aggressive," set max-tests to 10, launch, and show the whole run complete in under a minute with a score popping out.

---

### 5. Scan mode: Full repertoire — the entire *live-harvested* corpus

**Where:** `/scans/new`, the **Full repertoire** corpus button (`mode: "repertoire"`; the **Pack** dropdown disables, since the corpus is the whole live library).

**What it does / on screen:** Runs ROGUE's *entire harvested corpus* — every attack primitive continuously scraped from 19 open-web sources via Bright Data — against the target, capped at Max tests. This is the differentiator made operable: the attacks you're tested with are the attacks adversaries are *posting right now*, not a frozen benchmark. Because the corpus is the whole live library, the Pack dropdown greys out. The cap keeps cost bounded while still exercising the breadth of the threat database.

**Marketing hook:** "Tested against the open web's freshest jailbreaks — ROGUE harvests new attacks daily and throws the whole living arsenal at your model. Your benchmark updates itself."

**Video idea:** Select "Full repertoire," and overlay a ticker of source names (Reddit, X, jailbreak forums) feeding into the corpus, then launch and watch the breach counter climb against a wall of real attacks.

---

### 6. Scan mode: Full ladder — escalate every goal through the multi-tier arsenal

**Where:** `/scans/new`, the **Full ladder** corpus button (`mode: "ladder"`).

**What it does / on screen:** The deepest and most expensive mode. Rather than firing pre-formed attacks once, the ladder *escalates each goal* through ROGUE's full multi-tier arsenal — graduated techniques, chain-of-jailbreak, structured-data attacks, and image/audio renderers — climbing tiers until the model breaks or the ladder is exhausted. This is adaptive red-teaming: it doesn't just ask "does this known attack work?" but "how hard do I have to push *this specific model* before it gives?" The on-screen helper text is explicit that this is the deepest, costliest mode.

**Marketing hook:** "Don't just test known attacks — let ROGUE *escalate*. The ladder climbs technique by technique against your model until it finds the floor. The closest thing to a tireless human red-teamer."

**Video idea:** Animate a vertical ladder of tiers lighting up one rung at a time — text → structured data → image renderer — with the "Current attack" line on the progress card changing to match each rung.

---

### 7. Watch it run live — the breach counter climbing in real time

**Where:** `/scans/[scanId]` (`frontend/src/app/(app)/scans/[scanId]/page.tsx`) + `frontend/src/components/scan-progress.tsx`.

**What it does / on screen:** The live view. The server seeds the first paint with real data (no spinner), then a single client poll loop hits the same-origin `/api/scans/{id}` proxy every ~2s until the scan reaches a terminal state — and the proxy re-reads the cookie server-side, so the live poller never holds the bearer. On screen: a **status badge** (with a pulsing dot while running), a **progress bar** (green, animating to width), and a readout line — `67% · 32/50 tests complete · Current attack: Crescendo`. Below that, three live counters: **breaches so far** (red the moment it's non-zero, green at zero), **~$X spent** (an estimate, formatted to the cent or finer), and **~N min remaining** (a linear ETA projected from elapsed time and progress). Exactly one poll loop owns the page; every readout reads the single shared record, never its own fetcher.

**Marketing hook:** "Watch your model get attacked in real time — the breach counter climbing, the current attack named, the spend ticking, the ETA counting down. Red-teaming you can actually *watch happen*."

**Video idea:** Hold on the progress card as the bar crawls from 40% to 70%, the "Current attack" name flips through technique names, and the breach counter ticks 0 → 1 → 3 and flushes red.

---

### 8. Cancel a running scan — stop on a dime, keep what you've already learned

**Where:** `frontend/src/components/scan-progress.tsx`, the **Cancel scan** button → `POST /api/scans/{id}/cancel`.

**What it does / on screen:** While a scan is queued or running, a red **Cancel scan** button sits in the progress card. Clicking it pops a confirm ("Stop this scan? Tests already run still count toward the report.") and, on confirm, POSTs the same-origin cancel proxy (bearer attached server-side), which returns the updated record. The poll loop reconciles any drift. A canceled scan shows an explicit note that partial progress is real and counts toward any report — so cancellation isn't a loss, it's a stop with everything-so-far banked.

**Marketing hook:** "Seen enough? Stop the scan instantly — and keep every result it already produced. Cancellation banks your progress, it doesn't burn it."

**Video idea:** Mid-run, click Cancel, confirm the dialog, and show the status flip to "canceled" with the partial-progress note and a still-usable breach count.

---

### 9. The report — a 0–100 risk score that leads the page

**Where:** `/scans/[scanId]/report` (`frontend/src/app/(app)/scans/[scanId]/report/page.tsx`), the `RiskHeadline` + `Kpi` row; score band in `frontend/src/components/score-badge.tsx`.

**What it does / on screen:** When a scan completes, "View report →" links here. The page leads with the **risk headline** — a giant `N/100` score, color-banded (≥75 critical / ≥50 high / ≥25 medium / else low), with a severity pill, the **top attack** name on the right, and a one-line methodology caption explaining how the score is computed (the page never recomputes a rate — everything arrives pre-derived from the platform). Directly beneath it, a branded **executive-summary** card renders the report's top-level `executive_summary` markdown — the forward-to-your-boss overview, the first thing read after the score (the same exec narrative the MCP `create_executive_summary` tool returns; absent on older runs, in which case the card simply doesn't show). Below that, a four-tile **KPI row**: Tests, Breaches (red if any), Breach rate (as a %), and Cost. If a scan completed with nothing reproduced, the findings area shows a green "No vulnerabilities reproduced across N tests." A scan that isn't done yet shows "Report not ready" with a link back to the live view, not a hard error.

**Marketing hook:** "One number your CISO can read in three seconds, then an executive summary they can forward as-is: a 0–100 risk score and a written verdict leading every report."

**Video idea:** A completed scan's report fades up — the big red "82 /100 CRITICAL" headline lands first, the executive-summary card resolves beneath it, then the KPI tiles count up (Tests, Breaches, 41% breach rate, $4.20).

---

### 10. Severity-grouped findings — worst-first, explained, with the exact attack and the model's own words

**Where:** `/scans/[scanId]/report`, the `FindingCard` list (sorted by severity then success rate).

**What it does / on screen:** Below the KPIs, the findings — only the attacks that actually breached, sorted worst-first (critical → low, then by success rate). Each finding is a severity-tinted card with a rank (#1, #2…), a severity pill, the vector, and a hard number: `breached 4/5 trials · 80%` (red ≥70%, orange ≥30%, green below). The card titles the attack and names its family and technique, then carries a **"What this is"** block — the finding's plain-language `explanation`, so a non-expert grasps the risk before the fix or the proof. Below the explanation and remediation (next entry) sits a **single collapsible evidence section** — "Evidence — attack & model response" — that holds both the **Attack sent →** (the literal payload that broke the model, in a monospace block) and the **Model response** (an excerpt of what your model actually said back). It's collapsed by default so the page reads clean; because the finding breached, the summary line carries a red **"breached"** flag and the response is tinted red, so the evidence reads as confirmed proof, not a benign sample.

**Marketing hook:** "Not a verdict — *evidence*, explained. Every finding says what it is in plain language, then shows the exact payload that broke your model and the model's own words back, flagged as a breach. Worst-first, with a rate you can act on."

**Video idea:** Read a critical finding's "What this is" line, then expand its evidence to reveal the jailbreak payload and the model complying — the breach flag pulsing red beside it.

---

### 11. Per-finding remediation — what to actually change

**Where:** `/scans/[scanId]/report`, the per-finding `remediation` block + the report-level `RecommendationsPanel`.

**What it does / on screen:** Each finding card carries a green-accented **"How to fix"** block — a concrete, finding-specific remediation surfaced by the report route, visually distinct from the "What this is" explanation above it (green = the "do this" instruction) and sitting just above the evidence (degrades gracefully on older runs that lack it). Below all the findings, a report-level **Recommendations** panel lists "what to do next" as bullets; when the platform doesn't supply them, it falls back to a sensible one-liner ("N findings reproduced — prioritize the top attack (…)" or, for a clean scan, "keep monitoring as the threat corpus grows"). Together they turn a list of breaches into a to-do list.

**Marketing hook:** "Every breach comes with a fix. Per-finding remediation plus a prioritized action list — so the report ends with what to change, not just what's broken."

**Video idea:** Scroll past a finding to its green-bordered Remediation block, then down to the Recommendations panel's bulleted to-do list.

---

### 12. Export HTML — the shareable web report

**Where:** `/scans/[scanId]/report`, the **HTML** export button → `/api/scans/{id}/report?format=html` (same-origin proxy attaches the bearer).

**What it does / on screen:** Top-right of the report, three monospace export buttons. **HTML** opens the full report as a standalone web page in a new tab — the same findings, score, and evidence, rendered as a self-contained document you can host, link, or hand off. The secret never rides in the href: the same-origin route handler attaches the bearer server-side.

**Marketing hook:** "Share the whole report as a link — a standalone HTML document, no login wall, no secret in the URL."

**Video idea:** Click **HTML**, new tab opens with the styled report, copy the URL and "send it to a colleague."

---

### 13. Export PDF — a CISO-ready document

**Where:** `/scans/[scanId]/report`, the **PDF** export button → `/api/scans/{id}/report?format=pdf`.

**What it does / on screen:** The **PDF** button downloads the report as a polished, print-ready document — the artifact you attach to a security review, drop into a board deck, or send to a customer's procurement team. Same bearer-server-side discipline. This is the deliverable: a 0–100 score, severity-grouped findings, and remediation, bound into one file a non-engineer can read.

**Marketing hook:** "One click to a CISO-ready PDF — score, findings, evidence, and fixes in a document you can attach to a security review or a board deck."

**Video idea:** Click **PDF**, the file lands in the downloads tray, open it to a clean cover-page-to-findings document.

---

### 14. Export JSON — the machine-readable record

**Where:** `/scans/[scanId]/report`, the **JSON** export button → `/api/scans/{id}/report?format=json`; shape is `ScanReportJson` in `frontend/src/lib/platform-api.ts`.

**What it does / on screen:** The **JSON** button hands back the full structured report — `target`, `n_tests`, `n_breaches`, `breach_rate`, `top_attack`, `cost_usd`, `score`, `risk_level`, `score_methodology`, `executive_summary`, `recommendations[]`, and the full `findings[]` array (each with family, technique, vector, severity, success rate, trial counts, an `explanation`, example attack/response, and remediation). This is the integration seam: pipe it into your own dashboards, gate a CI run on `breach_rate`, or diff scores across releases.

**Marketing hook:** "Every report is also an API response — export the full structured JSON to gate CI on breach rate, trend your score across releases, or feed your own dashboards."

**Video idea:** Click **JSON**, show the structured payload, then cut to a CI log failing a build because `breach_rate > 0.1`.

---

### 15. Pre-flight validate / test-connection (near-term capability)

**Where:** `platformApi.validateTarget` → `POST /v1/scans/validate` (`frontend/src/lib/platform-api.ts`). The endpoint and client method exist; a dashboard button is **not yet wired** — call it a near-term capability.

**What it does / on screen:** A cheap pre-flight that dry-runs a target *before* you spend on a scan — checking reachability, credentials, model response, and supported modalities (image/audio), running no attacks. The platform endpoint and the typed client method ship today; the dashboard surface (a "Test connection" button on the New-scan form) is the obvious next wire-up. The MCP equivalent, `validate_target`, is already fully live (see B.3), so the capability exists end-to-end on the agent side — the dashboard just hasn't surfaced the button yet.

**Marketing hook:** "Check the connection before you spend a cent — a near-zero-cost pre-flight that confirms your target is reachable, authenticated, and responding (and whether it takes images and audio) before any attack runs."

**Video idea:** On the New-scan form, click a "Test connection" button (mark as coming-soon) that returns a green "reachable · authenticated · responds · supports image" check.

---

## B. MCP — operate the whole product from your IDE

**Where:** `docs/mcp/CONTRACT.md` — the frozen `v1` surface; `src/rogue/mcp_server/`. Connect Claude Desktop / Cursor / Windsurf to the ROGUE MCP server and your editor's agent gets 20 tools: 6 read-only threat-intel queries and 14 action tools that run the full scan → report → integration lifecycle against *your* endpoint. Tenancy is bound at the server from the key — **no tool ever takes an org argument**, so an LLM can never spoof or escalate the org it scans or bills under.

### 16. Query the live threat DB from your editor (6 read tools)

**Where:** `query_attacks`, `query_diff`, `query_threat_brief`, `query_breaches_for_config`, `query_attack_detail`, `query_worst_attacks` (read tools, `server.py`).

**What it does:** Read-only, global, money-free queries over ROGUE's continuously-harvested threat database — browse/filter the attack corpus by family/vector/recency, get today's newly-breaching-vs-newly-defended diff, pull the full daily CISO threat brief (markdown or JSON), inspect per-trial breach results for one deployment config (with judge rationale and response excerpts), drill into one attack's full record, or ask "what would hit a model like me?" (`query_worst_attacks`, where the agent passes *its own* model identity and ROGUE scopes to the closest config). The fast "am I exposed?" answer, inline in chat.

**Marketing hook:** "Ask your editor 'what jailbreaks would hit a model like me?' and get a live answer from a threat DB that updates daily — no scan required."

**Video idea:** In Cursor, type "what are the worst attacks against an opus-class model right now?" and the agent calls `query_worst_attacks` and prints a ranked list with breach rates.

---

### 17. Validate, scan, and operate from chat (the action tools)

**Where:** `validate_target`, `start_scan`, `get_scan_status` / `get_scan`, `cancel_scan`, `list_scans` (action tools, `scan_tools.py`).

**What it does:** The whole dashboard funnel, as tool calls. The agent can `validate_target` (the live pre-flight — reachable/authenticated/responds/supports-image/supports-audio), `start_scan` (same `pack`/`repertoire`/`ladder` modes, `max_tests`, optional `budget` USD cap — returns a queued `scan_id`), `get_scan_status` to poll progress and results, `cancel_scan`, and `list_scans` for the org's recent history. Every tool is org-scoped at the server; the target's `api_key` is redacted on persist and never logged. A recoverable failure returns `{"error": "<message>"}` rather than raising — so the agent reads the string and reacts.

**Marketing hook:** "Red-team your model without leaving your editor: 'validate this endpoint, then run a ladder scan, cap it at $5' — and the agent does it."

**Video idea:** Type "validate https://gateway.ours/v1 then start a repertoire scan" — the agent calls `validate_target`, sees green, calls `start_scan`, and posts back the scan id.

---

### 18. Get the report (and a CISO summary) as tool output

**Where:** `get_report` (`summary` markdown / `json`), `list_findings`, `create_executive_summary` (action tools).

**What it does:** Once a scan completes, the agent fetches the report inline — `get_report(format="summary")` returns pasteable markdown (headline `risk N/100 (level)`, the breach ratio, top findings with technique/severity/success-%/remediation); `format="json"` returns the full structured payload (the same `ReportService.build_json` the dashboard renders). `list_findings` returns flat finding rows for programmatic use. `create_executive_summary` returns a CISO-ready markdown exec summary — headline risk, breach ratio, critical & high findings with remediation, and a one-line business framing — ready to paste into an email or a ticket.

**Marketing hook:** "From scan to CISO-ready exec summary in one tool call — the agent reads the report and writes the brief."

**Video idea:** Agent calls `create_executive_summary` and drops a clean "Executive Summary — Risk 78/100 (High)" block straight into the chat, ready to forward.

---

### 19. Benchmark against published numbers — comparable ASR from chat

**Where:** `run_benchmark` (e.g. `advbench_100` / JailbreakBench, `max_goals`), `get_benchmark` (action tools).

**What it does:** Run a standard-dataset attack-success-rate benchmark against the target so a result is directly comparable to published numbers, then poll it. `get_benchmark` returns the full record — dataset, `n_goals`, `n_success`, `asr`, `cost_usd`, `cost_per_success`, and an optional `winner_rank`. The "how does our model stack up against the literature?" answer, from inside the editor.

**Marketing hook:** "Benchmark your model against AdvBench / JailbreakBench numbers without leaving chat — a comparable ASR and a cost-per-success, on demand."

**Video idea:** Agent runs `run_benchmark(dataset="advbench_100")`, polls, and reports "ASR 12% — better than the published 41% baseline."

---

### 20. Route findings to Slack and Jira — close the loop without secrets

**Where:** `list_integrations`, `send_slack_alert`, `create_jira_ticket` (action tools).

**What it does:** The agent ships results to where the team works. `list_integrations` discovers the org's stored Slack/Jira integrations *by name, never any secret*. `send_slack_alert` posts a scan's Block Kit summary (score / breach ratio / top attack) to a channel — by stored integration name (server resolves the secret) or a raw webhook. `create_jira_ticket` files a ticket for each **critical/high breached finding**, **idempotently** — a finding already carrying its stable `rogue-<finding_id>` label on an open ticket is skipped, so re-scans converge instead of spamming the board. Credentials resolve server-side; the model never handles a secret.

**Marketing hook:** "Scan, then close the loop — the agent files a Jira ticket per critical finding and pings Slack, idempotently, without ever touching a credential."

**Video idea:** Agent runs a scan, then "file Jira tickets for the criticals and alert #security" — chat shows `created: [SEC-412, SEC-413]` and a Slack card landing in the channel.

---

### 21. The "agent as security consultant" story — the full lifecycle in one conversation

**Where:** the whole MCP surface composed (`docs/mcp/CONTRACT.md`).

**What it does:** Because all 20 tools live on one server bound to your org, a single editor conversation can run the entire arc: *query* the live threat DB to see what's dangerous now → *validate* your endpoint → *start* a scan → *poll* it → *read* the report → *generate* a CISO exec summary → *alert* Slack and *file* Jira tickets. The agent becomes an on-call security consultant that never leaves your editor, can't escalate its own tenancy (org is bound at the server, never a tool argument), and never handles a raw secret (integration credentials resolve server-side).

**Marketing hook:** "An AI security consultant that lives in your editor: it checks the threat landscape, attacks your model, writes the brief, and files the tickets — all in one conversation, none of your secrets in its hands."

**Video idea:** A single uninterrupted Cursor session: "what's hitting opus models today? scan our gateway on the ladder, summarize for the CISO, and file the criticals to Jira" — and the agent walks the whole chain, tool call by tool call.

---

## Capability roll-up

The full operable surface, twenty-one capabilities across two surfaces:

**Dashboard (human):** (1) key-based sign-in with browser-invisible secret · (2) per-tenant scans dashboard · (3) launch a scan (provider *or* custom endpoint) · (4) Curated-pack mode · (5) Full-repertoire mode (live-harvested corpus) · (6) Full-ladder mode (escalation arsenal) · (7) live progress (breach counter / current-attack / spend / ETA) · (8) cancel-with-banked-progress · (9) 0–100 risk-score report headline + executive summary · (10) severity-grouped findings — explained, with breach-flagged attack/response evidence · (11) per-finding "how to fix" + recommendations · (12) HTML export · (13) CISO-ready PDF export · (14) structured JSON export · (15) pre-flight validate/test-connection (endpoint live, dashboard button near-term).

**MCP (agent):** (16) six read-only threat-DB queries · (17) validate/scan/poll/cancel/list action tools · (18) report + CISO exec-summary tools · (19) standard-dataset benchmarking · (20) Slack + Jira integration routing (idempotent, secret-free) · (21) the composed "agent as security consultant" lifecycle.
