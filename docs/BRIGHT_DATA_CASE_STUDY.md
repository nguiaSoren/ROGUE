# Case Study — ROGUE: Continuous-Harvest LLM Threat Intelligence on Bright Data

Built solo in 6 days by Soren Obounou Nguia for the Bright Data × lablab.ai
Web Data UNLOCKED Hackathon (May 2026).

## Problem

Enterprise teams deploying LLMs face an asymmetric threat landscape. New
jailbreak and prompt-injection techniques surface on Reddit, X, arXiv,
GitHub, and security blogs daily. Static red-team suites — the dominant
defensive tooling in 2026 — run yesterday's attacks against bare models. No
existing tool continuously harvests novel attacks from the open web and
reproduces them against the customer's actual deployment configuration.

The bottleneck is not modeling: it is web access at scale. Anti-bot WAFs,
JS-rendered content, rate limits, geo-blocks, and missing scrapers for
social platforms collectively block most would-be harvest systems from ever
shipping.

## Solution

ROGUE is a five-layer agent pipeline: harvest → extract → dedupe →
reproduce → diff. The harvest layer integrates all 5 Bright Data products
end-to-end. Each fetched document becomes a Pydantic `AttackPrimitive`
(15 families, 14-slot cross-deployment templates). The reproduction engine
instantiates each primitive against the customer's deployment panel —
GPT-5.4 Nano, Claude Haiku 4.5, Llama-3.1-8B-Instruct (via OpenRouter),
Mistral Small 4, Gemini 3.1 Flash-Lite, plus Claude Opus 4.8 — over N=5
trials with 95% bootstrap CIs. A separate Claude Sonnet judge scores each
trial, calibrated against independent human labels. The diff layer ships a
CISO-readable threat brief — markdown, JSON, Slack — plus ROGUE's own MCP
server so Claude / Cursor users query the live breach matrix from their IDE.

## Architecture (5-product walkthrough)

**Web Scraper API** — Reddit, X, and HuggingFace via pre-built scrapers.
Structured JSON out of the box, zero lines of anti-bot code. Without this,
roughly two weeks of scraper engineering.

**SERP API** — Google + Bing novel-attack discovery. The DiscoveryAgent runs
an ε-greedy bandit over 36 candidate queries across 15 sources, learning
per-query yield in *novel attacks per Bright Data dollar*. The spread is
dramatic: `site:github.com/elder-plinius` returns ~60 novel primitives per
dollar; `site:reddit.com/r/LocalLLaMA "uncensor"` returns ~1 — a ~60×
differential, and the bandit reallocates spend toward the winners on its own.

**Web Unlocker** — arXiv, security blogs (Embrace The Red, Lakera, Simon
Willison), MITRE ATLAS, OWASP LLM Top 10, vendor advisories. Clean Markdown
straight to the extractor. It also fetches the *real images* the multimodal
attacks are tested against.

**Scraping Browser** — JS-heavy fallback for archives and forums no pre-built
scraper covers.

**MCP Server** — Bright Data's hosted MCP exposes its products as tool calls
to the DiscoveryAgent (consumer side). ROGUE in turn exposes its **own** MCP
server — 6 tools (`query_attacks`, `query_diff`, `query_threat_brief`,
`query_breaches_for_config`, `query_attack_detail`, `query_worst_attacks`),
queryable over stdio *or* HTTP. That makes ROGUE a **two-way** Bright Data
MCP integration: it harvests the web *through* MCP and distributes its
results *back* through MCP — a loop no other red-team tool closes.

## Results (v1, verified against the live database)

- **459 attack primitives** (298 harvested-canonical from the open web) across **15 families**,
  deduplicated via pgvector cosine clustering.
- **8,321 reproduced + judged trials** across **6 deployment configs**;
  **252 attacks breached** at least one config (**619 breaching
  primitive × config cells**).
- **Per-model spread:** Mistral Small 4 broke at **51%** any-breach, Gemini
  32%, Llama 17%, GPT-5.4 Nano 12% — while **Claude Haiku held at 6%**.
- **Live proof:** elder_plinius posted a Claude-Opus-4.8 jailbreak on X;
  ROGUE harvested it via **Web Unlocker** and reproduced a **100% full breach
  against an Opus 4.8 deployment within ~2 minutes of ingestion** — Claude
  Haiku resisted the same attack entirely.
- **Cost:** **$276.70 all-in** ($92.48 Bright Data + $184.22 LLM) —
  **≈ $0.15 of Bright Data spend per detected breach**. The daily open-web
  harvest runs on **$0.05–$0.30** of Bright Data, allocated by the bandit.
- **Judge credibility:** **89.3%** agreement with human-majority labels on
  JailbreakBench (3rd of 5 field classifiers), plus **88.5%** on WildGuardTest's
  harm axis; a StrongREJECT cross-check confirms the breach rates are *not*
  inflated by an over-eager grader.
- **Public dataset:** 298 MIT-licensed attack primitives exported for
  HuggingFace.

## Self-quote

> "I built ROGUE solo in 6 days because Bright Data abstracted away 5
> different anti-bot stacks I'd otherwise have spent weeks on. The MCP
> Server + pre-built Reddit/X scrapers turned a 6-week project into a
> 6-day project. Without that infrastructure, this is not possible."
> — Soren Obounou Nguia, AI Systems Engineer

## Reproducibility

Source: github.com/nguiaSoren/ROGUE · Demo: https://rogue-eosin.vercel.app ·
License: MIT. `docker compose up` brings up the full local stack; the hosted
MCP server is live at `https://rogue-api-mr5w.onrender.com/mcp/`.
