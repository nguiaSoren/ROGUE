# 0002 — Single Postgres 17 + pgvector; no Redis/Kafka/Elasticsearch/service-mesh

- **Status:** Binding
- **Date:** 2026-06-08 (retroactive; decision frozen Day 0)

## Context

ROGUE needs relational state (`attack_primitives`, `breach_results`, `deployment_configs`, `source_provenances`, `bright_data_cost_log`), a job queue, vector similarity for dedup + technique retrieval, and a full-text-ish discovery surface. The default architecture reflex is to reach for a purpose-built service per concern (Redis for the queue, Elasticsearch for search, Kafka for events, Pinecone/Weaviate for vectors). `docs/architecture.md` ("One database, not a service mesh. Postgres holds everything.") and the "no vector DB beyond pgvector" line lock against this. Operationally the project runs solo on a small box (Docker capped at 3 GB / 2 CPU) and deploys to a free Neon tier — every extra service is an extra thing to host, secure, and pay for.

## Decision

One Postgres 17 instance with the `pgvector` extension is the only datastore. Vectors (1536-d `text-embedding-3-small`, ivfflat cosine) live in Postgres. The job queue is Postgres `LISTEN/NOTIFY`. No Redis, no Kafka, no Elasticsearch, no separate vector DB, no service mesh. Schema is owned by hand-written Alembic migrations in `src/rogue/db/migrations/versions/`.

## Consequences

- One connection string, one backup, one thing to monitor; transactional consistency across attacks, breaches, embeddings, and dedup for free.
- Vector recall and queue throughput are bounded by Postgres rather than a specialized engine — acceptable at ROGUE's scale (low thousands of primitives, batch reproduce runs).
- Neon serverless cold-starts must be tolerated at the app layer (`pool_pre_ping`, DB-free liveness) — see the serverless-resilience checklist.

## What would reverse this

A measured Postgres ceiling that batching/indexing can't lift — e.g. vector recall latency unacceptable past ~10^6 primitives, or queue contention under real multi-tenant load. The retrieval layer (migration 0026) is the early-warning canary for the vector half.
