# Database schema

Engineering reference for ROGUE's Postgres schema — the current table set, which migration
owns each table, and which subsystem it serves. Lets a reader see the whole schema without
reading all 38 migration files.

- **Stack:** Postgres 17 + pgvector (Docker container `rogue-postgres`, image
  `pgvector/pgvector:pg17`; Neon in prod). One service, no Redis/ES/Kafka.
- **ORM:** core domain tables in `src/rogue/db/models.py`; the SaaS platform tables in
  `src/rogue/platform/models.py` (both subclass the same `Base`).
- **Migrations:** `src/rogue/db/migrations/versions/` (hand-written; alembic linear chain
  `0001 → 0038`). Apply with `uv run alembic upgrade head`.
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

### v2 surfaces (`src/rogue/{attestation,instrument,oversight,memory}` + Slack)

| Table | ORM class | Created in | Subsystem |
|---|---|---|---|
| `attestation_entries` | `AttestationEntry` | 0031 | Per-org append-only hash-chained attestation record (ADR-0012); enforced by a DB-side append-only trigger. |
| `mitigations` | `Mitigation` | 0032 | Persisted measured-remediation outcomes (Surface 1b) — generated patch artifact + pre/post breach rate + over-block rate + bootstrap CI + accepted/rejected candidates, linked to a breach. |
| `slack_registered_agents` | `SlackRegisteredAgent` | 0033 | Per-org self-registered Slack agent targets (Surface 1) — base_url/model/system-prompt-ref + declared tools + forbidden topics + sandbox/security channel ids. |
| `snapshot_captures` | `SnapshotCapture` | 0034 | Per-org capture blobs (content-type + bytes) referenced by `snapshot_ref` from decisions/diffs (pointer, not inline blob). |
| `gated_cases` | `GatedCase` | 0036 | Surface 2 human-gate answer key — the designed-label `case_corpus` (designed_label + rationale + provenance + source_refs), the independent ground truth (ADR-0011). |
| `review_sessions` | `ReviewSession` | 0036 | Surface 2 — a human reviewer's assigned/decided/expired session over gated cases. |
| `gated_decisions` | `GatedDecision` | 0036 | Surface 2 — per-case human APPROVE/DENY decision + deliberation notes + latency + snapshot pointer. |
| `skills` | `Skill` | 0037 | Surface 3 agent-memory `SkillPool` — cohort/trust-domain-scoped skill (skill_md + pgvector embedding + applicability condition + lifecycle timestamps). |
| `skill_edges` | `SkillEdge` | 0037 | Surface 3 — directed edges between skills (combination risk graph; risk_score + evidence breach ref). |
| `skill_verifications` | `SkillVerification` | 0037 | Surface 3 — verified-promotion record (net_effect + repairs/regressions + leakage rate + held-out n + bootstrap CI), the signed assurance per cohort. |

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
| 0030 | Reconciles CHECK-constraint vocabularies with the ORM (`bright_data_cost_log.product` `serp_api`→`serp`; adds the missing `source_provenances` source_type / bright_data_product CHECKs) + adds missing platform indexes (`scan_jobs.org_id`, `scan_runs.project_id`). Non-destructive. |
| 0034 | Adds `slack_registered_agents.client_policy` (JSON) — the per-agent client policy snapshot (alongside the new `snapshot_captures` table). |
| 0035 | Adds `slack_registered_agents.target_api_key_ref` — pointer to the target's stored API key. |
| 0038 | Adds `breach_results.exfil_method` (`String(40)`, nullable) — output-side exfiltration-method label (`rogue.schemas.ExfiltrationMethod`: markdown-image beacon, hyperlink/data-URI/base64 exfil, PII/secret egress, tool-arg smuggling) deterministically classified from the model response; an extra label ON a breach, not a verdict axis. |

Head is **0038**. Confirm the live chain with `uv run alembic heads` /
`uv run alembic history`.
