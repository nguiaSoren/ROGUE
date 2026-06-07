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
