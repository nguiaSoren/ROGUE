# ROGUE — Technical Architecture of the Website

The engineering doc for ROGUE's website: the Next.js frontend, how it renders, and how it talks to the backend. Where the other documents in this folder describe what a visitor *sees*, this one describes what the machine *does* — the stack, the rendering modes, the two data clients, the server-side bearer proxy that is the security spine, and the design-token system that gives every page its look. Everything here is anchored to the real code under `frontend/`, and where the code and a comment disagree, the code wins (the known stale comments are called out at the end).

The live frontend is `https://rogue-eosin.vercel.app` (Vercel, git-connected, auto-deploy on push to `main`). It talks to two different backends: the **public threat-intel API** (FastAPI, `src/rogue/api/main.py`) and the **authenticated platform API** (the hosted SaaS service, defaulting to `https://rogue-private.onrender.com`). Both run on Render and read from the same Neon Postgres. The frontend never talks to Neon directly — only through those two HTTP services.

---

## 1. Stack and versions

The frontend is a single Next.js App Router application written in TypeScript, server-component-first, styled entirely with Tailwind v4. The dependency list (`frontend/package.json`) pins the exact versions:

| Concern | Choice | Version / notes |
|---|---|---|
| Framework | Next.js (App Router) | `16.2.6` — current major; see `frontend/AGENTS.md` ("This is NOT the Next.js you know" — breaking changes vs. older training data, read `node_modules/next/dist/docs/` before writing code). |
| React | React + React DOM | `19.2.4` — Server Components by default, `"use client"` only where interactivity is needed. |
| Language | TypeScript | `^5`, strict; every API shape is a typed mirror of the backend Pydantic/dataclass model. |
| Styling | Tailwind CSS | `v4` via `@tailwindcss/postcss`. **No `tailwind.config.js`** — v4 is CSS-config-first; the design tokens live in `globals.css` under `@theme inline`. |
| UI primitives | `@base-ui/react`, `shadcn`, `class-variance-authority`, `clsx`, `tailwind-merge`, `tw-animate-css`, `lucide-react` | shadcn-style component layer; `cn()` merge helper in `src/lib/utils.ts`. |
| Charts | `recharts` | `^3.8.1` — the augmentation-lab and brief charts. |
| Markdown | `react-markdown` | `^10` — renders the threat-brief markdown. |
| Theme | `next-themes` | dark-locked (see below). |
| Fonts | `next/font/google` Geist + Geist Mono | self-hosted via `--font-geist-sans` / `--font-geist-mono`. |
| Hosting | Vercel | git-connected; push to `main` auto-deploys. `next.config.ts` is intentionally empty (no custom webpack/turbopack, no rewrites) — all backend wiring is done in the data-client modules, not at the framework edge. |

The root layout (`src/app/layout.tsx`) hard-codes dark mode: `<html className="… dark">`, `ThemeProvider … defaultTheme="dark" enableSystem={false}`. The theme provider is present but the toggle is effectively off — ROGUE is a dark product. The root layout also mounts the global `<Nav>` and wraps the whole tree in `<SseFeedProvider>` (the live-attack SSE ticker connection, shared across pages).

`scripts` are the stock Next set: `next dev`, `next build`, `next start`, `eslint`. (Per project policy the dev server is never run locally to "preview" — changes are verified by pushing to the live Vercel deployment.)

---

## 2. Route groups and rendering modes

The app uses one App Router tree with a single route group, `(app)`, to separate the **authenticated product** from the **public** surfaces. The route group is a pure organizational/security boundary — it adds the auth gate and a sub-nav without adding a URL segment, so `(app)/scans/page.tsx` serves `/scans`.

| Route | Group | Rendering | Data client | Why |
|---|---|---|---|---|
| `/` (home) | public | static + components fetch with ISR | `lib/api.ts` | Marketing + live threat-intel snapshot; cached. |
| `/matrix` | public | **ISR, `revalidate = 300`** | `lib/api.ts` | The breach heatmap; explicitly matches the 300s ISR window. |
| `/matrix/cell` | public | dynamic shell, **client-fetched** | `lib/api.ts` (client) | Reads `?family/config/date`; deliberately does **no** server fetch so a Render cold-cycle retries client-side instead of hard-erroring. |
| `/brief` | public | static + ISR (default) | `lib/api.ts` | The daily CISO threat brief. |
| `/feed` | public | static + ISR (default) | `lib/api.ts` | The live attack feed + augmentation widgets. |
| `/analytics` | public | `"use client"` | client-side JSON | Self-contained analytics page. |
| `/sign-in` | public | `"use client"` | posts to `/api/session` | The key-entry form. |
| `/scans` | `(app)` | **`force-dynamic`** | `lib/platform-api.ts` (server) | Tenant scan list — never statically cached. |
| `/scans/new` | `(app)` | `"use client"` | posts to `/api/scans` | The new-scan form. |
| `/scans/[scanId]` | `(app)` | **`force-dynamic`** | `lib/platform-api.ts` (server) + client poller | Live scan progress. |
| `/scans/[scanId]/report` | `(app)` | **`force-dynamic`** | `lib/platform-api.ts` (server) | The scored report. |

The governing rule is **server-component-first, and the rendering mode follows the data's privacy**: public threat-intel is shared across all visitors, so it is statically prerendered and revalidated on a 5-minute ISR window (`export const revalidate = 300` on `/matrix`; the default-ISR pages inherit the same 300s from the data client's `next.revalidate`). Tenant data is per-customer and must never be cached or cross-served, so every `(app)` page that reads tenant data is `export const dynamic = "force-dynamic"`. Client components (`"use client"`) appear only where there is genuine interactivity — the two forms, the analytics page, and the polling/SSE widgets — and even those push their privileged network calls back to the server (see §4).

`/matrix` and `/matrix/cell` each ship a `loading.tsx` (Suspense skeleton) so a slow upstream paints a skeleton rather than a blank frame.

---

## 3. The two data clients

There are deliberately **two** typed HTTP clients, and the split is the cleanest way to understand the whole frontend. They never overlap: a page uses one or the other, never both.

### `lib/api.ts` — the public threat-intel reader

The credential-less client for the public corpus. It wraps the read-only `/api/*` endpoints of the FastAPI service (`src/rogue/api/main.py`) — health, attacks, breach matrix, brief, bandit/persona/escalation/mutation/stubbornness stats — with TypeScript types that mirror the JSON shapes. Key properties:

- **No credentials.** It sends no `Authorization` header. The corpus is public.
- **ISR-cached.** Every `fetch` is `{ next: { revalidate: 300 } }` (`REVALIDATE_SECONDS`), so visitors get instant loads off Vercel's edge cache and new Neon rows surface within the 5-minute window (or immediately via on-demand revalidation — see §4).
- **Base URL:** `process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000"`. This is the *public* API host (the `NEXT_PUBLIC_*` prefix is fine here — it's a non-secret read-only endpoint).
- **Cold-start resilience.** Render's free tier spins down when idle and returns transient 502/503/504 (or drops the socket) for the first request or two while it boots. `apiGet` rides that out: up to 2 retries with 1.5s→3s backoff, each attempt capped by a 12s `AbortSignal.timeout` so a held socket can't hang the request. Network-level throws are retried too.

### `lib/platform-api.ts` — the authenticated `/v1` client

The second, parallel client for the SaaS product surface — the per-tenant `/v1` API. It mirrors `lib/api.ts`'s cold-start posture (same 502/503/504 retry, 1.5s→3s backoff, 12s abort) but differs in three tenancy-driven ways:

1. **It injects `Authorization: Bearer <key>`.** The bearer is passed in *as an argument* — `apiV1(path, key, opts)` — read from the server session, never from a `NEXT_PUBLIC_*` env var, so the secret never ships to the browser.
2. **No ISR — every call is `cache: "no-store"`.** Tenant data is private and per-request; it must never be cached or cross-served.
3. **Typed error envelopes.** On a non-OK response it decodes `{ error: { code, message, details? } }` and throws an `ApiV1Error` carrying status/code/message, so product pages render an explicit error state instead of silently serving stale cross-tenant HTML. An `ApiV1Error` is treated as a *real* decoded failure and is **not** retried as a cold start (only gateway statuses / network throws retry).

- **Base URL:** `process.env.API_BASE ?? process.env.NEXT_PUBLIC_API_BASE ?? "https://rogue-private.onrender.com"`. Note the server-only `API_BASE` is preferred over the public one.
- **Surface:** `createScan` (POST, with `Idempotency-Key` so a double-submit can't launch two paid scans), `getScan` (the poller), `cancelScan`, `listScans` (cursor-paginated), `getReport` (JSON only — `html`/`pdf` are fetched as links, not decoded here), and `validateTarget`. The types (`ScanRecord`, `ScanStatus`, `ScanSpec`, `ScanReportJson`, `Finding`, …) mirror `src/rogue/platform/schemas.py` and `src/rogue/report.py`.
- **`reportUrl(scanId, format)`** returns a bare export URL for an `<a href>`; the bearer for that is supplied by the server-side route handler (§4), never appended to a client URL.

| | `lib/api.ts` | `lib/platform-api.ts` |
|---|---|---|
| Backend | public `/api/*` (FastAPI) | authed `/v1/*` (platform) |
| Credentials | none | `Bearer` (server-resolved) |
| Caching | ISR 300s | `no-store` (per-request) |
| Used by | public pages (server components) | `(app)` pages (server) + `/api/*` proxies |
| Errors | throws bare `Error` | throws typed `ApiV1Error` (decoded envelope) |
| Cold-start retry | yes (502/503/504, 12s abort) | yes (same), but never retries a decoded `ApiV1Error` |

---

## 4. The server-side proxy and auth pattern — the security spine

This is the single most important design decision in the app, and it holds the whole authenticated product together: **the `rk_live_` bearer never lives in the browser.** There is no username, no password, no user table — the platform authenticates with API keys, so the dashboard "session" *is* the key. The architecture exists to make sure JavaScript running in the page never touches that secret.

**The session cookie (`src/lib/session.ts`).** The key is parked in an httpOnly, secure cookie named `rogue_key`:

```
httpOnly: true, secure: true, sameSite: "lax", path: "/", maxAge: 30 days
```

Because it is `httpOnly`, page JS — including any XSS payload or third-party script — cannot read it back out. `session.ts` is server-only (it uses `next/headers`): Server Components read the key via `getApiKey()`; `setApiKey()` / `clearApiKey()` are called only from route handlers. `keyHint()` exposes a display-safe fingerprint (first 12 chars + `…`), never the full secret.

**Sign-in (`/api/session/route.ts`).** The `/sign-in` client form POSTs `{ api_key }` once, over HTTPS, into the same-origin route handler. The handler does not trust the key on its face — it **validates** it by calling `platformApi.listScans(key, { limit: 1 })` against the live platform. If that succeeds, `setApiKey()` writes the cookie and the client `router.push("/scans")`. Failure paths are explicit: a rejected key (401) returns `"That API key was not recognized."`; an unreachable platform returns a 502 with the upstream message, so "wrong key" reads differently from "service waking up." `DELETE /api/session` clears the cookie (the **Sign out** button).

**The gate (`(app)/layout.tsx`).** Every authenticated page sits inside the `(app)` route group whose layout is the bouncer: on the server it reads `getApiKey()` and, if absent, `redirect("/sign-in")` *before any dashboard byte renders* — no flash of protected content. It also paints the product sub-nav and the `keyHint()` fingerprint + sign-out control.

**The proxy routes (`/api/scans/*`).** Client components can't read the cookie and must not hold the bearer — so every privileged call a client makes goes through a same-origin `/api/*` route handler that re-reads the cookie server-side and forwards the bearer to `/v1`:

| Route handler | Forwards to | Caller |
|---|---|---|
| `POST /api/scans` | `POST /v1/scans` (with `Idempotency-Key`) | the `/scans/new` client form |
| `GET /api/scans/[scanId]` | `GET /v1/scans/{id}` | the client `ScanProgress` poller |
| `POST /api/scans/[scanId]/cancel` | `POST /v1/scans/{id}/cancel` | the client cancel button |
| `GET /api/scans/[scanId]/report` | `GET /v1/scans/{id}/report?format=…` | the report export links |

Each handler is the same shape: `getApiKey()` → 401 `{ error: { code: "no_session", … } }` if missing → call `platformApi.*` with the key → on `ApiV1Error`, re-emit `{ error: { code, message } }` at the upstream status; otherwise a 502 `upstream`. The report route is special: it `fetch`es the upstream with the bearer attached and **streams the body back** with the upstream content-type (and a `Content-Disposition` attachment for PDF), so the report page's download links can be plain same-origin `<a href>`s — the bearer stays server-side, never in a client-visible URL. (It uses a longer 20s abort, since report generation is heavier than a status poll.)

The net invariant: **every authenticated call either runs in a Server Component (reads the cookie directly) or goes through a same-origin `/api/*` proxy (re-reads the cookie, attaches the bearer).** The browser only ever holds a cookie it cannot read.

**On-demand revalidation (`/api/revalidate/route.ts`).** A small server-secret hook (`x-revalidate-token` must match `REVALIDATE_TOKEN`, fails closed, POST-only) that calls `revalidatePath` for `/matrix`, `/brief`, `/feed`, `/`. The harvest/reproduce scripts POST here after writing new Neon rows so the public ISR pages regenerate immediately instead of waiting out the 5-minute window.

---

## 5. Backend wiring

The frontend never touches the database — it speaks HTTP to two Render services, which own the Neon connection:

```
Browser ─► Vercel (rogue-eosin.vercel.app, Next.js)
              │
              ├─ Server Components / lib/api.ts ──────────► Render: public FastAPI  ─┐
              │     (NEXT_PUBLIC_API_BASE)                   (/api/*, ISR 300s)        │
              │                                                                        ├─► Neon Postgres
              └─ /api/* proxy routes / lib/platform-api.ts ─► Render: platform API  ──┘    (+ pgvector)
                    (API_BASE, bearer from cookie)            (/v1/*, no-store)
```

- **Public reads** go through `lib/api.ts` to the FastAPI service at `NEXT_PUBLIC_API_BASE` (defaults to `http://localhost:8000` for local dev; set to the live public API host on Vercel).
- **Tenant reads/writes** go through `lib/platform-api.ts` to the platform service at `API_BASE` (preferred) / `NEXT_PUBLIC_API_BASE` (fallback), defaulting to `https://rogue-private.onrender.com`. These calls originate either in a `(app)` Server Component or in an `/api/*` proxy route — both server-side, both with the cookie bearer attached.
- **Both base URLs are environment-configured** in Vercel project settings, with the defaults baked into the client modules as fallbacks. There is no rewrite config in `next.config.ts` — the base URL is resolved at fetch time inside each client.
- **Cold-start handling lives in the clients, not the platform.** Because both Render services can spin down, both clients carry the identical retry/abort logic so a cold boot reads as a brief wait, never a hard failure.

---

## 6. The design-token system

The visual identity is a two-layer token system in `globals.css` (there is no `tailwind.config.js` — Tailwind v4 reads its theme from CSS).

**Layer 1 — the shadcn semantic tokens.** `@theme inline { … }` maps Tailwind color/radius utilities (`--color-background`, `--color-card`, `--color-primary`, `--radius-*`, …) onto CSS variables, which are defined in `:root` (light) and `.dark` (dark) as OKLCH values. ROGUE overrides the dark palette to a "deep blue-black, not pure black" (`--background: oklch(0.06 0.005 270)`) so cards read as floating panels. This is the neutral chrome — borders, muted text, card surfaces.

**Layer 2 — the ROGUE signature accents.** A separate `:root` block defines the brand palette as raw hex, with `*-dim` (≈33% alpha) companions:

| Token | Value | Meaning |
|---|---|---|
| `--rogue-green` | `#00ff88` | signature / "alive" / OK / harvested |
| `--rogue-red` | `#ff003c` | critical breach / dangerous / alert |
| `--rogue-orange` | `#ff6b00` | HIGH tier |
| `--rogue-bg-deep` / `--rogue-bg-mid` | `#050508` / `#0a0a12` | near-black backgrounds |

Plus five per-widget accent hues (green / purple `#a78bfa` / amber `#fbbf24` / cyan `#22d3ee` / red `#f87171`) so the stacked augmentation tiles read as distinct subsystems at a glance.

**Backgrounds.** `.bg-rogue-grid` is a static 60px green grid over `--rogue-bg-deep`. `.bg-rogue-spotlight` adds a radial green glow at the top via a `::before`. `.bg-rogue-mesh` (home hero only) layers three drifting radial gradients (green/red/cyan) for an "alive" feel. Two of these were *deliberately de-animated* — the grid drift and the mesh drift were removed because a moving backdrop forced Chrome to re-blur every frosted card each frame; the static versions read identically and composite once.

**Animations.** A library of keyframe utilities: `rogue-fade-up` / `rogue-reveal` / `rogue-cell-pop` (entrances), `rogue-pulse-critical` / `rogue-pulse-green` / `rogue-cell-pulse-red` (heartbeats — all driven by `opacity`, not `box-shadow`, so they stay compositor-only), `rogue-scan` (sweep line), `rogue-glitch` (chromatic hover), `rogue-count-up` (CSS `@property` counter), `rogue-marquee` (sources strip), `rogue-word-cycle` (rotating hero word), the magnetic `.rogue-card` hover-lift, and the terminal `.rogue-caret`.

**Performance discipline baked into the CSS.** Three deliberate choices are worth noting because they encode real incidents: (1) `@media (prefers-reduced-motion: reduce)` kills all the infinite loops; (2) `[data-rg-pause="true"]` (toggled by `<PausedOffscreen>` via IntersectionObserver, with `lib/use-paused-on-offscreen.ts`) pauses animations on off-screen subtrees to save GPU; (3) a global `[class*="backdrop-blur"] { backdrop-filter: none !important }` strips frosted-glass blur entirely — Chrome re-blurred ~36 frosted cards on every scroll frame, the dominant scroll-jank source, and over the near-black background the frost was barely visible anyway. The terminal-style green scrollbar (`::-webkit-scrollbar`) completes the aesthetic.

---

## 7. Known cleanups (reported, not fixed)

Two stale spots surfaced while reading the code. Neither is a live bug — both are documentation/scaffold drift — and per the task scope they are reported, not changed.

1. **The stale `resolveKey()` / `NEXT_PUBLIC_*` fallback comment in `lib/platform-api.ts`.** The module header (lines 12–13) still says: *"SCAFFOLD NOTE: session wiring is a TODO; for now `resolveKey()` falls back to a `NEXT_PUBLIC_*` placeholder so the pages render."* That is no longer true. The live `resolveKey()` (lines 42–48) does the opposite — it has **no** `NEXT_PUBLIC_*` fallback; if no key is passed it throws `ApiV1Error(401, "no_session", …)`. The real session wiring now exists end-to-end (the `rogue_key` httpOnly cookie + the `/api/*` proxy routes), so the bearer is resolved from the server session, never from a public env var. The comment describes a scaffold phase that has been superseded; the code is correct, the comment is stale.

2. **`POST /v1/scans/validate` (`platformApi.validateTarget`) has no caller.** The client exposes `validateTarget(body, key)` (lines 305–311) for a pre-scan "dry-run a target (reachability/credentials) before a paid scan" — the intended "Test connection" button on the new-scan form. No page or route handler invokes it: there is no `/api/scans/validate` proxy route, and `(app)/scans/new/page.tsx` does not call it. It is a built-but-unwired endpoint waiting on the "test connection" UI that hasn't been built yet. (If/when wired, by the same security pattern it would need an `/api/scans/validate` server proxy so the bearer stays server-side — a client component can't call `validateTarget` directly with a real key.)
