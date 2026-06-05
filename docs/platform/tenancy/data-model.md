# Multi-Tenant Data Model (Team C)

> The persistence layer that turns ROGUE from a single-tenant tool into a SaaS platform. This doc owns the **new tables** — `organizations`, `users`, `memberships`, `projects`, `api_keys`, `scan_runs`, `reports` — and the alembic plan that lands them on the single Neon Postgres database alongside the engine's existing schema. It is written to the IDs, enums, and contracts frozen in [../ARCHITECTURE.md](../ARCHITECTURE.md): we **use** `org_<ulid>`/`proj_<ulid>`/`scan_<ulid>`/`rep_<ulid>`/`rk_live_*`, `ScanStatus`, `ScanRecord`, and `TargetSpec` — we never redefine them. Authentication, key verification, and row-scoping policy live in [./isolation-and-rbac.md](./isolation-and-rbac.md); secret storage and the `api_key_ref` handle live in [./secrets.md](./secrets.md); the `scan_jobs` work-queue table is owned by [../orchestration/job-queue.md](../orchestration/job-queue.md) and is referenced here, never duplicated.

Status: **BUILT (local), simpler than this spec.** The tables shipped — but in a **new module, `src/rogue/platform/models.py`** (its own `Base`), not `src/rogue/db/models.py`, and all in a **single migration `0022_platform_tables.py`** (not the `0022/0023/0024` tenancy chain this doc plans; those numbers were instead used for `secrets` (0023) and `integrations` (0024)). The shipped schema is leaner than the column tables below. Read this doc as the intended design; the actual shipped shape is summarized here:

**Shipped tables (`src/rogue/platform/models.py`, migration 0022):**

- `organizations` — `org_id` (PK), `name`, `created_at`. *No `slug`/`plan`/`deleted_at`.*
- `users` — `user_id` (PK), `email` (unique), `name`, `created_at`.
- `memberships` — **integer autoincrement `id`** (PK), `org_id` FK, `user_id` FK, `role` (`String(20)`); `UNIQUE(org_id, user_id)`. *No `mem_<ulid>`, no `created_at`.*
- `projects` — `project_id` (PK), `org_id` FK, `name`, `slug`, `created_at`; `UNIQUE(org_id, slug)`.
- `api_keys` — `key_id` (PK), `org_id` FK, `project_id` FK (nullable), `key_hash` (unique), `prefix` (`String(24)`), `name`, `scopes` (JSON), `created_at`, `last_used_at`, `revoked_at`. *No `expires_at`, `created_by`.*
- `scan_runs` — `scan_id` (`String(48)` PK), `org_id` FK, `project_id` FK (**nullable**), `status` (**`String(20)`, not a native `scan_status` enum**), `progress`, `n_tests`, `n_completed`, `n_breaches`, `top_attack`, `score`, `cost_usd`, `report_id` (**plain `String(48)`, no FK**), `error`, **`target` (JSON, redacted snapshot)**, `pack`, **`spec` (JSON)**, `idempotency_key`, `created_at`, `started_at`, `completed_at`. *The `TargetSpec` is a JSON snapshot, not `target_provider`/`target_model`/`target_endpoint`/`target_api_key_ref` columns.*
- `scan_jobs` — the queue table, **also in 0022** (see [../orchestration/job-queue.md](../orchestration/job-queue.md)).
- `reports` — `report_id` (PK), `scan_id` FK, `format` (`String(16)`, default `json`), **`payload` (JSON — the whole `ScanReport.to_dict()`)**, `created_at`. *No `formats`/`json_blob`/`html_ref`/`pdf_ref`/`exec_summary_ref`/`org_id`/score columns; PDF/HTML are rendered on demand by `ReportService`, not stored.*
- `secrets` (migration 0023) and `integrations` (migration 0024) — see [./secrets.md](./secrets.md) and [../integrations/slack-github-jira.md](../integrations/slack-github-jira.md).

Notably **not done:** soft-delete (`deleted_at`), the native `scan_status` Postgres enum, and the `deployment_configs.customer_id → org_id` expand/backfill migration (§4) — the legacy single-tenant `acme` engine tables are untouched. The detailed design below is retained for intent; defer to the shipped summary above for facts.

---

## 1. Where this fits

Every existing table in `src/rogue/db/models.py` is **tenant-blind**: `attack_primitives` (`:107`), `breach_results` (`:256`), `benchmark_runs` (`:728`) are global, shared red-team intelligence — they describe the open-web threat corpus, not any one customer. The only table that even gestures at a tenant is `DeploymentConfig` (`src/rogue/db/models.py:89`), which carries a free-text `customer_id: Mapped[str] = mapped_column(String(40), index=True)` (`:95`) defaulting to the literal `"acme"` in the Pydantic twin (`src/rogue/schemas/deployment_config.py:130`). That string is the single-tenant seam we are widening into a real org graph.

The new tables form a self-contained tenancy subgraph (`organizations → projects`, `users ⋈ organizations` via `memberships`, `api_keys` scoped to org/project) plus the **durable scan record** (`scan_runs`) and its **rendered artifacts** (`reports`). `scan_runs` is the bridge: it is the persisted form of the `ScanRecord` contract (ARCHITECTURE.md §5), modelled column-for-column on the `BenchmarkRun` precedent (`src/rogue/db/models.py:728`), and it is the first existing-engine-adjacent row that is hard-keyed to `org_id`/`project_id`. Where `BenchmarkRun` was append-only global telemetry, `scan_runs` is per-tenant operational state.

All of this lands in **one** database. ROGUE runs a single Neon Postgres instance (`DATABASE_URL`, `postgresql+psycopg://…`); there is no per-tenant database, no shard, no separate identity store. Tenant isolation is **logical** — every tenant-scoped query carries an `org_id` predicate, enforced by the data-access layer in [./isolation-and-rbac.md](./isolation-and-rbac.md). The data model's job is to make that predicate cheap (every tenant table leads its composite indexes with `org_id`) and impossible to forget (every tenant row has a non-null `org_id` FK).

## 2. ID and type conventions

- **Primary keys** are the prefixed ULID strings from ARCHITECTURE.md §5, stored as `String(40)` to match the existing convention (`config_id`, `primitive_id`, `breach_id` are all `String(40)`): `org_<ulid>`, `proj_<ulid>`, `scan_<ulid>`, `rep_<ulid>`. `users` use `usr_<ulid>`; `memberships` and `api_keys` use surrogate `String(40)` PKs (`mem_<ulid>`, `key_<ulid>`).
- **`ScanStatus`** is the single enum `queued | running | completed | failed | canceled` (ARCHITECTURE.md §5). It becomes a native Postgres enum named `scan_status`, declared exactly like the engine's enums — `SAEnum(ScanStatus, name="scan_status", values_callable=_enum_values)` — reusing the `_enum_values` helper at `src/rogue/db/models.py:70` so the storage vocabulary cannot drift from the wire vocabulary. The `ScanStatus` Python enum is defined once (Team B, `rogue.orchestration.types`) and imported here, never re-listed.
- **Roles** (`owner | admin | member | viewer`) and **scopes** (`scans:read`, `scans:write`, `reports:read`, …) are `Literal` types on the Pydantic side, stored as CHECK-constrained `String` columns, following the `SourceType`/`BrightDataProduct` pattern at `src/rogue/db/models.py:62` (vocabulary derived via `typing.get_args`, never hand-copied into the migration).
- **Timestamps** are `DateTime(timezone=True)`, matching every existing model. `created_at` defaults via `server_default=sa.func.now()` (as `benchmark_runs.run_at` does, `0021_add_benchmark_runs.py`).
- **Money** is `Float` `cost_usd`, consistent with `BreachResult.cost_usd` (`:289`) and `BenchmarkRun.cost_usd` (`:759`).

## 3. New tables — column-level schemas

### 3.1 `organizations`

The tenant root. Everything tenant-scoped roots here.

| Column | Type | Constraints |
|---|---|---|
| `org_id` | `String(40)` | **PK** (`org_<ulid>`) |
| `name` | `String(200)` | not null |
| `slug` | `String(80)` | not null, **unique** (URL/dashboard handle) |
| `plan` | `String(40)` | not null, default `'free'`, CHECK ∈ {`free`,`pro`,`enterprise`} |
| `created_at` | `DateTime(tz)` | not null, server_default `now()` |
| `deleted_at` | `DateTime(tz)` | nullable (soft-delete; a non-null value removes the org from all live queries) |

Indexes: PK; `UNIQUE(slug)`.

### 3.2 `users`

A human identity. Authentication mechanism (password hash vs. OAuth subject) is owned by [./isolation-and-rbac.md](./isolation-and-rbac.md); this table holds only the durable identity columns the rest of the schema FKs to.

| Column | Type | Constraints |
|---|---|---|
| `user_id` | `String(40)` | **PK** (`usr_<ulid>`) |
| `email` | `String(320)` | not null, **unique** (citext-style lower-cased at write) |
| `name` | `String(200)` | nullable |
| `created_at` | `DateTime(tz)` | not null, server_default `now()` |
| `deleted_at` | `DateTime(tz)` | nullable (soft-delete) |

Indexes: PK; `UNIQUE(email)`.

A user is **not** owned by an org — the user↔org relation is many-to-many through `memberships`, so one human can belong to several orgs (consulting, multiple companies).

### 3.3 `memberships`

The user×org join carrying the RBAC role. One row per (user, org).

| Column | Type | Constraints |
|---|---|---|
| `membership_id` | `String(40)` | **PK** (`mem_<ulid>`) |
| `user_id` | `String(40)` | **FK** → `users.user_id` `ON DELETE CASCADE`, not null |
| `org_id` | `String(40)` | **FK** → `organizations.org_id` `ON DELETE CASCADE`, not null |
| `role` | `String(20)` | not null, CHECK ∈ {`owner`,`admin`,`member`,`viewer`} |
| `created_at` | `DateTime(tz)` | not null, server_default `now()` |

Indexes: PK; `UNIQUE(user_id, org_id)` (a user has exactly one role per org); `ix_memberships_org_id` on `org_id` (list-members-of-org); `ix_memberships_user_id` on `user_id` (list-orgs-for-user — the login fan-out). Role semantics (what each role may do) are defined in [./isolation-and-rbac.md](./isolation-and-rbac.md); this table only stores the value.

### 3.4 `projects`

An org's sub-container. Scans, configs, and project-scoped keys hang off a project, so a tenant can separate `staging` from `production` targets.

| Column | Type | Constraints |
|---|---|---|
| `project_id` | `String(40)` | **PK** (`proj_<ulid>`) |
| `org_id` | `String(40)` | **FK** → `organizations.org_id` `ON DELETE CASCADE`, not null |
| `name` | `String(200)` | not null |
| `slug` | `String(80)` | not null |
| `created_at` | `DateTime(tz)` | not null, server_default `now()` |
| `deleted_at` | `DateTime(tz)` | nullable (soft-delete) |

Indexes: PK; `ix_projects_org_id` on `org_id`; `UNIQUE(org_id, slug)` (slug unique within an org, not globally). Hard FK to `organizations` guarantees no orphan project.

### 3.5 `api_keys`

Programmatic credentials for the SDK and REST API. **Only a SHA-256 of the key is stored** (ARCHITECTURE.md §5) — the raw `rk_live_*`/`rk_test_*` value is shown once at creation and never persisted. Verification logic lives in [./isolation-and-rbac.md](./isolation-and-rbac.md); this table is the store.

| Column | Type | Constraints |
|---|---|---|
| `key_id` | `String(40)` | **PK** (`key_<ulid>`) |
| `org_id` | `String(40)` | **FK** → `organizations.org_id` `ON DELETE CASCADE`, not null |
| `project_id` | `String(40)` | **FK** → `projects.project_id` `ON DELETE CASCADE`, **nullable** (null = org-wide key; set = project-scoped key) |
| `prefix` | `String(20)` | not null (the human-visible `rk_live_AbC3…` prefix shown in the dashboard list) |
| `key_hash` | `String(64)` | not null, **unique** (`sha256` hex of the full key — the lookup column on auth) |
| `name` | `String(200)` | not null (operator-supplied label) |
| `scopes` | `JSON` | not null, default `[]` (list of scope literals; vocabulary CHECK-validated app-side) |
| `created_by` | `String(40)` | **FK** → `users.user_id` `ON DELETE SET NULL`, nullable |
| `created_at` | `DateTime(tz)` | not null, server_default `now()` |
| `last_used_at` | `DateTime(tz)` | nullable (stamped on each successful auth; best-effort, async write) |
| `revoked_at` | `DateTime(tz)` | nullable (non-null = dead; auth rejects) |
| `expires_at` | `DateTime(tz)` | nullable (optional TTL) |

Indexes: PK; `UNIQUE(key_hash)` (the auth hot path is a single equality lookup on the hash); `ix_api_keys_org_id` on `org_id`; `ix_api_keys_project_id` on `project_id`. A key is **live** iff `revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now())` — that predicate is the auth gate, not a stored column.

### 3.6 `scan_runs`

The durable scan record — the persisted form of the `ScanRecord` contract (ARCHITECTURE.md §5) and the row `GET /v1/scans/{id}` reads. Deliberately modelled on `BenchmarkRun` (`src/rogue/db/models.py:728`): a flat result row with a JSON `detail`/snapshot blob, written once at create and updated as the worker progresses. The difference from `BenchmarkRun` is that this row is **tenant-keyed** and **mutable** (status/progress transition through the `ScanStatus` lifecycle).

| Column | Type | Constraints |
|---|---|---|
| `scan_id` | `String(40)` | **PK** (`scan_<ulid>`) |
| `org_id` | `String(40)` | **FK** → `organizations.org_id` `ON DELETE CASCADE`, not null |
| `project_id` | `String(40)` | **FK** → `projects.project_id` `ON DELETE CASCADE`, not null |
| `status` | `SAEnum(ScanStatus, name="scan_status")` | not null, default `queued` |
| `progress` | `Integer` | not null, default `0` (0–100; CHECK `0 ≤ progress ≤ 100`) |
| **TargetSpec snapshot** | | _the target as submitted, frozen at create time_ |
| `target_provider` | `String(40)` | nullable (e.g. `openai`, `anthropic`) |
| `target_model` | `String(100)` | nullable |
| `target_endpoint` | `Text` | nullable (custom base_url) |
| `target_api_key_ref` | `String(200)` | not null — the Vault/KMS **handle** from `TargetSpec.api_key_ref`, **never the raw secret** (see [./secrets.md](./secrets.md)) |
| `target_system_prompt` | `Text` | not null, default `''` |
| `pack` | `String(40)` | not null, default `'default'` (`default`/`aggressive`/`compliance`) |
| **ScanReport summary** | | _denormalized from the `ScanReport` (`src/rogue/report.py:75`) on completion_ |
| `n_tests` | `Integer` | nullable (null until the run sizes itself) |
| `n_completed` | `Integer` | not null, default `0` |
| `n_breaches` | `Integer` | nullable |
| `top_attack` | `String(200)` | nullable (the worst family/title, for the list view) |
| `score` | `Float` | nullable (the 0–100 headline risk number, Team F formula) |
| `cost_usd` | `Float` | nullable |
| `report_id` | `String(40)` | **FK** → `reports.report_id` `ON DELETE SET NULL`, nullable (set on completion) |
| `error` | `Text` | nullable (populated when `status = failed`) |
| **Timestamps** | | |
| `created_at` | `DateTime(tz)` | not null, server_default `now()` |
| `started_at` | `DateTime(tz)` | nullable (stamped on `queued → running`) |
| `completed_at` | `DateTime(tz)` | nullable (stamped on terminal `completed`/`failed`/`canceled`) |

Indexes: PK; `ix_scan_runs_org_project_created` composite `(org_id, project_id, created_at DESC)` — serves `ScanService.list_scans(org_id, project_id, limit)` (ARCHITECTURE.md §4) leading with the tenant predicate; `ix_scan_runs_status` on `status` (the worker's "claim queued / reap stuck running" sweeps); `ix_scan_runs_org_id` on `org_id` (org-wide scan list). The `report_id` FK is nullable and `SET NULL` so a scan row survives an artifact purge.

The full `TargetSpec` and `ScanSpec` (the create-time request, including `attacks`/`max_tests`/`n_trials`/`budget`) are also serialized verbatim into a single `spec: JSON` column (not tabled above for brevity but present) so a scan is reproducible from its own row — mirroring how `BenchmarkRun.detail` (`:762`) snapshots the per-run breakdown. The flat columns above are the **queryable projection** of that blob (list views, sorting, the dashboard), exactly as `benchmark_runs` flattens `asr`/`n_breached` out of `detail`.

### 3.7 `reports`

The rendered artifacts of a completed scan, produced by `ReportService` (ARCHITECTURE.md §4, Team F). One scan can have several format rows or one multi-format row; we use one row per scan holding all rendered formats, with large binaries stored as object-storage references (not inline BLOBs) to keep Neon small.

| Column | Type | Constraints |
|---|---|---|
| `report_id` | `String(40)` | **PK** (`rep_<ulid>`) |
| `scan_id` | `String(40)` | **FK** → `scan_runs.scan_id` `ON DELETE CASCADE`, not null, **unique** (one report per scan) |
| `org_id` | `String(40)` | **FK** → `organizations.org_id` `ON DELETE CASCADE`, not null (denormalized for cheap tenant-scoped reads without joining `scan_runs`) |
| `formats` | `JSON` | not null, default `[]` (which formats are materialized: `["json","html","pdf"]`) |
| `json_blob` | `JSON` | nullable (the canonical machine-readable report — small enough to inline, like `BenchmarkRun.detail`) |
| `html_ref` | `Text` | nullable (storage key/URL for the rendered HTML) |
| `pdf_ref` | `Text` | nullable (storage key/URL for the PDF) |
| `exec_summary_ref` | `Text` | nullable (storage key for the executive summary) |
| `score` | `Float` | nullable (denormalized headline score, == `scan_runs.score`) |
| `created_at` | `DateTime(tz)` | not null, server_default `now()` |

Indexes: PK; `UNIQUE(scan_id)`; `ix_reports_org_id` on `org_id`.

There is an intentional **mutual reference**: `scan_runs.report_id → reports.report_id` (nullable `SET NULL`) and `reports.scan_id → scan_runs.scan_id` (not-null `CASCADE`). The `reports → scan_runs` direction is the source of truth (a report cannot exist without its scan); `scan_runs.report_id` is a denormalized convenience pointer set on completion so the scan list can link to its artifact in one read. Alembic creates `scan_runs` first with `report_id` FK added in a follow-up `op.create_foreign_key` after `reports` exists, to avoid a circular create-table dependency (see §6).

The raw per-trial verdicts stay in the existing `breach_results` (`src/rogue/db/models.py:256`); `reports` holds the **rendered, customer-facing** view, not the underlying breach rows. Linking breach rows to a tenant scan is covered in §5.

## 4. The `customer_id → org_id` migration seam

`DeploymentConfig.customer_id` (`src/rogue/db/models.py:95`) is today an un-FK'd free-text string defaulting to `"acme"`. The platform replaces it with a real `org_id` (and optionally `project_id`) FK. The migration is **expand → backfill → contract**, spread across two migrations so no single step is destructive:

1. **Expand (`0023`, see §6):** add nullable `org_id String(40)` and `project_id String(40)` columns to `deployment_configs`, with FKs to `organizations`/`projects`. Keep `customer_id` in place. New writes populate `org_id`; old reads still work.
2. **Backfill (data migration inside `0023`):** create one bootstrap org per distinct `customer_id` (the lone real value is `"acme"` → a single `org_<ulid>` with `slug='acme'` and a default project), then `UPDATE deployment_configs SET org_id = …, project_id = …` by mapping `customer_id`. Since the live corpus is single-tenant (`"acme"`), this is one org, one project.
3. **Contract (a later migration, post-cutover, NOT in the 0022 wave):** once all readers go through `org_id`, drop `customer_id`. Deferred deliberately — ARCHITECTURE.md §7 puts tenant scoping in Week-2 but keeps the engine running throughout, so we do not drop the column until nothing reads it. Until then `customer_id` is a redundant shadow of `org_id`.

The same seam applies to scans: a `ScanRecord` links to **`org_id`/`project_id`, not `customer_id`** (ARCHITECTURE.md §4 `ScanService.create_scan(spec, *, org_id, project_id, actor)`). A scan never carries a free-text customer string; it is hard-keyed into the org graph from creation. `DeploymentConfig` is reachable from a scan only transitively (the scan's `TargetSpec` snapshot describes the target directly), so we do **not** add a `scan_runs.deployment_config_id` FK — the snapshot in `scan_runs` is self-contained, decoupling a scan's historical record from later config edits.

## 5. Relationship to existing engine tables

The new subgraph attaches to the engine at exactly three points, all additive:

- **`deployment_configs`** gains `org_id`/`project_id` (the §4 seam). This is the only existing table that gets new columns.
- **`breach_results`** (`src/rogue/db/models.py:256`) stays tenant-blind. A breach row is `(primitive × config × trial)`; its tenant is derivable through `deployment_config_id → deployment_configs.org_id` once §4 lands, so we add **no** `org_id` to `breach_results` (avoid denormalizing a column that is already one join away, and avoid touching the hot reproduce-write path). If per-scan breach attribution is needed later, it belongs in a `scan_runs ⋈ breach_results` association table owned by Team B's worker, not here.
- **`attack_primitives`** / `benchmark_runs` / all harvest tables stay **global**. They are shared threat intelligence, identical for every tenant; giving them an `org_id` would be a category error.

No existing FK, index, or enum is altered. The 0022 wave is purely "new tables + two nullable columns on `deployment_configs`."

## 6. Alembic plan (migration chain `0022+`)

Migrations are hand-written in `src/rogue/db/migrations/versions/`, following the established style (revision = zero-padded string, `down_revision` chains linearly, `op.create_table` + explicit `op.create_index`, matching `0021_add_benchmark_runs.py`). `env.py` (`src/rogue/db/migrations/env.py:9`) calls `load_dotenv()` **before** importing `Base`, then overrides `sqlalchemy.url` from `DATABASE_URL` — so every migration in this chain runs against the same Neon DB the engine uses; there is no separate tenancy database.

**As shipped, the chain collapsed into one platform migration plus two follow-ons** (not the 3-part tenancy plan originally written):

- **`0022_platform_tables`** (`down_revision = "0021"`): creates **all** the platform tables at once — `organizations`, `users`, `memberships`, `projects`, `api_keys`, `scan_runs`, **`scan_jobs`** (the queue table is in here, not a separate Team-B migration), and `reports`. `status` is a plain `String(20)` column (no native `scan_status` enum), and `scan_runs.report_id` is a plain string (no mutual-reference FK), so the two-phase create-FK dance below was unnecessary.
- **`0023_secrets`**: the Fernet `secrets` table ([./secrets.md](./secrets.md)).
- **`0024_integrations`**: the per-org `integrations` table ([../integrations/slack-github-jira.md](../integrations/slack-github-jira.md)).

The `deployment_configs.customer_id → org_id` expand/backfill migration (§4) was **not** written — the legacy engine tables are untouched, so the original design below is unrealized.

Verification per migration: `uv run alembic upgrade head` then `uv run alembic downgrade -1` round-trips cleanly (the project's migration-smoke bar), and `uv run pytest tests/test_smoke.py` still passes the metadata/alembic checks.

## 7. ER diagram (new + key existing tables)

```
                         organizations
                         ├─ org_id (PK, org_<ulid>)
                         ├─ slug (UNIQUE)
                         └─ plan
                              │ 1
            ┌─────────────────┼──────────────────┬───────────────────┐
            │ N               │ N                │ N                 │ N
       memberships         projects          api_keys           scan_runs
       ├─ membership_id PK  ├─ project_id PK   ├─ key_id PK        ├─ scan_id PK (scan_<ulid>)
       ├─ user_id  FK ──┐   ├─ org_id FK       ├─ org_id FK        ├─ org_id FK
       ├─ org_id   FK    │  ├─ slug            ├─ project_id FK?   ├─ project_id FK
       └─ role           │  └─ (org,slug)UNIQ  ├─ key_hash UNIQUE  ├─ status (ScanStatus)
       UNIQUE(user,org)  │        │ N          ├─ prefix/scopes    ├─ progress
                         │        │            ├─ last_used_at     ├─ TargetSpec snapshot
                       users      │            ├─ revoked_at       │   (provider/model/endpoint,
                       ├─ user_id │            └─ created_by FK ──┐│    api_key_ref → secrets.md)
                       │   PK     │                              ││├─ pack
                       ├─ email   │                              ││├─ n_tests/n_breaches/
                       │  UNIQUE  │                              │││   top_attack/score/cost_usd
                       └─ …       │                              ││├─ report_id FK? ─┐
                         ▲────────┘ (created_by)─────────────────┘│└─ created/started/completed
                                                                   │        │ 1
                                          (api_keys.project_id) ───┘        │ 1
                                                                            ▼
                                                                         reports
                                                                         ├─ report_id PK (rep_<ulid>)
                                                                         ├─ scan_id FK UNIQUE ──┘ 1:1
                                                                         ├─ org_id FK
                                                                         └─ formats/json_blob/refs

   ── existing engine tables (tenant-blind, unchanged except deployment_configs) ──

       deployment_configs                 breach_results              attack_primitives
       ├─ config_id PK                     ├─ breach_id PK             ├─ primitive_id PK
       ├─ customer_id  (→ being            ├─ deployment_config_id FK──┘ (global threat
       │     replaced, §4)                 ├─ primitive_id FK ──────────► corpus; NO org_id)
       ├─ org_id FK?    (NEW, 0023)        ├─ verdict / cost_usd
       ├─ project_id FK?(NEW, 0023)        └─ …
       └─ target_model / system_prompt

       scan_jobs  ── owned by orchestration/job-queue.md (queue/lease state); referenced, not defined here
```

Cardinalities: one org has many projects, memberships, api_keys, scan_runs; one user has many memberships (→ many orgs); one project has many scan_runs and api_keys; one scan_run has at most one report (1:1, `UNIQUE(scan_id)`). `breach_results` and `attack_primitives` remain global and gain no tenant key (§5).

## 8. Constraints, invariants, and open questions

- **Single Neon DB.** No per-tenant schema or database. Isolation is the `org_id` predicate (every composite index leads with it); enforcement is in [./isolation-and-rbac.md](./isolation-and-rbac.md). The data model only guarantees the predicate is always *available* (non-null `org_id` on every tenant row) and *cheap* (indexed).
- **No raw secrets in any column.** `scan_runs.target_api_key_ref` and `api_keys.key_hash` are the only credential-adjacent columns; the first is an opaque handle, the second a SHA-256. Raw target keys and raw `rk_*` values never touch Postgres — see [./secrets.md](./secrets.md).
- **Soft-delete on org/user/project** (`deleted_at`); hard `ON DELETE CASCADE` is declared so a *hard* purge (GDPR erasure) is one `DELETE FROM organizations` that cleans the whole subgraph, but day-to-day deletion sets `deleted_at` and live queries filter it.
- **`actor` provenance.** `ScanService.create_scan(..., actor=)` (ARCHITECTURE.md §4) carries who initiated a scan (a `user_id` or an `api_key.key_id`). Open question for [./isolation-and-rbac.md](./isolation-and-rbac.md): whether to add a nullable `created_by_actor String(40)` to `scan_runs` for an audit trail, or keep actor attribution in a separate audit log. Leaning toward the latter (keep `scan_runs` lean) — flagged, not decided here.
- **Enum ownership.** `ScanStatus` lives with Team B (orchestration), imported by this layer. If a tenancy doc ever needs a status value the engine doesn't have, the contract changes in ARCHITECTURE.md §5 first (per its closing note), not in a migration.
