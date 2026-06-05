# ROGUE Website — Sitemap & Navigation

This document maps every user-facing page on the ROGUE website and describes how a person moves between them. It is exact to the filesystem as of this writing: every route listed below corresponds to a real `page.tsx` (or static asset) under `frontend/src/app/` or `frontend/public/`. Routes that do not exist are not listed.

The ROGUE frontend is a Next.js App Router project. The app splits into two worlds that share one chrome: a **public** marketing + threat-intelligence surface (the app root), and an **authenticated** customer product (the `(app)` route group — a parenthesized group, so the `(app)` segment does not appear in any URL). The boundary between them is the `(app)/layout.tsx` auth gate, which redirects unauthenticated visitors to `/sign-in`. Everything else is reachable without signing in.

## Route table

Every user-facing route, its source file, whether it is public or gated, and what it is for. All paths are relative to `frontend/src/app/` unless noted.

| Route | File | Access | Purpose |
|---|---|---|---|
| `/` | `page.tsx` | Public | Cinematic landing / demo entry. Hero stat trio, product pitch, sources marquee, fresh-attacks ticker + mini-matrix, MCP-connect, the §10.7 augmentation showcase + interactive lab, and deep-dive cards to `/feed`, `/matrix`, `/brief`. The "5-second pitch, 5-minute deep-dive" page. |
| `/feed` | `feed/page.tsx` | Public | Live Feed (§11.1). 4-tile KPI strip, augmentation A/B summary strip, then a 3-column "war room": sources ribbon, expandable attack list (payload viewer + copy + replay), and an augmentation sidebar of widgets. Statically prerendered + ISR. |
| `/matrix` | `matrix/page.tsx` | Public | Breach Matrix heatmap — attack families × deployment configs, with SCOPE × ATTACKER quadrant toggles and a "worst attacker today" callout. Click a cell to open its drawer. Statically prerendered + ISR (300s). |
| `/matrix/cell` | `matrix/cell/page.tsx` | Public | Single-cell expansion. Reads `?family=&config=&date=&scope=&attacker=` query params and lists every breaching primitive in that (family × config) cell, worst-first. Reached from the matrix cell drawer and the "worst attacker today" callout. Client-fetched (dynamic route, no server fetch). |
| `/analytics` | `analytics/page.tsx` | Public | Telemetry report layer. Reads the bundled static `/analytics.json` (no API call) and renders capability / discovery / contextual / allocation / research / cost charts (Recharts + a custom family × model heatmap). |
| `/brief` | `brief/page.tsx` | Public | Threat Brief. Branded masthead (one-line headline + Markdown / JSON downloads), at-a-glance KPI snapshot strip, executive-snapshot panel (net Δ vs yesterday, top-3 new attackers, recommended action), tier chips, then the full CISO-readable markdown brief. Statically prerendered + ISR. |
| `/sign-in` | `sign-in/page.tsx` | Public (auth entry) | Paste an `rk_live_…` API key → `POST /api/session`, which validates it and stores it in an httpOnly cookie. On success routes to `/scans`. This is the gateway into the authenticated product. |
| `/scans` | `(app)/scans/page.tsx` | Authenticated | Scan list. Server-rendered table of the tenant's scans (id, target, status, breaches, score, created) with empty/error states. `force-dynamic`, per-request, never cached. |
| `/scans/new` | `(app)/scans/new/page.tsx` | Authenticated | Launch form. Choose provider or custom endpoint, model, target key, scan mode (pack / repertoire / ladder), pack, and max_tests → `POST /api/scans` with an `Idempotency-Key`, then routes to the detail page. |
| `/scans/[scanId]` | `(app)/scans/[scanId]/page.tsx` | Authenticated | Live scan detail. Server shell seeds the first paint, then the client `ScanProgress` component polls `/api/scans/{id}` every ~2s until terminal (progress bar, live cost/ETA, current-attack line, cancel button), and links through to the report. |
| `/scans/[scanId]/report` | `(app)/scans/[scanId]/report/page.tsx` | Authenticated | Completed-scan report. Headline KPIs (score, breach rate, top attack, cost), worst-first findings with per-finding attack/response detail and remediation, recommendations, and JSON / HTML / PDF export links (proxied so the bearer stays server-side). |
| `/sample-report.html` | `frontend/public/sample-report.html` | Public (static) | Static example report ("ROGUE Scan Report"). Not a React route — a plain HTML file served from `public/`, linked from the landing hero CTA and the product-pitch section so a visitor can see what a finished report looks like without signing in. |

Not user pages: the route handlers under `frontend/src/app/api/` (`/api/session`, `/api/scans`, `/api/scans/[scanId]`, `/api/scans/[scanId]/cancel`, `/api/scans/[scanId]/report`, `/api/revalidate`) are the server-side proxy layer. They re-read the session cookie and forward the bearer token to the platform API so the raw key never reaches client JavaScript. They render no UI and are not navigable destinations — they are covered in the technical document, not here.

## Navigation structure

**The chrome.** Every page renders inside `frontend/src/app/layout.tsx`, the root layout, which mounts the global `Nav` (`frontend/src/components/nav.tsx`) above all content and wraps everything in the theme and SSE-feed providers. The nav is sticky, semi-transparent, and present on both the public and authenticated surfaces.

**Top nav contents.** On the left, the ROGUE wordmark links to `/`. On the right sits a row of links: `/feed`, `/matrix`, `/analytics`, `/brief` (the four public threat-intel views, with active-link highlighting driven by the current pathname), then a live status pill ("live / db down · N 24h", fed by the shared SSE feed plus an independent `/api/health` poll), and finally a bordered **dashboard** button that links to `/scans`. The dashboard button is the single visible entry point from the public surface into the product.

**The public → app boundary.** Clicking **dashboard** (or otherwise navigating to any `/scans…` route) enters the `(app)` route group. That group's layout, `(app)/layout.tsx`, is the auth gate: it reads the API key from the httpOnly cookie via `getApiKey()` and, if absent, calls `redirect("/sign-in")`. So an unauthenticated visitor who clicks **dashboard** lands on `/sign-in`, not on the scan list. The "session" is the API key itself — there is no username/password; signing in means pasting an `rk_live_…` key, which `POST /api/session` validates and stores in the cookie.

**The authenticated sub-nav.** Once past the gate, `(app)/layout.tsx` adds a second nav bar beneath the global one: a "Dashboard" label, **Scans** (`/scans`), **New scan** (`/scans/new`), the API-key prefix hint, and a sign-out button (`DELETE /api/session`). The public top nav remains visible above it throughout the product.

**Default and redirect behavior.**
- `/` is the default landing page (the root index route).
- Any gated `/scans…` route with no valid session cookie → redirect to `/sign-in`.
- Successful sign-in → `router.push("/scans")`.
- `/scans/new` submit → routes to the new scan's `/scans/[scanId]` live page.
- `/matrix/cell` with missing `?family=`/`?config=` params renders an inline error rather than redirecting.
- Sign-out clears the session cookie; the next gated navigation falls back to the `/sign-in` redirect.

## The two journeys as link-paths

### (a) Visitor exploring threat intelligence — no sign-in required

```
/                      landing — hero, pitch, fresh-attacks ticker, mini-matrix, augmentation lab
 ├─ /feed              top nav "/feed" OR landing deep-dive card → live attack stream
 ├─ /matrix            top nav "/matrix" OR landing card → breach heatmap
 │   └─ /matrix/cell?family=…&config=…   click a heatmap cell drawer → "see all breaching primitives"
 ├─ /analytics         top nav "/analytics" → telemetry charts
 ├─ /brief             top nav "/brief" OR landing card → daily threat brief (+ MD/JSON download)
 └─ /sample-report.html   landing hero CTA / product-pitch link → static example report
```

The four top-nav links and the three landing deep-dive cards all stay on the public surface; nothing here touches the auth gate.

### (b) Customer running a scan — crosses the sign-in boundary

```
/                              landing
 └─ [click "dashboard"]  → /scans
      └─ (app) auth gate: no session  → redirect → /sign-in
           └─ paste rk_live_… key, POST /api/session  → redirect → /scans
                └─ [click "New scan"]  → /scans/new
                     └─ fill launch form, POST /api/scans (Idempotency-Key)  → /scans/[scanId]
                          └─ ScanProgress polls /api/scans/[scanId] every ~2s until terminal
                               └─ [scan completes]  → /scans/[scanId]/report
                                    └─ export: JSON / HTML / PDF
                                       via /api/scans/[scanId]/report?format=…  (bearer attached server-side)
```

If the visitor already has a valid session cookie, the `/scans` step skips the `/sign-in` detour and goes straight to the scan list. Sign-out (`DELETE /api/session`) from the product sub-nav clears the cookie and reinstates the gate.

## ASCII sitemap tree

```
ROGUE website
│
├── PUBLIC  (app root — no auth)
│   ├── /                         landing / demo entry
│   ├── /feed                     live attack feed (§11.1)
│   ├── /matrix                   breach matrix heatmap
│   │   └── /matrix/cell          single (family × config) cell expansion  [?family=&config=&…]
│   ├── /analytics                telemetry report charts (static analytics.json)
│   ├── /brief                    daily CISO threat brief (+ MD/JSON)
│   ├── /sign-in                  paste rk_live_… key → session cookie  ──► gateway into (app)
│   └── /sample-report.html       static example report (public/ asset)
│
└── AUTHENTICATED  ((app) group — gated by (app)/layout.tsx → /sign-in)
    └── /scans                    scan list (per-tenant, force-dynamic)
        ├── /scans/new            launch form  → POST /api/scans
        └── /scans/[scanId]       live scan detail (polls until terminal)
            └── /scans/[scanId]/report   completed report + JSON/HTML/PDF export

(server-side proxy, not navigable pages — see the technical doc):
    /api/session · /api/scans · /api/scans/[scanId] ·
    /api/scans/[scanId]/cancel · /api/scans/[scanId]/report · /api/revalidate
```
