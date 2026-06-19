# Technique Retrieval System

Design doc for the candidate-generator layer that sits in front of the contextual scheduler. All implementation files are under `src/rogue/retrieval/` unless noted.

---

## Motivation — library-scale economics

The contextual scheduler (`src/rogue/reproduce/ladder_priors.py`) scores every technique in the repertoire on every ladder call. Today the ladder holds ~28 strategies; that is cheap. As the self-growing repertoire compounds toward hundreds or thousands of techniques, scoring all of them per call becomes the dominant cost. The Technique Retrieval System changes per-run complexity from O(all techniques) to O(K), where K is a small retrieved set.

The key economic insight is that this is a two-step problem: "which techniques are worth considering at all?" (candidate generation) is a different and cheaper question than "which of those to try first?" (ranking). The retriever answers the first question using semantic similarity over precomputed embeddings; the scheduler answers the second using historical breach rates, vendor-conditioning, and the full ATP scoring stack. Separating them means the expensive scheduler logic runs on a tight, relevant field rather than the whole library.

**The purpose is NOT to raise ASR.** It is to prevent the scheduler from wasting evaluation budget on techniques that are structurally incompatible with a target (e.g. image-modality techniques against a text-only model). The headline KPI is retrieval quality: **Recall@50 ≥ 80% of eventual winners** at **>90% cost/latency reduction** vs scoring all techniques.

---

## Architecture

```
target (DeploymentConfig / target_model)
    │
    ▼
┌───────────────────────────────────┐
│  build_target_fingerprint()       │  src/rogue/retrieval/target_fingerprint.py
│  → TargetFingerprint              │  (vendor, family, modality caps, known_successes)
└───────────────────────────────────┘
    │  embed_fn(text) → 1536-d vec
    ▼
┌───────────────────────────────────┐
│  TechniqueRetriever.retrieve()    │  src/rogue/retrieval/retriever.py
│  pgvector cosine top-K            │  technique_embeddings table (migration 0026)
│  floor = MIN_K = 25              │
└───────────────────────────────────┘
    │  list[RetrievalResult]  (label, score, rank)
    ▼
┌───────────────────────────────────┐
│  contextual scheduler             │  src/rogue/reproduce/ladder_priors.py
│  order_by_blend() / ranker        │  (ATP cross-tier + vendor-conditioned scoring)
└───────────────────────────────────┘
    │
    ▼
  escalation ladder (src/rogue/reproduce/escalation_ladder.py)
```

The retriever answers **which techniques at all?** The scheduler answers **which technique first?** Those are separate responsibilities on purpose — the retriever is stateless over the breach history; the scheduler is the telemetry consumer.

---

## The candidate-generator vs ranker distinction

This distinction is the load-bearing design decision. Every prior piece of the ATP stack (viability scores, starvation-adjusted EV, contextual priors, cross-tier ordering) is a **ranker** — it decides the order of a fixed set. The retriever is the layer *before* the ranker: it decides the **set**. Adding a ranker when the library is small costs nothing; the value of the ranker is eroded if it must process thousands of irrelevant candidates first. The retriever is the O(N) → O(K) gate.

The practical consequence: switching the retriever on (via `ROGUE_RETRIEVAL_TOPK`) narrows the candidate set passed to the scheduler, but it must never change outcomes for techniques the scheduler would have ranked highly anyway. That correctness property is enforced by the `MIN_K` floor (see below) and validated by the Recall@K gate before activation is enabled.

---

## Components and file map

| Component | File | Role |
|---|---|---|
| `TechniqueProfile` | `src/rogue/schemas/technique_profile.py` | Pydantic wire type for a technique's retrieval-optimised view (label, family, description, steps, modalities, historical targets) |
| `TargetFingerprint` | `src/rogue/schemas/target_fingerprint.py` | Pydantic wire type for a target's capability profile (vendor, model_family, capability flags, known_successes) |
| `build_target_fingerprint` | `src/rogue/retrieval/target_fingerprint.py` | Assembles a `TargetFingerprint` from a `target_model` string; reads `model_specs` for capability flags; queries `ladder_attempts` for `known_successes` when a session is provided |
| `build_technique_profiles` | `src/rogue/retrieval/technique_profile_builder.py` | Builds one `TechniqueProfile` per ladder strategy label from three sources: ARMS strategies (no DB), tier labels (no DB), harvested strategies (requires session); telemetry coverage ensures every observed winner gets a profile |
| `TechniqueRetriever` | `src/rogue/retrieval/retriever.py` | pgvector cosine top-K over `technique_embeddings`; enforces `MIN_K=25`; returns `list[RetrievalResult]` sorted by descending similarity; `score = 1 - cosine_distance` |
| `build_technique_embedding_text` | `src/rogue/retrieval/embedding_text.py` | Deterministic text serialisation of a `TechniqueProfile` for the embedding call (label, family, principle, description, steps, modalities, historical_targets in fixed order) |
| `build_target_embedding_text` | `src/rogue/retrieval/embedding_text.py` | Deterministic text serialisation of a `TargetFingerprint` (target_key, vendor, family, modality caps, context_length, reasoning_model, known_successes) |
| `default_embed_fn` | `src/rogue/retrieval/embed.py` | Returns a live OpenAI `text-embedding-3-small` callable (lazy client construction — no API key at import time) |
| `deterministic_embed_fn` | `src/rogue/retrieval/embed.py` | Offline, reproducible SHA-256-seeded unit-normalised embedding; used in tests and shadow mode to avoid API spend |
| `evaluate_recall` | `src/rogue/retrieval/evaluation.py` | Offline Recall@K measurement replaying `ladder_attempts` telemetry against the retriever |
| Shadow mode hook | `src/rogue/reproduce/escalation_ladder.py:_record_retrieval_shadow` | Called post-ladder when `ROGUE_RETRIEVAL_SHADOW=1`; writes one `RetrievalMetric` row per winner; pure side-channel, never alters execution |

The `rogue.retrieval` package re-exports all public symbols from the submodules above. Import via `from rogue.retrieval import TechniqueRetriever, TechniqueProfile, TargetFingerprint, build_target_fingerprint, build_technique_profiles, evaluate_recall`.

---

## Data model (migration 0026)

Migration `src/rogue/db/migrations/versions/0026_technique_retrieval_tables.py` creates three tables.

**`technique_embeddings`** — one row per ladder strategy label (the retrieval key). Stores the serialised `TechniqueProfile` and its 1536-d embedding. Primary key is `label` (e.g. `"crescendo"`, `"image:mml:wr"`). The `embedding` column carries an ivfflat cosine ANN index (`lists=100`). Schema owner: `src/rogue/db/models.py:TechniqueEmbedding`.

| Column | Type | Notes |
|---|---|---|
| `label` | `String(80)` PK | Ladder strategy label; matches `ladder_attempts.entity_id` |
| `technique_id` | `String(40)` nullable | Strategy ULID when available |
| `embedding` | `Vector(1536)` nullable | text-embedding-3-small 1536-d vector; ivfflat cosine index |
| `profile` | `JSON` | Serialised `TechniqueProfile` dict |
| `modalities` | `JSON` | List of modality strings (denormalised for fast filtering) |
| `version` | `String(20)` nullable | Schema version tag |
| `created_at` | `DateTime(tz)` | Populated on insert |

**`target_embeddings`** — one row per target (the `target_model` string as primary key). Stores the serialised `TargetFingerprint` and its 1536-d embedding. Same ivfflat cosine index as above. Schema owner: `src/rogue/db/models.py:TargetEmbedding`.

| Column | Type | Notes |
|---|---|---|
| `target_key` | `String(100)` PK | `target_model` string, e.g. `"anthropic/claude-haiku-4-5"` |
| `embedding` | `Vector(1536)` nullable | ivfflat cosine index |
| `fingerprint` | `JSON` | Serialised `TargetFingerprint` dict |
| `version` | `String(20)` nullable | Schema version tag |
| `created_at` | `DateTime(tz)` | Populated on insert |

**`retrieval_metrics`** — append-only shadow-mode telemetry, one row per (run × winner). Records how the retriever would have ranked the technique that actually won, enabling offline Recall@K measurement before the retriever drives execution. No hard foreign keys (analytics-only). Schema owner: `src/rogue/db/models.py:RetrievalMetric`.

| Column | Type | Notes |
|---|---|---|
| `id` | `BigInteger` autoincrement PK | |
| `run_id` | `String(40)` | Sweep run identifier |
| `parent_id` | `String(40)` | `AttackPrimitive` ULID |
| `target_key` | `String(100)` | Target model string |
| `label` | `String(80)` | Winning technique label |
| `retrieved_rank` | `Integer` nullable | 1-based rank the retriever gave the winner; NULL if winner was not in top-K |
| `winner_rank` | `Integer` nullable | 1-based rank the winner executed at in the actual ladder |
| `retrieval_hit` | `Boolean` | True iff the winner was within the retrieved top-K |
| `k` | `Integer` | The K used for this measurement |
| `created_at` | `DateTime(tz)` | |

---

## Embedding stack

The system reuses the existing ROGUE embedding stack rather than introducing a second embedding dimension or provider. Embedding model: **OpenAI text-embedding-3-small**, 1536 dimensions (the same model and dimension used by the dedup layer in `src/rogue/dedupe/embeddings.py`). Storage: pgvector `Vector(1536)` with ivfflat cosine ANN index on both `technique_embeddings` and `target_embeddings`. The query shape mirrors the dedup lookup: `cosine_distance` ascending, `limit K`, filtered to non-null embeddings.

The `embed_fn` dependency is injected into `TechniqueRetriever.__init__` so the module is testable offline. Tests and shadow-mode use `deterministic_embed_fn()` (SHA-256-seeded, unit-normalised, no network). Production index builds use `default_embed_fn()` (live OpenAI call, costs money — treat like a harvest or reproduce call, never run on a loop).

---

## MIN_K floor

`TechniqueRetriever.MIN_K = 25`. If the caller requests fewer than 25 candidates, the retriever silently returns 25. The rationale is safety for early-stage targets: when a target has little or no telemetry, the contextual scheduler has sparse breach rates and may not rank the eventual winner near the top. Capping retrieval too tightly in that regime can permanently strand a technique — a technique that is never surfaced to the scheduler is never tried, so its true performance is never measured. Over-retrieval is cheap (the scheduler re-ranks in memory); under-retrieval is irreversible (a missed winner is a missed graduation). The MIN_K floor is therefore a structural safeguard, not a performance knob.

---

## Offline Recall@K evaluation

The correctness gate before activation. The `evaluate_recall` function (importable from `rogue.retrieval`) replays historical `ladder_attempts` telemetry: for each (run × parent × target), take the actual winning technique label and ask "would the retriever at top-K have included this label in its candidate set?" The aggregate is Recall@K: the fraction of past winners that would have been retrieved. The KPI gate for enabling activation is **Recall@50 ≥ 80%**.

The evaluation is deliberately offline — it reads existing `ladder_attempts` (winner rows from `is_winner=True`) and `technique_embeddings` (requires the index to be built), and produces a single number without running any new ladder attempts or spending on embeddings beyond what the index already holds.

---

## Shadow mode

Shadow mode logs what retrieval *would* pick without changing ladder execution. It is the measurement instrument for Recall@K in a live system.

**Activation:** set `ROGUE_RETRIEVAL_SHADOW=1` before running a reproduce sweep. The hook `_record_retrieval_shadow` in `src/rogue/reproduce/escalation_ladder.py` is called after each parent's ladder returns. It builds a `TargetFingerprint` for the winning target, runs `TechniqueRetriever` over it, and writes one `RetrievalMetric` row recording `retrieved_rank` and `retrieval_hit` for the actual winner. The whole call is wrapped in `try/except` by the caller — retrieval errors can never break a ladder run.

**What it measures:** `retrieval_hit = (winner was in top-K)`. After enough shadow runs, `sum(retrieval_hit) / count(retrieval_metrics)` is the live Recall@K — not a replay, but the retriever's actual performance on the current index against the current repertoire.

**It does not change ladder execution.** Techniques run in exactly the same order, with the same early-stop semantics, whether shadow mode is on or off. Shadow mode is a pure side-channel.

---

## Activation roadmap (Weeks 5/6/7 — deferred this session)

Activation means passing the retriever's top-K to the scheduler instead of the full technique set, which changes which techniques are evaluated. This is the step that goes from "measuring" to "operating" the retrieval system.

**Activation env var:** `ROGUE_RETRIEVAL_TOPK`. Default `"0"` (disabled). Setting it to a positive integer (e.g. `"50"`) enables activation: the ladder only considers the top-K retrieved techniques. The shadow mode still logs even when activation is disabled, measuring the K=`_SHADOW_DEFAULT_TOPK` (50) floor.

**Gate:** activation is only safe once `evaluate_recall` confirms Recall@K ≥ 80% on the current telemetry. Activation before the gate passes risks silently dropping real winners. The gate is cheap to run (read-only, no API spend); the decision to flip `ROGUE_RETRIEVAL_TOPK` from `0` to `50` is a deliberate ops choice, not a code change.

**Weeks 5/6/7 plan summary:**
- Week 5: shadow mode accumulates data; offline `evaluate_recall` confirms recall gate.
- Week 6: activation enabled at K=50; monitor for recall regression after each harvest cycle.
- Week 7: tune K downward (K=35, K=25) if recall holds, unlocking the full cost reduction.

---

## Explicit non-goals

The following are explicitly out of scope for the Technique Retrieval System and will not be built as part of it:

- Thompson sampling, bandits, reinforcement learning, or any online-learning update to the retrieval index.
- Evolutionary search or LLM-generated rankings of techniques.
- A separate embedding dimension, vector DB, or provider beyond the existing pgvector/OpenAI stack.
- Automatic index rebuilds on a timer or cron (index builds cost money — run deliberately via `build_technique_profiles` + an embedding call, the same discipline as reproduce sweeps).
- Synthetic technique generation or augmentation of the technique library.
- Any modification to the five-layer pipeline architecture (§3 of `ROGUE_PLAN.md`), the frozen taxonomy (§13 non-goal), or the contextual scheduler's scoring logic.

The retrieval system is purely additive: it sits in front of the scheduler and narrows the candidate set. It never changes what a technique *is*, what a breach *means*, or how the scheduler *ranks*.
