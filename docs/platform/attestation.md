# The signed-attestation layer

The tamper-evident, reproducible, queryable record every ROGUE surface emits — "the unit the CISO actually buys." Net-new in ROGUE v2 (Phase 0). Code: `src/rogue/attestation/`; storage: `platform/models.py:AttestationEntry` + migration `0031_attestation_entries.py`. Design: ADR-0012 (`docs/v2/adr/0012-…`). Build spec: `docs/v2/build/03_attestation.md`.

## The framing (non-negotiable, on every entry and every render)

> **Threat-informed assurance, tested against the open-web corpus as of date D — NOT a safety guarantee.**

We claim the *property set* below, not a proven regulatory outcome. The framing line (`emit.framing_line`) travels structurally on every entry's `payload` and on every `AttestationEntryOut` response, so a client can never render an entry without it. `corpus_as_of` is NOT NULL — the service refuses to append without it.

## The five properties → how each is delivered

1. **Tamper-evidence** — a per-`org_id` append-only hash chain: `entry_hash = sha256(prev_hash || canonical_json(payload))`, `seq` per-org monotonic (genesis = 0), genesis `prev_hash` = 64 zeros. Append-only is *enforced*, not intended: a Postgres `BEFORE UPDATE OR DELETE` trigger RAISEs (dialect-guarded for SQLite test backends). Verifiable offline via `chain.verify_chain` (imports no DB). This is table-stakes, not the differentiator — we don't oversell it.

2. **Completeness** — every COMPLETED scan appends exactly one `scan` entry (the worker hook, `worker.py:ScanWorker._attest_completed_scan`). Honestly scoped: FAILED/CANCELED scans are recorded in `scan_runs.status` and are NOT attested — there is no verdict to attest. The hook is best-effort (logs, never fails a paid scan) and idempotent on `reproducibility_ref` (a worker retry never double-appends).

3. **Decision-rationale capture** — the `payload` is structured *what / what the judge scored / why*, not a flat timestamp. `emit.payload_for_scan` builds, per finding: rule/family, breach_type, n_breach/n_trials, success_rate, verdict, judge_rationale, consummation_event, `snapshot_ref`, `ground_truth_ref` — plus the headline and the framing line. Every free-text field is redacted (`report_service._redact`): an append-only entry can never carry a secret.

4. **Replayability** — reconstruction-from-stored, not re-execution (`replay.py`). Given an entry's `reproducibility_ref`, re-read the stored inputs the worker had, recompute the payload via the same `emit` recipe, recompute `entry_hash`, assert it equals the stored hash. **No model call, no judge call** — re-firing the model is non-deterministic and out of scope. This is honest "replayable": byte-reproducible from stored inputs. It is also a *second* tamper check — the chain catches edits to the entry; replay catches edits to the source rows (returns `{reproducible, recomputed_hash, stored_hash, drift}`).

5. **Queryability** — the tenant-scoped `/v1/attestation` API (`api/v1/attestation.py`): `GET /entries` (paginated by `seq`; filter `entry_type`/`since_seq`), `/entries/{id}`, `/verify` (re-walk the chain), `/entries/{id}/replay`. Cross-org reads are a clean 404 (no existence leak). The rich auditor predicates ("every scan over threshold X where the mitigation failed re-test") become expressible as the `payload` grows across surfaces; Phase 0 ships the list/filter/verify/replay spine.

## Design decisions (ADR-0012)

- **One chain per org**, not one global chain (per-tenant system-of-record, ADR-0006; a global chain couples tenant integrity and leaks existence).
- **Stays in Postgres** — no Merkle service, no blockchain, no external timestamping authority, no Redis/queue (ADR-0009 affirms ADR-0002). One table, one per-org hash chain.
- **Captures are pointers, not blobs** — the entry stores `reproducibility_ref` + the verdict & rationale inline, never the transcript.
- **The independence pointer travels with the verdict** (ADR-0011) — `ground_truth_ref` is the independent label this verdict is scored against (never the regulation, the operators' votes, or the judge's own score). Harm Phase-0 entries leave it null (the calibrated harm judge is the verdict); the column exists from day one so surfaces don't fork the schema.
- **Surface-agnostic shape** — one table, one `entry_type` discriminator (`genesis | scan | decision | mitigation | promotion`) + a JSON `payload`. Surfaces add `payload` shapes (`payload_for_decision`/`payload_for_promotion`), never per-surface attestation tables.

## What this layer deliberately does NOT do

- No new datastore (ADR-0009/0002).
- No re-execution replay (no re-firing the model).
- No per-surface attestation tables.
- No queryability beyond the spine (rich predicates land as the `payload` grows).

## Wiring

The `AttestationService` is constructed over the scan store's hardened sessionmaker and injected into the worker (`attestation_service=`), wired in `api/main.py:_wire_platform` (also exposed via `deps.get_attestation_service` for the API) and `worker.main()`. The chain primitives (`chain.py`) and response schemas (`schemas.py`) are pure (no DB/platform import) so the auditable math is testable offline.
