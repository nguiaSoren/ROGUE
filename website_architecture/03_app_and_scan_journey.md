# ROGUE — The App & The Scan Journey

A detailed, step-by-step account of ROGUE's **authenticated** product — the part of the site you only reach with a key — and the end-to-end journey a customer takes from "I have a key" to "I have a scored, downloadable report." Everything here is written as what the *customer does* and *sees*, anchored to the real code under `frontend/src/app/(app)/`. The public marketing/threat-intel pages (matrix, feed, sources) live at the app root and are covered elsewhere; this document is the dashboard behind the door.

The product surface is a deliberately small, linear funnel: **sign in → scans list → new scan → watch it run → read the report**. Four routes, one shell, one security pattern that holds the whole thing together. Live frontend at `https://rogue-eosin.vercel.app`; the authenticated API it talks to is the hosted platform service (defaults to `https://rogue-private.onrender.com`).

---

## 0. The authentication model in one breath

There is no username, no password, no user table. The platform authenticates with **API keys** (`rk_live_…`), so the dashboard "session" *is* the key — and the single most important design decision in the whole app is that **the key never lives in the browser.** It is POSTed once over HTTPS, validated, and parked in an httpOnly, secure cookie (`rogue_key`, `src/lib/session.ts`). From then on the browser holds a cookie it cannot read; every authenticated call either runs in a Server Component (which reads the cookie directly) or goes through a same-origin `/api/*` proxy route that re-reads the cookie server-side and attaches the bearer. JavaScript running in the page never touches the raw secret. Hold this fact — it recurs at every step.

---

## 1. Sign in — the key *is* the session

**Route:** `/sign-in` (`frontend/src/app/sign-in/page.tsx`)

The customer lands on a deliberately spare screen: a heading "Sign in to ROGUE," one line of copy, and a single password-masked input that says `rk_live_…`. The copy itself does the security reassurance work — "It is stored only in a secure, server-side session cookie — never in the browser." There is one button: **Sign in** (disabled until something is typed; it reads "Verifying…" while the request is in flight).

What happens when they paste a key and submit:

1. The client form `POST`s `{ api_key }` to the same-origin route `/api/session` (`frontend/src/app/api/session/route.ts`). The key travels exactly once, in a request body, over HTTPS.
2. That route handler does **not** trust the key on its face — it *validates* it by making an authenticated call against the live platform: `GET /v1/scans?limit=1` with the key as a bearer. If the platform answers, the key is real and scoped to a real tenant.
3. On success the handler calls `setApiKey()`, which writes the key into the `rogue_key` cookie with `httpOnly: true, secure: true, sameSite: "lax", path: "/", maxAge: 30 days`. Because it is `httpOnly`, the browser's JS — including any third-party script or XSS payload — cannot read it back out.
4. The client then `router.push("/scans")` and refreshes, landing the customer in the dashboard.

The failure paths are explicit and human:
- A key the platform rejects (401) surfaces as **"That API key was not recognized."**
- The platform being unreachable (cold start, network) surfaces as a 502 with the upstream message, so the customer can tell "wrong key" apart from "service is waking up."

**The "request access" path.** A prospect without a key isn't stranded. Below the form: "Don't have a key yet? **Request access** and we'll set up your account." It's a `mailto:` to `nguiasoren@gmail.com` pre-filled with the subject "ROGUE access request." Honest for a solo product pre-self-serve-signup — there is no key-vending machine yet, so the funnel routes a request straight to the founder.

**The gate.** Every authenticated page sits inside the `(app)` route group, whose layout (`(app)/layout.tsx`) is the bouncer: it reads the cookie via `getApiKey()` on the server and, if it's absent, `redirect("/sign-in")` before a single byte of dashboard renders. There is no flash of protected content. The layout also paints the product sub-nav — "Dashboard · Scans · New scan" — plus, on the right, a monospace fingerprint of the active key (`keyHint()` shows only the first 12 chars, e.g. `rk_live_abc…`, never the full secret) and a **Sign out** button. Sign-out (`components/sign-out-button.tsx`) is a `DELETE /api/session` that clears the cookie and returns to `/sign-in`.

---

## 2. The scans list — every red-team you've run

**Route:** `/scans` (`frontend/src/app/(app)/scans/page.tsx`)

This is the dashboard home. It's a **server-rendered** page (`dynamic = "force-dynamic"` — tenant data is never statically cached or shared), so the customer's scans are fetched on the server with their key already in hand, and the first paint is real data. It re-reads the key with `getApiKey()` and calls `platformApi.listScans(key, { limit: 50 })` directly — no client fetch, no bearer in the browser.

**What it shows.** A header eyebrow `/scans`, a big "Scans" title, the one-line promise ("Every red-team scan your org has launched, newest first. Click a row to watch a running scan or open its report."), and a **New scan** call-to-action in the top-right. Then a table, newest-first, one row per scan with six columns:

- **Scan** — the `scan_id`, monospace and green, linking to that scan's detail/live page.
- **Target** — a human label for the redacted target snapshot, picked as `model → provider → endpoint` (whichever exists first), truncated. Note this is the *redacted* target: a name, never a credential.
- **Status** — a tinted `StatusBadge` (running shows a pulsing green dot; completed green; failed red; queued/canceled muted).
- **Breaches** — the count, red if non-zero, muted at zero.
- **Score** — a `ScoreBadge` showing the 0–100 headline banded by color (≥70 red, ≥40 orange, <40 green), or a muted "—" while a scan is still running and unscored.
- **Created** — a compact localized timestamp.

**The empty state.** A first-time customer with zero scans doesn't see a bare table — they get a dashed-border panel: "No scans yet," a sentence explaining what a scan produces ("breaches, a risk score, and a downloadable report"), and a **New scan** button. The funnel never dead-ends.

**The error state.** Because tenant data must never be quietly stale or cross-tenant, a failed fetch does *not* fall back to cached HTML — it renders an explicit red panel, "Couldn't load scans," with the underlying message. Better an honest error than a wrong tenant's data.

---

## 3. New scan — point ROGUE at a model

**Route:** `/scans/new` (`frontend/src/app/(app)/scans/new/page.tsx`)

This is the only heavily-interactive page in the funnel, so it's a client component. The framing copy is plain: "Point ROGUE at a model and pick an attack pack. Scans run asynchronously — you'll watch progress live on the next screen." The form has a few decisions to make:

**Target — provider vs. endpoint.** A two-button toggle:
- **Known provider** — a dropdown of `openai / anthropic / openrouter / groq / gemini`. The model field is optional here (provider default is used if blank; placeholder hints `gpt-5.4-nano`).
- **Custom endpoint** — a free-text field for an OpenAI-compatible base URL (placeholder `https://gateway.company.ai/v1`), for pointing ROGUE at a company's own gateway or a self-hosted model. In this mode the model field is the model name and the Launch button stays disabled until an endpoint is typed.

**Target API key (optional).** A password-masked, `autoComplete="off"` field. If left blank, the platform uses its server-side key for that provider; if the customer needs ROGUE to authenticate as *them* against *their* gateway, they paste it here. (At the API boundary this maps to `TargetSpec.api_key`, a raw credential that the platform never persists or echoes back — the redacted snapshot only records `has_api_key`.)

**Attack corpus — the three modes.** A three-button toggle that chooses how hard ROGUE hits, with an inline explainer:
- **Curated pack** (`pack`) — a quick sample of ROGUE's threat library. The cheap, fast default.
- **Full repertoire** (`repertoire`) — the entire live harvested corpus, capped at `max_tests`. (Choosing this disables the pack dropdown — there's no pack to pick when you're running everything.)
- **Full ladder** (`ladder`) — escalate each goal through ROGUE's full multi-tier arsenal (graduated techniques, chain-of-jailbreak, structured-data, image/audio renderers). The deepest and most expensive mode.

**Pack & max tests.** When in pack mode, a **Pack** dropdown (`default / aggressive / compliance`) and a **Max tests** number input (1–1000, default 10) bound the run.

**What gets sent.** On submit the form assembles a `ScanSpec` — `{ target: { provider|endpoint, model, api_key }, mode, pack, max_tests }` — and `POST`s it to the same-origin `/api/scans` route (`frontend/src/app/api/scans/route.ts`) with a freshly-minted `Idempotency-Key: crypto.randomUUID()` header. That idempotency key matters: scans cost real money (LLM panel + judge calls), so a double-click or a flaky retry must not launch two paid scans — the platform de-dupes on that key. The `/api/scans` route reads the session cookie server-side, forwards the spec to `POST /v1/scans` with the bearer attached, and returns the created `ScanRecord` (status `queued`, a 202). The browser, again, never sees the key.

On the `{ scan_id }` coming back, the form immediately `router.push("/scans/{scan_id}")` — straight to the live page. Failures (a 4xx/5xx error envelope, or an unreachable server) render inline in red without leaving the form.

---

## 4. Live progress — watch it run

**Route:** `/scans/[scanId]` (`frontend/src/app/(app)/scans/[scanId]/page.tsx`)

This page is a thin server shell wrapping a live client poller, and the split is intentional. The **server shell** owns the route and the *initial* `getScan(scanId, key)` fetch (key read server-side), so the first paint is already real data — the customer never stares at an empty spinner. The header shows the scan id (monospace, breakable) and a one-line summary: `{target} · {pack} pack · {n_tests} tests planned`. If the seed fetch fails, the page renders a red "Couldn't load this scan" panel with a link back to `/scans`. Otherwise it hands the record to the **client poller**, `<ScanProgress>` (`frontend/src/components/scan-progress.tsx`).

**The poller.** `ScanProgress` runs exactly **one** poll loop for the page (the "one connection, many consumers" discipline — every sub-readout reads the single `record` state, no per-widget fetchers). Every ~2 seconds it `fetch`es the same-origin `GET /api/scans/{id}` proxy — note again: the client poller holds no bearer; the proxy route (`frontend/src/app/api/scans/[scanId]/route.ts`) re-reads the cookie and attaches the key. The loop:

- If the scan was *already* terminal on first load, it never polls at all.
- On each tick it replaces the `record` state and re-renders; when the status goes terminal (`completed / failed / canceled`) it stops rescheduling.
- A transient blip (Render cold start, a gateway 502) does **not** paint the scan as broken — the loop swallows the error, keeps the last good progress on screen, shows a tiny "connection blip — retrying" line, and tries again. The progress UI is resilient by design.

**What the customer watches.** A live card that updates in place:
- A **status badge** (with the pulsing dot while running) and, once the platform has set it, a live **risk** score badge.
- A **progress bar** — determinate once running (green fill animating to the live `progress`%), painted red on failure, snapped to 100% on completion.
- The spec's signature **progress line**: `67% · 32/50 tests complete · Current attack: Crescendo` — percent, the `n_completed/n_tests` counter, and the current attack name.
- A **running readouts** row: `{n_breaches} breaches so far` (red once any breach lands), `~$X.XX spent (estimate)`, and a linear-projection **ETA** (`elapsed × (100 − progress) / progress`, floored at 1 min) while it's running.

**Cancel.** While the scan is non-terminal, a red **Cancel scan** button is live. It confirms ("Stop this scan? Tests already run still count toward the report."), then `POST`s the same-origin `/api/scans/{id}/cancel` proxy (bearer attached server-side), and updates the card from the returned record; the poll loop reconciles any drift.

**Terminal framing.** Each end-state gets its own line: *queued* → "Queued — waiting for a worker"; *failed* → the error message in a red box; *canceled* → "partial progress above is real and counts toward any report"; *completed* → a green **View report →** button that links to the report route. The customer never has to guess what happened or where to go next.

---

## 5. The report — the deliverable

**Route:** `/scans/[scanId]/report` (`frontend/src/app/(app)/scans/[scanId]/report/page.tsx`)

This is the product's payoff: the brief for one scan. It's a server component (`force-dynamic`) that reads the key server-side and fetches `GET /v1/scans/{id}/report?format=json`. The page **never recomputes a rate or a score** — everything arrives pre-derived in the report JSON (`ScanReportJson`, mirroring `ScanReport.to_dict()` plus the platform's `score`, `risk_level`, `score_methodology`, and `recommendations[]`). If the report isn't ready yet (the route 404s with `report_not_ready` while the scan is still running), the page treats that as a soft "not ready" state — "this scan hasn't completed yet" with a link back to watch progress — not a hard error.

The deliverable, top to bottom:

**The RiskHeadline.** The score leads. A big `score/100` numeral, color-tinted to the banded risk level (critical red / high orange / medium yellow / low green), with a risk-level pill beside it and, pulled to the right, the **Top attack** name. Below it, set off by a top border, the **methodology caption** — one plain-English line (`score_methodology`) explaining how the score is computed, so the headline number is never a black box. (`risk_level` comes from the report route; on older runs the page derives the band from `score` with the same cut-points the platform uses: ≥75 critical, ≥50 high, ≥25 medium, else low.)

**The executive summary.** Directly under the headline — before the KPI row — a branded "Executive summary" card renders the report's top-level `executive_summary` markdown (via `ReportSummaryMarkdown`): the forward-to-your-boss overview a customer reads first after the score. It's the same exec narrative the platform's `ReportService.build_json` emits and the MCP `create_executive_summary` tool returns. It degrades to nothing on older runs that didn't carry one.

**The KPI row.** Four cards: **Tests** (`n_tests`), **Breaches** (red if any, green at zero), **Breach rate** (`Math.round(breach_rate × 100)%`, same coloring), and **Cost** (formatted USD — two decimals at/above a cent, four below). The whole risk picture in one glance.

**The findings.** Each breached finding (filtered to `n_breach > 0`, sorted worst-first by severity then success rate) becomes a color-banded card carrying:
- a rank, a severity pill, and the attack **vector**;
- the breach math, e.g. `breached 4/5 trials · 80%`, colored by how bad the rate is;
- the finding **title**, and a monospace `family · technique` line;
- a **"What this is"** block — the per-finding `explanation`, plain-language framing so a non-expert grasps the risk, shown above the fix and the evidence (degrades gracefully when absent);
- a distinct **"How to fix"** block — the finding's `remediation`, given a green accent so it reads as the "do this" instruction, visually separated from the explanation;
- a single **collapsible evidence** `<details>` — "Evidence — attack & model response" — holding both the **Attack sent →** (the literal jailbreak payload, in a monospace block) and the **Model response** (the target's actual reply). It's folded by default so the report reads clean; because the finding breached, the summary line carries a red **"breached"** flag and the response is tinted red, so the evidence reads as confirmed proof of a compromise, not a benign sample.

If nothing reproduced, the findings section is a green all-clear: "No vulnerabilities reproduced across N tests." And a closing **Recommendations** panel lists the report-level "what to do next" (`recommendations[]`), degrading gracefully to a sensible one-liner when the platform didn't supply any.

**The exports — HTML / PDF / JSON.** Top-right of the report sit three export buttons. These are the only place the report leaves the app, and they're built carefully:
- They are plain same-origin `<a href>`s pointing at `/api/scans/{id}/report?format={html|pdf|json}` — the export *proxy* (`frontend/src/app/api/scans/[scanId]/report/route.ts`), **not** the platform URL. The proxy re-reads the cookie, fetches upstream with the bearer attached, and streams the body straight back with the upstream content-type. This is why the buttons can be ordinary links: the secret never appears in a client-visible URL.
- **HTML** opens in a new tab (`target="_blank"`) — the standalone, shareable brief.
- **PDF** downloads. The proxy sets `Content-Disposition: attachment; filename="rogue-{scanId}.pdf"`, so the customer gets a sensibly-named file rather than a tab full of binary. (The PDF is now produced server-side by reportlab on the platform.)
- **JSON** is the raw machine-readable report — the same shape this page rendered from — for piping into a customer's own tooling.

---

## 6. The proxy / security pattern — the spine under all of it

One pattern holds the entire authenticated app together, and it's worth stating on its own because it repeats at every step above:

**The `rk_live_` key is server-side, always. The browser only ever holds an httpOnly cookie.**

Two kinds of code consume the key, and neither leaks it:

1. **Server Components** (`/scans`, `/scans/[scanId]` shell, `/scans/[scanId]/report`) read the cookie directly via `getApiKey()` and call `platformApi.*(…, key)` server-side. The bearer is injected by the `apiV1` client (`frontend/src/lib/platform-api.ts`) as an `Authorization: Bearer` header on a server-to-server fetch. It is never `NEXT_PUBLIC_*`, so it cannot ship in the JS bundle.

2. **Client components** (the new-scan form, the live poller + cancel button, the export links, sign-in/out) never touch the key. They call **same-origin `/api/*` route handlers** — `POST /api/session`, `DELETE /api/session`, `POST /api/scans`, `GET /api/scans/{id}`, `POST /api/scans/{id}/cancel`, `GET /api/scans/{id}/report` — and *each* handler re-reads the `rogue_key` cookie server-side and forwards the bearer upstream. The cookie rides along automatically (same origin); the secret inside it is unreadable to script.

Two supporting properties round it out. **Tenancy:** every authenticated call is `cache: "no-store"` (never the public corpus's 300s ISR), and a failed fetch renders an explicit error rather than risk serving another tenant's cached HTML. **Resilience:** the platform client carries the same Render cold-start posture as the public reader — a 502/503/504 retry with 1.5s→3s backoff and a 12s per-attempt timeout — so the first call after the service has been idle rides out the boot instead of failing the customer.

The net effect for the customer is the experience of a normal logged-in dashboard — and the net effect for security is that there is no client-side surface from which the key can be exfiltrated.

---

## Appendix — files behind each step

| Step | Customer-facing route | Code |
|---|---|---|
| Sign in | `/sign-in` | `frontend/src/app/sign-in/page.tsx`, `frontend/src/app/api/session/route.ts`, `frontend/src/lib/session.ts` |
| Auth gate + shell | `(app)` group | `frontend/src/app/(app)/layout.tsx`, `frontend/src/components/sign-out-button.tsx` |
| Scans list | `/scans` | `frontend/src/app/(app)/scans/page.tsx`, `frontend/src/components/score-badge.tsx` |
| New scan | `/scans/new` | `frontend/src/app/(app)/scans/new/page.tsx`, `frontend/src/app/api/scans/route.ts` |
| Live progress | `/scans/[scanId]` | `frontend/src/app/(app)/scans/[scanId]/page.tsx`, `frontend/src/components/scan-progress.tsx`, `frontend/src/app/api/scans/[scanId]/route.ts`, `frontend/src/app/api/scans/[scanId]/cancel/route.ts` |
| Report + exports | `/scans/[scanId]/report` | `frontend/src/app/(app)/scans/[scanId]/report/page.tsx`, `frontend/src/app/api/scans/[scanId]/report/route.ts` |
| Typed client + types | — | `frontend/src/lib/platform-api.ts` (`platformApi`, `ScanSpec`, `ScanRecord`, `ScanReportJson`, `Finding`) |
