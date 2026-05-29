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
JS-rendered content, rate limits, geo-blocks, and pre-built scrapers for
social platforms collectively block 95% of would-be harvest systems from
ever shipping.

## Solution

ROGUE is a five-layer agent pipeline: harvest → extract → dedupe →
reproduce → diff. The harvest layer integrates all 5 Bright Data products
end-to-end. Each fetched document becomes a Pydantic `AttackPrimitive` (14
families, 7 vectors, 14-slot templates). The reproduction engine
instantiates each primitive against the customer's deployment panel
(GPT-5.4 Nano, Claude Haiku 4.5, Llama-3.1-8B-Instant via Groq, Mistral
Small 4, Gemini 3.1 Flash-Lite) over N=5 trials with bootstrap CIs. A separate Claude Sonnet
judge scores each trial. The diff layer ships a CISO threat brief —
markdown, JSON, Slack, plus ROGUE's own MCP server for Claude/Cursor.

## Architecture (5-product walkthrough)

**Web Scraper API** — Reddit + X + HuggingFace pre-built scrapers.
Structured JSON out of the box. ~120 daily social-media fetches with 0
lines of anti-bot code. Without this, ~2 weeks of scraper engineering.

**SERP API** — 32 daily Google + Bing queries. Sub-1s response. The
DiscoveryAgent runs an epsilon-greedy bandit over the 32-query pool,
learning per-query yield across the backfill.

**Web Unlocker** — arXiv, Simon Willison's blog, Embrace The Red, Lakera,
MITRE ATLAS, OWASP LLM Top 10, vendor safety announcements. Clean Markdown
returned directly to the extractor — saves a parsing layer.

**Scraping Browser** — JS-heavy fallback. jailbreakchat archives, Discord
mirrors, community attack forums. Playwright-compatible WebSocket.

**MCP Server** — Bright Data's hosted MCP exposes all 4 products as tool
calls to the DiscoveryAgent. ROGUE in turn exposes its **own** MCP server
with 5 tools (`query_attacks`, `query_diff`, `query_threat_brief`,
`query_breaches_for_config`, `query_attack_detail`) — first project to use
Bright Data MCP on both sides.

## Results

(Numbers from May 26–30 backfill; final values locked Day 4 morning.)

- **{N} unique canonical attack primitives** across 14 families.
- **{M} reproduced breaches**; {K} CRITICAL, {L} HIGH.
- **97.3% [88.1%, 99.6%]** breach rate against weakest deployment (B=1000 bootstrap CI).
- **Under 8 minutes** publication-to-verified-breach end-to-end.
- **${cost} total spend**; **${cost-per-breach}** per detected breach.
- **Public dataset** on HuggingFace (`<handle>/rogue-attacks-2026-05`, MIT).

## Self-quote

> "I built ROGUE solo in 6 days because Bright Data abstracted away 5
> different anti-bot stacks I'd otherwise have spent weeks on. The MCP
> Server + pre-built Reddit/X scrapers turned a 6-week project into a
> 6-day project. Without that infrastructure, this is not possible."
> — Soren Obounou Nguia, AI Systems Engineer

## Reproducibility

Source: github.com/<handle>/rogue. Demo: <vercel-url>. License: MIT.
`docker compose up` reproduces the full stack in <90s.
