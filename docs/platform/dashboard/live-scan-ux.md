# Live Scan UX (Team D)

> The scan detail page while a scan is **executing**. A customer fires `POST /v1/scans`, lands on `/scans/{id}`, and watches a progress bar fill, a test counter climb, and the current attack name change in real time — then the page flips to the finished report without a manual refresh. This doc specifies that one view: the data it consumes, the transport that feeds it, the components it renders, and the state machine that ties them together. It defines **no new vocabulary** — `ScanRecord`, `ScanStatus`, `progress`, `n_tests`, `n_completed`, `n_breaches`, `top_attack`, `cost_usd`, `score`, `report_id`, `error` are owned by [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md) §5 and used here verbatim. The transport hits routes owned by Team A in [`../api/scans-endpoints.md`](../api/scans-endpoints.md) and consumes the per-test progress the worker writes per [`../orchestration/worker.md`](../orchestration/worker.md). See also [`./pages-and-routes.md`](./pages-and-routes.md) for where this page sits in the app tree and [`./report-views.md`](./report-views.md) for the view it transitions into on completion.

Status: **BUILT (local), poll-based not SSE.** The page shipped at `frontend/src/app/(app)/scans/[scanId]/page.tsx` (route param `[scanId]`), and its backing pieces exist: `POST /v1/scans`, `GET /v1/scans/{id}` (returning the worker-written `progress`/`n_completed`/`n_tests`/`top_attack` per [`../orchestration/worker.md`](../orchestration/worker.md)), and the report route it flips to (`(app)/scans/[scanId]/report`). **Important transport correction:** the live view is a **client-side poller**, not SSE. A server component seeds the record, then a `"use client"` `ScanProgress` component **polls a same-origin `/api/scans/{id}` proxy route** (which re-attaches the bearer) until terminal. There is no Redis heartbeat and no per-scan SSE channel — the worker writes progress straight into the Postgres `scan_runs` row and `GET /v1/scans/{id}` reads it. Where this doc specifies an SSE/streaming transport for scan progress, that is the original design; the shipped page polls. The rest (state machine, components) is broadly accurate.

---

## 1. What the page renders

The target mock, exactly as scoped:

```
Current status   █████████ 67%   32/50 tests complete   Current attack: Crescendo
```

Every number in that line maps to a `ScanRecord` field — there is nothing the page computes that the backend does not already carry (ARCHITECTURE §5; `ScanRecord` JSON shape reproduced in [`../api/scans-endpoints.md`](../api/scans-endpoints.md) "Shared shapes"):

- the bar fill % — `progress` (`0–100`).
- `32/50 tests complete` — `n_completed` / `n_tests`.
- `Current attack: Crescendo` — `top_attack` (the worker writes the *in-flight* attack's human label here while running; see §6).
- a breach tally — `n_breaches` (running count).
- live cost — `cost_usd` (running USD spend, climbing as panel/judge calls bill).
- elapsed / ETA — derived client-side from `started_at` + `progress` (see §4); not a backend field.
- the headline risk number — `score`, which is `null` while running (ARCHITECTURE §5: synthesized from findings, Team-F formula) and only renders once non-null, i.e. effectively at completion.

The page is a thin, read-only projection of one `ScanRecord` plus a cancel action. It holds **no scanning logic** — same discipline as the API routes (ARCHITECTURE §2).

## 2. Transport — how the page gets live updates

Two options, both consuming the **same** data (`ScanRecord`, written by the worker — [`../orchestration/worker.md`](../orchestration/worker.md)). The choice is a transport detail, not a contract change.

**Option A — poll `GET /v1/scans/{id}`.** The simplest correct thing. The page fetches the full `ScanRecord` (route 2, [`../api/scans-endpoints.md`](../api/scans-endpoints.md) §2) on an interval and re-renders. The SDK's `wait_for` loop already hits this same route, so polling is a first-class supported access pattern, not a hack. Interval: ~2 s while `status == "running"`, stop polling on any terminal state. This is the **baseline** — it works with zero new backend surface and degrades gracefully under cold start (§7).

**Option B — SSE from a new `GET /v1/scans/{id}/events`.** A push stream that emits the `ScanRecord` (or a progress delta) as a `scan` event each time the worker advances, plus heartbeats. This is strictly an *optimization* over Option A: lower latency on the progress bar, no idle polling. It reuses ROGUE's existing SSE machinery on the backend (`src/rogue/api/main.py:945`, `GET /api/sse/feed` — `StreamingResponse(gen(), media_type="text/event-stream")` at `main.py:990`) and the existing single-Provider consumer pattern on the frontend (§3).

**Recommendation: ship Option A first, add Option B behind the same hook.** The component contract is identical either way — it consumes a `ScanRecord` and re-renders. Build the polling path for Week-1/2 (it needs nothing beyond route 2, which Team A already ships), and slot the SSE stream in later as a transport swap behind the hook in §3, with polling as the always-present fallback. The page must never *require* SSE: if the stream is unavailable (cold start, proxy that buffers, Neon blip), polling carries it.

### 2a. The new `GET /v1/scans/{id}/events` stream (Option B spec)

Modeled directly on `/api/sse/feed` (`src/rogue/api/main.py:945`) and bound by the hard lesson that endpoint taught (`tasks/LESSONS.md` 2026-06-01):

- **Tenant-scoped** like route 2: resolve `org_id` from the API key, `404` if the scan isn't this org's (no existence leak — same rule as [`../api/scans-endpoints.md`](../api/scans-endpoints.md) §2).
- **Initial event = a `scan` event carrying the current full `ScanRecord`** (the snapshot, analogous to `/api/sse/feed`'s initial `snapshot`), so a late-joining or reconnecting client paints immediately without waiting for the next worker tick.
- **Subsequent `scan` events** on each worker progress write. For Week-1 simplicity the stream MAY re-snapshot on a short server-side timer (read the `ScanRecord`, emit, sleep) exactly as `/api/sse/feed` re-snapshots per connection — a true DB subscription is **not** required and is explicitly out of scope (matches the `/api/sse/feed` comment at `main.py:949`).
- **A terminal `scan` event then server-closed stream** when `status` goes terminal (`completed | failed | canceled`). The client treats stream-close-after-terminal as normal, not an error to reconnect (§5).
- **`: heartbeat` comments every 15 s** (`main.py:987–988`) so the browser's EventSource doesn't churn-reconnect on an idle stream.
- **NEVER hold a DB connection across the stream lifetime.** This is the load-bearing rule. Scope every `ScanRecord` read to a `with _session_factory()() as db:` block and return the connection to the pool *before* yielding — exactly the fix at `src/rogue/api/main.py:959–981`. The 2026-06-01 outage was a leaked SSE connection sitting in a `while True: sleep(15)` loop holding a pooled connection; under reconnect churn the 5+10 pool leaked dry and the *entire* DB-backed API 502'd. A per-scan stream multiplies connections by concurrent live viewers, so this rule is non-negotiable here.

## 3. Frontend transport plumbing — one shared connection, never N

REUSE the pattern already learned and codified (`tasks/LESSONS.md` 2026-05-28, "one Provider, not N EventSources"; implemented in `frontend/src/components/sse-feed-provider.tsx`). On the global feed, three components each opened their own `EventSource` to `/api/sse/feed` and all three retry-stormed when the backend was down; the fix was a single `SseFeedProvider` (one `EventSource`, `[]`-dep effect, value via React Context) consumed through a `useSseFeed()` hook.

Apply the **same shape** here, scoped per scan:

- A `useScanProgress(scanId)` hook is the single seam every component on the page reads. It returns `{ record: ScanRecord | null, connected: boolean, error: string | null }`.
- Internally the hook owns **exactly one** live connection for the page: one `EventSource(\`${API_BASE}/v1/scans/${scanId}/events\`)` (Option B) **or** one `setInterval` poll loop (Option A) — never both live at once, never one per child component. The progress bar, the counter, the cost readout, and the cancel button are all *consumers* of this one hook, not independent fetchers. This is the direct analogue of the `SseFeedProvider` → `useSseFeed()` split: hoist the connection, fan out the reads.
- The effect runs with `[scanId]` deps (the connection's identity is the scan), opens one connection, and on cleanup `removeEventListener` + `es.close()` (or `clearInterval`) — mirroring `sse-feed-provider.tsx:53–86`. Reconnection on disconnect is the browser's job for EventSource (`tasks/LESSONS.md` 2026-05-28 point 2); for the polling path, the loop simply continues.
- `API_BASE` resolves from `process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000"`, the same convention as `sse-feed-provider.tsx:12` and `frontend/src/lib/api.ts:14`.

Because the per-scan stream is page-scoped (not app-global like `SseFeedProvider`), the hook lives in the page component rather than `app/layout.tsx` — but the "one connection, many consumers" invariant is identical.

## 4. The progress component

A single `ScanProgress` component, fed the `ScanRecord` from `useScanProgress`. Sub-parts:

- **Progress bar** — fill width = `progress%`. Indeterminate/striped while `queued` (no meaningful percentage yet); determinate once `running`. Snaps to 100% on `completed`.
- **Test counter** — `{n_completed}/{n_tests} tests complete`. `n_tests` is the planned count, fixed at create time; `n_completed` climbs (ARCHITECTURE §5).
- **Current-attack label** — `Current attack: {top_attack}`. `top_attack` is a human technique label (e.g. `Crescendo`, via `technique_label` — same source the report's `findings[].technique` uses, [`../api/scans-endpoints.md`](../api/scans-endpoints.md) §3 worked example). Hidden when `null` (e.g. just-queued).
- **Breach tally** — `{n_breaches} breaches so far`, with the same severity coloring the report views use ([`./report-views.md`](./report-views.md)) so the running count reads consistently against the finished report.
- **Live cost** — `cost_usd` formatted as USD, climbing. Honest about being an estimate (the engine's `cost_usd` is a budget estimate, not a billing source of truth).
- **Elapsed / ETA** — elapsed = `now − started_at`. ETA is derived, not a backend field: a simple linear projection `elapsed × (100 − progress) / progress` once `progress > 0`, rendered as "~N min remaining" and clearly approximate. Suppress ETA while `progress == 0` (divide-by-zero / no signal) and while `queued`. Do **not** ask the backend for an ETA — the page owns this derivation.

`top_attack` while running is the *in-flight* attack the worker is currently exercising; the worker writes it on each test boundary ([`../orchestration/worker.md`](../orchestration/worker.md)). On `completed` the same field denotes the worst/headline attack for the finished scan ([`../api/scans-endpoints.md`](../api/scans-endpoints.md) route-5 example). The label's *meaning* shifts at the terminal transition; the component just renders whatever the record says.

## 5. The state machine the UI renders

The page renders one of the `ScanStatus` states (ARCHITECTURE §5: `queued | running | completed | failed | canceled`). It is a pure projection — the **worker owns every transition** ([`../orchestration/worker.md`](../orchestration/worker.md); create owns only `→ queued`, [`../api/scans-endpoints.md`](../api/scans-endpoints.md) §1); the UI never infers a transition it didn't read from a `ScanRecord`.

```
        ┌──────────┐   worker picks up    ┌──────────┐   all tests done    ┌────────────┐
        │  queued  │ ───────────────────► │ running  │ ──────────────────► │ completed  │
        └────┬─────┘                      └────┬─────┘                     └────────────┘
             │                                 │  error / budget abort     ┌────────────┐
             │                                 ├─────────────────────────► │   failed   │
             │ cancel                          │                           └────────────┘
             │ (POST /cancel)         cancel   │                           ┌────────────┐
             └─────────────────────────────────┴─────────────────────────► │  canceled  │
```

Per-state rendering:

- **`queued`** — "Queued — waiting for a worker." Indeterminate bar, cancel button enabled (cancel of a queued scan is immediate, [`../api/scans-endpoints.md`](../api/scans-endpoints.md) §4). No counter/ETA yet.
- **`running`** — the full progress component (§4). Cancel enabled.
- **`completed`** — bar at 100%, `score` now non-null. The page transitions to the report view (§8). Cancel hidden.
- **`failed`** — error banner showing `ScanRecord.error` (the only state where `error` is non-null, ARCHITECTURE §5 / [`../api/scans-endpoints.md`](../api/scans-endpoints.md) §2). Offer "Start a new scan" linking back to the create flow ([`./pages-and-routes.md`](./pages-and-routes.md)). No report (`report_id` stays `null`).
- **`canceled`** — "Scan canceled." Show whatever partial `n_completed`/`n_breaches`/`cost_usd` the record carries (a running scan stops at a trial boundary, so partial progress is real and worth showing). No report.

`completed | failed | canceled` are **terminal**: the hook stops polling / treats stream-close as expected (§2a), and the page renders the terminal view. There is no client-side state the worker can't override — a reconnect always re-reads truth from the `ScanRecord`.

## 6. The cancel button

A single action calling `POST /v1/scans/{id}/cancel` ([`../api/scans-endpoints.md`](../api/scans-endpoints.md) §4). Behavior:

- Visible/enabled only in non-terminal states (`queued`, `running`). Hidden once terminal.
- On click → confirm ("Stop this scan? Tests already run still count toward the report.") → `POST` the cancel route. The response is the updated `ScanRecord`; feed it straight back into the hook's state so the UI reflects the new status without waiting for the next poll/event.
- **Idempotent & best-effort**, matching the route: a `queued` scan flips to `canceled` immediately; a `running` scan may come back still `running` with a cancellation flag the worker honors at the next trial boundary ([`../api/scans-endpoints.md`](../api/scans-endpoints.md) §4, [`../orchestration/worker.md`](../orchestration/worker.md)). So after cancel the page may briefly stay `running` — that is expected; keep the live connection open and let the eventual terminal `canceled` record arrive. Disable the button (don't hide) during the in-flight request to prevent double-submits; re-fire is harmless (idempotent) but noisy.
- **`409 conflict`** (the scan went terminal — `completed`/`failed` — between render and click) → surface a small toast ("Scan already finished") and refresh the record; do not treat as a hard error. The error envelope `{ "error": { "code": "conflict", … } }` ([`../api/scans-endpoints.md`](../api/scans-endpoints.md) §4) carries the current `status` in `details` to render the right terminal view.

## 7. Reconnection, backoff, and cold start

The live connection has to survive three realities: Render free-tier cold start, Neon connection drops, and ordinary network blips.

- **EventSource reconnect (Option B)** — the browser auto-reconnects on disconnect; that is intentionally *its* job, not React's (`tasks/LESSONS.md` 2026-05-28 point 2). The hook does not hand-roll reconnection for the SSE path — it relies on the built-in retry and on the heartbeat (§2a) to keep an idle stream from churning. On reconnect the server re-emits the current `ScanRecord` snapshot, so the bar never regresses to stale values.
- **Polling backoff (Option A)** — fixed ~2 s interval while `running`. On a request error (gateway 502/503/504 or a network throw), reuse the proven backoff from `frontend/src/lib/api.ts:34–62`: retry with `1.5 s → 3 s` growing sleeps and an `AbortSignal.timeout(12_000)` cap per attempt, so a Render cold boot that *holds* the socket can't hang the loop forever (`lib/api.ts:25–28`). Treat a handful of transient gateway errors as "still warming," not "failed" — never paint the scan as broken because the API was asleep (`lib/api.ts:19–22`).
- **Cold start on first paint** — the API sleeps on Render's free tier and returns transient `502/503/504` (or drops the socket) for the first request or two while it boots (`lib/api.ts:19–22`). The page must render a "connecting…" affordance and ride out `MAX_RETRIES` before showing any error — identical posture to the rest of the dashboard. A just-created scan whose first poll/connect hits a cold API should show `queued`, not an error.
- **Neon resilience** — the live connection touches the DB on every `ScanRecord` read. Per `tasks/LESSONS.md` 2026-06-01 and the Neon resilience checklist, the *server* must not hold a pooled connection across the stream (§2a) and must `pool_pre_ping`; the *client* simply needs to tolerate a momentary `5xx` mid-stream (the backoff above) without tearing down the page. A Neon blip should manifest as a one-tick pause in the bar, then resume — never a dead page.

## 8. Transition to the finished report

When the live connection reports a terminal `completed`, the page hands off to the report view ([`./report-views.md`](./report-views.md)):

- The hook stops the live connection (terminal — §5).
- `report_id` (`rep_<ulid>`) is now non-null on the record (ARCHITECTURE §5; set by the worker at completion, [`../api/scans-endpoints.md`](../api/scans-endpoints.md) §2). The page can either render the report inline by fetching `GET /v1/scans/{id}/report?format=json` ([`../api/scans-endpoints.md`](../api/scans-endpoints.md) §3) or route to the dedicated report page ([`./pages-and-routes.md`](./pages-and-routes.md), [`./report-views.md`](./report-views.md)) — Team D's page-layout call, but the data seam is the report route in both cases.
- The transition should be visually continuous: the progress card collapses into the report header (which carries the same `score`, `n_tests`, `n_breaches`, `top_attack`, `cost_usd`), so the customer sees the live numbers settle into the final report rather than a jarring page swap. The headline `score` — `null` throughout the run — appears here for the first time.
- **Race guard:** the report route returns `404 report_not_ready` if asked before `status == completed` ([`../api/scans-endpoints.md`](../api/scans-endpoints.md) §3). The page must only fetch the report *after* it has observed a `completed` record (or treat `report_not_ready` as "not yet — keep showing progress"), never speculatively. `failed`/`canceled` never produce a report and route to their terminal views (§5) instead.

## 9. Out of scope

- The report rendering itself (HTML/PDF/exec layouts) — [`./report-views.md`](./report-views.md) and Team F's `ReportService`.
- The create-scan form and the scans index/list page — [`./pages-and-routes.md`](./pages-and-routes.md).
- Auth / how `org_id` is resolved for the live connection — inherited from the API key like every other route ([`../api/scans-endpoints.md`](../api/scans-endpoints.md) §, Team C).
- The worker's actual interruption mechanics and what it writes per test — [`../orchestration/worker.md`](../orchestration/worker.md). This page only *reads* `ScanRecord.progress`/`top_attack`/`n_completed`.
- Any change to `ScanRecord` / `ScanStatus` — owned by [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md); if this UX needed a new field it would change there first (ARCHITECTURE §, "if a doc needs to change a contract, it changes here first").
