# Website architecture — ROGUE

Everything about the ROGUE website: what it is, how you move through it, what you get, and how it's built. Live at `https://rogue-eosin.vercel.app` (frontend, Vercel) → API `https://rogue-private.onrender.com` (Render) → Neon. Written 2026-06-05.

| Doc | What it covers |
|---|---|
| [`00_overview_and_trailer_walkthrough.md`](00_overview_and_trailer_walkthrough.md) | The experiential overview + a cinematic, screen-by-screen **trailer walkthrough** (shot list: route, what's on screen, the copy/numbers that pop, the money shot, a VO beat). Start here for demo videos. |
| [`01_sitemap_and_navigation.md`](01_sitemap_and_navigation.md) | Every route, the nav structure, the public→app boundary, the two click-paths (explore threat intel · run a scan), an ASCII sitemap. |
| [`02_public_surfaces.md`](02_public_surfaces.md) | The public pages — landing, `/matrix`, `/feed`, `/brief`, `/analytics`, `/sample-report.html`: purpose, what's on each, the data behind it, its role in the story. |
| [`03_app_and_scan_journey.md`](03_app_and_scan_journey.md) | The authenticated dashboard + the end-to-end customer journey: sign-in → scans → new scan → live progress → report → JSON/HTML/PDF exports. |
| [`04_technical_architecture.md`](04_technical_architecture.md) | The engineering doc: Next 16 App Router, route groups, the two API clients, the server-side bearer-proxy + cookie-session security spine, backend wiring, the design-token system. |
| [`05_capabilities_landing_and_intelligence.md`](05_capabilities_landing_and_intelligence.md) | **Capability catalog (1/3)** — every feature/interaction on the landing page + the "how ROGUE thinks" intelligence demos (hero, intro overlay, augmentation lab, the 5 intelligence widgets, MCP-connect…), each with a marketing hook + a video idea. |
| [`06_capabilities_threat_intel.md`](06_capabilities_threat_intel.md) | **Capability catalog (2/3)** — ~44 capabilities across `/matrix` (heatmap, toggles, cell-drawer drill-down), `/feed` (live SSE, attack replay), `/brief`, `/analytics`, each as a filmable beat. |
| [`07_capabilities_product_scanning_reports.md`](07_capabilities_product_scanning_reports.md) | **Capability catalog (3/3)** — the product: sign-in, the 3 scan modes (pack/repertoire/ladder), live progress, the report + HTML/PDF/JSON exports, and operating ROGUE from an IDE via MCP. |
| [`08_brand_kit.md`](08_brand_kit.md) | Designer brand kit: exact hex palette, fonts, the (text) wordmark + logo situation, motion principles, the grid/spotlight background recipe, do/don'ts. |

**The capability catalog (05–07) is the "everything" layer** — one entry per distinct thing the site does (≈86 capabilities total), each framed as a marketable beat with a one-line video idea, so no feature is missed when planning videos.

**The two arcs the site tells:** (A) *threat intelligence* — a live, continuously-updated breach matrix proving "your LLM is being jailbroken right now" (landing → `/matrix` → `/feed` → `/brief`); (B) *the product* — point ROGUE at your own endpoint and get a scored report with remediation (landing → sign-in → `/scans/new` → live scan → report → PDF).
