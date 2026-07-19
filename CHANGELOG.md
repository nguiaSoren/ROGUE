# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

v2 preparation and production-readiness work in progress:

- Continuous integration (GitHub Actions): backend lint/type/test with a
  Postgres 17 + pgvector service container, frontend lint and type-check.
- Repository hygiene: pre-commit hooks (ruff lint/format + basic file checks),
  `SECURITY.md` disclosure policy, this changelog.
- Schema reconciliation between the Pydantic wire format and the SQLAlchemy
  storage layer.
- Architecture Decision Records (ADRs) for the locked design decisions.
- Production-readiness hardening across the hosted platform layer.

Red-team capability additions (all new attacks flag-gated, **off by default**, byte-identical when off; cross-model efficacy numbers are gated paid measurements, not shipped numbers):

- **Adaptive multi-turn attacks** — a per-turn judge-in-the-loop conversation engine with auto-backtracking (Crescendomation), an Observation→Thought→Strategy attacker (GOAT), context-poisoning (Echo Chamber) and a partial-compliance beam (SIEGE), on a new stateful `Conversation` object; replaces the plan-once-fire-static tier-5 path when enabled.
- **Reasoning-channel attack** — realizes the `CHAIN_OF_THOUGHT_HIJACK` family (H-CoT + CoT-Hijacking templates) and a `cot_forge` tool that re-points the reasoning-capture instrument from leak-detection to compliance-induction.
- **Agentic indirect-injection breadth** — MCP tool-schema poisoning + rug-pull, a template × carrier × concealment injection bank, PoisonedRAG adoption, a guardrail-stack fingerprint, and a `live_tool_target` on `/v1/scans` to point ROGUE at a customer's live MCP server; all reuse the existing deterministic `TraceJudge`.
- **Assistant-prefill message surface** — protocol-aware response-priming (native prefill on Anthropic, in-band fold on OpenAI-style), a capability the instantiator previously lacked.
- **Extended obfuscation/strategy arsenal** — FlipAttack (first reversal operators), a numeric-transport pack, payload-splitting, bijection learning, TokenBreak, and skeleton-key / past-tense / MathPrompt/LogiBreak templates.
- **Distill-from-failure** — a target's refusal reason is captured on losing attempts and injected as avoid-rules into later attacker prompts (negative cross-run memory).

Product & operations:

- **Baseline-regression CI gate** (`baseline save` / `compare --max-regression`) — fails a build when an update re-opens a previously-closed bypass.
- **Graded scan reports** — per-family A–F scorecard (worst-category-dominates), a probed-vs-never-fired coverage matrix, and OWASP/ATLAS/NIST framework tags on every finding (JSON/HTML/PDF) and the dashboard report view.
- **New leaderboard facets** — a safeguard (false-refusal-rate) board and an injection-robustness board, shipped in an honest measurement-pending state.
- **Content-hash verdict cache**, **scan crash-resume**, and **OpenRouter provider pinning** for cheaper, more reproducible runs.

Fixes:

- Judge no longer crashes on null OpenRouter `choices` (retries instead).
- `crawl4ai` availability probe no longer falsely returns unavailable inside the async harvest loop (which had silently forced the rate-limited keyless fallback).
- Cost estimation prices by the real judge model instead of a flat heuristic.

## [1.0.0] — —

First production release of the ROGUE continuous open-web LLM red-team.

### Added

- **Open-web harvest** of jailbreaks and prompt-injection from 19 sources via
  five Bright Data products (MCP Server, SERP API, Web Unlocker, Scraping
  Browser, Web Scraper API).
- **Extraction layer** that normalizes harvested material into canonical
  `AttackPrimitive`s (attack family / vector / severity taxonomy, frozen Day 0).
- **Reproduction layer** that replays attacks against customer
  `DeploymentConfig`s (model × system prompt × tools), including the escalation
  ladder and augmentation sweeps.
- **LLM judge** with a calibrated verdict pipeline; v3 recalibration measured
  across in-distribution, WildGuardTest, and StrongREJECT axes, plus a full
  re-judge of the stored breach matrix corpus.
- **Daily threat-brief diff** generation.
- **Hosted platform**: one-engine SaaS layer with a versioned `/v1` API,
  tenancy, scan orchestration, and report generation.
- **MCP server** so Claude Desktop / Cursor / Windsurf can query the ROGUE
  threat DB directly.
- **Next.js dashboard** for browsing breaches, the breach matrix, and analytics.
- **Postgres 17 + pgvector** storage with hand-written Alembic migrations.

[Unreleased]: https://github.com/soren/rogue/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/soren/rogue/releases/tag/v1.0.0
