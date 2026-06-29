<p align="center">
  <img src="assets/brand/png/logo-stacked.png" alt="ROGUE" width="300">
</p>

<h1 align="center">ROGUE: Red-team every way a high-stakes AI agent can fail</h1>
<p align="center"><b><i>The Red-Team That Never Sleeps.</i></b></p>
<p align="center"><sub>Independent, reproducible evidence of how an AI agent fails — <b>before</b> you ship it. Open-source, runs in 2 minutes, no vendor lock-in.</sub></p>

**ROGUE red-teams your AI agent against live open-web jailbreaks, grades each with a human-calibrated judge, and hands you signed, reproducible evidence — before you deploy.** Backed by **11,973 calibrated-judge trials across 8 production models**, with a counterintuitive measured finding: most *claimed* jailbreaks don't survive a real deployment — reproduction collapses **40% → 4%**.

ROGUE measures **every place a high-stakes AI agent can go wrong**: whether the **model** can be broken by a live jailbreak or prompt-injection, whether the **human oversight** around it is meaningful, and whether the **memory it accumulates** stays contained. Each is scored against an independent, continuously-refreshed standard and emitted as a reproducible **signed** record — and it closes the loop, **generating and verifying the fix** before you deploy (you own the runtime, so ROGUE never sits in your request path).

> ### ▶ See a real breach in 20 seconds — no key, no signup
> ```bash
> pip install rogue-live-redteam && rogue try
> ```
> A live **ATTACKER → MODEL → JUDGE** red-team in your terminal, then ROGUE's real measured breach rates across 8 production models. Then point it at **your own** deployment — `rogue scan --endpoint <your-api> --system-prompt <yours>` — for a scored report of exactly which attacks break it: the exact attack, your model's response, and a remediation hook for each finding.
>
> → **Full 5-minute walkthrough, clean machine to `report.html`:** [QUICKSTART.md](QUICKSTART.md)

[![Demo](https://img.shields.io/badge/demo-live-brightgreen)](https://rogue-eosin.vercel.app)
[![Trailer](https://img.shields.io/badge/%E2%96%B6%20trailer-watch-red)](https://youtu.be/pVOQYJvMC6w)
[![Dataset](https://img.shields.io/badge/%F0%9F%A4%97%20dataset-gated-yellow)](https://huggingface.co/datasets/soren19/rogue-attacks-2026-05)
[![Research](https://img.shields.io/badge/research-4_papers-b31b1b?logo=arxiv)](PAPERS.md)
[![Tests](https://img.shields.io/badge/tests-3026-brightgreen)](tests/)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)

> **📄 Research** — ROGUE's findings are **four papers**, each reproducible from this repo (frozen data + a script per result): open-web jailbreaks mostly don't reproduce in deployment (**40% → 4%**); a per-type judge gate reaching **91% human agreement** (top of field); evaluation *allocation* as a capability lever (**8/20 vs 0/20** candidates graduate, Fisher *p* = 0.003); and canary leakage from shared agent memory that tracks **alignment, not model size** (85% on a weak model). → **[PAPERS.md](PAPERS.md)**

> **🔒 Security & Trust** — ROGUE generates and verifies fixes but **never sits in your request path** — you own the runtime. Scans run **locally** against your own endpoint; your prompts, system prompts, and keys never leave your machine. Released data is **derived-only**, never raw scraped corpora ([RESPONSIBLE_RELEASE.md](RESPONSIBLE_RELEASE.md)). Found a security issue? [SECURITY.md](SECURITY.md).

## See it live

- **Dashboard:** https://rogue-eosin.vercel.app (live, deployed).
- **Trailer:** [watch the 45-second trailer on YouTube](https://youtu.be/pVOQYJvMC6w) (preview below).
- **Dataset:** [298 harvested attack primitives across 15 families](https://huggingface.co/datasets/soren19/rogue-attacks-2026-05) (the open-web-harvested slice of a 459-primitive live corpus), MIT-licensed and access-gated (defensive-research-only terms; see [`RESPONSIBLE_RELEASE.md`](RESPONSIBLE_RELEASE.md)).
- **In Slack:** point a Slack incoming webhook at ROGUE and the daily threat brief plus every new HIGH/CRITICAL breach post straight to your workspace (the platform integration also files findings to Jira). ROGUE comes to where your team already triages.

https://github.com/user-attachments/assets/355df07c-71a1-44e1-8146-e59d93187d24

## Why ROGUE

Other LLM red-teams run a *fixed* attack set you have to keep updating. ROGUE is the only one that does all of this together:

- **Harvests on a schedule.** New jailbreaks and prompt-injections pulled from 15 open-web sources on a recurring cron — **scraping is free and keyless** (scraper-agnostic, no scraper is a dependency; extraction runs on any LLM you choose, incl. a local one), so the threat DB keeps refreshing without manual runs. (The breach-rate measurements are periodic measured snapshots, re-run deliberately, not a continuously-updating number.)
- **Reproduces against *your* exact config.** Your model **and its system-prompt**, not a generic safety benchmark (tool-call scoping is on the roadmap).
- **Is queryable over MCP, both ways.** It *harvests* through MCP and *serves* results through its own MCP server, so you can ask "what breaches a model like mine?" from inside Cursor or Claude. No other red-team closes that loop.
- **Measures three surfaces, signed.** The **model** surface is deep and paper-backed; the **human approval gate** and the **shared skill-pool** are two further instruments at proof-of-concept scale. Each is scored against an independent answer key and emitted as a tamper-evident attestation.
- **Runs on the LLM you choose.** The judge and extraction models are configurable (`JUDGE_MODEL`): any provider or a local model (Ollama via `OPENAI_BASE_URL`), not locked to one vendor.

Each ingredient exists somewhere; **no competitor does the whole combination.** That is what makes ROGUE a continuous, queryable, multi-surface red-team rather than a one-off scan.

## Use it in 30 seconds

**What needs a key — straight answer:** the demo is genuinely keyless; scanning a *real* model needs that model's key, and grading/harvesting need an LLM you choose (any provider, or a local Ollama → ~$0). The open-web *scraping* is always free and keyless.

| Action | What it needs |
|---|---|
| `rogue try` | **Nothing** — mock target + keyless heuristic judge, fully offline |
| `rogue scan` | your **target model's** API key (the heuristic judge stays keyless) |
| `rogue scan --judge calibrated` | target key **+ a judge LLM key** |
| Harvest (clone the repo) | free, keyless **scraping** **+ an LLM extraction key** (any provider, incl. local) |

### See your first breach in 20 seconds (no key, no signup)
```bash
pip install rogue-live-redteam
rogue try        # 20s, offline, zero keys: real breach rates + a shareable card
rogue setup      # install the best free scraper (crawl4ai) — prep for harvesting from a repo clone
```
`rogue try` runs a live **ATTACKER → MODEL → JUDGE** red-team in your terminal, fully offline and zero keys, then overlays ROGUE's **real measured breach rates across 6 production text models + 2 audio targets** (11,973 calibrated-judge trials; the two audio targets are sampled lighter, ~185 trials each) and drops a shareable breach card:

<p align="center"><img src="assets/card/marketing/breach-card.png" alt="ROGUE breach card: mistral-small-2603, 668/2189 breached, calibrated judge" width="620"></p>

**Then scan _your_ model.** The target is *your own* deployment: any OpenAI-compatible **`--endpoint`** plus your real **`--system-prompt`** (that's what makes it a deployment red-team, not a bare-model test). Pass `--provider`/`--model` instead to hit a hosted model by name:

```bash
rogue scan --endpoint https://api.your-co.com/v1 --model your-model --system-prompt-file ./prompt.txt
rogue scan --provider openai --model gpt-5.4-nano --judge calibrated   # …or a hosted model by name
```

Every scan drops the same **shareable breach card** as `rogue try` (`--no-card` to skip), now with *your* model's real numbers.

- **Judge:** defaults to a **keyless heuristic** (no API key). `--judge calibrated` grades with the v3 LLM judge, and that one uses **your** judge key (e.g. `ANTHROPIC_API_KEY` / `JUDGE_MODEL`'s provider).
- **Attacks:** the scan fires a **bundled attack pack** (`--pack default|aggressive|compliance`), frozen at this release: fresh as of `pip install`, *not* live-updating. The continuously-harvested live corpus drives the hosted dashboard plus the [public corpus](corpus/); to run that live open-web harvest locally, use **`rogue setup`** (above) and see [Run the harvest free](#run-the-harvest-free-keyless-scraping).

Compare any model on the public **[leaderboard](https://rogue-eosin.vercel.app/leaderboard)**, or browse the measured **[attack corpus](corpus/)** (every attack tagged with *which models it actually breaches*, not an unverified prompt dump).

### Query ROGUE from your IDE (hosted MCP, zero setup)
The MCP server is mounted into the live API, so there is nothing to clone or run:

```
https://rogue-private.onrender.com/mcp/
```

The [dashboard home](https://rogue-eosin.vercel.app) has one-click **Add to Cursor** / **Add to VS Code** buttons; for Claude Desktop, add it as a custom connector. It exposes ~19 tools: read-only corpus/breach queries plus scan / report / benchmark actions. Full tool list and local install: [MCP integration](#mcp-integration) below.

### Get a scored report, locally, no account
The CLI and Python SDK run a full scan against your own target **today** and emit a scored report (`report.to_html()` / JSON from the SDK, plus a CISO-ready PDF via the report service) on the same engine as the dashboard, no signup, nothing to buy. A FastAPI `/v1` server (`POST /v1/scans` + OpenAPI spec) is included in the self-hosted stack (below) for programmatic access.

### Run it locally: the full app (dashboard + API)
Self-host the whole thing (Postgres + API + the Next.js dashboard) with one command. It migrates and seeds a **redacted snapshot of the real all-time breach matrix** on startup, so every surface is fully populated on first boot, no scan and no keys. (The attack payloads and model responses are redacted to `[redacted]`, exactly like the public site; the verdicts/rates are the real ones.)

```bash
git clone https://github.com/nguiaSoren/ROGUE && cd ROGUE
cp .env.example .env                                       # demo data needs no keys
docker compose -f docker-compose.full.yml up -d            # detached: ~30s to migrate, seed, and start
```

Open **http://localhost:3000**: `/feed`, `/matrix`, `/analytics`, and `/brief` run against your own local instance, no account and no hosted site required. (Follow startup with `docker compose -f docker-compose.full.yml logs -f`.)

**Fill it with *your* model's data.** ROGUE scans a **model endpoint** (any OpenAI-compatible API URL, your gateway or a hosted provider), not local files. The stack runs detached, so stay in the same terminal: install the `rogue` CLI on the host and point it at your endpoint with `--persist` so each result is written into the same DB the dashboard reads:

```bash
pip install rogue-live-redteam                            # the CLI, on the host (or: pip install -e . from this clone)
export ANTHROPIC_API_KEY=sk-ant-...                       # the judge that grades each response (or repoint JUDGE_MODEL)
rogue scan --endpoint https://api.company.com/v1 --model my-model --persist --config-name "my-bot"
# (writes to $DATABASE_URL; its local default already matches the stack's Postgres, so no config needed)
```

Then open **http://localhost:3000/matrix?config=my-bot**: the breach matrix scoped to *your* deployment. (The judge LLM costs API spend per scan; point `JUDGE_MODEL` at a local model, Ollama via `OPENAI_BASE_URL`, to keep it ~$0.)

**Want a dashboard that's *only* your data?** Bring the stack up with `SEED_DEMO=0` and the DB starts empty; then every surface (`/feed`, `/matrix`, `/analytics`, `/brief`) shows nothing but your own scans, no demo rows to filter past:

```bash
SEED_DEMO=0 docker compose -f docker-compose.full.yml up -d   # empty DB, detached
rogue scan --endpoint https://api.company.com/v1 --model my-model --persist --config-name my-bot
# → http://localhost:3000 (every surface is now 100% your data)
```

<details><summary><b>Just the backend API, no dashboard (for development)</b></summary>

Skip the frontend, bring up a plain Postgres and run the API with hot-reload:

```bash
git clone https://github.com/nguiaSoren/ROGUE && cd ROGUE
cp .env.example .env          # add your keys
docker compose up -d && uv sync --extra dev
uv run alembic upgrade head && uv run python scripts/ops/seed_demo_data.py
uv run uvicorn rogue.api.main:app --reload
```

</details>

### Scan your own model: the SDK
Install from PyPI for the `rogue` CLI + Python SDK, no clone needed (Python 3.11+):

```bash
pip install rogue-live-redteam
```

Scan any OpenAI-compatible target in three lines (plus a judge key, since ROGUE grades every response; see [`docs/SDK.md`](docs/SDK.md)):

```python
from rogue import Client
client = Client(
    endpoint="https://api.company.com/v1", api_key="sk-...",   # or Client(provider="openai")
    system_prompt="<your production system prompt>",           # red-team your REAL deployment, not a bare model
)
report = client.scan(pack="aggressive", budget=10.0)
print(report.summary()); report.to_html("scan.html")
```

…or from the CLI: `rogue scan --provider openai --pack aggressive --system-prompt-file ./system_prompt.txt` (`--system-prompt "…"` for inline; both also work with `--persist`). Pick your scrape backend and judge model in [`docs/harvest-backends.md`](docs/harvest-backends.md).

No API key handy? Clone the repo and run the offline demo (mocked target + judge → an HTML report): `PYTHONPATH=src python3 examples/sdk_quickstart.py`.

## Integrations

ROGUE meets your team where it already works:

| Surface | Status | What you get |
|---|---|---|
| **Your IDE** (MCP) | ✅ **Available now** · keyless | One config block in Claude Desktop / Cursor / Windsurf / VS Code; the editor's agent queries the live threat DB on the spot, read-only corpus/breach queries plus scan / report / benchmark action tools. `https://rogue-private.onrender.com/mcp` |
| **Your chat & tracker** (Slack + Jira) | ✅ Slack alerts now | Point a Slack incoming webhook (`SLACK_WEBHOOK_URL`) at ROGUE and the daily threat brief + new CRITICAL/HIGH breaches post to your workspace automatically. Jira findings file via the MCP action tools (`send_slack_alert` / `create_jira_ticket`). [Setup](docs/platform/integrations/slack-github-jira.md) |
| **API & SDK** (REST `/v1` + Python) | ✅ runs locally | The **Python SDK runs real scans today** against your own target (`pip install rogue-live-redteam`; `from rogue import Client`, see [`docs/SDK.md`](docs/SDK.md)). A FastAPI `/v1` server + OpenAPI spec ship in the self-hosted stack. |
| **Your CI** (GitHub Action) | ✅ shift-left gate | Add one `uses:` block to a `pull_request` workflow; ROGUE red-teams your deployment on every PR and **fails the merge on any HIGH/CRITICAL breach** (overridable). [Setup](docs/ci-action.md) |

### Gate your CI

Red-team your model on every pull request and block the merge on a HIGH/CRITICAL breach. Drop this into `.github/workflows/rogue-scan.yml`:

```yaml
- uses: nguiaSoren/ROGUE@v1
  with:
    endpoint: https://gateway.your-company.com/v1
    model: your-deployed-model
    system-prompt-file: prompts/production-system-prompt.txt
    fail-on: high
    api-key: ${{ secrets.ROGUE_TARGET_KEY }}
```

Inputs, fail policy, and the security note are in [`docs/ci-action.md`](docs/ci-action.md); a full copy-paste workflow is at [`examples/github-action/rogue-scan.yml`](examples/github-action/rogue-scan.yml).

## What ROGUE does

Five-layer pipeline: **Harvest → Extract → Dedupe → Reproduce → Diff.**

1. **Harvest.** 15 open-web sources via a fully scraper-agnostic fetcher (scraping is free/keyless, bring any scraper — none required; the extraction step calls an LLM you choose).
2. **Extract.** An LLM agent structures each fetched document into an `AttackPrimitive`.
3. **Dedupe.** pgvector cosine similarity clusters near-duplicate attacks, with surface-obfuscation canonicalization (leetspeak/homoglyph/zero-width/Unicode folds) so an attack clusters by *technique*, not by spelling: `1gn0r3 pr3v10us` and `ignore previous` land in one cluster instead of re-entering the corpus once per skin.
4. **Reproduce.** Each canonical primitive runs against your `DeploymentConfig` × 5 trials.
5. **Diff.** A separate judge model verdicts each trial; the daily diff ships to Slack, MCP, and the dashboard.

> **New to the codebase?** [`docs/PROJECT_STRUCTURE.md`](docs/PROJECT_STRUCTURE.md) maps every directory to its pipeline layer and the architecture doc that explains it.

## What ROGUE red-teams

ROGUE measures **every place a high-stakes AI agent can go wrong**: whether the agent can be **broken**, whether the **human oversight** around it is meaningful, and whether the **knowledge it accumulates** is safe. Each is scored against an independent, continuously-refreshed standard, and each is backed by a result rather than a claim:

- **The model.** Does a live jailbreak or prompt-injection break *your* deployment? The daily breach matrix replays open-web attacks against your model × system-prompt, graded by a [human-calibrated judge](docs/judge-calibration.md). Finding: most *claimed* jailbreaks don't even reproduce ([Open-Web Jailbreaks Mostly Don't Reproduce in Deployment](PAPERS.md)).
- **The human gate.** When a person "approves" an AI action, does that approval mean anything? ROGUE measures a reviewer's **false-approve rate** against an independent answer key — the rubber-stamping failure mode regulators now care about. *Early instrument, demonstrated at proof-of-concept scale (n=1)* ([oversight](PAPERS.md)).
- **The agent's memory.** Does a shared agent skill-pool leak one user's secrets to the next? ROGUE plants canaries in scrubbed skills and measures recovery: 85% leaked on a weak model despite an explicit never-reveal instruction. *Measured on a small canary set (wide, overlapping CIs) — an early result, not a benchmark* ([A Dead Call Cannot Leak](PAPERS.md)).

…and it **closes the loop (assurance-native remediation).** Finding a breach is half the job. ROGUE *generates* a verified mitigation (a system-prompt patch, a tool-permission scope, distilled fine-tuning data) and **re-tests it against the same live corpus to prove it actually closed the breach without over-blocking** (measured with the same calibrated judge). ROGUE generates and verifies the fix; **you own the runtime, so it never sits in your request path.**

One engine, one independent standard, the same operation each time: fire inputs at an AI decision-maker, capture what it does, score it against the standard, emit a reproducible signed record.

## Research

ROGUE's findings are written up as papers and posts. **[PAPERS.md](PAPERS.md)** is the index, and each entry links to its preprint plus the code and data *in this repo* that reproduces it.

- **Allocation Is a Capability-Growth Mechanism.** In a self-growing red-team, evaluation *allocation* is a capability lever, not an efficiency layer (8 of 20 starved candidates graduate vs 0 of 20; Fisher *p* = 0.003). · *arXiv `cs.CL`×`cs.CR`, preprint posting soon*
- **Calibrating LLM-as-Judge Breach Detectors.** One gate template ("engagement ≠ breach; consummation = breach") calibrates breach judges across classes, validated against human labels four ways. · *arXiv `cs.CL`×`cs.CR`, preprint posting soon*
- **Open-Web Jailbreaks Mostly Don't Reproduce in Deployment.** Most open-web jailbreaks don't survive as working carriers in deployment context, and a source's claimed rate carries no usable signal (Spearman −0.07). · *arXiv `cs.CL`×`cs.CR` (lead paper), preprint posting soon*
- **A Dead Call Cannot Leak.** Canary leakage from shared agent skill pools tracks *alignment*, not model size. · *arXiv `cs.CL`×`cs.CR`, also a workshop/blog candidate, posting soon*

## Deep dives

The mechanics behind the pipeline, each on its own page:

- **Scraper-agnostic harvest.** A `Fetcher` registry picks the best backend per capability (page fetch, JS render, search, PDF), so the *scraping* runs free and keyless out of the box and any scraper or proxy slots in behind one env var — none is a dependency (extraction calls an LLM you choose). Plus a self-tuning ε-greedy bandit that allocates harvest budget by yield (novel primitives per dollar). → [docs/harvest-backends.md](docs/harvest-backends.md)
- **Multimodal red-team.** Refused text jailbreaks become real images and audio via deterministic black-box renderers, climbing an autonomous escalation ladder that stops at the first breach. → [docs/multimodal.md](docs/multimodal.md)
- **Self-growing attack repertoire.** ROGUE harvests reusable *techniques*, not just payloads, classifying, routing, and graduating / retiring / resurrecting them on live breach evidence, with a governed renderer registry and grammar-driven planning (the planner-willingness finding: 22% → 100% by changing only the planner). → [docs/self-growing-repertoire.md](docs/self-growing-repertoire.md)
- **Judge calibration.** Every breach number is an LLM verdict, so the judge is validated against independent human labels four ways: in-distribution FP 2.56%, WildGuardTest harm 88.5%, StrongREJECT −26% inflation, JBB **89.3%** human agreement (3rd of 5 field classifiers, tied with the frontier LLM-as-judge baselines, reproducible from `data/calibration/`), up from a 70.3% v1 judge after a diagnosed recalibration. → [docs/judge-calibration.md](docs/judge-calibration.md)
- **Benchmark, coverage over time.** Frozen AdvBench / JBB goal sets run through ROGUE's own graduated ladder against a fixed target, to answer "is this month's ROGUE better than last month's?" (honest caveat: still N=1, pre-recalibration). → [docs/benchmark.md](docs/benchmark.md)
- **Dashboard tour.** A 5-second pitch and a 5-minute deep-dive: cinematic home, `/feed` war room (attacks replayed as ATTACKER → MODEL → JUDGE), `/matrix` breach heatmap, `/brief` threat brief. → [docs/dashboard.md](docs/dashboard.md)

## Capabilities

- 15-family attack taxonomy (OWASP LLM Top 10 + MITRE ATLAS aligned); see [`docs/taxonomy.md`](docs/taxonomy.md).
- 14-slot payload-template vocabulary for cross-deployment reproduction.
- 15-source open-web harvest list; see [`docs/sources.md`](docs/sources.md). Not a fixed set: add your own with a ~30-line plugin → [`docs/adding-sources.md`](docs/adding-sources.md).
- Target panel of 6 production text models (GPT-5.4 Nano, Claude Haiku 4.5, Llama-3.1-8B, Mistral Small, Gemini 3.1 Flash-Lite, Claude Opus 4.8) + 2 audio targets (sampled lighter): cheap-tier models per lab, an open-weight reliability anchor, a frontier reference, and audio endpoints for multimodal coverage.
- Judge-model verdict pipeline (REFUSED / EVADED / PARTIAL_BREACH / FULL_BREACH), human-validated four ways; see [Judge calibration](docs/judge-calibration.md).
- Daily threat brief (markdown + JSON) + Slack webhook.
- ROGUE-as-MCP-server: query the attack DB from Claude Desktop / Cursor / Windsurf.
- True multimodal red-team and a self-growing technique repertoire (see [Deep dives](#deep-dives)).
- Deterministic obfuscation augmentation: 10 labelled, zero-LLM-cost transforms (leetspeak, homoglyph, zero-width, fullwidth, zalgo + base64 / ROT13 / hex / Unicode-escape / HTML-entity decode-wraps) skin a defended attack to measure a **flip-rate-per-transform**, separating "the target pattern-matches the surface string" from "the target understands the technique."
- External benchmark layer against frozen AdvBench / JailbreakBench goal sets.

## Roadmap

- **Expand source coverage.** More source plugins bring the next ~100 open-web sources online.
- **Tool-aware scans.** Supply your agent's tool schemas so a reproduction exercises the full model × system-prompt × **tools** surface (today's scan covers model × system-prompt).
- **Break bandit.** A second, contextual Thompson-sampling bandit that learns *how to break* (which escalation strategy to try first per attack-family × target); the control surface and reward log are already built and instrumented in prod.

---

# Run it yourself

*Everything below is for builders: connecting ROGUE to your tools, running it locally, or driving the pipeline.*

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for the five-layer pipeline diagram and the locked stack table.

## MCP integration

ROGUE exposes its threat-intelligence database as a **producer-side MCP server**: Claude Desktop / Cursor / Windsurf users query the live breach matrix from inside their IDE.

**Hosted (recommended, zero setup).** The server is mounted into the live API at `https://rogue-private.onrender.com/mcp/`. Use the **Add to Cursor / Add to VS Code** buttons on the [dashboard home](https://rogue-eosin.vercel.app), or add it as a custom connector in Claude Desktop (Settings → Customize → add a custom connector → paste the URL). The hosted server exposes the read-only query tools **and** the action tools (validate / scan / report / benchmark + Level-3 workflow tools), ~19 in all.

**Local (against your own DB), one command:**

```bash
uv run python scripts/ops/install_mcp.py                  # Claude Desktop (default)
uv run python scripts/ops/install_mcp.py --client cursor  # or: cursor / windsurf
```

This detects the client's config path, merges in the `rogue` server entry pointing at your checkout (preserving every other key), and backs up the old file first. It's idempotent; `--dry-run` previews, `--uninstall` removes. Then restart the client. Requires a populated DB (run `harvest_once.py` + `reproduce_once.py` at least once); the deployed build reads the live Neon DB.

**Read-only query tools:** `query_attacks`, `query_diff`, `query_threat_brief`, `query_breaches_for_config`, `query_attack_detail`, `query_worst_attacks`. After connecting, ask Claude *"What new attacks broke our customer-support config in the last 24 hours?"* and it will call `query_diff` + `query_breaches_for_config` and summarize.

**Transport.** Stdio by default (the Claude Desktop path). For remote clients, serve over HTTP:

```bash
ROGUE_MCP_TRANSPORT=streamable-http uv run python -m rogue.mcp_server.server
# serves http://127.0.0.1:8001/mcp  (ROGUE_MCP_HOST / ROGUE_MCP_PORT override the bind)
```

## Run the harvest free (keyless scraping)

ROGUE's **scraping** is free and **fully scraper-agnostic** — a `Fetcher` registry picks the best backend per capability, so no scraper is ever a dependency. (The extraction step still calls an LLM you choose — see "what 'free' means, honestly" below.) One command sets up the best free scraper:

```bash
rogue setup
```

That installs **crawl4ai** plus its Chromium, and that's all most people need: it then auto-leads page fetch + JS render (clean markdown, stealth, unlimited). The harvest is **backend-agnostic** (a `Fetcher` registry picks the best backend per capability), so the rest of the free stack slots in automatically with no further config:

| Capability | Free backend | How |
|---|---|---|
| Page fetch + JS render | **crawl4ai** | `rogue setup` (clean markdown, stealth, **unlimited**) |
| Web + image search | **SearXNG** | self-host → `SEARXNG_URL` (70+ engines, unlimited) |
| PDF → markdown | **local_pdf** | always on (`pypdf` core; `rogue setup --pdf` upgrades it) |
| Zero-install fallback | **Firecrawl keyless** | auto-enabled when nothing else is configured (no account) |

Add **residential scale** with any cheap proxy (Webshare, IPRoyal, your own): one var, applied to all scrapers, `ROGUE_PROXY_URL=http://user:pass@host:port`. Full matrix + preference order: [`docs/harvest-backends.md`](docs/harvest-backends.md).

**Add your own backend.** A new backend (the ones above, or anything else: ScrapeGraphAI, context.dev, a house proxy, a paid SERP API) is a single `Fetcher` file plus one line in the preference order (`ROGUE_FETCHER_ORDER`). Sources, the harvest pipeline, and the scan never change. PRs welcome.

> **What "free" means, honestly:** the open-web *scraping* is free. The *extraction* and the *scan judge* still call an LLM; point them at any OpenAI-compatible endpoint (including a local **Ollama** model) to keep the whole loop ~$0.

## Bring your own LLM (including a local one)

ROGUE is **not locked to one model or API**. The target you scan, the extraction step (scraped page → attack primitive), and the judge (grades each response) are each a configurable `provider/model`: Anthropic, OpenAI, OpenRouter, Groq, Gemini, or an OpenAI-compatible local endpoint:

```bash
# Run the judge on a local model (Ollama); the OpenAI SDK honors OPENAI_BASE_URL:
JUDGE_MODEL=openai/llama3.1
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama
```

> **Honest caveat on a local judge:** ROGUE's judge is *calibrated*, and its verdict credibility (89.3% agreement vs human labels, the κ / SHIP gate in [`docs/judge-calibration.md`](docs/judge-calibration.md)) is validated against the **default** judge. A local/open judge is **uncalibrated** and tends to *under-report* breaches until you re-run the calibration harness (`scripts/calibration/`) against it. Free judge: yes. Trusted judge: re-calibrate first.

## Pipeline CLI reference

The two `$`-billed driver scripts spend LLM credit (plus whatever your chosen scrape backend costs, if any) and write the live DB, so run them deliberately. All flags are optional.

<details><summary><b><code>harvest_once.py</code>: harvest → extract → dedup → persist</b></summary>

```bash
uv run python scripts/harvest/harvest_once.py --since 1d
```

| Flag | Default | What it does |
|---|---|---|
| `--since` | `1d` | Harvest window (`1d`, `14d`, `6h`). |
| `--x-handles` | off | Comma-separated X handles to scrape this run (X is off by default; profile scraping is slow). |
| `--database-url` | `$DATABASE_URL` | Target SQLAlchemy URL. |
| `--extraction-model` | Claude Haiku 4.5 | Provider-prefixed extraction model (prompt-cached). |
| `--embedding-model` | `text-embedding-3-small` | Embedding model for dedup. |

Env toggles: `EXTRACTION_CONCURRENCY` · `HARVEST_INGEST_IMAGES=0` · `HARVEST_FOLLOW_LINKS=0`. For a single known-fresh URL, use `scripts/harvest/harvest_url.py --url "https://x.com/.../status/<id>"`.

</details>

<details><summary><b><code>reproduce_once.py</code>: render → target panel → judge → persist</b></summary>

```bash
uv run python scripts/reproduce/reproduce_once.py --primitive-limit 50 --judge-batch
```

| Flag | Default | What it does |
|---|---|---|
| `--primitive-limit N` | all | Cap how many primitives are reproduced (top-N by `reproducibility_score`). |
| `--only-unreproduced` | off | Reproduce only primitives with no `breach_results` yet. |
| `--primitive-ids A,B,…` | none | Reproduce exactly the named primitives (overrides other filters). |
| `--n-trials N` | 5 | Trials per (primitive × config), powers the bootstrap CI. |
| `--multimodal-only` | off | Only image/audio primitives, rendered as real media. |
| `--persona NAME` | off | PAP persona wrap (the B side of the A/B). |
| `--escalate` | off | Inline auto-ladder for panel-wide refusals (costly; bound with `--escalate-max-spend`). |
| `--candidate-quota N` | 0 | Reserve N guaranteed harvested-candidate attempts before early-stop (scheduler policy). |
| `--judge-batch` | off | Grade via the Anthropic Batch API (50% off + caching; baseline-only). |

`scripts/reproduce/candidate_quota_ab.py` runs the candidate-quota A/B (the empirical baseline for the break-bandit).

</details>

## Add your own source

ROGUE's sources are plugins, not a hard-coded list. To harvest from a forum, blog, repo, or feed it doesn't cover yet, write one `SourcePlugin` subclass: declare a `name`, a `source_type`, the `required_capabilities` it needs to fetch (e.g. `UNLOCK` for a page, `SERP` for a search), and an `async fetch_since(fetcher, since)` that returns `RawDocument`s. Your plugin owns *what the content means*; the injected fetcher owns *how the bytes arrive*. Register it in `default_plugins()` and the next harvest run extracts, dedupes, and reproduces from it like any built-in. Full walkthrough + a copy-paste example: **[`docs/adding-sources.md`](docs/adding-sources.md)**.

## Repository layout

```
src/rogue/     # Python package (schemas, harvest, extract, dedupe, reproduce, diff, mcp_server, db, api)
docs/          # architecture, schemas, taxonomy, sources, budget + the deep-dive pages
tests/         # schema round-trip tests + golden fixtures
scripts/       # harvest_once.py, reproduce_once.py, calibration/, ops/
frontend/      # Next.js dashboard
```

## Built by

Benaja Soren Obounou Lekogo Nguia, AI Systems Engineer; previously Grand-Prize winner at Yonsei University for LLM security tooling (GPTFuzz optimization).

## License

MIT. See [`LICENSE`](LICENSE).
