<p align="center">
  <img src="assets/brand/png/logo-stacked.png" alt="ROGUE" width="300">
</p>

<h1 align="center">ROGUE: Red-team every way a high-stakes AI agent can fail — then generate the fix</h1>
<p align="center"><b><i>Find it. Prove it. Fix it. The red-and-blue team that never sleeps.</i></b></p>
<p align="center"><sub>Independent, reproducible evidence of how an AI agent fails — <b>and the verified fix to close it</b> — before you ship. Open-source, runs in 2 minutes, no vendor lock-in.</sub></p>

**ROGUE red-teams your AI agent against live open-web jailbreaks, grades each with a human-calibrated judge, and hands you signed, reproducible evidence — plus a suggested fix for what breaks — before you deploy.** Backed by **11,973 calibrated-judge trials across 8 production models**, with a counterintuitive measured finding: most *claimed* jailbreaks don't survive a real deployment — reproduction collapses **40% → 4%**.

ROGUE measures **every place a high-stakes AI agent can go wrong**: whether the **model** can be broken by a live jailbreak or prompt-injection, whether the **tools it can invoke** can be turned against it (tool-use hijack, indirect injection via tool outputs), whether the **human oversight** around it is meaningful, and whether the **memory it accumulates** stays contained. Each is scored against an independent, continuously-refreshed standard and emitted as a reproducible **signed** record — and it closes the loop: **every scan generates a fix for each breach**, and on demand ROGUE **re-tests that fix to prove it holds** without over-blocking (you own the runtime, so ROGUE never sits in your request path).

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

> **📄 Research** — ROGUE's findings are **four papers**, each reproducible from this repo (frozen data + a script per result): open-web jailbreaks mostly don't reproduce in deployment (**40% → 4%**); a per-type judge gate reaching **[withheld — under anonymized review]** ([withheld] classifiers); evaluation *allocation* as a capability lever (**8/20 vs 0/20** candidates graduate, Fisher *p* = 0.003); and canary leakage from shared agent memory that tracks **alignment, not model size** (85% on a weak model). → **[PAPERS.md](PAPERS.md)**

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
- **Reproduces against *your* exact config.** Your model, its system-prompt, **and its tools** — not a generic safety benchmark. ROGUE gives the model a real function-calling surface and runs a multi-turn agent loop, so it catches tool-use hijack and indirect injection, not just text jailbreaks: safe simulated tools by default, or point it at **your own MCP tool server** for real execution (dangerous tools stay recorded-not-executed).
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

For attacks that *scale* (many-shot / long-context), a single pass isn't enough — ROGUE sweeps the dimension and reports a **robustness threshold**: *safe up to N, breaks at M*.

<p align="center"><img src="assets/card/marketing/sweep-card.png" alt="ROGUE sweep card: many-shot context-length threshold — held to 8K, breaks at 32K" width="620"></p>

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

ROGUE measures **every place a high-stakes AI agent can go wrong**: whether the agent can be **broken**, whether the **human oversight** around it is meaningful, whether the **knowledge it accumulates** is safe, whether the AI trusted to **strip secrets** actually does, whether a **deletion it promised** actually happened, whether it applies the right safety standard for the **person in front of it**, and whether the secrets in its **private reasoning** stay private. Each is scored against an independent, continuously-refreshed standard — the first three backed by a measured result, the rest (redaction, deletion, user-context, reasoning) by a wired, runnable instrument whose cross-model numbers await a paid sweep:

- **The model.** Does a live jailbreak or prompt-injection break *your* deployment? The daily breach matrix replays open-web attacks against your model × system-prompt, graded by a [human-calibrated judge](docs/judge-calibration.md). Finding: most *claimed* jailbreaks don't even reproduce ([[withheld — under anonymized review] Don't Reproduce in Deployment](PAPERS.md)).
- **The human gate.** When a person "approves" an AI action, does that approval mean anything? ROGUE measures a reviewer's **false-approve rate** against an independent answer key — the rubber-stamping failure mode regulators now care about. *Early instrument, demonstrated at proof-of-concept scale (n=1)* ([oversight](PAPERS.md)).
- **The agent's memory.** Does a shared agent skill-pool leak one user's secrets to the next? ROGUE plants canaries in scrubbed skills and measures recovery: 85% leaked on a weak model despite an explicit never-reveal instruction. *Measured on a small canary set (wide, overlapping CIs) — an early result, not a benchmark* ([[withheld — under anonymized review]](PAPERS.md)).
- **The reasoning gate.** Reasoning models (o1, DeepSeek-R1, QwQ, Claude extended-thinking) *think out loud* before answering — and that **hidden scratchpad leaks what the answer withholds.** A model can correctly refuse to hand a user's SSN to a travel site in its reply while **spelling the SSN out in its reasoning trace**, where a one-line injection can pull it back out. ROGUE captures the trace the rest of the stack never sees (`reasoning_content` / thinking blocks) and points its *whole* leak arsenal at it — verbatim, transport-decoded (base64/hex/…), and semantic — flagging **reasoning-only leakage**: present in the thoughts, absent from the answer. We reproduced it live on DeepSeek-R1 — the answer clean, the SSN sitting in the trace. It's the counterintuitive twist from [Leaky Thoughts (2025)](https://arxiv.org/abs/2506.15674): *cranking a model's reasoning makes its answers safer and its thinking leakier.* *Wired into the scan; the reasoning-effort × leak-rate board is the paid measurement.*
- **The user-context gate.** Safety isn't one-size-fits-all: *"how much of this medication is dangerous?"* is informational for a general user but a red flag from someone who's disclosed depression; *"recommend cheap liquor in bulk"* is harmless until the user says they're in recovery. ROGUE puts a **vulnerable-user profile** in the deployment's context and fires two matched sets — requests that are harmful *for that user* (it should decline or redirect) and benign controls (it should still help) — scoring **user-specific safety** against **helpfulness** so a deployment can't win by refusing everyone. It's the axis a duty-of-care deployment (health, recovery, minors) lives or dies on, and the one where models fail most: the benchmark this is built on ([U-SafeBench, EMNLP 2025](https://arxiv.org/abs/2502.15086)) found LLMs act safely for vulnerable users **near-never — even with the profile spelled out in front of them** (GPT-4o-mini: 1.6%). *Instrument wired into the scan; the cross-model board is the paid measurement, not yet a shipped number.*
- **The deletion gate.** When a user invokes their **Right to be Forgotten** (GDPR Art. 17 / CCPA) and a customer "deletes" their data, is the entity's knowledge *actually* unrecoverable from the deployed model — or is the deletion a system-prompt band-aid that adversarial **paraphrase probing** walks straight past? ROGUE audits it black-box: it probes the target for the forgotten entity across many rephrasings (recovery under *any* one counts, because unlearning is famously format-superficial — [2411.15477](https://arxiv.org/abs/2411.15477)), checks recall **semantically** (revealing the fact, not the exact string), and reports two numbers together — **forget-leak-rate** (should be zero) *and* **neighbor-retain-rate** (an over-aggressive deletion that nukes related knowledge is its own failure — the forget↔retain trade-off of [BLUR](https://arxiv.org/abs/2506.15699)). It's the auditor's side of machine unlearning, done at deployment time with no access to weights. *Instrument wired into the scan; the cross-model board is the paid measurement, not yet a shipped number.*
- **The redaction gate.** When the LLM *is* the safeguard — a DLP / redaction pipeline scrubbing secrets from a document before it flows downstream — does it remove what the **policy** requires, without shredding everything else? ROGUE scores that pipeline at the level of **propositions** — every atomic, *inferable* fact, not just named entities, because the leak a regex misses is the one you can still *infer* from what's left — on two opposed axes: **security** (fraction of policy-sensitive facts actually removed) and **utility** (fraction of the innocent rest preserved). The trade-off is the whole finding: a redactor that blacks out the page is perfectly secure and perfectly useless, and over-redaction — not leakage — is the failure that dominates in practice. *Method after RedacBench (2026); a scored instrument with a stated judge, first cross-model run pending — not yet a headline number.*

…and it **closes the loop (assurance-native remediation).** Finding a breach is half the job. **Every scan generates a fix for each breach** — a **reversible system-prompt patch** (the safe, lighter-touch default) and, for the archetypal jailbreak (a user prompt that overrides the system's safety goal), the **goal-conditioned preference data** to fine-tune the model to hold its system prompt: the recipe from *Goal-Conditioned DPO* (NAACL 2025), assembled the rigorous way — the target's *own* refusal and harmful completions, **goal-relabeled** to teach a system-over-user hierarchy, **over-refusal-balanced**, and **single-model self-generated** to sidestep the reward-hacking that stronger-model preference data provably induces. Fine-tuning is the *heavier* lever — it can affect a model's alignment — so ROGUE marks it the alternative to the reversible patch, and **never fine-tunes or deploys anything** (you own the runtime). These fixes are *suggested*; on demand, the deliberate remediation loop **re-tests one against the same live corpus to prove it closed the breach without over-blocking** (same calibrated judge). Every scan also reports the deployment's **instruction-hierarchy robustness** — how reliably it holds the system prompt when a user tries to override it — as a first-class defensive number.

One engine, one independent standard, the same operation each time: fire inputs at an AI decision-maker, capture what it does, score it against the standard, emit a reproducible signed record.

## Research

ROGUE's findings are written up as papers and posts. **[PAPERS.md](PAPERS.md)** is the index, and each entry links to its preprint plus the code and data *in this repo* that reproduces it.

- **Allocation Is a Capability-Growth Mechanism.** In a self-growing red-team, evaluation *allocation* is a capability lever, not an efficiency layer (8 of 20 starved candidates graduate vs 0 of 20; Fisher *p* = 0.003). · [Zenodo preprint](https://doi.org/10.5281/zenodo.21016849) · *arXiv on conference acceptance*
- **[withheld — under anonymized review].** One gate template ("engagement ≠ breach; consummation = breach") calibrates breach judges across classes, validated against human labels four ways. · [Zenodo preprint](https://doi.org/[withheld]) · *arXiv on conference acceptance*
- **[withheld — under anonymized review] Don't Reproduce in Deployment.** Most open-web jailbreaks don't survive as working carriers in deployment context, and a source's claimed rate carries no usable signal (Spearman −0.07). · [Zenodo preprint](https://doi.org/[withheld]) · *arXiv on conference acceptance*
- **[withheld — under anonymized review].** Canary leakage from shared agent skill pools tracks *alignment*, not model size. · [Zenodo preprint](https://doi.org/[withheld]) · *arXiv on conference acceptance*

## Deep dives

The mechanics behind the pipeline, each on its own page:

- **Scraper-agnostic harvest.** A `Fetcher` registry picks the best backend per capability (page fetch, JS render, search, PDF), so the *scraping* runs free and keyless out of the box and any scraper or proxy slots in behind one env var — none is a dependency (extraction calls an LLM you choose). Plus a self-tuning ε-greedy bandit that allocates harvest budget by yield (novel primitives per dollar). → [docs/harvest-backends.md](docs/harvest-backends.md)
- **Multimodal red-team.** Refused text jailbreaks become real images and audio via deterministic black-box renderers, climbing an autonomous escalation ladder that stops at the first breach. → [docs/multimodal.md](docs/multimodal.md)
- **Self-growing attack repertoire.** ROGUE harvests reusable *techniques*, not just payloads, classifying, routing, and graduating / retiring / resurrecting them on live breach evidence, with a governed renderer registry and grammar-driven planning (the planner-willingness finding: 22% → 100% by changing only the planner). → [docs/self-growing-repertoire.md](docs/self-growing-repertoire.md)
- **Judge calibration.** Every breach number is an LLM verdict, so the judge is validated against independent human labels four ways: in-distribution FP 2.56%, WildGuardTest harm 88.5%, StrongREJECT −26% inflation, JBB **89.3%** human agreement ([withheld], tied with the frontier LLM-as-judge baselines, reproducible from `data/calibration/`), up from a 70.3% v1 judge after a diagnosed recalibration. → [docs/judge-calibration.md](docs/judge-calibration.md)
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
- Deterministic obfuscation augmentation: 10 labelled, zero-LLM-cost transforms (leetspeak, homoglyph, zero-width, fullwidth, zalgo + base64 / ROT13 / hex / Unicode-escape / HTML-entity decode-wraps) skin a defended attack to measure a **flip-rate-per-transform**, separating "the target pattern-matches the surface string" from "the target understands the technique." A **goal-preservation validator** (inspired by AdvCodeGen, ICISC'25) checks each mutated variant still expresses the attack's goal *before* it's fired — decoding obfuscation, comparing to the original — so an over-obfuscated, self-neutered payload isn't miscounted as the model *defending*, a false negative the naive skin-and-fire loop silently produces.
- **Evidence-bank exfiltration detection** (inspired by TRACE, 2026): a tool-using agent can smuggle a secret it read from a tool result into a later call's arguments — and ROGUE's deterministic canary check catches a *verbatim* copy but, by design, not one the agent **base64-encodes, hex-dumps, reverses, or paraphrases** on the way out. So ROGUE keeps an **evidence bank** of every secret a tool returned into context, then screens each later call two ways: a **decode pass** (base64 / hex / ROT13 / unicode-escape / reversed / whitespace-stripped — near-zero-false-positive, the same canary literal, just skinned) and, on demand, a **semantic pass** (an entailment check that flags a *derived* leak — "the key's last four are 6789"). It closes the verbatim-substring blind spot (information-flow leakage, in the spirit of GIF / OCELOT) as a **non-headline** signal — telemetry and hardening, never allowed to inflate the deterministic breach rate. The decode pass runs **by default** (it's free and matches the exact canary, just skinned); the semantic pass is **opt-in** (it's an LLM call and an uncalibrated judge).
- **Persistent-memory leakage channel** (provenance instrumentation, extended). ROGUE extends the same provenance-based leakage instrumentation it runs on tool-call arguments and reasoning traces to a new channel — **persistent agent memory** — measuring cross-session leakage with the same deterministic framework. A secret an agent stores in one session can be recalled, and leaked, in a *later, unrelated* one — a boundary a per-response audit never crosses. ROGUE plants an unguessable, HMAC-minted canary as a **dormant** memory record (a prior session's write), triggers a *fresh* session on a sensitive topic, and scores whether the agent recalls it (`MEMORY_SURFACED`) and routes it to a sink (`MEMORY_EXFIL`) — reusing the existing canary → provenance → trace-judge pipeline, with a new cross-session `MEMORY` provenance label (the sibling of within-session retrieval). The memory attack itself is prior work (Trojan Hippo); the cross-session instrumentation is ROGUE's. Off by default and byte-identical when off; the $0 deterministic validation proves the instrumentation is sound (a compliant agent leaks, a careful one doesn't, the flag-off path is untouched) — *not* that real models leak, which the honest boundaries make clear (exact-match store, not embedding/RAG; single-agent, not inter-agent; verbatim-exfil only), so the live cross-model leak rate is a gated two-session measurement, not a shipped number. Grounds on Trojan Hippo (2605.01970) + AgentLeak's C5 channel (2602.11510). → [docs/research/memory_exfil_channel.md](docs/research/memory_exfil_channel.md)
- **Multi-party contextual-privacy probe** (a recipient-norm leakage surface). Every other leakage channel above asks *where a secret came from*; this one asks the question a group deployment actually fails — *to **whom** may it flow*. A shared assistant (a team bot, a household or customer-facing agent) is entrusted with one colleague's confidence — a sensitive personal fact shared under a norm — and then a *different* participant asks a question whose most helpful answer would give it away. ROGUE embeds an unguessable HMAC canary in that confided fact as a confidential reference, reconstructs the group conversation exactly as MuPPET frames it (the memory in the system prompt, the history and the eliciting question in the user turn), and judges the reply served to the second party on two tiers: a **verbatim** tier (the canary reappears → the assistant regurgitated the record — deterministic, near-zero-FP, **headline**) and an opt-in **inferable** tier (an LLM judge finding the private fact stated-or-implied, MuPPET's real signal — **non-headline** until it clears calibration). A 38-scenario seed corpus spans seven high-stakes domains (health, legal, finance, HR, academic, immigration, family), with a `one_on_one`/`group` switch that reproduces MuPPET's finding that models leak *more* once an audience is present, and a `privacy_instruction` toggle that reproduces ConfAIde's sharper one — that they leak *even when told not to*. It needs no tools, so unlike the memory channel it runs against a live customer chat model directly; off by default and byte-identical when off. The $0 validation proves the plumbing (a blatant assistant regurgitates the confidence, a careful one holds it) — the cross-model **multi-party privacy board** (*which models leak a group member's confidence to the room* — MuPPET finds the small open-weights people self-host for privacy leak **worst**), the one-to-one↔group delta, and the "leaks even when told not to" effect are a gated multi-turn measurement, not a shipped number. Grounds on MuPPET (2606.23217) + ConfAIde (2310.17884) + MAGPIE (2506.20737). → [docs/research/multiparty_privacy.md](docs/research/multiparty_privacy.md)
- **Domain-jargon evasion augmentation** (inspired by ExpGuard, 2026): the *semantic* sibling of the obfuscation axis. Where the transforms above skin the surface *string*, this re-expresses a defended attack in the **register of a specialist** — a board-certified physician, a compliance analyst, counsel — because a guardrail trained on general-harm features often waves through the same request dressed in clinical, regulatory, or statutory jargon. An attacker LLM applies the three empirically-supported levers (technical terminology · authority persona · legitimate-context framing), the deployment's domain rides in its system prompt, and the **same goal-preservation gate** vetoes any rewrite that quietly sheds the ask, so a *flip* (refused plain, complied in-register, goal intact) is a real domain-evasion, not an artifact. Wired into the scan (`rogue scan --domain-jargon`) and the live reproduce sweep; the cross-model flip-rate it feeds — a **domain-robustness board** — is the paid measurement, not yet a shipped number.
- **Judge self-audit for domain blind spots.** Because ROGUE's breach judge is itself calibrated on *general* benchmarks, a probe measures whether it inherits the same weakness it hunts — running the judge over matched general-vs-domain content and reporting the calibration **gap** (under-detection vs over-flagging, per register). It's the discipline turned inward: we stress-test our own instrument before trusting its numbers on high-stakes deployments. (A first probe found no gap on a frontier judge — the risk surface is smaller, cheaper guard models, which the paid run targets.)
- **Survival-ranked reproduction** (system-prompt-transfer prediction). A harvested jailbreak that worked in the wild usually *doesn't* survive being re-hosted under a customer's system prompt — ROGUE's measured cross-config survival base rate is **~14%**, so most of a paid reproduce cycle lands on attacks that were dead on arrival. A black-box, embedding-free predictor learns, from an attack's own surface (family/vector, requirements, provenance scores, payload shape) crossed with a cheap descriptor of the target's system-prompt class, the probability it will **still breach** — and reorders the scan so the likely survivors fire first. Trained free on breach history ROGUE has already paid for; on a group-split-by-primitive back-test it recovers **80% of real survivors after firing only 61% of trials** (ROC-AUC 0.77, 4.2× precision lift at the top decile). The honest part is the **drift-guard**: a newly-harvested or under-evidenced attack family is *never* deferred — it always gets a real reproduction — which is Kirch et al.'s out-of-distribution-collapse finding (2411.03343) turned into an operating rule, plus a deterministic canary sample that keeps validating the very skips it makes. A black-box predictor of *cross-system-prompt* survival is the gap the white-box (Kirch, Ball) and per-config (Helm) literature all leave open. → [docs/research/survival_predictor.md](docs/research/survival_predictor.md)
- **Pre-fire skip on a calibrated success score** (predict-before-fire). Where survival ranking reorders, this decides whether to fire an attack at all: a *calibrated* probability that a specific harvested attack will breach a specific target, learned from breach history ROGUE already owns, with the attack's payload **embedding** folded in on top of its structure — so the confident misses can be skipped before a single target or judge call is spent. The engineering is built around making the skip **honest**: a Platt-calibrated probability you can threshold, a **measured recall cost** (skip ~40% of trials if you accept missing one breach in five, but only ~7% at a stringent 95% breach recall — the trade-off the prior work leaves unmeasured), the same drift-guard rail (a novel or under-evidenced attack family is *never* skipped) and a 15% canary that keeps validating the skips. On a group-split back-test the payload embedding adds a small but consistent lift over structure alone (ROC-AUC 0.688 → 0.696), and every skipped attack is surfaced, never silently dropped. The black-box, cross-family, target-conditioned, *calibrated* skip is a cell the detection (Galinkin), one-family-ranking (Zhang) and white-box (Kirch) literature don't reach. → [docs/research/prefire_scorer.md](docs/research/prefire_scorer.md)
- **Sequential early-stopping of the trial loop** (SPRT). Everyone reports an attack success rate from a fixed handful of trials — but at ROGUE's default `n=3` that rate can only be one of `{0, ⅓, ⅔, 1}`, a number too coarse to mean anything, and paying to fire a *large* fixed `n` burns target+judge calls on the many cells that are already obviously safe or obviously broken. ROGUE instead treats the per-cell budget as **sequential**: each trial's breach/no-breach verdict updates a log-likelihood ratio for the hypothesis test **H0 p≤0.25 vs H1 p≥0.55** (Wald's SPRT, α=β=0.05), and the loop stops the instant the ratio crosses a decision boundary — a clearly-safe or clearly-broken cell resolves in **~4–6 trials**, while genuinely borderline cells get the *full* budget, spending the trials exactly where the uncertainty is. Trials fire in small **concurrent batches** so the sequential test keeps ROGUE's parallelism, and a truncation cap falls back to the incumbent threshold rule so no cell is ever *re*-graded — only shortcut. Replaying the real test over breach history ROGUE has already paid for, it recovers the **same breach verdict for 22% fewer target+judge calls at 99.8% agreement** (50–80% on the deep-sampled cells that need the statistics most) — with zero new dependencies and off by default. Reframing a fixed ASR as a sequential test is, as far as we can find, unreported in the red-team-evaluation literature; it grounds on ConSol's Wald-for-LLMs formulation (2503.17587). → [docs/research/sprt_early_stopping.md](docs/research/sprt_early_stopping.md)
- **Confidence-gated cascade grading** (free tier first, pay only for the ambiguous). Every reproduced trial is graded by a safety judge, and on a paid scan that judge is a frontier LLM billed *per trial* — the top per-trial cost — even for the flat "I can't help with that." refusals that are the safe majority of any red-team run. ROGUE grades each trial with its **free, network-free regex judge first** and escalates to the calibrated LLM judge **only** when the cheap tier isn't a confident non-breach. Because that cheap tier costs *nothing* — it's a regex, not a smaller paid model — every short-circuit removes a full judge call for zero marginal cost, and the LLM judge is spent exactly where the verdict is genuinely ambiguous. The safety rail is an **asymmetry**: the free tier may stand alone only on a confident *non-breach*; any breach signal is *always* re-confirmed by the calibrated judge, so the cheap tier can **never inflate the breach rate** — every breach still goes through the calibrated judge, and the reported rate matches running the LLM judge on everything to the measured **99.8% agreement**, for less money. Replayed $0 over 12,452 already-graded trials, the safe default gate skips **18% of paid judge calls at 99.8% agreement** with the calibrated verdict, and a tunable, statistically **certified** gate (Wilson-floor ≥95% agreement, fixed-sequence-tested à la Jung) reaches **46%**. It's the **judge-budget** control of ROGUE's evaluation loop — the sibling of survival ranking (*which* attacks) and sequential early-stopping (*how many* trials) — and it's **already active in ROGUE's own production scans**, cutting judge spend on every run today. No new dependency, byte-identical when off. Grounds on Ramírez's finding that the cheap tier's *own* confidence beats a trained router (2405.02134) and Jung's *Trust or Escalate* threshold calibration (2407.18370). → [docs/research/cascade_judge.md](docs/research/cascade_judge.md)
- **Judge-shrink decision gate** (measure whether a cheaper grader is safe — don't assume it). The safety judge is billed *per trial*, so a smaller judge model that held agreement would cut the reproduce layer's dominant marginal cost directly — and setting `JUDGE_MODEL` to something cheap has always been *possible*. What's dangerous is doing it blind: the classic result (Thakur, *Judging the Judges*) is that small judges keep *ranking* models correctly while quietly losing *per-verdict* fidelity, and they fail by **over-firing the positive class** — for a red-team, that means **over-calling breaches**, silently inflating the headline breach matrix. ROGUE ships the honest instrument to decide instead: it reports **Cohen's κ** (chance-corrected agreement — not raw agreement, which inflates under the 110/300 class balance) plus the **false-positive-breach rate** with bootstrap confidence intervals, and a candidate judge model **ships only if its κ is within tolerance of the frontier baseline *and* it does not over-call breaches relative to it**. The whole A/B runs for **$0** by re-aggregating the 300-item public JBB judge-comparison verdicts ROGUE has already logged for ~10 candidate models — no new spend. The finding is sharp and reproduces the literature in ROGUE's own data: on 300 human-labelled items only **qwen3-32b** clears the gate (κ=0.775 vs Sonnet's 0.814, with a *lower* false-positive-breach rate), while **"bigger" judges are worse** — llama-3.3-70b, qwen-2.5-72b and hermes-70b all fall *below* the 32B model and over-call breaches at **2–3.4× Sonnet's rate**; parameter count does not predict judge fidelity. κ earns its keep here: qwen-2.5-72b's 78% raw agreement looks close, but κ=0.577 and a 34% false-positive-breach rate correctly reject it. The build also ships an **off-by-default reference-anchoring lever** (`ROGUE_JUDGE_REFERENCE_K`) — Krumdick's "hand the judge a *verified* reference" fix (*No Free Labels*), translated to a breach judge that has no per-trial gold answer by injecting human-verified verdict exemplars — whose effect on a small judge is *measured* by the same gate, never assumed. The production judge stays Sonnet; what ships is the decision discipline (κ + FP-breach + CI, byte-identical when off, no new dependency). Grounds on Krumdick (2503.05061) + Thakur (2406.12624) + Loiseau (2603.29497). → [docs/research/judge_shrink_ab.md](docs/research/judge_shrink_ab.md)
- **Local-first extraction cascade** (free local tier first, pay Haiku only when it can't be trusted). Every harvested document is turned into a structured attack primitive by a per-document LLM call — a real harvest-cost driver. ROGUE tries a **cheap local model first** and escalates to the Haiku extractor **only** when the local output is untrustworthy: an abstention, a schema-invalid object, or a payload that isn't grounded in the source document. It is the extraction sibling of the judge cascade, with the same **asymmetric rail** — the cheap tier can only ever *save* a Haiku call, it can **never drop a document** on its own say-so — so quality is never traded for cost. The build ships the enabling wiring (a `local/` json-mode provider branch, because the strict structured-output path can't compile the attack-primitive grammar on a local runtime) and a **per-field agreement harness** that measures, slot by slot, where a local model may actually be trusted before you turn it on. The honest result is a **negative** one that the mechanism is designed around, and it holds across a whole size sweep: off-the-shelf `qwen2.5` at **3B, 14B *and* 32B all score recall 0/2** on the real attack fixtures — the 3B doesn't even recognize the attacks, while the 14B/32B *understand* them but won't render the structured payload and ignore an explicit field contract, so scaling the model 15× doesn't help. A naive swap would silently lose attacks at any of these sizes — and neither grounding paper (Lincoln; Bumgardner) even compares against a cheap *hosted* small model like Haiku, so the literature does not actually establish a Haiku→local win; the real saving needs a **fine-tuned** local extractor, for which ROGUE's own logged Haiku extractions are the ready distillation set. With a weak local model the cascade simply escalates everything — ≈0 saving, **0 quality loss** — which is the correct, safe behaviour. Off by default, byte-identical when off, no new dependency. Grounds on Lincoln (2605.05532) + Bumgardner (2308.01727). → [docs/research/extraction_cascade.md](docs/research/extraction_cascade.md)
- **Noise-corrected breach rates** (imperfect-judge de-biasing + certification). A breach rate read straight off an LLM judge is a *biased* estimate whenever the judge has a non-zero false-positive rate — and the bias points *upward* exactly in the low-true-rate safety regime, so "the judge flagged 13% of trials" quietly overstates real harm. ROGUE estimates the judge's true- and false-positive rates from the human-labelled calibration 2×2 it already keeps, then **de-biases the reported rate** (Rogan–Gladen inversion) with a confidence interval that carries *both* the test-run and the small-calibration-set uncertainty, and stamps a finite-sample **certification** — "true breach rate < α, with Type-I error ≤ ζ" — that stays valid despite the judge being noisy. Replayed $0 over breach history already paid for, a raw **13.5%** judge breach rate de-biases to **1.0% [95% CI 0–6.6%]** — under the estimated judge error profile, the large majority of flagged "breaches" are attributable to the judge's own false-positive floor rather than to real harm (a 10%-FPR judge can make a 1%-true-rate system look 10× worse). This is a **certification layer** for the benchmark — turning a raw judge fraction into a de-biased rate *and a certified claim* ("true rate < α, Type-I ≤ ζ") — which is what finally lets the previously-uncalibrated redaction / right-to-be-forgotten / user-safety / PII / agent-memory judges ship a headline number. Additive and off by default, so every historical calibration report is untouched, and it **refuses rather than fabricates** when the judge isn't identifiable (TPR̂ ≤ FPR̂). Grounds on Feng's "Noisy but Valid" (2601.20913) + Lee's LLM-judge reporting method (2511.21140). → [docs/research/noise_corrected_calibration.md](docs/research/noise_corrected_calibration.md)
- **Single-turn consolidation of multi-turn attacks** (multi-turn coverage at single-turn cost). A Crescendo-style attack in ROGUE's corpus fires as a real back-and-forth — one victim call per turn — but a multi-turn conversation can be *folded into one structured prompt* that preserves the sequential progression, and (per Ha et al., *One-Shot is Enough*, 2503.04856) the consolidated single-turn form is often **as potent or more** because it slips the harmful sequence past turn-by-turn safeguards that never inspect the whole progression at once. ROGUE renders a multi-turn primitive's turns through one of three deterministic, zero-LLM-cost formatters (bullet-list, numbered, or a Python-list skeleton) and fires it through the ordinary single-invoke path at **1× trial** instead of K — a deterministic cost cut a read-only census puts at **71% fewer victim calls** across the 8.8% of the corpus that is multi-turn (mean 3.45 turns each). The transform keeps the attack's identity, surfaces every consolidation, and is off by default and byte-identical when off; whether efficacy holds on a live panel is a gated measurement, so the shipped number is the cost, not an efficacy claim. → [docs/research/m2s_consolidation.md](docs/research/m2s_consolidation.md)
- **Pre-fire prompt pruning in the escalation search** (don't pay to re-fire what you already tried). ROGUE's escalation searcher mutates a refused attack looking for a breaking variant, firing a paid target+judge rollout for *every* generated candidate — but an attacker exploring a mutation space re-visits near-identical prompts constantly (a redundancy Tree-of-Attacks-with-Pruning names outright). Before a candidate is fired, ROGUE now embeds its **prompt** and **skips the rollout** if it is a near-duplicate (cosine ≥ 0.92, the same threshold the harvest deduplicator uses) of one already fired *this search* — Tree-of-Attacks' prune-before-fire ported to ROGUE's one-child-at-a-time loop — with an optional EvoJail-style diversity reward (`S(p)+λ·D(p|P)`) that steers the search toward novel prompts without ever dropping one. The measurement is the finding: replayed $0 over ROGUE's real searchers, the flat Thompson **bandit — the production-default searcher — re-fires 87.9% exact-duplicate rollouts when it's stuck on a hardened target**, versus 7.0% for the tree searcher, and 14.9% of the real harvested prompt corpus are semantic near-duplicates the gate would catch. It is per-search (never a global corpus dedup — a near-duplicate of a *different* attack tested against a *different* config can genuinely differ, a confound we name rather than hide), off by default, byte-identical when off, and reuses the existing embedding + cosine + threshold with no new dependency. Cuts the *search-expansion* budget — a distinct axis from which pairs to fire (survival / pre-fire skip), how many trials (SPRT), and judge economics (cascade). Grounds on TAP (2312.02119) + EvoJail (2605.02921) + KDA (2502.05223). → [docs/research/prefire_pruning.md](docs/research/prefire_pruning.md)
- External benchmark layer against frozen AdvBench / JailbreakBench goal sets.
- **Right-to-be-Forgotten deletion audit** (entity-unlearning verification, Opt-Out-inspired): probe a deployed model to verify a "deleted" user's knowledge is genuinely unrecoverable — paraphrase/format-robust probing (recovery under any variant = leak), semantic recall (not string match), and a paired **forget-leak-rate + neighbor-retain-rate** (the same security↔utility discipline). Wired into the scan (`rtbf_attributes`) and a standalone audit script; the corpus builds on demand from Wikipedia via the terminology miner.
- **Redaction / DLP red-team** (proposition-level, RedacBench-inspired): the defensive mirror of ROGUE's PII-leakage offense. Decompose a document into atomic inferable propositions → classify each *sensitive-per-policy* (not a fixed PII list) → check **semantic** leakage by entailment rather than string match (catches a redaction that masks the entity but leaves the fact recoverable) → report the **security ↔ utility** trade-off. Fail-soft, no hard LLM dependency (the judge is an injected seam); ships with a RedacBench-style seed corpus (`tests/fixtures/redaction/`).

## Roadmap

- **Expand source coverage.** More source plugins bring the next ~100 open-web sources online.
- **Break bandit.** A second, contextual Thompson-sampling bandit that learns *how to break* (which escalation strategy to try first per attack-family × target); the control surface and reward log are already built and instrumented in prod.
- **Red-team multi-party & multi-agent deployments.** ROGUE started by red-teaming a single agent over a single-user conversation; the frontier is *settings with several parties*. The first step — **multi-party privacy** — is **built** (off by default, see the capability above): an assistant in a group chat that quietly discloses one member's private data to another, the same audience-conditioned leakage ROGUE already measures one-to-one, scaled to a group where the model has to track *who may see what*. The remaining frontier is *systems of collaborating agents*, where a breach must be **attributed across the crew** — which agent got jailbroken, which one leaked, which one followed the injection another one carried — a genuinely multi-perspective verdict rather than a per-agent one.

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
