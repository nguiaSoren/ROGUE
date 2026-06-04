# `(app)` — authenticated product group

The customer-facing SaaS product (the org-scoped scan workflow), distinct from the public marketing/threat-intel pages that stay in the app root. Specced in `docs/platform/dashboard/{pages-and-routes,live-scan-ux,report-views}.md`. **Auth is wired and live (2026-06-05)** against the hosted `/v1` API; `tsc --noEmit` + `eslint` clean.

## Auth model — the API key is the session

The platform authenticates with API keys (not user logins), so the dashboard "session" is the key itself, held server-side:

- **`/sign-in`** (`src/app/sign-in/page.tsx`) — paste an `rk_live_…` key → `POST /api/session`, which validates it against the platform and stores it in an **httpOnly, secure cookie** (`src/lib/session.ts`). The browser's JS never holds the raw key.
- **`(app)/layout.tsx`** — the auth gate: reads the cookie via `getApiKey()` and `redirect("/sign-in")`s when absent. Renders the product sub-nav + sign-out (`components/sign-out-button.tsx`, `DELETE /api/session`).
- **Server Components** read the key with `getApiKey()` and call `platformApi.*` directly (server-side). **Client components** never see the key — they call same-origin **Route Handlers** that re-read the cookie and forward the bearer:
  - `GET /api/scans/{id}` (the live poller), `POST /api/scans/{id}/cancel`, `GET /api/scans/{id}/report?format=json|html|pdf` (export proxy — keeps the bearer out of client hrefs), `POST /api/scans` (the launch form), `POST|DELETE /api/session`.

## Pages

- `scans/` — server-rendered list (id, target, status, breaches, score, created) with empty/error states.
- `scans/new/` — the launch form (provider or custom endpoint, model, target key, pack, max_tests) → `POST /api/scans` with an `Idempotency-Key` → routes to the detail page.
- `scans/[scanId]/` — server shell + `components/scan-progress.tsx`, a single-poller client component that polls `/api/scans/{id}` every ~2s until terminal (the `█████ 67% — 32/50 — Current attack: …` line + live cost/ETA), with a working cancel button.
- `scans/[scanId]/report/` — completed report: KPIs (score/breach-rate/top-attack/cost), worst-first findings with remediation, recommendations, and HTML/PDF/JSON exports via the authed proxy.

## Remaining (nice-to-have, not blocking)

- **SSE transport (Option B).** The detail page polls; a `GET /v1/scans/{id}/events` stream can slot in behind the same `ScanProgress` seam later without a contract change.
- **Multi-project / org switcher.** One key = one tenant today; a switcher (and project scoping in the list) is future work once a tenant has multiple projects.
- **`NEXT_PUBLIC_API_BASE`** should point at `https://rogue-private.onrender.com` on Vercel (the platform client also defaults there).
