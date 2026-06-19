# Tenant Isolation & RBAC

> **Team C — Multi-Tenant.** This is the doc that makes ROGUE multi-tenant *safe*: the rules and the one helper that guarantee no request ever reads another org's data, the role/permission model that decides who inside an org may do what, and the migration that kills the single-tenant `acme` hard-codes inherited from the Week-1–3 engine. It elaborates the **Team C** box in [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §6 and is bound by the `ScanService` contract in §4. The tenant tables themselves (orgs/users/projects/api_keys, and the org-scoping columns added to existing tables) are specified in [`./data-model.md`](./data-model.md); secret material (the `api_key_ref` Vault handles, key hashing) lives in [`./secrets.md`](./secrets.md); the authentication step that resolves a key into an org lives in [`../api/auth-and-keys.md`](../api/auth-and-keys.md); the methods every rule below applies to are in [`../orchestration/scan-service.md`](../orchestration/scan-service.md).

Status: **PARTIALLY BUILT (local).** The core isolation seam shipped in `src/rogue/platform/tenancy.py`: a `Principal` (org_id / role / key_id / project_id / scopes), `resolve_principal_from_token`, and the **`query_scope(stmt, principal)`** helper that appends `WHERE org_id = :org [AND project_id = :project]` (raising if the entity has no `org_id` column). The 4-role vocabulary (`owner|admin|member|viewer`) and `has_scope`/`role_at_least` exist. **What did NOT ship:** the `scoped()`/`scoped_project()` naming and the `TenantScoped` mixin (the real helper is `query_scope`, and it inspects the statement's FROM entity for an `org_id` column rather than a marker mixin); the **CI lint rule** that turns a missing filter into a build failure; **RLS**; the **`audit_log`** table and audit writes; the **`deployment_configs.customer_id → org_id` migration** (the legacy `acme` hard-codes in `threat_brief.py` / MCP / `api/main.py:1052` are untouched); and per-route RBAC *enforcement* in the `/v1` handlers (they gate on `require_principal` only, not `require(principal, resource, action)`). Sections below describing those are design — each is flagged inline. The tenant tables are in [`./data-model.md`](./data-model.md); key hashing + the Fernet secret store in [`./secrets.md`](./secrets.md); key→org resolution in [`../api/auth-and-keys.md`](../api/auth-and-keys.md).

---

## 1. The one invariant

**No request can read or mutate a row belonging to an `org_id` other than the one on its authenticated principal.** Everything in this document is in service of that single sentence. We do not protect tenant boundaries with code review and good intentions; we protect them with (a) an `org_id` that rides every request from key to query, (b) a query-scoping helper that makes an *unscoped* tenant query a build/lint failure rather than a silent leak, and (c) an audit trail of every privileged action. Isolation is the floor, not a feature.

The canonical IDs from [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §5 are load-bearing here and are never redefined: `org_<ulid>`, `proj_<ulid>`, `scan_<ulid>`, `rep_<ulid>`, and API keys `rk_live_<rand>` / `rk_test_<rand>` (only a SHA-256 of the key is stored — see [`./secrets.md`](./secrets.md)).

---

## 2. Isolation strategy: shared-DB row-scoping on the single Neon database

ROGUE runs on **one Neon Postgres database** (the runtime store from the project's `CLAUDE.md`; the platform adds tenant tables via migration 0022+, per [`./data-model.md`](./data-model.md)). Two isolation strategies were on the table:

| Strategy | What it is | Verdict |
|---|---|---|
| **Schema-per-tenant** | A Postgres schema (or database) per org; the connection's `search_path` switches per request. | **Rejected.** N migrations to run per release, connection-pool fragmentation across schemas, cross-tenant analytics (the benchmark trend lines, Team E) become a union over N schemas, and Neon's branching/pooling model is built for one logical DB. Operationally heavy for a solo-operated platform. |
| **Shared-DB row-scoping** | One schema; every tenant-owned table carries an `org_id` column; every query filters `WHERE org_id = :org`. | **Recommended.** One migration set, one connection pool, trivial cross-org rollups for the operator, and isolation enforced in code rather than in the DBA's head. The risk — *a developer forgets the `WHERE` clause* — is real, and §4 makes that risk a compile/lint failure instead of a production incident. |

**Decision: shared-DB row-scoping.** Postgres Row-Level Security (RLS) is a defensible *defence-in-depth* second layer (a `USING (org_id = current_setting('rogue.org_id'))` policy set from a per-request `SET LOCAL`), but it is **not** our primary guard: ROGUE uses a single application role and a pooled connection, RLS policy bugs fail *open* in subtle ways, and RLS gives no help to the MCP server or background workers that don't go through the HTTP request path. We treat the application-level scoping helper (§4) as the contract and may add RLS later purely as a backstop. The primary guarantee is structural, not policy-based.

---

## 3. How `org_id` flows: key → context → service → query

`org_id` is not a parameter a handler chooses to pass; it is established once at the edge and threaded as a non-optional argument through every layer. The chain has four hops.

**(1) Key → principal.** A request arrives with `Authorization: Bearer rk_…`. `require_principal` ([`../api/auth-and-keys.md`](../api/auth-and-keys.md)) hashes the presented key (SHA-256), looks the hash up in `api_keys`, and resolves a **`Principal`** (the shipped name; the doc's `RequestPrincipal` is the same idea):

```python
@dataclass
class Principal:               # src/rogue/platform/tenancy.py
    org_id: str                # org_<ulid> — the tenant boundary
    role: str                  # owner | admin | member | viewer  (§5)
    key_id: str                # the issuing api_keys row
    project_id: str | None = None  # set iff the key is project-scoped (§6); None = org-wide
    scopes: list[str] = …      # the key's explicit scope grant
```

(There is no `actor` field on the shipped `Principal`; `key_id` is the audit handle.)

The raw key never travels past this step; from here on the system speaks in `RequestPrincipal`. An unrecognised or revoked key never produces a principal — the request is rejected with `401` and the error envelope from [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §5 before any handler runs.

**(2) Principal → request context.** A FastAPI dependency stashes the principal in a `contextvars.ContextVar` for the life of the request. The same dependency is the *only* sanctioned source of `org_id` — handlers obtain it from `Depends(get_principal)`, never from a query string, body field, or path segment. A client cannot ask for someone else's `org_id`; there is no field through which to ask.

**(3) Context → ScanService.** Every `ScanService` method in the [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §4 contract takes `org_id` as a **keyword-only, non-default** argument — `create_scan(spec, *, org_id, project_id, actor)`, `get_scan(scan_id, *, org_id)`, `cancel_scan(scan_id, *, org_id)`, `list_scans(*, org_id, …)`. There is no overload that omits it. The handler passes `principal.org_id` straight through; see [`../orchestration/scan-service.md`](../orchestration/scan-service.md) for the method bodies. This is why the contract was written keyword-only with no default: you cannot *accidentally* call a service method tenant-blind.

**(4) ScanService → query.** Inside the service, `org_id` reaches the database only through the scoping helper of §4 — every `SELECT`/`UPDATE`/`DELETE` against a tenant-owned table is filtered `WHERE org_id = :org`. A `get_scan(scan_id, org_id=A)` for a scan owned by org B returns **not found**, never "forbidden": we do not confirm the existence of another tenant's resources (a `403` would leak that `scan_id` is real). The boundary is invisible from outside.

```
  Bearer rk_live_…              get_principal()            ScanService.get_scan(            scoped(select(ScanRun)
  ──────────────►  auth-and-keys ──────────►  ContextVar  ─────────────►  scan_id, *,        , org)  →  WHERE org_id = :org
  (../api/...)     SHA-256 → api_keys row     RequestPrincipal           org_id=principal.org_id)        AND scan_id = :id
                   → org_id, role, project    (org_id is here, only here)                                 → row | None
```

---

## 4. The query-scoping helper — a missing filter is a build error, not a leak

Row-scoping fails the day someone writes `session.execute(select(ScanRun).where(ScanRun.scan_id == sid))` and forgets `.where(ScanRun.org_id == org)`. The mitigation is to make the *unscoped* call impossible to express against a tenant table. Two layers:

**(a) The `query_scope()` helper is the sanctioned way to scope a tenant query.** The shipped signature is `query_scope(stmt, principal)` (not `scoped(stmt, org_id)`): it takes the whole `Principal`, applies `WHERE org_id = :org` and — when `principal.project_id` is set and the entity has a `project_id` column — `AND project_id = :project`, and **raises `ValueError` if the statement's FROM entity has no `org_id` column** (the "not tenant-scoped" guard):

```python
def query_scope(stmt, principal: Principal):           # src/rogue/platform/tenancy.py
    entity = stmt.get_final_froms()[0]
    org_col = getattr(entity.c, "org_id", None)
    if org_col is None:
        raise ValueError("query_scope: target has no org_id column — it is not tenant-scoped")
    stmt = stmt.where(org_col == principal.org_id)
    project_col = getattr(entity.c, "project_id", None)
    if principal.project_id is not None and project_col is not None:
        stmt = stmt.where(project_col == principal.project_id)
    return stmt
```

The "is it tenant-owned?" test is **column presence (`entity.c.org_id`)**, not a `TenantScoped` mixin — there is no such mixin in the shipped code. Tenant-owned tables (`scan_runs`, `scan_jobs`, `reports`, `api_keys`, `projects`, …) carry an `org_id` column and pass; genuinely global tables (the shared `attack_primitives` corpus) have none and raise.

**(b) The CI lint rule is NOT built.** The blocking AST check that would flag a bare `session.execute` over a tenant model is design only — there is no Ruff/flake8 plugin enforcing `query_scope` usage today. The discipline is by-convention (route every tenant read through `query_scope`), not machine-enforced. Note also: the `DefaultScanService`/`PostgresScanStore` shipped path filters by passing `org_id` to the store methods (`store.get(scan_id, org_id=…)` does the cross-tenant `→ None` check inline) rather than via `query_scope` — `query_scope` is the general helper, used where a raw `select` is built.

---

## 5. RBAC roles & the permission matrix

Authentication answers *which org*; authorization answers *what may this principal do inside it*. Four roles, ordered by privilege, stored on the membership row (the table is **`memberships`**, per [`./data-model.md`](./data-model.md)) and on `Principal.role`. **Shipped caveat:** the building blocks exist (`Principal.role`, `Principal.scopes`, `role_at_least`, `has_scope`), but the `(role, resource, action)` permission **matrix and the `require(principal, …)` enforcement call are NOT wired into the `/v1` handlers** — routes gate on authentication (`require_principal`) only. The matrix below is the intended policy, not an enforced one.

- **owner** — the org's root authority. Billing, deleting the org, transferring ownership. Exactly one (or a small set) per org.
- **admin** — manages people and configuration: invite/remove members, issue/revoke API keys, manage projects and org settings. No billing-destructive or org-deletion rights.
- **member** — the working engineer: create/cancel/view scans, view and export reports, manage deployment-config targets. The default role for an invited teammate.
- **viewer** — read-only: view scans and reports, nothing that writes or costs money. The role for an auditor, an exec, or a read-only dashboard share.

Permissions are checked against a static **matrix** keyed by `(role, resource, action)`. The handler calls `require(principal, Resource.SCANS, Action.CREATE)` *after* org-scoping; a failure returns `403` with the standard envelope (this `403` is intra-org and safe — the principal already proved org membership, so we're not leaking cross-tenant existence).

| Resource → / Role ↓ | **scans** | **reports** | **api keys** | **projects** | **billing** | **org settings** |
|---|---|---|---|---|---|---|
| **owner**  | CRUD + cancel | read + export | CRUD | CRUD | **manage** | **manage** + delete org |
| **admin**  | CRUD + cancel | read + export | CRUD | CRUD | read | manage (non-destructive) |
| **member** | create / cancel / read | read + export | — | read + manage targets | — | read |
| **viewer** | read | read | — | read | — | read |

Reading the matrix: a **member** can run and cancel scans and read reports but cannot mint API keys or see billing; a **viewer** cannot create a scan (so cannot spend money); only **owner**/**admin** touch keys; only **owner** can delete the org or manage the billing relationship. Roles are *coarse and stable* — we deliberately ship four, not a custom-permission engine; that is a §13-style scope line we hold for the platform's first cut.

API keys carry a role too (a key is a non-human principal). A `rk_live_…` key issued at **member** level can drive scans; a key issued at **viewer** level is a read-only token safe to embed in a dashboard or a CI status check. A key's effective permission is `min(key.role, issuer.role)` — an admin cannot mint a key more powerful than itself.

---

## 6. Project sub-scope

A **project** (`proj_<ulid>`) is an optional sub-tenant boundary *inside* an org — e.g. "staging-bot" vs "prod-bot", or one project per customer team. A principal may be **project-scoped**: `RequestPrincipal.project_id` is set, and that principal sees only rows whose `project_id` matches. This composes with org-scoping; it never replaces it.

- A **project-scoped key** (the common case: a CI key bound to one service's project) can only create scans in, and read scans/reports of, its `project_id`. `scoped()` is extended to a `scoped_project(stmt, org_id, project_id)` that adds `AND project_id = :proj` when the principal is project-bound, and is a no-op (org-wide) when `project_id is None`.
- A project-scoped principal cannot widen itself — there is no parameter to request `project_id = None`; the scope comes from the membership/key row, not the request.
- Org-wide principals (most owners/admins) see all projects in their org. `list_scans(*, org_id, project_id=…)` from the [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §4 contract lets an org-wide caller *filter* to a project; a project-scoped caller is *forced* to it regardless of the argument.

Project scope is enforced in the same helper layer as org scope, so the same lint rule covers it: a query against a `TenantScoped` model is scoped to org always, and to project when the principal demands it.

---

## 7. Killing the single-tenant hard-codes

> **Shipped status: NOT done.** The three `acme` hard-codes below were **not** removed — the legacy single-tenant dashboard/threat-brief/MCP path still uses `customer_id="acme"` (`api/main.py:1052`, `threat_brief.py`, `mcp_server/server.py`), and `deployment_configs.customer_id` is unchanged. The new multi-tenant `/v1` + `platform/` stack was added *alongside* the legacy single-tenant engine rather than by migrating it. This section remains the intended cutover plan.

The Week-1–3 engine was built for one customer, `acme`, with a string `customer_id` standing in for a real tenant. Three concrete hard-codes leak that assumption and were slated to die in the "make it SaaS" milestone ([`../ARCHITECTURE.md`](../ARCHITECTURE.md) §7). Each is a place where the new `org_id` chain (§3) would replace a literal.

**(a) `ThreatBriefBuilder.build_diff(customer_id="acme")`** — `src/rogue/diff/threat_brief.py:152` takes `customer_id: str` and is called with the literal `"acme"`; its own docstring (`threat_brief.py:159`) already flags this as "single-customer for now … a WHERE swap." Migration: rename the parameter to `org_id: str`, make it non-default and keyword-only (`build_diff(*, org_id, target_date=None)`), and have `_fetch_breach_matrix` filter the `breach_matrix` view on the org-scoped column instead of `customer_id`. No caller may pass a literal; the org comes from the request principal.

**(b) MCP tools `query_diff` / `query_threat_brief`** — `src/rogue/mcp_server/server.py:198` and `:229` both call `builder.build_diff(customer_id="acme", …)` (lines `:219`, `:258`) with a comment ("If multi-tenancy lands, accept `customer_id` as another tool arg") that this milestone cashes in. Migration: the MCP server is itself an authenticated surface (Team G, [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §6) — it resolves an `org_id` from the connection's API key exactly as the REST API does (§3 hop 1) and passes that `org_id` into `build_diff`. The org is **never** a tool argument the model fills in: that would let a prompt name another tenant's org and exfiltrate its brief. The `acme` default and its sibling default in the read-only REST handler at `src/rogue/api/main.py:934` are removed in the same change.

**(c) `DeploymentConfig.customer_id`** — the Pydantic field at `src/rogue/schemas/deployment_config.py:28` (default `"acme"` in the example builder, `deployment_config.py:130`) and its ORM mirror at `src/rogue/db/models.py:95` (`customer_id: Mapped[str]`, indexed). This is the single column that *is* the tenant boundary today, under the wrong name and the wrong type. Migration path:
  1. Add a nullable `org_id` column (FK to `orgs`, indexed) to `deployment_configs` (migration 0022+).
  2. Backfill: every existing row's `customer_id="acme"` maps to the bootstrap org `org_<acme-ulid>` created for Soren's own deployment. The mapping table is recorded in the migration so the backfill is reproducible.
  3. Make `DeploymentConfig` `TenantScoped` (the §4 mixin); every query touching it now goes through `scoped()`.
  4. Drop `customer_id` once no code references it. Pydantic `DeploymentConfig.customer_id` becomes `org_id: str` (still `min_length=1`), and the example fixture's `"acme"` becomes the bootstrap org ID.

The principle across all three: **`customer_id` was a stringly-typed stand-in for a tenant; `org_id` is the real one, sourced from the authenticated principal and never from a literal, a default, or an LLM-supplied tool argument.** After this milestone, grepping the codebase for `"acme"` returns only test fixtures and the bootstrap-org seed — never a query default.

---

## 8. Audit logging of privileged actions

> **Shipped status: NOT built.** There is no `audit_log` table and no audit-write path in the shipped platform. `api_keys.last_used_at` is the only usage breadcrumb. This section is the intended design.

Every action that mutates tenant state or touches credentials/billing would write an immutable **`audit_log`** row. Audit is append-only: no `UPDATE`, no `DELETE`, retained for the org's lifetime.

A row records: `org_id`, `actor` (the `RequestPrincipal.actor` — `user:usr_…` or `key:…last4`), `action` (e.g. `scan.create`, `scan.cancel`, `apikey.issue`, `apikey.revoke`, `member.invite`, `member.role_change`, `project.create`, `org.settings_change`, `billing.change`), `resource_id`, `before`/`after` for state changes, request IP/user-agent, and `ts`. Privileged actions that **must** be audited: any API-key lifecycle event, any membership/role change, any project create/delete, any billing or org-settings change, and scan create/cancel (they spend money — see the costly-scripts note in the project `CLAUDE.md`). Reads are **not** audited by default (too noisy; the value is in mutations and credential events).

`audit_log` is itself `TenantScoped`, so an org's owner/admin can review their own trail through a (future) settings page, and the operator can review cross-org for incident response. Writes happen in the same transaction as the mutation they describe, so an action and its audit row commit or roll back together — there is no committed change without its audit record.

---

## 9. End-to-end sequence — a scan request, org-scoped from key to query

The whole chain for `POST /v1/scans` with a `member`-level live key bound to a project:

```
Client                  API (Team A)              ScanService (Team B)         DB (one Neon)
  │  POST /v1/scans          │                          │                          │
  │  Bearer rk_live_…  ─────►│                          │                          │
  │                          │ get_principal():          │                          │
  │                          │   SHA-256(key) → api_keys │  ── scoped(select(ApiKey),│
  │                          │   (../api/auth-and-keys)  │      <no org yet: keyed   │
  │                          │   → RequestPrincipal{      │      by hash> ) ─────────►│
  │                          │      org_id, role=member, │◄── org_id, role, project ─┤
  │                          │      project_id, actor }   │                          │
  │                          │                          │                          │
  │                          │ require(principal,        │                          │
  │                          │   SCANS, CREATE) → ok (§5)│                          │
  │                          │                          │                          │
  │                          │ create_scan(spec, *,      │                          │
  │                          │   org_id=principal.org_id,│                          │
  │                          │   project_id, actor) ────►│ stamp org_id+project_id  │
  │                          │                          │ on the new ScanRecord    │
  │                          │                          │ audit_log: scan.create ──►│ (same txn, §8)
  │                          │                          │ enqueue job (org_id rides │
  │                          │                          │   on the job payload) ───►│
  │                          │◄──── ScanRecord ──────────┤                          │
  │◄── 202 {scan_id, status} │                          │                          │
  │                          │                          │                          │
  │  GET /v1/scans/{id}  ───►│ get_principal() → org_id  │ get_scan(id, *,           │
  │  Bearer rk_live_…        │ require(SCANS, READ)      │   org_id) ───────────────►│ scoped(): WHERE org_id=:org
  │                          │                          │                          │   AND scan_id=:id
  │                          │                          │◄── row | None ───────────┤   (other org's id → None → 404)
  │◄── 200 ScanRecord / 404  │                          │                          │
```

Note the two structural guarantees the diagram encodes: `org_id` is *minted by the auth layer and only there* (the client never supplies it), and the read-back is `scoped()` so a guessed `scan_<ulid>` belonging to another tenant returns `404`, not its contents and not a `403`. The worker that later runs the job (Team B, [`../orchestration/scan-service.md`](../orchestration/scan-service.md)) carries the same `org_id` on the job payload and writes results back through `scoped()` — the tenant boundary holds off the request path too.

---

## 10. Open questions for Team C

- **RLS as a backstop (§2):** worth the `SET LOCAL` per-request plumbing on a pooled connection, or does the lint rule (§4) suffice? Leaning: lint first, RLS later if an incident or an auditor demands defence-in-depth.
- **Org-scoping the harvest/breach corpus (§4, §7):** `attack_primitives` is shared intel and stays global, but `breach_results` are per-deployment and therefore per-org once `deployment_configs` is org-scoped. Confirm the `breach_matrix` view (migration 0002) joins to `deployment_configs.org_id` so the threat brief (§7a) is org-correct by construction.
- **Bootstrap org (§7c):** the `org_<acme-ulid>` Soren's own deployments backfill into — does it stay a real first-class org (so the operator dogfoods the tenant path), or a reserved internal org? Leaning: a real org, so there is no untested "operator" code path.
