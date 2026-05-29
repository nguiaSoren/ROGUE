# Architecture (locked)

Extracted from ROGUE_PLAN.md §3. Do not redesign during the build.

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

This is a real agentic loop, not "for query in queries: requests.get(query)". The DiscoveryAgent runs an epsilon-greedy bandit over a 32-query pool, learning per-query yield-per-dollar across daily runs (per ROGUE_PLAN.md §11.6, locked-as-committed 2026-05-24 PM — replaces the earlier "LLM-planning evolves Day 2" framing). Same agentic principle in extraction: `ExtractionAgent` chooses which schema fields to populate confidently and which to defer, with rationale stored.

## What the reproduce layer actually does (multimodal + escalation)

Layer 4 is more than "send text, judge the reply." Two build-time extensions (§10.7–§10.10) live *inside* the §3 architecture — they enrich Layer 4, they do not redesign the five layers:

- **True multimodal rendering.** `instantiator.render()` turns an attack into the modality its `vector` demands — text, a real **image** (typographic / OCR / MML / VPI / EXIF), spoken **audio** (TTS + acoustic styles), or **structured-data** (JSON/CSV/YAML/XML) injection — all deterministic renderers under `reproduce/modality_renderers/` (+ `structured_data.py`, `coj.py`). `target_panel` attaches image/audio as provider-specific content blocks, gated by per-model capability (`supports_image` / `supports_audio`). This is the real multimodal path that replaced the project's earlier text-only-pretending-to-be-multimodal stub.
- **Auto-escalation ladder.** A refused (EVADE-band) attack can be escalated through a 5-tier ladder that **stops at the first breach**: image renderers → CoJ edit-step decomposition → structured-data → audio → planner-authored multi-turn escalation (crescendo → actor_attack → acronym). Runs standalone (`synthesize_escalations.py --ladder`) or **inline in reproduce** (`reproduce_once.py --escalate`, bounded by `--escalate-max-spend`). Tiers 1–4 are planner-free, so the ladder works even when the escalation planner refuses; the planner backbone auto-falls-back to a less-aligned model.
- **Roadmap (§10.10).** A contextual Thompson bandit will reorder the ladder to try the likely-winning strategy first — the "how to break" counterpart to the harvest "what to harvest" bandit.

## What we deliberately do NOT do

- **No LangChain / LangGraph.** Adds an abstraction layer we fight more than benefit from.
- **No vector DB beyond pgvector.** Pinecone/Weaviate add a service.
- **No GraphQL.** REST endpoints, ~6 of them, FastAPI.
- **No streaming responses except SSE for the live feed.** Three lines in FastAPI, dashboard looks alive.
- **No fine-tuning.** Prompt engineering only.
