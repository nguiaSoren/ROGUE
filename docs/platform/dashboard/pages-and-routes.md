# Dashboard — Pages & Routes

> Team D, the Dashboard box of [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §6. This doc owns the **page tree and routing** of the authenticated, multi-tenant dashboard: the App Router segment layout, the marketing-vs-authed split, how a session attaches its credential to the API client, the server-component data-fetching shape, and how the existing single-tenant pages (`/matrix`, `/feed`, `/brief`, `/analytics`) relate to the new org-scoped product. Two sibling docs own the depth that would bloat this one: the streaming progress UI of a running scan lives in [`./live-scan-ux.md`](./live-scan-ux.md), and the rendered report surface (the HTML/PDF/exec views Team F produces) lives in [`./report-views.md`](./report-views.md). The credential this doc threads through `lib/api.ts` — sessions, keys, the bearer — is specified by Team C in [`../api/auth-and-keys.md`](../api/auth-and-keys.md); the routes the pages call are catalogued in [`../api/overview.md`](../api/overview.md). This doc never redefines `ScanRecord`, `ScanStatus`, `score`, or any endpoint — it consumes the vocabulary from ARCHITECTURE §5 and the contracts from those docs.

Status: **PARTIALLY BUILT (local); narrower than this spec.** The authenticated **`(app)` route group shipped** with the scan-centric pages — but the broader page tree below is mostly unrealized. **Shipped under `frontend/src/app/`:**
- `(app)/layout.tsx`, `(app)/scans/page.tsx` (list), `(app)/scans/new/page.tsx` (create), `(app)/scans/[scanId]/page.tsx` (detail/live), `(app)/scans/[scanId]/report/page.tsx` (report view).
- `sign-in/page.tsx` (a top-level route, **not** an `(auth)/` group).
- The legacy pages — `/` (landing), `/matrix`, `/matrix/cell`, `/feed`, `/brief`, `/analytics` — **stayed at the top level; they were NOT moved into a `(marketing)/` route group.**

**Not built:** the `(marketing)/` and `(auth)/` route groups; `(app)/dashboard`, `(app)/reports`, `(app)/reports/[id]`, `(app)/benchmarks`, and `(app)/settings/*`. The route param is `[scanId]` (not `[id]`), and the report view is a nested route `(app)/scans/[scanId]/report` rather than a top-level `/reports/[id]`. Treat the tree and layout-refactor below as the intended design; the shipped surface is the scan list/create/detail/report flow inside `(app)`.

---

## 1. What exists today, and the split we impose

The live app is a single-tenant marketing-and-internals site. Every page under `frontend/src/app/` (`page.tsx`, `analytics/`, `brief/`, `feed/`, `matrix/`, `matrix/cell/`) is publicly readable, unauthenticated, and reads the bespoke `/api/*` dashboard endpoints through the one client in `frontend/src/lib/api.ts`. The tenant is hard-coded `acme` server-side (`src/rogue/api/main.py:934`, noted in [`../api/overview.md`](../api/overview.md)) — the frontend never names a tenant because there is only one. The root layout (`frontend/src/app/layout.tsx:24`) wraps everything in one `ThemeProvider` + `SseFeedProvider` + a single `Nav` (`frontend/src/components/nav.tsx:18`).

The product split is: **the marketing site and the ROGUE-internal threat-intel pages stay public and route-group-isolated; the customer-facing product lives behind auth in a new route group.** We use App Router **route groups** (parenthesized segments that organize without adding a URL segment) to draw that boundary without renaming any existing URL:

```
frontend/src/app/
  (marketing)/            ← public; no API key; the landing + internal threat-intel views
    page.tsx              ← / (the existing landing page, moved in — URL unchanged)
    feed/page.tsx         ← /feed     ┐ the existing single-tenant `acme` pages,
    matrix/page.tsx       ← /matrix   │ moved verbatim into the group. URLs unchanged.
    matrix/cell/page.tsx  ← /matrix/cell
    brief/page.tsx        ← /brief    │ §6 reframes these as ROGUE's own corpus
    analytics/page.tsx    ← /analytics┘ ("our research", not "your scan").
  (app)/                  ← authenticated product; every route requires a session
    layout.tsx            ← AppShell: auth gate + org switcher + product nav
    dashboard/page.tsx    ← /dashboard      overview KPIs across the org's projects
    scans/page.tsx        ← /scans          scan list (status table)
    scans/[id]/page.tsx   ← /scans/{scan_id} scan detail (live UX → ./live-scan-ux.md)
    scans/new/page.tsx    ← /scans/new      create a scan (POST /v1/scans)
    reports/page.tsx      ← /reports        report index   (→ ./report-views.md)
    reports/[id]/page.tsx ← /reports/{report_id} a rendered report (→ ./report-views.md)
    benchmarks/page.tsx   ← /benchmarks     benchmark runs + trend
    settings/...          ← /settings/*     org / projects / members / API keys (§5)
  (auth)/                 ← unauthenticated, but not marketing chrome
    sign-in/page.tsx      ← /sign-in
  api/revalidate/route.ts ← unchanged ISR hook (frontend/src/app/api/revalidate/route.ts)
  layout.tsx              ← root layout: html/body/fonts/theme ONLY (see §2)
```

Moving the existing files into `(marketing)/` is a directory move — the parenthesized group contributes nothing to the URL, so `/`, `/matrix`, `/feed`, `/brief`, `/analytics`, `/matrix/cell` all resolve exactly as today. No redirects, no broken links, no Vercel config change. The `frontend/src/app/api/revalidate/route.ts` hook (it revalidates `/matrix`, `/brief`, `/feed`, `/` — `route.ts:18`) is untouched because those paths don't move.

## 2. Layout tree — where the chrome lives

App Router nests layouts by segment, so the route-group boundary is also the chrome boundary. We push everything *shared by literally every page* up to the root and let each group own its own shell:

- **Root `layout.tsx`** keeps only what is universal: `<html>`/`<body>`, the Geist fonts, and the `ThemeProvider` (today `frontend/src/app/layout.tsx:8–45`). We **lift `Nav` and `SseFeedProvider` out of the root** — they are marketing-internal chrome (`SseFeedProvider` holds the single `/api/sse/feed` connection for the live ticker, which the product pages don't want) and belong in `(marketing)/layout.tsx`.
- **`(marketing)/layout.tsx`** renders the existing `Nav` (`frontend/src/components/nav.tsx`) and `SseFeedProvider`. This is the current root layout's body, relocated. The marketing nav's links (`/feed`, `/matrix`, `/analytics`, `/brief` at `nav.tsx:61–64`) and its live "DB · UP · N 24h" pill stay exactly as built.
- **`(app)/layout.tsx`** is the **AppShell**: it is the auth gate (§3), it mounts the org switcher + product nav, and it is a Server Component that reads the session once and passes `org` context down. It does **not** import `SseFeedProvider` — the only product surface that streams is the running-scan view, which opens its own connection scoped to one `scan_id` (owned by [`./live-scan-ux.md`](./live-scan-ux.md)), not an app-wide feed.
- **`(auth)/layout.tsx`** is a bare centered card — no nav, no org context (there's no org yet).

This gives three independent navigation contexts (public threat-intel, the authed product, the sign-in flow) with zero shared mutable chrome, and it keeps the heavy SSE provider off every product page that doesn't need it.

## 3. Auth, session, and the API credential

Auth is owned by Team C ([`../api/auth-and-keys.md`](../api/auth-and-keys.md)); this doc consumes it. The dashboard's two jobs are: **gate the `(app)` group on a session**, and **attach the right credential to every `/v1` call**.

**The gate.** `(app)/layout.tsx` resolves the session server-side (the session cookie → `{ user, org_id, project_id, role }`). No session ⇒ `redirect("/sign-in?next=…")` before any child renders; this is a single server-side check at the group root, so no `(app)` page can render unauthenticated and there is no place to forget the check (mirrors the API's router-level `Depends(get_api_key)` discipline in [`../api/overview.md`](../api/overview.md)). `/sign-in` lives in `(auth)` and posts to Team C's session endpoint; on success it redirects to `next`.

**The org switcher.** A user may belong to several `org_<ulid>`s (ARCHITECTURE §5). The active org lives in the session, surfaced by a switcher in the AppShell header; switching writes the new `org_id` to the session and triggers a router refresh so every server component re-fetches under the new tenant. Because tenancy is enforced server-side on the API (every `/v1` call is scoped by the resolved key/org — [`../api/overview.md`](../api/overview.md)), the switcher is a *convenience*, not the security boundary: a stale client cannot read another org's data, the API rejects it.

**Threading the credential into `lib/api.ts`.** Today `lib/api.ts` is a single bare `apiGet` against `API_BASE = process.env.NEXT_PUBLIC_API_BASE` (`frontend/src/lib/api.ts:14`, `:34`) with **no auth header** — correct for the credential-less public `/api/*` surface, which stays exactly as is. The product pages call the **new `/v1` surface**, which is key-authenticated (an `Authorization: Bearer` header, never a cookie — [`../api/overview.md`](../api/overview.md) §CORS). So we add a **second, parallel client** rather than retrofitting the existing one:

- Keep `api` / `apiGet` (the `/api/*` reader) untouched — `(marketing)` keeps using it verbatim.
- Add `apiV1<T>(path, init)` in the same file (or `lib/api-v1.ts`): same retry/backoff/timeout shape as `apiGet` (the Render cold-start `502/503/504` retry with 1.5s→3s backoff and the 12s per-attempt abort, `lib/api.ts:23–28`, `:37–60`) — that resilience is exactly as valuable for `/v1` — but it **injects the bearer** and reads the error envelope (`{ error: { code, message } }`, ARCHITECTURE §5) instead of a bare status.
- The bearer is **never** `NEXT_PUBLIC_*` (that would ship a secret to the browser). `(app)` data fetching is server-side (§4): the credential is read from the server session inside the Server Component / Route Handler and passed to `apiV1` as an argument — it never crosses to the client. A client component that must call `/v1` (e.g. the `/scans/new` submit) posts to a thin Next **Route Handler** under `(app)` that re-reads the session server-side and forwards with the bearer; the browser never holds it.

The customer's own scan **target** key (`TargetSpec.api_key_ref`, ARCHITECTURE §5) is a Vault/KMS handle managed by Team C — the dashboard only ever displays/selects the *reference*, never the secret, and never sends a raw target key from the browser.

## 4. Data fetching — server components + the retry pattern

The existing pages are an exact template to follow: `frontend/src/app/matrix/page.tsx` is an `async` Server Component that `export const revalidate = 300` (`matrix/page.tsx:26`) and `await`s the data at the top (`api.breachMatrix()`, `matrix/page.tsx:40–43`), deliberately *not* catching the critical fetch so a transient failure lets Next keep serving the last-good static page rather than caching an error (`matrix/page.tsx:34–39`). Product pages reuse this shape with two differences driven by tenancy:

- **Per-request, not ISR, for tenant data.** A `ScanRecord` list or a live scan is private and changes per request — it cannot be statically shared across tenants. `(app)` pages fetch with `cache: "no-store"` (or short per-tag revalidation), not the 300s ISR window the public corpus uses. The marketing/threat-intel pages keep their ISR + the `revalidate` hook; the product pages opt out.
- **Reuse the retry/backoff verbatim.** `apiV1` carries the same cold-start resilience as `apiGet` (§3) — Render still spins down. The "let the critical fetch throw" choice (`matrix/page.tsx:34`) is *reversed* for product pages: a tenant page that fails to load should render an explicit error state (the envelope's `message`), not silently serve stale cross-request HTML, because there's no safe last-good static page for private data.

Page-by-page data sources, all via `apiV1` against routes catalogued in [`../api/overview.md`](../api/overview.md):

- **`/dashboard`** — `GET /v1/scans` (newest-first, paginated) rolled up into KPI capsules: total scans, scans this week, worst `score` across projects, count of `running`/`queued`, and a recent-scans table. The capsule component is the existing `StatCapsule` pattern (`matrix/page.tsx:223`) reused, tinted by `score` band. A project filter narrows `GET /v1/scans?project_id=…`.
- **`/scans`** — `GET /v1/scans` as a paginated table keyed on `ScanRecord`: `created_at`, `status` (the `ScanStatus` badge), `progress`, `n_breaches`, `score`, `top_attack`. Cursor pagination (`limit`/`cursor`, [`../api/overview.md`](../api/overview.md)). Each row links to `/scans/{scan_id}`.
- **`/scans/[id]`** — `GET /v1/scans/{scan_id}` for the `ScanRecord`. While `status ∈ {queued, running}` the page hands off to the live progress UX in [`./live-scan-ux.md`](./live-scan-ux.md) (its own stream + poll); on `completed` it links to the report via `report_id`; on `failed` it shows the record's `error`. **This page defers all running-state rendering to that sibling doc** — here it only owns the route, the initial server fetch, and the terminal-state framing.
- **`/scans/new`** — a form that builds a `ScanSpec` (`target`, `pack`, `attacks`, `max_tests`, `n_trials`, `budget` — ARCHITECTURE §5) and POSTs `POST /v1/scans` via the `(app)` Route Handler (§3). On the `202` it redirects to `/scans/{scan_id}`. Sends an `Idempotency-Key` so a double-submit can't launch two paid scans ([`../api/overview.md`](../api/overview.md), idempotency).
- **`/reports` and `/reports/[id]`** — index from the completed scans' `report_id`s; the rendered view is owned by [`./report-views.md`](./report-views.md) (it consumes `GET /v1/scans/{id}/report`, JSON/HTML/PDF via `Accept`). This doc only routes to it.
- **`/benchmarks`** — benchmark runs and their trended score. Submits via `POST /v1/benchmark` (async-job, same pattern as scans) and lists results; the dataset list + scoring/trend semantics are Team E's ([`../api/overview.md`](../api/overview.md) links to `validate-benchmark-endpoints.md`). The dashboard renders the trend line with the existing lightweight `spark`/`count-up` components, not a new chart lib.
- **`/settings/*`** — see §5.

## 5. Settings — org, projects, members, API keys

`(app)/settings/` is a nested-layout section with a left sub-nav (its own `layout.tsx`) and four leaf pages, all reading/writing Team C's tenancy surface ([`../api/auth-and-keys.md`](../api/auth-and-keys.md)):

- **`/settings/org`** — org name, plan, usage/quota against the rate-limit tiers ([`../api/overview.md`](../api/overview.md), rate limiting).
- **`/settings/projects`** — list/create `proj_<ulid>`s; a project scopes scans (`project_id` on every `ScanSpec`/`ScanRecord`).
- **`/settings/members`** — invite/list members and roles (RBAC owned by Team C; the dashboard renders the role, the API enforces it).
- **`/settings/keys`** — create/revoke `rk_live_…` / `rk_test_…` keys. The **full key is shown exactly once at creation** (only its SHA-256 is stored, ARCHITECTURE §5); the list thereafter shows a prefix + last-four + `created_at` + `last_used_at`. These keys authenticate *external* `/v1` clients (SDK, curl, MCP) — they are distinct from the dashboard's own session credential, and creating one here is the canonical "company → API → ROGUE with no human" onramp (ARCHITECTURE §8). Writes go through the `(app)` Route Handler so the session, not a stored key, authorizes them.

## 6. How the existing internal pages relate

`/matrix`, `/feed`, `/brief`, `/analytics` were built single-tenant against `acme`. We do **not** org-scope them and we do **not** delete them — they become **ROGUE's own continuously-running red-team result set**, reframed as marketing/credibility surface ("here is the open-web threat corpus and how it breaks frontier models") rather than per-customer data. They keep their public `/api/*` reads, their ISR + `revalidate` hook, the `SseFeedProvider` live ticker, and their URLs. This is why they sit in `(marketing)` and not `(app)`. A customer's *own* breach matrix is a different artifact — it is the per-scan report ([`./report-views.md`](./report-views.md)) rendered from their `ScanRecord`, scoped by `org_id`/`project_id`, never the global `acme` corpus. If later we want an internal-admin cut of these (per-tenant matrix for support), it is a separate `(app)/admin/` section gated on an internal role, reusing the same heatmap component (`frontend/src/components/matrix-heatmap.tsx`) against an org-scoped endpoint — explicitly out of scope here.

## 7. The "no heavy client" constraint

ROGUE's frontend is deliberately light (the host-machine note in the project conventions; Turbopack `next dev` is banned). The product pages **reuse the existing component vocabulary** rather than introduce a framework: `StatCapsule` (`matrix/page.tsx:223`) for KPIs, the `Term`/glossary affordance (`frontend/src/components/glossary.tsx`), `count-up` and `spark` for numbers and trends, `ui/button` for actions, and the `loading.tsx` route-segment convention already used at `frontend/src/app/matrix/loading.tsx` and `matrix/cell/loading.tsx` for streaming Suspense fallbacks. Default to Server Components; a page goes `"use client"` only where it must (the org switcher, the `/scans/new` form, the live scan view in [`./live-scan-ux.md`](./live-scan-ux.md)) — matching today's split where `nav.tsx:1` is the rare client component and `matrix/page.tsx` is a server one. No new charting/state/data-grid dependency: the scan table is a server-rendered `<table>` with cursor links, not a client data-grid. Any client interactivity that streams opens exactly one connection scoped to the thing on screen, never an app-wide provider.

## 8. Route table (the authoritative IA)

This is the complete `(app)` IA at a glance — every product URL, the API contract behind it, the rendering mode, and who owns the deep detail. The `(marketing)` URLs (`/`, `/feed`, `/matrix`, `/matrix/cell`, `/brief`, `/analytics`) are unchanged from today and intentionally absent here.

| URL | Segment file | API call(s) | Render | Owner of detail |
|---|---|---|---|---|
| `/dashboard` | `(app)/dashboard/page.tsx` | `GET /v1/scans` (rollup) | server, `no-store` | this doc |
| `/scans` | `(app)/scans/page.tsx` | `GET /v1/scans` (cursor) | server, `no-store` | this doc |
| `/scans/new` | `(app)/scans/new/page.tsx` | `POST /v1/scans` (202) | client form → Route Handler | this doc |
| `/scans/{id}` | `(app)/scans/[id]/page.tsx` | `GET /v1/scans/{id}` + stream | server shell + client stream | [`./live-scan-ux.md`](./live-scan-ux.md) |
| `/reports` | `(app)/reports/page.tsx` | derived from completed `ScanRecord`s | server, `no-store` | this doc |
| `/reports/{id}` | `(app)/reports/[id]/page.tsx` | `GET /v1/scans/{id}/report` | server (+ `Accept` for HTML/PDF) | [`./report-views.md`](./report-views.md) |
| `/benchmarks` | `(app)/benchmarks/page.tsx` | `POST /v1/benchmark` (202) + list | server, `no-store` | Team E + this doc |
| `/settings/org` | `(app)/settings/org/page.tsx` | tenancy read/write | server + Route Handler | Team C ([`../api/auth-and-keys.md`](../api/auth-and-keys.md)) |
| `/settings/projects` | `(app)/settings/projects/page.tsx` | tenancy read/write | server + Route Handler | Team C |
| `/settings/members` | `(app)/settings/members/page.tsx` | tenancy read/write | server + Route Handler | Team C |
| `/settings/keys` | `(app)/settings/keys/page.tsx` | key create/revoke | server + Route Handler | Team C |
| `/sign-in` | `(auth)/sign-in/page.tsx` | session create | client form → Route Handler | Team C |

The `loading.tsx` segment convention (already used at `frontend/src/app/matrix/loading.tsx`) gives each of these a skeleton during the server fetch for free; the `(app)` group adds one `loading.tsx` at the group root and per-segment overrides where the skeleton differs (the scan table vs the dashboard KPIs).

## 9. Open questions for sibling teams

- **Session shape.** The exact cookie/JWT contract and the org-switch endpoint are Team C's ([`../api/auth-and-keys.md`](../api/auth-and-keys.md)); this doc assumes a server-readable session yielding `{ user, org_id, project_id, role }`. If sessions are stateless JWTs the AppShell gate is a verify, not a lookup — either satisfies §3.
- **Report identity.** Whether `/reports/[id]` keys on `report_id` or on `scan_id` is Team F's call ([`./report-views.md`](./report-views.md)); the routing above is written to either by linking through the `ScanRecord.report_id`.
- **Live transport.** SSE vs WebSocket vs poll for `/scans/[id]` is owned by [`./live-scan-ux.md`](./live-scan-ux.md); §2's decision to keep `SseFeedProvider` out of `(app)` holds regardless — the running-scan stream is per-`scan_id`, not app-wide.
