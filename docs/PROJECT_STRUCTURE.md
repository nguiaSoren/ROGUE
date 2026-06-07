# Repository structure — how ROGUE is organized

The map a new contributor reads first: what each directory is, how it maps to the
five-layer pipeline, and which architecture doc to open next. For *design* of a
subsystem, follow the → pointers. For *decisions* (why it's built this way), see
`docs/adr/`.

## Top level

```
ROGUE/
├── src/rogue/          # the Python package — backend, engine, MCP server, platform
├── frontend/           # Next.js 16 dashboard + marketing site   → frontend/ARCHITECTURE.md
├── sdk/                # customer-facing Python SDK (separate uv project; frozen v1 contract)
├── tests/              # pytest suite (~132 files, ~1,931 tests); DB tests skip when Docker is down
├── scripts/            # operational + research scripts (~70) — harvest/reproduce/re-judge/benchmark
├── benchmark/          # frozen field-standard goal sets (AdvBench / JailbreakBench / judge_comparison)
├── docs/               # architecture docs, ADRs, specs, research artifacts (some gitignored)
├── docker/             # docker-compose init + test-DB bootstrap
├── examples/           # usage examples
├── data/               # runtime state (gitignored except data/discovery_bandit.json)
├── assets/             # demo media (cover.png; large video/audio gitignored)
├── .github/workflows/  # CI (ci.yml: pytest+ruff+pyright on a Postgres service; frontend lint+tsc)
├── pyproject.toml · uv.lock · docker-compose.yml · alembic.ini · .env.example
└── (local-only, gitignored: ROGUE_PLAN.md · CLAUDE.md · glossary.md · docs/RESEARCH_TODO.md
     · the paper artifacts · website/ · papers/)
```

## `src/rogue/` — the backend package

Organized by **pipeline layer** (Harvest → Extract → Dedupe → Reproduce → Diff) plus
the cross-cutting substrate (schemas/db/core/adapters) and the product surfaces
(api/platform/mcp_server).

| Package | Role | Layer / role | Arch doc |
|---|---|---|---|
| `schemas/` | **Pydantic wire format** — the single source for every enum (`AttackFamily`, `AttackVector`, `Severity`, `JudgeVerdict`, `SourceType`, `BrightDataProduct`) + request/response models | substrate (wire) | `docs/schemas.md` |
| `db/` | **SQLAlchemy storage** — `models.py` + `migrations/versions/` (Alembic, 0001→0030) + session | substrate (storage) | `docs/db_schema.md`, `docs/schemas.md` |
| `core/` | **Provider-abstraction substrate** — `CanonicalMessage`, `InvocationResult`, `TargetAdapter`, `AdapterRegistry`, content blocks, errors | substrate | `src/rogue/core/ARCHITECTURE.md`, ADR-0004 |
| `adapters/` | **Concrete provider adapters** (OpenAI / Anthropic / Gemini / Groq / OpenRouter / CustomHTTP) + `model_specs` + conformance suite. Nothing above this boundary imports a provider SDK type | substrate | ADR-0004 |
| `harvest/` | **Layer 1 — Harvest.** Bright Data client, `sources/` plugins (11), discovery agent, ε-greedy yield bandit | L1 | `docs/sources.md`, `docs/bandit_for_humans.md` |
| `extract/` | **Layer 2 — Extract.** LLM agent → typed `AttackPrimitive` | L2 | `docs/architecture.md` §L2 |
| `dedupe/` | **Layer 3 — Dedupe.** pgvector cosine clustering to canonical primitives | L3 | `docs/architecture.md` §L3 |
| `reproduce/` | **Layer 4 — Reproduce (the core win).** `target_panel`, `instantiator`, the judge (`judge` + `judge_batch` + `verdict_projection`), the escalation ladder (`escalation_ladder` + `escalation_planner`), the scheduler (`ladder_priors` + `growth_scheduler`), `iterative_attacker` (PAIR), `modality_renderers/` + `renderer_registry`, `llm_cost_log` | L4 | `docs/judge.md`, `docs/scheduling.md`, `docs/escalation_ladder.md` |
| `diff/` | **Layer 5 — Diff.** Today-vs-yesterday threat brief, severity scoring, Slack alert | L5 | `docs/architecture.md` §L5 |
| `grammar/` | Grammar-component labeling + predictive-power study (the #TRS-C null result) | research | `docs/grammar_efficacy.md` |
| `retrieval/` | Technique-retrieval system (deployed-inactive; waiting on winner telemetry) | research | `docs/retrieval.md` |
| `mcp_server/` | **Producer-side MCP server** (19-tool full-lifecycle surface) | product surface | `docs/mcp/ARCHITECTURE.md`, `docs/mcp/CONTRACT.md` |
| `api/` | **FastAPI app** — `main.py` (public read API), `v1/` (authed write/scan API), `observability.py` (logging/Sentry/rate-limit) | product surface | `docs/platform/api/` |
| `platform/` | **Hosted multi-tenant SaaS engine** — `ScanService`, Postgres job queue + worker, tenancy, Fernet `secrets`, `report_service` + `scoring`, integration store | product surface | `docs/platform/ARCHITECTURE.md`, ADR-0006 |
| `packs/` | Curated attack packs (aggressive / compliance) | data | — |

**Key convention:** wire (Pydantic, `schemas/`) and storage (SQLAlchemy, `db/models.py`)
share their enum/vocabulary from one source via `typing.get_args`, so the two can
never drift (enforced by the CHECK constraints reconciled in migration 0030).

## `frontend/` (Next.js 16 App Router)

```
frontend/src/
├── app/         # routes: / · /feed · /matrix(/cell) · /brief · /analytics · /product
│                #         + commercial (gated by NEXT_PUBLIC_SHOW_COMMERCIAL):
│                #         /pricing · /enterprise · /security · /about · /deck · /request-demo …
│                #         + (app)/ authed scan flow, api/ route handlers (revalidate, scan proxy)
├── components/  # ~40 components (cinematic hero, matrix heatmap, SSE feed widget, marketing/*)
├── lib/         # api.ts (public reader) · platform-api.ts (/v1) · flags.ts · proof.ts
└── content/     # static copy
```
→ `frontend/ARCHITECTURE.md` (routes → components → endpoints).

## `docs/` layout

- **Pipeline + subsystems:** `architecture.md`, `judge.md`, `scheduling.md`, `escalation_ladder.md`, `db_schema.md`, `retrieval.md`, `sources.md`, `taxonomy.md`, `schemas.md`, `budget.md`, `bandit_for_humans.md`
- **Product:** `platform/` (api · benchmark · dashboard · integrations · orchestration · reports · tenancy), `mcp/` (ARCHITECTURE + CONTRACT), `deployment.md`, `company_onboarding.md`
- **Decisions:** `adr/` (0001–0008 + README index)
- **Calibration / research:** `judge_fp_taxonomy.md`, `grammar_efficacy.md`, `outbound_package.md`
- **Local-only (gitignored):** `RESEARCH_TODO.md`, `paper_figures.md`, `adaptive_orchestration_*.md`, `scheduler_allocation_study.md`, `3b_v2_renderer_design.md`

## Where to start

1. **`docs/architecture.md`** — the five-layer pipeline overview.
2. **This file** — where each layer's code lives.
3. **`docs/adr/`** — why the load-bearing decisions were made (and which §13 non-goals were reversed).
4. The per-subsystem doc for whatever you're touching (table above).
