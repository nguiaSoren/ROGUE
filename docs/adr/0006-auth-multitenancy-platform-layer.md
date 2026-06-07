# 0006 — Authentication + multi-tenancy for the hosted platform layer

- **Status:** Supersedes-for-platform (overrides `ROGUE_PLAN.md §13 #3` no-auth and `§13 #4` no-multi-tenancy *for the product layer only*)
- **Date:** 2026-06-08 (retroactive; platform built 2026-06-05)

## Context

`ROGUE_PLAN.md §13` froze a *hackathon research deliverable*: #3 "A real authentication system. Demo customer hardcoded." and #4 "Multi-tenancy. One customer. Schema supports N; demo shows one." Those non-goals were correct for a Day-0 research demo. The subsequent **startup pivot** (KSGC track) turned ROGUE into a hosted security-SaaS platform — which *cannot* exist without authentication and tenant isolation. This is the drift the ADR layer exists to reconcile: §13 was silently crossed, and the most-cited authority no longer described reality. Code reality: `src/rogue/platform/` (ScanService/queue/worker/engine), the `api/v1` surface, and migrations `0022_platform_tables` / `0023_secrets` / `0024_integrations` / `0028_demo_requests` / `0029_newsletter_subscribers` implement tenants, API keys (`rk_live...`), and per-tenant scans.

## Decision

The **hosted product layer** adds real authentication (API keys / tenant identity) and real multi-tenancy (per-tenant scans, reports, integrations, isolation), **deliberately reversing §13 #3 and #4 for that layer**. Crucially, this is *additive atop an unchanged research engine*: the §8–§12 research pipeline (harvest → extract → reproduce → diff) remains single-tenant / no-auth — it is a batch engine the platform invokes, not a multi-tenant service itself. The §13 freeze still binds the research engine; it no longer binds the product layer.

## Consequences

- The "single source of authority" is now layered: §13 governs the research engine; this ADR governs the product layer. Citing "§13 says no auth" to block product work is now wrong — cite this ADR.
- Tenant isolation is a security-critical invariant of the platform (a cross-tenant leak is a P0), tested at the platform boundary.
- Other §13 items the pivot also crossed (CLI #6, landing page #8, marketing copy #9, migrations-beyond-first #7, a paper #17) are likewise product/research-track scope, not violations — tracked in the README index note.

## What would reverse this

Abandoning the hosted-product track and reverting to a pure research artifact — at which point auth/multi-tenancy become dead weight and §13 #3/#4 are reinstated in full.
