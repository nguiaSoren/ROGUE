# Architecture Decision Records (ADRs)

Retroactive MADR-style records for ROGUE's load-bearing decisions. Each ADR has: Title, Status, Date, Context, Decision, Consequences, and "What would reverse this." ADRs are descriptive of decisions already made and shipped, not proposals.

**Status vocabulary**

- **Binding** — a frozen invariant the codebase enforces; changing it is a re-architecture, not a tweak.
- **Accepted** — a decision in force, revisable if its triggering condition changes.
- **Supersedes-for-platform** — overrides a specific `ROGUE_PLAN.md §13` non-goal *for the hosted-product layer only*; the research engine still obeys §13.

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-python-only-no-rust.md) | Python-only, no Rust | Binding |
| [0002](0002-single-postgres-pgvector.md) | Single Postgres 17 + pgvector; no Redis/Kafka/Elasticsearch/service-mesh | Binding |
| [0003](0003-no-langchain-hand-rolled-agents.md) | No LangChain/LangGraph; hand-rolled agents | Binding |
| [0004](0004-provider-abstraction-layer.md) | Provider-abstraction layer; no provider SDK types above the adapter boundary | Binding |
| [0005](0005-judge-content-transfer-gate-v3.md) | LLM-judge content-transfer gate (v1→v3) + stored-matrix re-judge | Accepted |
| [0006](0006-auth-multitenancy-platform-layer.md) | Authentication + multi-tenancy for the hosted platform layer | Supersedes-for-platform |
| [0007](0007-scheduler-reorder-never-exclude.md) | Scheduler reproducibility invariant: "reorder, never exclude" | Binding |
| [0008](0008-batch-api-resume-by-batch-id.md) | Batch-API + resume-by-batch-id for cost-controlled re-grades | Accepted |

## Relationship to `ROGUE_PLAN.md §13`

`ROGUE_PLAN.md §13` froze 20 non-goals for the Day-0 *research deliverable*, and remained the project's most-cited authority. The **startup pivot** built a hosted SaaS layer atop the unchanged research engine, deliberately crossing several §13 items. Where an ADR is marked **Supersedes-for-platform**, it overrides the named §13 item **for the product layer only** — the §8–§12 research engine still obeys §13 in full. ADR-0006 is the primary reconciliation: it supersedes §13 #3 (no-auth) and #4 (no-multi-tenancy) for the product layer, and notes that the same pivot scope also accounts for §13 #6 (CLI), #7 (migrations beyond the first), #8 (landing page), #9 (marketing copy), and #17 (a paper) — these are product/research-track scope, not violations of a still-binding rule. The Binding ADRs (0001–0004, 0007) restate §13 items that remain frozen everywhere. When §13 and an ADR appear to conflict, the ADR is authoritative for current behavior; §13 records the original intent.
