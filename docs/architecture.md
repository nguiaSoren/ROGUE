# Architecture (locked)

Extracted from ROGUE_PLAN.md §3. Do not redesign during the build.

> This doc is the **research pipeline** architecture (harvest → extract → reproduce → diff). For the **product/platform** architecture — turning ROGUE into a SaaS platform (SDK + REST API + dashboard + MCP over one scan engine) — see `docs/platform/ARCHITECTURE.md` and its per-team docs (a design spec, not yet built).

## The five-layer pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 1 — HARVEST  (Bright Data, 5 products)                   │
│  • Web Scraper API: Reddit, X/Twitter, LinkedIn, HuggingFace    │
│    (pre-built scrapers, structured JSON, fastest path)          │
│  • SERP API: daily Google/Bing discovery queries for novel      │
│    attack terms across the open web                             │
│  • Web Unlocker: arXiv, GitHub READMEs, vendor blogs            │
│    (Anthropic, OpenAI, Lakera, Embrace The Red), MITRE ATLAS,   │
│    OWASP, Simon Willison                                        │
│  • Scraping Browser: fallback for JS-heavy / interactive sites  │
│    not covered by Web Scraper API (e.g. jailbreakchat archive)  │
│  • Bright Data MCP Server: DiscoveryAgent's primary tool        │
│    surface — agent calls serp_search, web_unlock, scrape_*      │
│    via MCP rather than direct HTTP                              │
│  Outputs: raw_documents table                                   │
└────────────────────────┬────────────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 2 — EXTRACT  (LLM agent, structured output)              │
│  • For each raw_document, run extraction prompt                 │
│  • Output: AttackPrimitive Pydantic object (§4.1)               │
│  • Filter classifier drops non-attack documents                 │
│  • LLM self-judgment reproducibility score (0–10)               │
│  Outputs: attack_primitives table                               │
└────────────────────────┬────────────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 3 — DEDUPLICATE                                          │
│  • Embed payload_template with text-embedding-3-small (1536d)   │
│  • pgvector cosine similarity > 0.92 → duplicate cluster        │
│  • Function-word JS divergence as cheap secondary check         │
│  Outputs: cluster_id, canonical flag on attack_primitives       │
└────────────────────────┬────────────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 4 — REPRODUCE  (the win)                                 │
│  For each canonical primitive × each DeploymentConfig:          │
│    DeploymentConfig = (target_model, system_prompt, tools)      │
│  • Render payload against the customer's system prompt —        │
│    modality-aware: text, OR a real image / audio render for     │
│    multimodal attacks (§10.8 renderers)                         │
│  • N=5 trials, temperature varied                               │
│  • Separate judge model scores: refused / evaded / partial /    │
│    full_breach (§10.2 rubric)                                   │
│  • Refused attacks → optional auto-escalation ladder (§10.8)    │
│  Outputs: breach_results table, breach_matrix view              │
└────────────────────────┬────────────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 5 — DIFF & ALERT                                         │
│  • today_breach_set vs yesterday_breach_set                     │
│  • Threat brief (markdown + JSON)                               │
│  • Severity scoring: family_weight × breach_rate × vector_wt    │
│  • Slack webhook for new HIGH/CRITICAL                          │
│  • ROGUE-as-MCP-server: query_attacks, query_diff,              │
│    query_brief, query_breaches_for_config                       │
│  Outputs: daily_threat_brief.{md,json}, Slack, MCP, dashboard   │
└─────────────────────────────────────────────────────────────────┘
```

## Stack (locked)

| Layer | Choice | Why |
|---|---|---|
| Language (backend) | Python 3.11 | Fastest path; every LLM SDK is Python-first; no Rust temptations |
| Web framework | FastAPI | Async, Pydantic-native, low ceremony |
| Schemas | Pydantic v2 | Required for OpenAI/Anthropic structured-output mode |
| Async orchestration | `asyncio` + `httpx.AsyncClient` | LangGraph adds complexity without payoff |
| Database | Postgres 17 + pgvector | Single store for attacks, breaches, embeddings, dedup |
| Queue | Postgres `LISTEN/NOTIFY` for jobs | One fewer service to host |
| Frontend | Next.js 16 (app router) + shadcn/ui + Tailwind | Vercel-native, terminal/CISO aesthetic |
| Charts | Recharts | Lightest weight that looks polished |
| LLM (extraction) | Claude Haiku or GPT-4o-mini | Cheap, reliable structured output |
| LLM (judge) | Claude Sonnet or GPT-4o | Quality matters; bounded cost |
| LLM (target panel) | OpenRouter + native APIs | Multi-model fanout, no self-hosting |
| Bright Data | Web Scraper API, SERP API, Web Unlocker, Scraping Browser, MCP Server | §6 |
| Hosting (frontend) | Vercel (free Hobby) | Live: rogue-eosin.vercel.app |
| Hosting (backend) | Render (free Web Service) | Live: rogue-api-mr5w.onrender.com |
| Hosting (database) | Neon (free Postgres 17 + pgvector) | Cloud DB the live site reads — see docs/deployment.md |
| Demo Slack | New workspace, one channel, one webhook | Throwaway |

**Locked decisions worth restating:**

- **Python, not Rust.** Anywhere. The Rust reflex eats 12 hours and produces nothing judges can see.
- **No self-hosted Llama.** Together/Groq endpoints.
- **One database, not a service mesh.** Postgres holds everything. No Redis, no Elasticsearch, no Kafka.
- **No authentication.** Demo customer hardcoded.
- **No mobile responsive.** Desktop only.
- **One customer.** The demo customer. Schema supports N; demo shows one.

## What the agent layer actually does

The harvest layer is built around a `DiscoveryAgent` that:

1. Reads discovery memory: previously-seen attack families, recent search queries that paid off, low-yield queries to retire.
2. Decides which 5–10 SERP queries to issue today (out of a pool of ~30 — see §5.3 of the plan).
3. Issues queries via the Bright Data MCP server (tools = `serp_search`, `web_unlock`, `scrape_browser_page`, `web_scraper_reddit_subreddit`, `web_scraper_x_user_posts`, `web_scraper_huggingface_discussion`).
4. For each result, decides whether to deep-fetch: pre-built Web Scraper for social sources, Web Unlocker for static blogs, Scraping Browser as fallback.
5. Updates discovery memory: which queries surfaced novel primitives, which sources are most prolific.

This is a real agentic loop, not "for query in queries: requests.get(query)". The DiscoveryAgent runs an epsilon-greedy bandit over a 52-query pool (39 original + 6 multimodal arms 2026-06-03 + 7 source-expansion arms 2026-06-04), learning per-query yield-per-dollar across daily runs (per ROGUE_PLAN.md §11.6, locked-as-committed 2026-05-24 PM — replaces the earlier "LLM-planning evolves Day 2" framing). Same agentic principle in extraction: `ExtractionAgent` chooses which schema fields to populate confidently and which to defer, with rationale stored.

**Persistent skip-cache (§11.7).** Where the bandit decides *which queries* to spend on, the cross-run `fetch_cache` table decides *which individual URLs not to re-pay for* — so re-running the harvest over many days stops re-spending on content it already took. Two tiers, keyed by URL:

- **Tier B (pre-fetch, saves Bright Data $):** skip the BD fetch entirely when the source's cheap freshness `version_token` is unchanged since last run — git blob SHA, arXiv `updated` date, Reddit `created:num_comments`, or HTTP `ETag`. Implemented for the per-URL sources that expose such a token.
- **Tier A (pre-extraction, universal, saves LLM $):** skip the LLM extraction when the fetched body's `content_hash` (`RawDocument.archive_hash`) is unchanged.

Every processed URL is recorded (including zero-yield ones — the worst to re-crawl), so the ledger grows monotonically across runs. This prunes cost *before* the fetch/extract spend; the pgvector dedup gate runs *after* and only stops a duplicate from being *stored*. Net: a daily (or 9-day) re-run pays only for **genuinely new or changed** URLs — unchanged ones are skipped, new ones are fetched, changed ones are re-fetched and re-extracted.

## Technique Retrieval Layer (additive — candidate-generator in the reproduce path)

This subsection documents an additive layer inside Layer 4 (REPRODUCE) that sits in front of the contextual scheduler. It does not change the five-layer pipeline shape or any decision in §3 or §13.

**What it does.** As the self-growing attack repertoire scales from ~22 techniques today toward hundreds, scoring every technique on every ladder call becomes the dominant per-run cost. The Technique Retrieval Layer changes this from O(all techniques) to O(K) by inserting a cheap semantic-similarity gate before the scheduler: given a target's capability profile, retrieve the K most relevant techniques first, then let the scheduler rank and order only those.

**Position in the reproduce path:**

```
target (DeploymentConfig)
    │
    ▼  [build_target_fingerprint]
TargetFingerprint (vendor, family, modality caps, known_successes)
    │
    ▼  [TechniqueRetriever — pgvector cosine top-K, MIN_K=25]
top-K technique labels  ←── technique_embeddings table (migration 0026)
    │
    ▼
contextual scheduler (ladder_priors.order_by_blend)
    │
    ▼
escalation ladder (escalation_ladder.py)
```

**Key distinction — candidate generator vs ranker.** The retriever answers "which techniques at all?" (candidate generation). The contextual scheduler answers "which technique first?" (ranking). These are kept separate because the retriever is stateless over breach history, while the scheduler is the telemetry consumer. The retriever narrows the field; the scheduler decides the order.

**Components.** All code lives under `src/rogue/retrieval/`. Schemas: `TechniqueProfile` (`src/rogue/schemas/technique_profile.py`) and `TargetFingerprint` (`src/rogue/schemas/target_fingerprint.py`). New DB tables (migration `0026`): `technique_embeddings`, `target_embeddings`, `retrieval_metrics`. Reuses the existing embedding stack: OpenAI text-embedding-3-small, 1536 dimensions, pgvector ivfflat cosine.

**Safety measures.** The `MIN_K=25` floor prevents under-retrieval for cold-start targets. A shadow mode (`ROGUE_RETRIEVAL_SHADOW=1`) measures retrieval quality without changing ladder execution. Activation (`ROGUE_RETRIEVAL_TOPK`) is **disabled by default** this session and is gated on Recall@50 ≥ 80% measured by `evaluate_recall` (offline Recall@K replay of `ladder_attempts` telemetry).

**Non-goal.** This layer does not raise ASR; it reduces per-run cost as the library scales. It introduces no new bandits, RL, LLM-generated rankings, or architectural changes to the scheduler, the escalation ladder, or any other layer.

Full design: `docs/retrieval.md`. Glossary entries: Technique Retrieval System, TechniqueProfile, TargetFingerprint, TechniqueRetriever, MIN_K, Recall@K, retrieval shadow mode, technique_embeddings / target_embeddings / retrieval_metrics.

## What the reproduce layer actually does (multimodal + escalation)

Layer 4 is more than "send text, judge the reply." Two build-time extensions (§10.7–§10.10) live *inside* the §3 architecture — they enrich Layer 4, they do not redesign the five layers:

- **True multimodal rendering.** `instantiator.render()` turns an attack into the modality its `vector` demands — text, a real **image** (typographic / OCR / MML / VPI / EXIF), spoken **audio** (TTS + acoustic styles), or **structured-data** (JSON/CSV/YAML/XML) injection — all deterministic renderers under `reproduce/modality_renderers/` (+ `structured_data.py`, `coj.py`). `target_panel` attaches image/audio as provider-specific content blocks, gated by per-model capability (`supports_image` / `supports_audio`). This is the real multimodal path that replaced the project's earlier text-only-pretending-to-be-multimodal stub.
- **Auto-escalation ladder.** A refused (EVADE-band) attack can be escalated through a 5-tier ladder that **stops at the first breach**: image renderers → CoJ edit-step decomposition → structured-data → audio → planner-authored multi-turn escalation (crescendo → actor_attack → acronym). Runs standalone (`synthesize_escalations.py --ladder`) or **inline in reproduce** (`reproduce_once.py --escalate`, bounded by `--escalate-max-spend`). Tiers 1–4 are planner-free, so the ladder works even when the escalation planner refuses; the planner backbone auto-falls-back to a less-aligned model.
- **Roadmap (§10.10).** A contextual Thompson bandit will reorder the ladder to try the likely-winning strategy first — the "how to break" counterpart to the harvest "what to harvest" bandit.

## Grammar Component Analysis (observational)

This subsection documents a measurement layer that is purely additive to the five-layer pipeline and to the frozen §3/§13 design decisions. It does not change `AttackFamily`, `AttackVector`, or any other locked taxonomy, and does not generate new attacks or spend on API calls.

**What it is.** An observational, $0, read-only predictive-power study that tests the hypothesis behind any Technique-AST or synthetic-generation roadmap: do grammar components — and their combinations — actually predict breach outcomes? The analysis labels each existing `AttackPrimitive` with structural `GrammarNode`s, joins those labels to breach outcomes from `breach_matrix`, and measures per-node lift and pairwise synergy with appropriate confound controls.

**Why it is needed before building.** Building a Technique-AST compositor (a system that assembles new attacks by combining structural grammar nodes) costs months of engineering. If grammar nodes do not independently predict breach — i.e., if knowing that a primitive has `AUTHORITY_FRAME` + `TRIGGER_BACKDOOR` does not move the breach probability beyond what `AttackFamily` already captures — then the whole premise of composition is empirically unfounded and the build should not happen. A null result saves months. A positive result (at least one cross-family node with FDR-significant lift that survives family stratification) validates the premise with real data before any engineering investment.

**Position in the architecture.** This is a measurement layer below Layer 2 (EXTRACT) and beside Layer 4 (REPRODUCE). It reads `attack_primitives` (from Layer 2) and `breach_results` (from Layer 4) but writes nothing back to either table. It uses a dedicated side table — `primitive_grammar_labels` (migration `0027`) — to store labels without touching the frozen schema.

**The `GrammarNode` layer vs `AttackFamily`.** `AttackFamily` (15 members, locked Day 0, §13 frozen) classifies *what* an attack attempts. `GrammarNode` (23 members) classifies *how* an attack is structurally constructed — derived from `payload_slots` keys (e.g. `authority_claim`, `trigger_phrase`, `exfil_destination`, `encoding_scheme`) and from `requires_multi_turn`. This is a deliberately different abstraction layer: a cross-family node like `AUTHORITY_FRAME` fires across `role_hijack`, `refusal_suppression`, `indirect_prompt_injection`, and `direct_instruction_override` — the cross-family firing pattern is what makes the signal non-circular and what would justify using nodes as composition primitives for a generator.

**Analysis unit.** The per-(primitive × target) outcome (~1540 pairs across ~298 primitives × ~6 configs) rather than the per-primitive level. The per-primitive ANY-breach base rate is ~0.79 in a 6-model panel, a ceiling that washes out all contrast. The per-(primitive × target) outcome has real spread and is the correct unit.

**Confound controls.** (1) Family collinearity: family-mirroring nodes (those derived directly from `family`) are flagged as near-circular and their lift is interpreted accordingly; Mantel–Haenszel stratification tests whether cross-family structural nodes show lift after controlling for `AttackFamily`. (2) Multiple comparisons: Benjamini–Hochberg FDR correction applied across all 23 per-node Fisher exact p-values. (3) Judge-version caveat: `breach_matrix` is graded by the v1/v2 judge (over-reports vs v3); all breach signals inherit that bias and are treated as v1/v2-baseline.

**File map.** `src/rogue/schemas/grammar_node.py` (enum + wire type) · `src/rogue/grammar/` (`dataset.py`, `labeler.py`, `stats.py`, `combinations.py`) · migration `0027` · `docs/research/grammar_efficacy.md` (full design + methodology).

## What we deliberately do NOT do

- **No LangChain / LangGraph.** Adds an abstraction layer we fight more than benefit from.
- **No vector DB beyond pgvector.** Pinecone/Weaviate add a service.
- **No GraphQL.** REST endpoints, ~6 of them, FastAPI.
- **No streaming responses except SSE for the live feed.** Three lines in FastAPI, dashboard looks alive.
- **No fine-tuning.** Prompt engineering only.
