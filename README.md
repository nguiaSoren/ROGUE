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

## MCP integration

ROGUE exposes its threat-intelligence database as a **producer-side MCP server** — Claude Desktop / Cursor / Windsurf users can query the live breach matrix from inside their IDE.

### Hosted — zero setup (recommended)

The MCP server is mounted into the live API, so there's nothing to clone or run:

```
https://rogue-api-mr5w.onrender.com/mcp/
```

- **From the dashboard:** the [home page](https://rogue-eosin.vercel.app) has **Add to Cursor** / **Add to VS Code** one-click buttons + a copy-URL.
- **Claude Desktop:** Settings → Connectors → Add custom connector → paste the URL.

It's read-only (the five query tools below). For local development against your own DB, use the one-command installer instead:

### Install locally (one command)

```bash
uv run python scripts/install_mcp.py           # Claude Desktop (default)
uv run python scripts/install_mcp.py --client cursor    # or: cursor / windsurf
```

This detects the client's config path for your OS, merges in the `rogue` server entry pointing at this checkout (preserving every other key/server), and backs up the old file first. It's idempotent and refuses to touch a config it can't parse. Then fully restart the client. Add `--dry-run` to preview the merge without writing.

> **Reviewer flow (any MCP client):** clone the repo → `uv run python scripts/install_mcp.py` (writes the pointer at *your* clone's path) → restart the client. No manual JSON editing. ROGUE is a standard MCP server, so any compliant client works — the installer just covers Claude Desktop / Cursor / Windsurf out of the box; everything else can point at the same `uv … -m rogue.mcp_server.server` command (stdio) or the HTTP endpoint on :8001 (see [Transport](#transport)).

<details><summary>Or edit the config by hand</summary>

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

Replace the `--directory` path with your local repo location.

</details>

Requires a populated DB (`scripts/harvest_once.py` + `scripts/reproduce_once.py` ran at least once); the deployed build reads the live Neon DB.

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

**Stdio** by default (the Claude Desktop path) — the server runs as a subprocess Claude Desktop spawns, logging to stderr so the JSON-RPC channel on stdout stays clean.

For **remote** clients (Cursor / Windsurf / a hosted client), serve the same five tools over HTTP on a dedicated port (8001, alongside the FastAPI dashboard on 8000):

```bash
ROGUE_MCP_TRANSPORT=streamable-http uv run python -m rogue.mcp_server.server
# serves http://127.0.0.1:8001/mcp  (set ROGUE_MCP_HOST=0.0.0.0 to expose off-box)
```

`ROGUE_MCP_TRANSPORT` accepts `stdio` | `sse` | `streamable-http`; `ROGUE_MCP_PORT` / `ROGUE_MCP_HOST` override the bind address.

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

## Architecture

See `docs/architecture.md` for the five-layer pipeline diagram + locked stack table.

## Capabilities

- 15-family attack taxonomy (OWASP LLM Top 10 + MITRE ATLAS aligned) — see `docs/taxonomy.md`
- 14-slot payload-template vocabulary for cross-deployment reproduction
- 15-source open-web harvest list — see `docs/sources.md`
- 5-model target panel (GPT-5.4 Nano, Claude Haiku 4.5, Llama-3.1-8B-Instruct via OpenRouter, Mistral Small 4, Gemini 3.1 Flash-Lite) — deliberate vintage mix: 4 current cheap-tier models from each major lab + 1 older open-weight reliability anchor (the Llama slot) chosen for the role of "weakest-guardrails baseline" so the breach matrix has a comparison point against which the newer-model safety wins stand out.
- Judge-model verdict pipeline (REFUSED / EVADED / PARTIAL_BREACH / FULL_BREACH), human-validated on 50 blind-labeled rows — **2.56% false-positive breach rate (1/39), 0 missed breaches (0/11)**, plus **91.8% refusal-axis agreement on WildGuardTest** (n=196) (small samples — see [Judge calibration](#judge-calibration))
- Daily threat brief (markdown + JSON) + Slack webhook
- ROGUE-as-MCP-server: query the attack DB from Claude Desktop / Cursor / Windsurf
- **True multimodal red-team** — renders attacks as real images/audio and an autonomous escalation ladder (see below)

## Judge calibration

Every breach number ROGUE reports is ultimately an LLM verdict, so the entire matrix inherits the judge's error rate. "Trust the judge" is not good enough — so the judge is scored against **independent human labels**, not just spot-checked.

**The judge: calibrated primary, permissive fallback.** The primary judge is Claude Sonnet — the model the numbers below validate. But on the most harmful *full compliances*, Sonnet hits Anthropic's `refusal` stop-reason and returns empty, which would silently drop the single most severe breaches as ERROR. So a cell Sonnet refuses is re-graded by a permissive secondary judge (**DeepSeek V4 Flash** via OpenRouter, set by `JUDGE_FALLBACK_MODEL`) and the verdict is flagged `[JUDGE_REFUSED→…]` so the matrix shows which cells Sonnet wouldn't touch. A bake-off settled the roles: on the 50 human labels, **Sonnet (82% agreement, 0% false-negative breach) clearly beat DeepSeek V3.2 (68%, 45% FN) and V4 Flash (74%, 27% FN)** — so Sonnet stays primary, and the cheaper open model is used *only* where Sonnet refuses (where the alternative is no verdict at all). Those fallback verdicts are flagged and are **not** part of the human-calibration below, which validates Sonnet's grading. To keep the validated judge affordable, the rubric/system prompt is **prompt-cached** (charged at ~0.1× on every call after the first in a 5-min window), and an opt-in **Batch-API path** (`reproduce_once.py --judge-batch`, a further 50% off, latency-tolerant) grades a whole sweep in one batch. Cost ladder per judge call: **$0.011 → $0.0064 (caching) → ~$0.0032 (caching + batch)** — near Haiku's sticker, with the only validated judge.

**In-distribution — the false-positive breach rate.** 50 real reproduce rows were sampled from the live DB, **stratified across verdicts × models × families** — so the rare `partial_breach`/`full_breach` and the ambiguous `evaded` cases are represented, not just easy refusals — then the judge's verdict was hidden and the rows **hand-labeled blind** by the operator and scored with `scripts/run_calibration.py`. The number that matters for matrix credibility — *how often does the judge cry breach on a response a human cleared?* — is **2.56% (1 of 39** human-cleared responses), and it missed **0 of 11** human-labeled breaches (0% false-negative). Those 11 breaches include 3 `partial_breach` (the ambiguous breach class) and the cleared side includes 9 `evaded`, so the test did hit the hard middle where misses happen. **These are small samples** — 1/39 and 0/11 carry wide confidence intervals (the honest ceiling on the miss rate is roughly 1 in 4, not "never"); read them as *directional evidence the judge is conservative*, not precise rates. On the breach / no-breach axis the matrix reports, judge and human agree **98%** (49/50); exact 4-way agreement is 82% (`borderline` gate), the gap almost entirely the matrix-irrelevant `refused`↔`evaded` boundary (6 of 9 disagreements, both non-breaches).

**External validation — WildGuardTest.** The judge is scored against [WildGuardTest](https://huggingface.co/datasets/allenai/wildguardmix) (Allen AI) — ~1.7k responses labeled by independent human annotators. WildGuardTest annotates *response refusal* as a task separate from *response harm*, the same split ROGUE's verdicts make, so the judge is scored on two axes instead of being collapsed to safe/unsafe. Scored on the **human-annotated Test split only** — the Train split is GPT-4-labeled, and scoring against it would be the model-grades-model circularity this whole exercise exists to escape. One judge call per item; fully reproducible via `scripts/eval_wildguard.py` (seed-deterministic subset).

| Axis | Agreement with independent human annotators | n |
|---|---|---|
| **Refusal** — did the model cleanly decline? | **91.8%** | 196 |
| **Harm** — was the response harmful? (adversarial prompts) | 78.1% | 196 |

The **refusal axis (91.8%)** is the headline number: `REFUSED` ↔ human-labeled refusal is a 1:1 construct match, so this is a clean, independent agreement figure — the thing that converts "an LLM grades an LLM, trust us" into a measured claim.

The **harm axis (78.1%)** is reported with one honest caveat. Its disagreement is asymmetric — the judge **over-calls** harm (false positives ≫ false negatives) — but two distinct things sit inside that gap: (1) genuine judge over-eagerness, and (2) a *construct* difference — ROGUE's `breach` means *the attacker gained traction*, whereas WildGuard's harm label means *the response is harmful content*; a response can give partial traction without itself being harmful content. A re-run restricted to adversarial prompts only **ruled out** a benign-compliance sampling artifact (the harm number was unchanged), so the over-eagerness is real, not an artifact of the sample.

**Independent cross-check — StrongREJECT.** To probe whether the breach matrix runs *hot*, a second published grader — the **StrongREJECT** rubric autograder (arXiv [2402.10260](https://arxiv.org/abs/2402.10260); rubric copied verbatim from the reference implementation) — was run over 50 of ROGUE's own reproduce rows, stratified across verdicts and all five target models (`scripts/second_grader_pass.py`). StrongREJECT's headline finding is that automated graders *overstate* jailbreak success, so this is the adversarial test of ROGUE's numbers. It passes: the judge agrees with StrongREJECT **82%** of the time, and the **inflation delta is ≤ 0 at every threshold** across the grader's full 0.01–0.75 range (−16% at the most lenient cut, converging to 0% at the strictest — *never positive*). ROGUE's judge is, if anything, **more conservative** than StrongREJECT — the breach rates are not inflated by an over-eager grader. (Raw 0–1 scores are persisted per-item, so the threshold sweep is recomputed offline with no re-grading.) **Scope (n=50):** StrongREJECT grades *harmful-content effectiveness*, so this cross-check is strongest on the harmful-content families (≈ two-thirds of the rows). For the injection / agentic / prompt-leak families — `indirect_prompt_injection`, `tool_use_hijack`, `system_prompt_leak` — where a breach means *executing an injected instruction* or *leaking a prompt* rather than emitting harmful content, StrongREJECT's rubric is a looser fit, so the delta there is weaker evidence; the claim is scoped accordingly.

These two external checks point in apparently opposite directions — WildGuard's *harm* axis says the judge over-calls, StrongREJECT says it under-calls — and that is the honest, useful result: they measure different constructs (harmful *content* vs jailbreak *effectiveness*) at different strictness, and together they **bracket** ROGUE's judge from both sides. It sits stricter than a lenient effectiveness grader and looser than a strict harmful-content label — exactly where a *"did the attacker gain useful traction"* verdict should land. No single external tool flags the matrix as inflated.

All three checks are reproducible — `scripts/run_calibration.py` (in-distribution, against `tests/fixtures/judge_calibration_pairs.json`), `scripts/eval_wildguard.py`, and `scripts/second_grader_pass.py` — and the calibration runner enforces a locked ship/refine gate (`< 0.80` agreement → refine the rubric; `≥ 0.90` → ship).

## Multimodal red-team

A jailbreak a model refuses as typed text often succeeds as a *picture* of that text — the OCR/vision path is less safety-aligned than the text path. ROGUE turns harvested text attacks into **real images and audio**, sends them to vision/speech models, and judges the result. Five published techniques are reimplemented as **deterministic, black-box renderers** (no model weights, no diffusion, byte-for-byte reproducible):

| Technique | Source | What it renders |
|---|---|---|
| **Promptfoo** | promptfoo.dev | text → image (the baseline) |
| **MML** | arXiv 2412.00473 | payload obfuscated into the image (base64 / word-replace / rotate / mirror) + a "decode-this" linkage prompt |
| **VPI** | arXiv 2506.02456 | attack drawn as authoritative UI chrome (system banner / chat / dialog / low-contrast), optionally composited onto a screenshot you supply |
| **PolyJailbreak** | arXiv 2510.17277 | cross-modal split — benign expert-roleplay text + payload hidden in a benign worksheet image |
| **ARMs** | arXiv 2510.02677 | a 17-strategy taxonomy + multi-turn escalation (crescendo / actor / acronym) |
| **CoJ** | arXiv 2410.03869 | multi-turn edit-step decomposition — split a refused request into benign sub-queries that reconstruct it (delete-then-insert / insert-then-delete / change-then-change-back) |

**Multimodality is native to the pipeline, not bolted on.** When ROGUE harvests an attack, the extractor records its *modality* on the `vector` field (`multimodal_image` / `multimodal_audio` vs text). Reproduction reads that and **automatically renders a multimodal-native attack as an image/audio and sends it to vision/speech models — no flag, no human, no "try text first."** The renderer itself is auto-selected by attack family. So the moment a multimodal jailbreak shows up in the wild, ROGUE reproduces it multimodally on the next run.

For *text* attacks the panel refused, those techniques compose into an **autonomous escalation ladder** that tries transforms in order and **stops at the first that breaches**, spanning all three modalities:

1. **image** — the payload rendered as a picture (typographic → OCR → MML → VPI)
2. **CoJ** — a deterministic edit-step chain (delete-then-insert / insert-then-delete / change-then-change-back)
3. **structured-data** — the payload re-cast as a JSON/CSV/YAML/XML document whose directive field carries it
4. **audio** — the payload spoken in each acoustic style (fast / noisy / …) against speech-capable models
5. **multi-turn escalation** — planner-authored, run as three sub-strategies in order: **crescendo → actor_attack → acronym** (optionally with the final turn rendered multimodally)

Tiers 1–4 need **no planner**, so the ladder keeps working even when the escalation planner refuses to author an attack; the planner backbone also auto-falls-back to a less-aligned model. **Composition beats the parts** — a multi-turn escalation whose final turn lands as an MML image has scored `full_breach` on models (GPT-5.4 Nano, Gemini) that resisted either the escalation or the image alone.

The ladder runs either as a standalone pass (`synthesize_escalations.py --ladder`) or **inline inside reproduce** (`reproduce_once.py --escalate`, off by default): when on, any primitive the whole panel refuses is laddered right after its cells finish, bounded by `--escalate-max-spend`.

### Real-world carriers via Bright Data (§11.8)

The renderers can draw a synthetic image — but a multimodal attack is far more realistic composited onto a **real** image. When extraction sees a multimodal attack that describes its carrier (e.g. *"overlay on a bank-login screenshot"*), it records that as `media_query`. A pipeline step (`scripts/fetch_media_assets.py`) then uses **Bright Data** to fetch a matching real image — **SERP API** Google-Images search (`udm=2`) to find a candidate, **Web Unlocker** to download the bytes — and caches it under `data/media_cache/`. The reproduction layer composites the attack overlay onto that real carrier and sends it to the vision panel.

So Bright Data does double duty: it **discovers** the attacks (SERP + Web Unlocker + Web Scraper + Scraping Browser + MCP) *and* **sources the real images** the multimodal attacks are tested against. The fetch is cached (deterministic replays, no re-spend) and gated (`$`-billed, run deliberately). `harvest → extract (media_query) → fetch-media (Bright Data) → reproduce (composite)`.

## Pipeline CLI reference

The two `$`-billed driver scripts (run deliberately — they spend Bright Data + LLM credit and write the live DB). All flags are optional.

### `scripts/harvest_once.py` — harvest → extract → dedup → persist

```bash
uv run python scripts/harvest_once.py --since 1d
```

| Flag | Default | What it does |
|---|---|---|
| `--since` | `1d` | Harvest window (`1d`, `14d`, `6h`). |
| `--x-handles` | off | Comma-separated X handles to scrape this run (e.g. `elder_plinius`). X is **off by default** (BD's profile scraper is slow, ~5–15 min/handle); opt in per run. Pulls each handle's recent posts within `--since`; attached images are ingested and outbound links followed. Needs `BRIGHTDATA_X_POSTS_DATASET_ID`. |
| `--database-url` | `$DATABASE_URL` or local | Target SQLAlchemy URL. |
| `--extraction-model` | `$EXTRACTION_MODEL` / `anthropic/claude-haiku-4-5` | Provider-prefixed extraction model (system prompt is prompt-cached). |
| `--embedding-model` | `text-embedding-3-small` | OpenAI embedding model for dedup. |

Env toggles: `EXTRACTION_CONCURRENCY` (TPM-aware fan-out) · `HARVEST_INGEST_IMAGES=0` (disable multimodal image ingestion) · `MEDIA_INGEST_MAX_PER_DOC` (4) / `MEDIA_INGEST_MAX_TOTAL` (60) · `HARVEST_FOLLOW_LINKS=0` (disable post→link following).

#### Scraping a specific X account on demand (`--x-handles`)

X is the hardest source to scrape (brutal anti-bot), so it's **off by default** (`default_plugins()` omits it) — every other source still runs. Opt in for a run with `--x-handles`:

```bash
# scrape elder_plinius's recent posts (then extract/ingest-images/dedup/persist)
uv run python scripts/harvest_once.py --since 21d --x-handles elder_plinius
# multiple handles:
uv run python scripts/harvest_once.py --since 14d --x-handles elder_plinius,wunderwuzzi23
```

**How it works (the reliable path):** BD's *structured* X scraper (discover-by-profile-URL) times out / returns empty for these accounts, so `--x-handles` uses **`XViaUnlockerPlugin`**: it **SERP-discovers** `site:x.com/<handle> after:<date>` to find recent status URLs, then **Web-Unlocks each one** and parses the tweet text + `pbs.twimg` screenshots. Those flow through the same pipeline as any source — screenshots are **vision-read / ingested** (multimodal), outbound links **followed 1-hop**. Both SERP + Web Unlocker are fast (no async-snapshot poll), so there's no timeout to tune.

> **Caveat:** discovery is bounded by **Google's index of X**, which X heavily restricts — so very-fresh posts (last hours/days) may not be SERP-discoverable yet. For a *known-fresh* post, fetch it directly by URL (below).

- `--x-only` — harvest **only** the X handle(s), skipping the other 9 sources + the SERP discovery phase (fast, focused re-run; link-following stays on).

**For a known URL (the most reliable path — used for video-fresh drops):** grab the exact tweet by URL. Web Unlocker fetches a single X status page (text + screenshots) even when discovery returns nothing:

```bash
uv run python scripts/harvest_url.py --url "https://x.com/elder_plinius/status/<id>"
```

(`BRIGHTDATA_POLL_TIMEOUT_SECONDS` is still useful for Reddit's async snapshots, which *do* poll — see `.env.example`.)

`harvest_url.py` web-unlocks one URL, ingests its images (the jailbreak screenshots → vision-read), extracts + dedups + persists the primitive, and syncs to Neon — then prints a `--primitive-ids <id>` command to reproduce just that attack against the panel. (This is how a freshly-posted X jailbreak gets from tweet → breach-matrix cell.)

### `scripts/reproduce_once.py` — render → target panel → judge → persist

```bash
uv run python scripts/reproduce_once.py --primitive-limit 50 --judge-batch
```

| Flag | Default | What it does |
|---|---|---|
| `--primitive-limit N` | all | Cap how many primitives are reproduced — the top-N by `reproducibility_score` (a cost cap, **not** "the newest"). |
| `--only-unreproduced` | off | Incremental sweep: reproduce **only** primitives with no `breach_results` yet (the genuinely-new attacks), skipping everything already done. Off by default so re-grade / re-test runs still re-fire the corpus. |
| `--primitive-ids A,B,…` | — | Reproduce **exactly** the named primitive_ids (canonical or not) — overrides every other selection filter. For a focused demo of one specific attack against the panel. |
| `--n-trials N` | 5 | Trials per (primitive × config) — powers the bootstrap CI. |
| `--temperature T` | 0.7 | Target-model sampling temperature. |
| `--concurrency N` | — | Parallel target calls. |
| `--multimodal-only` | off | Only `multimodal_image` / `multimodal_audio` primitives, rendered as real image/audio (vision/audio configs only). |
| `--no-fetch-media` | off | Skip the §11.8 real-carrier fetch; render synthetic canvases instead. |
| `--persona NAME` | off | §10.7 PAP persona wrap (`'Expert Endorsement'`, …, or `random`) — the B side of the A/B. |
| `--synthesized-only` | off | Only `synthesized=True` rows (escalation/mutation children). |
| `--pair-max-iters N` | 0 | §10.7 PAIR: up to N iterative-attacker refinements per evaded/refused trial. |
| `--no-iterative` | off | Force `--pair-max-iters=0`. |
| `--escalate` | off | §10.8 inline auto-ladder for panel-wide refusals (COSTLY; bound with `--escalate-max-spend`). |
| `--escalate-max-spend USD` | none | Cap cumulative escalation spend. |
| `--escalate-n-trials N` | 1 | Trials per ladder variant × config. |
| `--escalate-planner-model` | Claude+fallback | Override the Tier-5 escalation planner backbone. |
| `--judge-batch` | off | Grade via the Anthropic **Batch API** (50% off + caching, latency-tolerant; baseline-only). |
| `--database-url` | `$DATABASE_URL` or local | Target SQLAlchemy URL. |

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
