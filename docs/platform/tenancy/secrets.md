# Secrets & Settings (Team C)

> The platform stores two kinds of secrets that must never touch a log line, a report, or an error body: **tenant secrets** (a customer's target endpoint credentials and provider API keys, per-org) and **platform secrets** (our own infra — `DATABASE_URL`, our provider keys, our KMS/Vault credentials). This doc specifies how both are stored, resolved just-in-time, rotated, revoked, and kept out of every customer-visible artifact, and it specifies the typed settings module that replaces the ad-hoc `os.environ.get` reads scattered across the engine today. It owns the implementation of the empty `src/rogue/config.py` stub (`config.py:1`).

Status: **design spec, not yet built.** Grounds in [ARCHITECTURE.md](../ARCHITECTURE.md); reuses its `TargetSpec.api_key_ref`, ID, and error-envelope vocabulary verbatim and never redefines them. Cross-links: [./data-model.md](./data-model.md) (the `api_keys` / `scan_runs` columns), [./isolation-and-rbac.md](./isolation-and-rbac.md) (who may read/rotate a secret), [../api/auth-and-keys.md](../api/auth-and-keys.md) (`rk_live_*` platform keys vs. the tenant secrets below).

---

## 1. Two secret classes — keep them apart

The single most important distinction in this doc. They live in different stores, have different blast radii, and are read by different code.

| | **Platform secrets** | **Tenant secrets** |
|---|---|---|
| Owner | ROGUE infra | one `org_<ulid>` |
| Examples | `DATABASE_URL`, `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`GROQ_API_KEY`/`OPENROUTER_API_KEY` (our judge/extraction/escalation spend), `BRIGHTDATA_API_KEY`, `SLACK_WEBHOOK_URL`, `REVALIDATE_TOKEN`, KMS/Vault creds | a customer's target endpoint credential (the key behind `TargetSpec.api_key_ref`), their target `endpoint` auth |
| Where | process environment → the typed settings object (§4), loaded once at boot | encrypted ciphertext in Postgres (§3), keyed per org, resolved JIT (§2) |
| Read by | any worker/process, at startup | only the worker, only while running that org's scan |
| Rotation | redeploy / env update | tenant-driven via API + envelope re-wrap (§5) |
| If leaked | our bill, our data | a *customer's* model access — contractually catastrophic |

Today both classes are read the same way — `os.environ.get(...)` inline at the call site. That is correct enough for platform secrets and **completely wrong** for tenant secrets (single-tenant `acme` has no tenant secrets yet, which is why the gap is invisible). The settings module (§4) formalizes platform secrets; the `api_key_ref` indirection (§2) is the entire mechanism for tenant secrets.

## 2. The `api_key_ref` indirection — TargetSpec never carries a raw secret

Per ARCHITECTURE.md §5, `TargetSpec = { endpoint, provider, model, api_key_ref: str, system_prompt }`, and `api_key_ref` "is a Vault/KMS handle, never the raw secret (Team C)." This doc makes that handle real. The lifecycle:

1. **Submit.** A customer registers a target credential through the API (Team A, [../api/auth-and-keys.md](../api/auth-and-keys.md)) authenticated by their `rk_live_*` platform key. The raw provider key arrives over TLS, is encrypted (§3), and is written to `api_keys` (see [./data-model.md](./data-model.md)). The API responds with a **handle**, never echoing the secret back.
2. **Reference.** `api_key_ref` is that handle, of the form `secref_<ulid>` (a new ID joining ARCHITECTURE.md §5's `scan_*`/`rep_*`/`org_*`/`proj_*` family). It is org-scoped: a `secref_*` resolves only within the `org_id` that created it (enforced per [./isolation-and-rbac.md](./isolation-and-rbac.md)). The handle is safe to store in a `ScanSpec`, persist on the `scan_runs` row, return from `GET /v1/scans/{id}`, and print in any log — it is **not** a secret.
3. **Resolve JIT, in the worker only.** When `ScanEngine.run(target, ...)` (ARCHITECTURE.md §4) needs to call the customer model, it resolves the handle to plaintext *at the last possible moment* — inside the worker process that owns the scan, never in the API request thread, never in the queue payload. Resolution is `org`-checked: `resolve(secref, org_id)` fails closed if the handle's org ≠ the scan's org.
4. **Use, then drop.** The plaintext is held only as a local in the adapter call — passed as `DeploymentConfig.api_key` into the existing adapters (which today read `config.api_key or os.environ.get(...)`, e.g. `adapters/openai.py:27`). It is never assigned to a logged field, never put on `ScanRecord`, and goes out of scope when the adapter call returns. No plaintext is ever persisted.

```
TargetSpec.api_key_ref = "secref_01J..."           # handle — safe everywhere
        │  (in ScanSpec, on scan_runs, in logs)
        ▼   worker only, JIT
SecretService.resolve("secref_01J...", org_id) ──► plaintext  (held in-frame)
        ▼
DeploymentConfig.api_key = plaintext ──► adapter HTTP call ──► dropped on return
```

`SecretService` is the only code that ever sees both the ciphertext and the plaintext. Every other layer traffics in `secref_*`.

```python
class SecretService:
    async def put(self, *, org_id: str, label: str, plaintext: str) -> str:        # -> "secref_<ulid>"
    async def resolve(self, ref: str, *, org_id: str) -> str:                        # plaintext; fails closed on org mismatch / revoked
    async def rotate(self, ref: str, *, org_id: str, new_plaintext: str) -> None:    # re-wrap, bump version
    async def revoke(self, ref: str, *, org_id: str) -> None:                        # tombstone; subsequent resolve raises
```

## 3. Envelope encryption — what's stored, and where

Tenant secrets are encrypted at rest with **envelope encryption**, the standard two-tier scheme: a per-secret **data key (DEK)** encrypts the plaintext; a **key-encryption key (KEK)** held in the key manager encrypts the DEK. ROGUE's plaintext is itself stored — only the wrapped DEK + ciphertext live in Postgres.

- **Backend, two interchangeable options** (pick one at deploy; the `SecretService` interface is identical):
  - **AWS KMS** — `GenerateDataKey` returns `{plaintext_dek, encrypted_dek}`; we AES-256-GCM the secret under `plaintext_dek`, store `encrypted_dek` + ciphertext, discard `plaintext_dek`. Decrypt path: `Decrypt(encrypted_dek)` → AES-GCM-open.
  - **HashiCorp Vault Transit** — Vault holds the key and does the crypto; we send plaintext to `transit/encrypt/rogue-tenant` and store the returned `vault:v1:...` blob. No DEK lands on our side at all (strongest option; preferred if Vault is already in the stack).
- **Where the ciphertext lives** ([./data-model.md](./data-model.md), `api_keys` table): a `ciphertext BYTEA NOT NULL` column holds the AES-GCM (or Vault) blob; `wrapped_dek BYTEA` holds the KMS-encrypted DEK (NULL for Vault Transit, which is self-describing); `kek_id TEXT` / `key_version INT` record which KEK + version wrapped it (for rotation, §5); `nonce BYTEA`, `org_id`, `label`, `created_at`, `revoked_at`. The plaintext column **does not exist** — there is nowhere in the schema to accidentally store it.
- **`scan_runs` carries only the handle.** Per [./data-model.md](./data-model.md), a `scan_runs` row references the target by `api_key_ref` (the `secref_*` string), never a foreign key that could be joined back to plaintext and never the ciphertext. A dump of `scan_runs` leaks nothing.
- **Platform secrets are not enveloped.** `DATABASE_URL` and our provider keys come from the process environment via the settings module (§4); they are protected by the deploy platform's env-var secret store (Render/Vercel), not this Postgres path. Mixing the two is a design error — platform secrets in `api_keys` would give every tenant a column to subpoena.

## 4. The settings module — `src/rogue/config.py`

Today `config.py` is a one-line stub (`config.py:1`) and **every** platform secret is read ad-hoc via `os.environ.get` at the call site. This is real and widespread: 21 modules under `src/rogue/` read `os.environ` directly. Concrete instances this module consolidates:

- `api/main.py:74` and `mcp_server/server.py:78` define the **same** `DEFAULT_DATABASE_URL` fallback string and the **same** `_database_url()` helper — duplicated verbatim across two files (the `66`/`78` lines).
- `reproduce/judge.py:232` reads `JUDGE_MODEL` (and `:241` `JUDGE_FALLBACK_MODEL`) inline.
- `adapters/openai.py:27` reads `OPENAI_API_KEY`, `:46` reads `GROQ_API_KEY`; the other adapters do the same for Anthropic/OpenRouter/Gemini.
- `notify.py:32-33` read `FRONTEND_REVALIDATE_URL` + `REVALIDATE_TOKEN`; `harvest/bright_data_client.py`, `diff/threat_brief.py`, `extract/extraction_agent.py`, and the §10.9 escalation modules each read their own slice.

The canonical key list lives in [`.env.example`](../../../.env.example) — **27** keys today, grouped by concern (provider keys, Bright Data, LeakHub auth, database, revalidation, harvest toggles, Slack, model selection, run-tuning, MCP transport). The settings module is the **one source of truth** that loads exactly those keys, typed and validated once.

**Design: `pydantic-settings` (`BaseSettings`).** One module, one object, env-backed with an optional secret backend:

```python
# src/rogue/config.py
from functools import lru_cache
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- platform infra ---
    database_url: str = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"
    neon_database_url: str | None = None

    # --- platform provider keys (our judge/extraction/escalation spend) ---
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    brightdata_api_key: SecretStr | None = None
    slack_webhook_url: SecretStr | None = None
    revalidate_token: SecretStr | None = None

    # --- model selection / tuning (non-secret) ---
    judge_model: str = "anthropic/claude-sonnet-4-6"
    judge_fallback_model: str = "deepseek/deepseek-v4-flash"
    extraction_model: str = "anthropic/claude-haiku-4-5"
    n_trials_per_attack: int = 5
    breach_rate_threshold: float = 0.4

    # --- tenant-secret backend selection (drives §3) ---
    secret_backend: str = "kms"            # "kms" | "vault" | "local" (dev only)
    kms_key_id: str | None = None
    vault_addr: str | None = None
    vault_token: SecretStr | None = None

@lru_cache
def get_settings() -> Settings: ...
```

Key decisions:

- **Every secret field is `SecretStr`.** `repr(settings)` and any accidental `str(settings)`/log of the object renders `SecretStr('**********')` — the value never appears unless `.get_secret_value()` is called explicitly. This is the first line of redaction defense (§6) and is the reason to migrate the raw-`str` `os.environ.get` reads.
- **One default for `DATABASE_URL`.** The fallback string now lives in `Settings.database_url`; `api/main.py` and `mcp_server/server.py` both `from rogue.config import get_settings` and read `get_settings().database_url`, deleting their duplicated `DEFAULT_DATABASE_URL` + `_database_url()` (kill `api/main.py:66` and `mcp_server/server.py:78`).
- **The settings object holds platform secrets only.** Tenant secrets are *never* fields here — they flow through `SecretService` (§2) keyed by org. `secret_backend`/`kms_key_id`/`vault_*` here are how `SecretService` reaches its backend, not the tenant material itself.
- **Migration is mechanical and incremental.** Replace each `os.environ.get("X")` with `get_settings().x`. Adapters keep their `config.api_key or <settings fallback>` shape — the per-call `DeploymentConfig.api_key` (which is where a *tenant's* resolved secret lands, §2) still wins over the platform default, preserving today's behavior. Non-secret toggles (`HARVEST_*`, MCP transport) move too, so `.env.example` stays the literal field list.

## 5. Rotation & revocation

- **Tenant secret rotation.** `SecretService.rotate(ref, org_id, new_plaintext)` generates a fresh DEK (or re-encrypts under Transit), writes new `ciphertext`/`wrapped_dek`/`nonce`, and bumps `key_version` on the **same** `api_keys` row — so `api_key_ref` (`secref_*`) is stable across rotations and existing `scan_runs`/`ScanSpec`s keep working. In-flight scans already hold resolved plaintext in-frame and finish on the old value; the next resolve picks up the new one.
- **Revocation.** `revoke(ref, org_id)` sets `revoked_at` and tombstones the row (keeps `ciphertext` only long enough for audit, then nulls it on a sweep). A revoked handle fails `resolve` closed with the error envelope `{ "error": { "code": "secret_revoked", "message": "..." } }` (ARCHITECTURE.md §5 shape) — and per [./isolation-and-rbac.md](./isolation-and-rbac.md) only an org admin may revoke.
- **KEK rotation (platform-wide).** Rotating the KMS/Vault KEK does **not** require touching every row immediately: KMS re-wrap is a cheap `Decrypt`→`Encrypt` of the DEK (ciphertext untouched); a background re-wrap sweep upgrades `key_version` lazily. `kek_id`/`key_version` on each row records what to re-wrap.
- **Platform secret rotation** is a deploy-time concern: update the env var in Render/Vercel and redeploy; `get_settings()`'s `lru_cache` is per-process, so a fresh process picks up the new value. No DB involvement.

## 6. Redaction — secrets never appear in any artifact

A tenant secret (or a platform key) must never surface in **logs, `scan_runs` rows, reports, or error envelopes**. Defense in depth:

1. **Type-level.** `SecretStr` (§4) makes platform secrets unprintable by default; `SecretService` returns plaintext as a bare local that is never assigned to a logged structure (§2).
2. **Never persisted.** `scan_runs` stores `api_key_ref`, not the secret; `api_keys` has no plaintext column (§3). There is structurally no row that holds a resolvable secret in cleartext.
3. **Log scrubbing.** A logging filter on the `rogue.*` loggers (e.g. `rogue.api`, `rogue.mcp_server`, the worker) redacts any token matching known secret shapes — provider prefixes (`sk-`, `sk-ant-`, `gsk_`, `sk-or-`), `brd-`, Slack webhook URLs, and `secref_*`-adjacent material — before a record is emitted. Belt to the `SecretStr` braces.
4. **Report payload scrubbing — the subtle one.** `ScanReport.findings[]` (ARCHITECTURE.md §3, `report.py:75`) carry `rendered_payload` and `model_response`. An attack can *inject* a credential into the prompt, or the target model can *echo* one back in its response — so the raw secret can legitimately end up inside an attack payload or a model reply that we then store and render to the customer. `ReportService` (Team F, [../reports/report-service.md](../reports/report-service.md), if/when present) MUST run the same scrubber over `rendered_payload` and `model_response` before persisting or rendering them, replacing any matched secret with `‹redacted-secret›`. This is the one place secrets can leak *through* the engine rather than around it; it is Team C's scrubber, called by Team F.
5. **Error envelopes.** The ARCHITECTURE.md §5 envelope (`{ error: { code, message, details? } }`) is built from fixed codes (`secret_revoked`, `secret_not_found`, `secret_forbidden`) — never from a raw exception string that might embed a connection URL or key. Adapter/HTTP exceptions are caught and re-wrapped before they reach `details`.

## 7. Boundaries — what this doc does NOT own

- **AuthN of the caller** (the `rk_live_*` / `rk_test_*` platform keys, of which only a SHA-256 is stored per ARCHITECTURE.md §5) is [../api/auth-and-keys.md](../api/auth-and-keys.md). Those keys authenticate *requests*; `secref_*` handles reference *tenant target credentials*. Different things, different docs.
- **AuthZ** — who in an org may `put`/`rotate`/`revoke`/`resolve` a secret — is [./isolation-and-rbac.md](./isolation-and-rbac.md). This doc assumes those checks and fails closed when they're absent.
- **The `api_keys` / `scan_runs` column definitions** are [./data-model.md](./data-model.md); this doc specifies what those columns must *hold* (ciphertext, wrapped DEK, key version, handle) and why, not their full DDL.
- **The scan execution path** is unchanged — `ScanEngine.run` (ARCHITECTURE.md §4) gains exactly one new call, `SecretService.resolve`, just before it builds `DeploymentConfig`; no scanning logic moves here.

## 8. Build order (within Team C)

1. **Settings module** — implement `src/rogue/config.py` (§4); migrate `api/main.py`/`mcp_server/server.py` `DATABASE_URL` first (removes the duplication), then judge/adapters/notify. Lowest risk, immediate cleanup, no DB.
2. **`api_keys` columns** — add `ciphertext`/`wrapped_dek`/`nonce`/`kek_id`/`key_version`/`revoked_at` (migration 0022+, the next number after the committed 0021; coordinate with Team B's 0022 scan tables — see ARCHITECTURE.md §7).
3. **`SecretService`** — `local` backend first (dev: a static KEK, so the whole flow is testable without cloud creds), then KMS/Vault behind the same interface.
4. **`ScanEngine.resolve` hook** + the report/log scrubber (§6) — wire JIT resolution and prove, with a test, that an injected credential in a `model_response` comes out `‹redacted-secret›` in the persisted report.
