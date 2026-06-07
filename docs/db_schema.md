# Database schema

Engineering reference for ROGUE's Postgres schema — the current table set, which migration
owns each table, and which subsystem it serves. Lets a reader see the whole schema without
reading all 29 migration files.

- **Stack:** Postgres 17 + pgvector (Docker container `rogue-postgres`, image
  `pgvector/pgvector:pg17`; Neon in prod). One service, no Redis/ES/Kafka.
- **ORM:** core domain tables in `src/rogue/db/models.py`; the SaaS platform tables in
  `src/rogue/platform/models.py` (both subclass the same `Base`).
- **Migrations:** `src/rogue/db/migrations/versions/` (hand-written; alembic linear chain
  `0001 → 0029`). Apply with `uv run alembic upgrade head`.
- **Pydantic = wire format** (`src/rogue/schemas/`); **SQLAlchemy = storage**. Enums are
  imported into the ORM, never duplicated. ORM class names collide with Pydantic names
  (`AttackPrimitive`, `BreachResult`, `DeploymentConfig`, `SourceProvenance`) — alias when
  importing both.

## Table → owning migration → subsystem

### Core domain (`src/rogue/db/models.py`)

| Table | ORM class | Created in | Subsystem |
|---|---|---|---|
| `deployment_configs` | `DeploymentConfig` | 0001 | Reproduction targets (model × system_prompt × tools). |
| `attack_primitives` | `AttackPrimitive` | 0001 | Harvested/extracted attacks (the corpus). |
| `source_provenances` | `SourceProvenance` | 0001 | Where each primitive was harvested from (Bright Data provenance). |
| `breach_results` | `BreachResult` | 0001 | Per-(primitive × config × trial) judge verdicts — the matrix substrate. |
| `bright_data_cost_log` | `BrightDataCostLog` | 0001 | Bright Data API spend log. |
| `pair_refinement_steps` | `PairRefinementStep` | 0007 | §10.7 full-PAIR attacker iteration steps (stubbornness metrics). |
| `bandit_state` | `BanditState` | 0010 | Harvest-source ε-greedy bandit arm state. |
| `fetch_cache` | `FetchCache` | 0011 | Cached Bright Data fetches (avoid re-paying for re-harvest). |
| `primitive_images` | `PrimitiveImage` | 0012 | Rendered/ingested carrier images for multimodal primitives. |
| `attack_strategies` | `AttackStrategy` | 0013 | §10.9 self-growing technique repertoire (candidate → graduated lifecycle). |
| `renderer_capabilities` | `RendererCapability` | 0015 | §10.9 Phase 3b harvested renderer registry (image/audio). |
| `ladder_attempts` | `LadderAttempt` | 0017 | §10.10 per-strategy escalation telemetry — breach-rate priors. |
| `ladder_rotation_membership` | `LadderRotationMembership` | 0019 | §10.10 per-strategy eligibility/execution — reachability/starvation. |
| `benchmark_runs` | `BenchmarkRun` | 0021 | §10.x external-benchmark (AdvBench/JBB) run records. |
| `technique_embeddings` | `TechniqueEmbedding` | 0026 | Technique-retrieval pgvector embeddings (E8). |
| `target_embeddings` | `TargetEmbedding` | 0026 | Target-fingerprint pgvector embeddings (E8). |
| `retrieval_metrics` | `RetrievalMetric` | 0026 | Shadow-mode retrieval telemetry (where the winner ranked). |
| `primitive_grammar_labels` | `PrimitiveGrammarLabel` | 0027 | Grammar-component labels (grammar predictive-power study). |
| `demo_requests` | `DemoRequest` | 0028 | Commercial-site demo-request lead capture. |
| `newsletter_subscribers` | `NewsletterSubscriber` | 0029 | Commercial-site newsletter signups. |

### SaaS platform (`src/rogue/platform/models.py`, all created in 0022)

| Table | ORM class | Subsystem |
|---|---|---|
| `organizations` | `Organization` | Tenancy (the org root). |
| `users` | `User` | Platform users. |
| `memberships` | `Membership` | User ↔ org membership. |
| `projects` | `Project` | Per-org projects. |
| `api_keys` | `ApiKey` | `rk_live` API-key auth. |
| `scan_runs` | `ScanRun` | A hosted scan request. |
| `scan_jobs` | `ScanJob` | Queue/worker units within a scan. |
| `reports` | `Report` | Generated scan reports. |
| `secrets` | `Secret` | (table created 0022; further hardened in 0023) Per-tenant provider secrets. |
| `integrations` | `Integration` | (created in 0024) Per-tenant outbound integrations (Slack/webhook). |

> 0022 creates the eight core platform tables; `secrets` and `integrations` are split into
> their own follow-up migrations (0023, 0024).

## Views (not tables)

| Object | Created in | Subsystem |
|---|---|---|
| `breach_matrix` (view) | 0002 | The per-(primitive × config) breach-rate rollup the dashboard + EVADE-band selector read. |
| `breach_matrix_daily_snapshot` (materialized view) | 0008, redefined 0009 | Daily snapshot for the dashboard matrix; 0009 re-scopes it to baseline-only (excludes augmentation re-runs). |

## Alteration-only migrations (no new table)

| Migration | What it changes |
|---|---|
| 0002 | Creates the `breach_matrix` view. |
| 0003 | Aligns `bright_data_cost_log` columns with the ORM. |
| 0004 | Adds `multi_turn_persona_chain` to the `attack_family` enum (§4.2 row 15). |
| 0005 | Adds `persona_used` to `breach_results` (§10.7 persona A/B). |
| 0006 | Adds `synthesized`, `slot_requirements`, `derived_from_primitive_id` to `attack_primitives` (§10.7 synthesis). |
| 0008 / 0009 | Materialized breach-matrix snapshot; 0009 makes it baseline-only. |
| 0014 | `attack_strategies` lifecycle columns — graduation / retirement / resurrection (§10.9 Phase 4). |
| 0016 | Adds `ladder_strategies` to `renderer_capabilities` (§10.9 Phase 3b-v1 ladder wiring). |
| 0018 | Splits attack-strategy trials into total attempts vs valid trials (§10.9/§10.10 correctness — the validity-rate denominator). |
| 0020 | Adds `harvest_run_id` to `attack_strategies` — technique provenance for campaign metrics. |
| 0023 | Hardens `secrets`. |
| 0025 | Adaptive-prioritization columns — vendor/family + winner segmentation on `ladder_attempts` (the contextual blend's vendor/family scopes; see `docs/scheduling.md`). |

Head is **0029**. Confirm the live chain with `uv run alembic heads` /
`uv run alembic history`.
