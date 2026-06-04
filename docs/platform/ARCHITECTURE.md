# ROGUE Platform Architecture

> The design that turns ROGUE from a **security tool** (`client.scan()`) into a **security platform** — one backend reachable from the SDK, a public REST API, the dashboard, and MCP, all hitting the **same scan engine**. This document is the spine: the core principle, the system diagram, the internal service contracts, the canonical vocabulary, and the index of the per-team detail docs. Everything else under `docs/platform/` elaborates one box of the diagram.

Status: **design spec, not yet built.** Week-1–3 already shipped the scan *engine* (the `ScanEngine` box below exists today); the platform is the layers above it. Local-only design docs.

---

## 1. Product goal

A company receives a scan report **without talking to Soren.** The same scan is reachable four ways, all converging on one execution path:

```
  from rogue import Client          curl POST /v1/scans          ChatGPT / Cursor (MCP)        Company dashboard
            │                              │                              │                              │
            └──────────────────────────────┴───────────── ScanService ───┴──────────────────────────────┘
                                                               │
                                                          ScanEngine            ← EXISTS (rogue.scan.run_scan)
                                                               │
                                  ┌────────────────────────────┼────────────────────────────┐
                                  ▼                            ▼                            ▼
                            TargetAdapter                 JudgeAgent                 ReportService
                                  │
                                  ▼
                           Customer models
```

## 2. Core principle — ONE scan engine

There is exactly one place a scan executes. Not an SDK engine + an API engine + a dashboard engine + an MCP engine — **one**. Every surface is a thin client of `ScanService`, which enqueues a job that a worker runs through `ScanEngine`, which wraps the existing `rogue.scan.run_scan`. If two surfaces ever produce different results for the same target+pack, the architecture has failed.

```
                    +------------------+
                    |  Public API      |   Team A   docs/platform/api/
                    +---------+--------+
                              v
                    +------------------+
                    | Scan Orchestrator|   Team B   docs/platform/orchestration/
                    | (Service+Queue+  |
                    |  Worker)         |
                    +---------+--------+
                              v
                    +------------------+
                    | Scan Engine      |   EXISTS — rogue.scan.run_scan + adapters + judge + packs
                    +---------+--------+
         +--------------------+--------------------+
         v                    v                    v
   TargetAdapter        JudgeAgent           ReportService   Team F   docs/platform/reports/
   (rogue.adapters)     (rogue.reproduce)
         v
   Customer models

  cross-cutting:  Multi-tenancy (Team C, tenancy/)   Dashboard (Team D, dashboard/)
                  Benchmark (Team E, benchmark/)      MCP & integrations (Team G, integrations/)
```

## 3. What already exists (the engine the platform wraps)

The platform does **not** rebuild scanning. These ship today (Weeks 1–3, committed locally):

- **`rogue.scan.run_scan(config, primitives, *, n_trials, breach_threshold, budget, adapter_extra, panel, judge, judge_model) -> ScanReport`** (`src/rogue/scan.py:24`) — the provider-agnostic loop: `render` → `TargetPanel.run_attack` → `JudgeAgent.judge` → aggregate.
- **`rogue.client.Client`** (`src/rogue/client.py:40`) — the SDK facade (`.scan()/.validate()/.benchmark()`), which `ScanEngine` and the SDK both ultimately route through.
- **`rogue.reproduce.target_panel.TargetPanel`** (adapters, multimodal gate) · **`rogue.reproduce.judge.JudgeAgent`** · **`rogue.adapters`** (OpenAI/Anthropic/OpenRouter/Gemini/Groq/Custom) · **`rogue.packs`** (`default`/`aggressive`/`compliance`).
- **`rogue.report.ScanReport`** (`src/rogue/report.py:75`): `target, n_tests, n_breaches, cost_usd, findings[]`; `summary()/to_json()/to_html()`.
- **`src/rogue/api/main.py`** — a FastAPI app (read-only, **no auth**, single-tenant `acme`) that Team A extends. **`src/rogue/db/models.py`** (latest migration **0021**) that Team C extends. **`src/rogue/mcp_server/server.py`** (6 read-only tools) that Team G extends. **`frontend/`** (Next.js 16) that Team D extends. **`src/rogue/config.py`** is an empty stub — Team C builds the settings/secrets layer there.

## 4. Internal service contracts (the load-bearing interfaces)

Every team codes to these. They are the only seams that cross box boundaries.

```python
# ScanService — Team B. The single entry every surface calls. Async, queue-backed; NEVER runs a scan
# in the request thread.
class ScanService:
    async def create_scan(self, spec: ScanSpec, *, org_id: str, project_id: str, actor: str) -> ScanRecord: ...
    async def get_scan(self, scan_id: str, *, org_id: str) -> ScanRecord: ...
    async def cancel_scan(self, scan_id: str, *, org_id: str) -> ScanRecord: ...
    async def list_scans(self, *, org_id: str, project_id: str | None = None, limit: int = 50) -> list[ScanRecord]: ...

# ScanEngine — Team B (thin) over the existing engine. The ONE execution path. Wraps rogue.scan.run_scan.
class ScanEngine:
    async def run(self, target: TargetSpec, pack: str, config: ScanConfig,
                  *, progress: ProgressCallback | None = None) -> ScanReport: ...
    async def validate(self, target: TargetSpec) -> ValidationResult: ...
    async def benchmark(self, target: TargetSpec, dataset: str, *, max_goals: int) -> BenchmarkReport: ...

# ReportService — Team F. Renders a persisted scan into the formats customers consume.
class ReportService:
    async def build_json(self, scan_id: str) -> dict: ...
    async def build_html(self, scan_id: str) -> str: ...
    async def build_pdf(self, scan_id: str) -> bytes: ...
    async def build_executive_summary(self, scan_id: str) -> bytes: ...
```

`ScanEngine.run` is a ~30-line wrapper: build a `DeploymentConfig` from `TargetSpec` (endpoint→`base_url` / provider→prefix), `load_pack(pack)`, call `run_scan(...)` with a `panel`/`judge` wired for progress, return the `ScanReport`. **No scanning logic is reimplemented.**

## 5. Canonical vocabulary (all 20 docs use these exact names)

- **IDs:** `scan_<ulid>`, `rep_<ulid>`, `org_<ulid>`, `proj_<ulid>`; API keys `rk_live_<rand>` / `rk_test_<rand>` (only a SHA-256 of the key is stored).
- **`ScanStatus`** (one enum, everywhere): `queued | running | completed | failed | canceled`.
- **`ScanSpec`** (create request): `{ target: TargetSpec, pack: str = "default", attacks: list[str] | None, max_tests: int = 50, n_trials: int = 1, budget: float | None }`.
- **`TargetSpec`**: `{ endpoint: str | None, provider: str | None, model: str | None, api_key_ref: str, system_prompt: str = "" }` — `api_key_ref` is a Vault/KMS handle, never the raw secret (Team C).
- **`ScanRecord`** (status/result row, what `GET /v1/scans/{id}` returns): `{ scan_id, org_id, project_id, status: ScanStatus, progress: int (0-100), n_tests, n_completed, n_breaches, top_attack, score: float (0-100), cost_usd, report_id, error, created_at, started_at, completed_at }`.
- **`score`** — the platform's single headline risk number, `0-100`, synthesized from findings (severity × success-rate, saturating). Formula owned by **Team F** (`reports/`); mirrors the SDK's `compute_risk_score`. (Distinct from `breach_rate`, which is raw.)
- **Error envelope** (all API non-2xx): `{ "error": { "code": str, "message": str, "details"?: {} } }`.

## 6. Team split → document index

| Team | Engineers | Owns | Docs |
|---|---|---|---|
| **A — API Platform** | 4 | Public REST API on the existing FastAPI app | `api/overview.md`, `api/scans-endpoints.md`, `api/validate-benchmark-endpoints.md`, `api/auth-and-keys.md` |
| **B — Scan Orchestration** | 4 | `ScanService`, queue, worker, the `ScanEngine` wrapper | `orchestration/scan-service.md`, `orchestration/job-queue.md`, `orchestration/worker.md`, `orchestration/scan-engine-adapter.md` |
| **C — Multi-Tenant** | 3 | orgs/users/projects/keys, isolation, secrets | `tenancy/data-model.md`, `tenancy/isolation-and-rbac.md`, `tenancy/secrets.md` |
| **D — Dashboard** | 3 | Next.js app: pages, live scan UX, report views | `dashboard/pages-and-routes.md`, `dashboard/live-scan-ux.md`, `dashboard/report-views.md` |
| **E — Benchmark** | 2 | benchmark API, datasets, scoring/trends | `benchmark/api-and-datasets.md`, `benchmark/scoring-and-trends.md` |
| **F — Report Generation** | 2 | `ReportService`: HTML/PDF/exec/eng reports | `reports/report-service.md`, `reports/executive-and-engineering.md` |
| **G — MCP & Integrations** | 2 | MCP scan tools, Slack/GitHub/Jira | `integrations/mcp.md`, `integrations/slack-github-jira.md` |

## 7. First 30-day roadmap

- **Week 1 — engine on a queue.** `ScanEngine` wrapper + `ScanService.create_scan/get_scan` + Redis queue + `ScanWorker` + `scan_jobs`/`scan_runs` persistence (migration 0022+). `POST /v1/scans`, `GET /v1/scans/{id}`, `GET /v1/scans/{id}/report`. Scans run in a worker, never the request thread.
- **Week 2 — make it SaaS.** Orgs/users/projects/api_keys tables + key auth on the API + tenant scoping (kill the hard-coded `acme`). Dashboard auth + Scans/Reports pages on the live data.
- **Week 3 — depth + artifacts.** `POST /v1/benchmark` + benchmark scoring/trends. `ReportService` HTML/PDF/executive reports. Hosted scans GA.
- **Week 4 — distribution.** MCP scan/validate tools (the "scan staging endpoint" in Cursor flow). Slack/GitHub/Jira. Enterprise onboarding.

## 8. Success metric

Not "more attacks / more renderers / more papers." The metric is: **Company → Hosted API → ROGUE → Report, with no human in the loop.** When that path works end-to-end for a tenant who has never met the founder, ROGUE is a platform.

---

*Per-team detail lives in the linked docs. Each is written to the contracts and vocabulary above; if a doc needs to change a contract, it changes here first.*
