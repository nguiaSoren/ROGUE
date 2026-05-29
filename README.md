# ROGUE — Open-web LLM Threat Intelligence Agent
Real-time Open-web Generation of jailbreak Updates & Evaluation — Bright Data × LLM threat intelligence hackathon submission.

> Continuous red-team for production LLM deployments. Harvests new jailbreaks from
> the open web via Bright Data, reproduces them against your deployment configuration,
> ships a daily diff of which attacks now bypass your guardrails.

[![Demo](https://img.shields.io/badge/demo-live-brightgreen)](https://rogue-eosin.vercel.app)
[![Video](https://img.shields.io/badge/video-5min-blue)](#)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11-blue)](pyproject.toml)

## What ROGUE does

Five-layer pipeline: **Harvest → Extract → Dedupe → Reproduce → Diff.**

1. **Harvest.** 15 open-web sources fetched via 5 Bright Data products.
2. **Extract.** An LLM agent structures each fetched document into an `AttackPrimitive`.
3. **Dedupe.** pgvector cosine similarity clusters near-duplicate attacks.
4. **Reproduce.** Each canonical primitive runs against your `DeploymentConfig` × 5 trials.
5. **Diff.** A separate judge model verdicts each trial; daily diff shipped to Slack, MCP, dashboard.

## Live demo

- Dashboard: https://rogue-eosin.vercel.app
- Video walkthrough: TODO  <!-- TODO Day 4: YouTube/Loom link -->
- MCP server: configure Claude Desktop / Cursor to query ROGUE directly (see below)

## Quick start (local)

```bash
git clone https://github.com/<you>/rogue
cd rogue
cp .env.example .env  # fill in your keys
docker compose up -d
uv sync --extra dev   # or: pip install -e ".[dev]"
alembic upgrade head
python scripts/seed_demo_data.py
uvicorn rogue.api.main:app --reload
```

## Bright Data integration

ROGUE uses 5 Bright Data products end-to-end:

| Product | Used for |
|---|---|
| Web Scraper API | Reddit, X/Twitter, HuggingFace (pre-built scrapers) |
| SERP API | Novel-attack discovery via Google + Bing queries |
| Web Unlocker | arXiv, vendor blogs, MITRE ATLAS, OWASP |
| Scraping Browser | Fallback for JS-heavy sites without pre-built scrapers |
| MCP Server | DiscoveryAgent's primary tool surface (consumer); ROGUE also exposes its own MCP server (producer) |

### Self-tuning Bright Data SERP spend (online learning)

The discovery layer doesn't just *call* Bright Data SERP — it learns to use it
better over time. An ε-greedy multi-armed bandit (`src/rogue/harvest/bandit.py`)
maintains 36 candidate SERP queries across the 19 sources and picks the 10
highest-yield queries per daily harvest, where **yield = novel canonical attack
primitives per dollar of Bright Data spend**.

How a single harvest uses Bright Data:

1. **Plugin phase** — 8 source plugins fetch via the BD product best suited to
   each source (BD's Reddit Scraper for r/* listings, Web Unlocker for arXiv +
   blogs, Scraping Browser for JS-heavy archives).
2. **Bandit-driven SERP phase** — `bandit.select(k=10)` picks 10 queries; each
   is issued via `BrightDataClient.serp_search()`; returned URLs are deduplicated
   against plugin output (no double-spend); the rest are fetched via Web Unlocker.
3. **Per-arm reward** — for each picked arm, `bandit.record(arm_id, novel,
   cost_usd)` updates the persisted state in `data/discovery_bandit.json` with
   the real per-arm BD spend and the count of net-new canonical primitives the
   arm surfaced.

Concrete per-harvest economics:

- ~16 SERP calls (6 from plugins + 10 from bandit) ≈ **$0.024 in SERP credit**
- ~10-100 follow-on Web Unlocker fetches ≈ **$0.025–$0.25 in fetch credit**
- **Total: $0.05–$0.30 in Bright Data spend per daily harvest**, allocated by
  online learning

The `/feed` dashboard widget surfaces the live top-3 / bottom-3 arms by
`mean_yield` (novel primitives per dollar) with provenance fields
(`seeded_from_corpus_at` / `last_live_pulled_at`) so the warm-prior baseline is
honestly distinguished from live observation. See `docs/bandit_for_humans.md`
for a plain-English explainer of how the bandit works.

## Dashboard

The dashboard is a Next.js 16 + React 19 + Tailwind v4 app under `frontend/`.
Designed for a 5-second pitch and a 5-minute deep-dive: the cinematic home
page lands the value prop; `/feed`, `/matrix`, `/brief` provide the depth.

### `/` — cinematic home (7 sections, top-to-bottom)

1. **Cinematic hero** — full-viewport opener with rotating-word headline
   (*"jailbroken → prompt-injected → role-played → escalated"*), hero stat
   trio pulled live from `/api/health`, and a single high-contrast CTA.
2. **Aha moment** — freshest 48h attack ticker side-by-side with the
   `MiniMatrix` so visitors see real data within 2 scrolls.
3. **How ROGUE thinks** — 3-step narrative (HARVEST → REPRODUCE → DEFEND)
   with color-coded top borders and live counters per step.
4. **Augmentation showcase** — 5 large story cards (one per augmentation:
   bandit, persona, escalation, mutation, PAIR) each carrying a hero stat,
   mini chart, "what this is / why it matters" copy, and a `live`/`no data`
   badge.
5. **Augmentation Lab (interactive)** — pick a deployment config, toggle
   persona / escalation / mutation switches, watch the estimated breach
   rate animate as stacked colored segments. Uses real `max_delta` /
   `delta` / `pattern_matching_score` values from the §10.7 API.
6. **Bright Data spotlight** — 4 hero metrics (5 BD products in use, 19
   sources fanned out, novel-attacks-per-BD-$, 2-tier reliability), the
   per-product role breakdown, and the hover-pause sources marquee.
7. **Deep-dive cards** — links to `/feed`, `/matrix`, `/brief`.

### `/feed` — live attack feed

Headline KPIs, the §10.7 augmentation A/B strip, then a 3-column war room:
left ribbon (hot families + BD-product histogram), center attack list
(expandable rows with a **▶ play** button that streams the attack as a
3-phase ATTACKER → MODEL → JUDGE terminal replay), right sidebar with all
5 augmentation widgets. Every widget has a `?` icon that opens a "What
this is / Why it matters" panel — the canonical copy lives in one place
(`src/components/explainer.tsx` → `AUGMENTATION_COPY`) so the explanation
never drifts.

The bandit widget's arm rows each carry a CSS-only hover-card with
`pulls / novel-found / BD-spend / yield` and an ε-greedy explanation.

### `/matrix` — breach heatmap

14 attack families × 5 deployment configs. Click any red cell to see the
exact primitive that cracked it, with 95% bootstrap CIs. Column headers
carry the PAIR avg-iters-to-breach so the matrix and the §10.7
augmentation story stay tied together visually.

### `/brief` — daily threat brief

Executive snapshot (net Δ vs yesterday, top-3 worst new attackers,
recommended action), tier-count chips, then the full markdown brief with
`.md` and `.json` download buttons.

## MCP integration

ROGUE exposes its threat-intelligence database as a **producer-side MCP server** — Claude Desktop / Cursor / Windsurf users can query the live breach matrix from inside their IDE.

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows), then restart Claude Desktop:

```json
{
  "mcpServers": {
    "rogue": {
      "command": "uv",
      "args": [
        "--directory", "/absolute/path/to/ROGUE",
        "run", "python", "-m", "rogue.mcp_server.server"
      ]
    }
  }
}
```

Replace the `--directory` path with your local repo location. Requires Postgres running (`docker compose up -d`) and a populated DB (`scripts/harvest_once.py` + `scripts/reproduce_once.py` already ran at least once).

### Tools exposed

| Tool | Purpose |
|---|---|
| `query_attacks(family?, vector?, since_days?, limit?)` | Filter the attack-primitive corpus by family/vector/recency. Returns full primitive records with sources. |
| `query_diff(date_str?)` | Today vs yesterday breach diff — what's new, what's newly defended, per-tier counts. |
| `query_threat_brief(date_str?, format?)` | Full daily threat brief in markdown or JSON. Reads from `data/threat_briefs/` then falls back to live DB render. |
| `query_breaches_for_config(deployment_config_id, since_days?, limit?)` | Per-trial breach results for one customer deployment, with judge rationale + model-response excerpts. |
| `query_attack_detail(primitive_id)` | One attack's full record + its per-config breach aggregates (n_full / n_partial / n_refused / n_evaded). |

### Try it

After connecting, ask Claude:

> "What new attacks broke our customer support config in the last 24 hours?"

Claude will call `query_diff` + `query_breaches_for_config` and summarize.

### Transport

Stdio (the Claude Desktop default). The server runs as a subprocess Claude Desktop spawns. Logs to stderr so the JSON-RPC channel on stdout stays clean.

## Architecture

See `docs/architecture.md` for the five-layer pipeline diagram + locked stack table.

## Capabilities

- 14-family attack taxonomy (OWASP LLM Top 10 + MITRE ATLAS aligned) — see `docs/taxonomy.md`
- 14-slot payload-template vocabulary for cross-deployment reproduction
- 15-source open-web harvest list — see `docs/sources.md`
- 5-model target panel (GPT-5.4 Nano, Claude Haiku 4.5, Llama-3.1-8B-Instruct via OpenRouter, Mistral Small 4, Gemini 3.1 Flash-Lite) — deliberate vintage mix: 4 current cheap-tier models from each major lab + 1 older open-weight reliability anchor (the Llama slot) chosen for the role of "weakest-guardrails baseline" so the breach matrix has a comparison point against which the newer-model safety wins stand out.
- Judge-model verdict pipeline (REFUSED / EVADED / PARTIAL_BREACH / FULL_BREACH) with calibration
- Daily threat brief (markdown + JSON) + Slack webhook
- ROGUE-as-MCP-server: query the attack DB from Claude Desktop / Cursor / Windsurf

## Repository layout

```
src/rogue/         # Python package (schemas/, harvest/, extract/, dedupe/, reproduce/, diff/, mcp_server/, db/, api/)
docs/              # architecture, schemas, taxonomy, sources, budget — extracted from ROGUE_PLAN.md
tests/             # schema round-trip tests + golden fixtures
scripts/           # harvest_once.py, reproduce_once.py, seed_demo_data.py
frontend/          # Next.js dashboard (Day 3 scaffold)
ROGUE_PLAN.md      # master plan (3800+ lines)
```

## Built by

Soren Obounou Nguia — AI Systems Engineer; previously Grand-Prize winner at Yonsei University for LLM security tooling (GPTFuzz optimization), adversarial-ML research at AIM Intelligence (HWARANG red-team series).

## License

MIT. See `LICENSE`.
