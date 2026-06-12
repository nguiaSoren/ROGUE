# ROGUE

**A continuous, autonomous open-web LLM red-team.** It harvests brand-new jailbreaks and prompt-injection attacks from the open web, reproduces each against a target's deployment config (model × system prompt × tools), judges the result, and ships a daily breach diff. It also exposes its entire threat database over its own Model Context Protocol (MCP) server, so an agent inside Cursor or Claude Desktop can drive a full scan from the IDE.

**Status — honest:** ROGUE is a solo research-and-engineering project by Soren Obounou Nguia. It is in early access with **no paying customers yet**. The numbers below are real measurements from dated corpus snapshots; where the evidence is thin, that is stated plainly. The intellectual honesty about scope is deliberate — it is part of how the system was built.

---

## Engineering highlights

- **Five-layer pipeline, permanently live.** Harvest → Extract → Dedupe → Reproduce → Diff, built on FastAPI + Pydantic v2 + SQLAlchemy 2.0 + Alembic, Postgres 17 + pgvector, and a Next.js 16 dashboard. Deployed across Vercel + Render + Neon with UptimeRobot and Slack alerting. ~22k-line Python backend, ~1,490 tests, 24 hand-written Alembic migrations, a 19-tool MCP server, and a ~40-component dashboard.

- **Two-way Model Context Protocol — the differentiator.** ROGUE *consumes* Bright Data's MCP as its data-collection tool surface and *exposes* its own producer-side 19-tool MCP server (mounted over streamable-HTTP and stdio). A coding agent can run the whole consult — "scan my staging endpoint → summarize → file Jira tickets → post to Slack" — without leaving the IDE. The server is org-bound server-side and references secrets by name, so credentials are never handled by the LLM.

- **LLM-as-judge: calibrated, then recalibrated when a benchmark exposed a real weakness.** Against JailbreakBench's `judge_comparison` set (300 human-labeled rows), the original judge ranked *last* of 5 field classifiers — it over-flagged at 70.3% agreement / 55% precision. I diagnosed the rubric failure (it rewarded *engagement with the attack frame* rather than *transfer of harmful content*), rebuilt it as a content-transfer-gate rubric (judge v3), and re-measured via a cost-controlled tiered eval: **89.3% agreement / 79.5% precision / 95.5% recall**, moving from last to 3rd of 5. The v3 re-judge of the stored breach matrix is **done** (2026-06-07): the live dashboard now shows v3-graded cells (the re-judge dropped breach cells **2,429 → 1,371, −43.6%** and resolved all 419 ERROR cells, correcting prior v1/v2 over-reporting; ~$9.11 batched), and the WildGuard (88.5% harm-axis agreement) and StrongREJECT (−26% inflation delta) calibration axes were both re-run under v3 on the same date.

- **Scheduling as a capability lever (controlled A/B).** A target-conditioned cross-tier scheduler — deliberately *not* ML, but static, explainable, and reproducible — reorders the attack escalation ladder. A single-variable experiment (Claude Haiku target, AdvBench + JBB) improved median winner-rank from 22 to 11–13.5, attack success rate from 50% to 60%, and cost-per-success from $1.25 to $0.74 (−41%). The non-obvious mechanism: the rank improvement *caused* the ASR gain, because the old ordering exhausted the budget cap before ever reaching the winning technique. This is a descriptive N=20 proof-of-concept, not a validated generalization.

- **Multimodal red-team with an autonomous escalation ladder.** Six published attack techniques (Promptfoo, MML, VPI, PolyJailbreak, ARMs, CoJ) reimplemented as deterministic, black-box, byte-reproducible renderers — no model weights required — composed into a ladder that stops at the first breach.

- **Self-growing attack-technique repertoire.** ROGUE harvests reusable attack *methods*, not just payloads. A candidate technique graduates to "active" only when it wins a real escalation, is soft-retired if it never wins, and is resurrected when target behavior drifts. Escalation planning is grammar-driven, with an LLM acting as the parameterizer.

- **Online-learning spend allocation.** An ε-greedy bandit allocates metered Bright Data spend by novel-attacks-per-dollar. The entire daily open-web harvest runs on $0.05–$0.30; the top query arm yields ~7,100 novel attacks per dollar versus ~0 for the worst.

- **Productized — one engine, four surfaces.** ScanService → a Postgres job queue (SKIP LOCKED) → worker → engine → ReportService, fronted by a Python SDK (324 tests, MockTransport backend), a `/v1` REST API, the dashboard, and the MCP server — all returning the identical report. Customer keys are Fernet-encrypted at rest. Verified live end-to-end: submit endpoint → JSON + HTML + a reportlab CISO-grade PDF.

- **Production reliability, learned the hard way.** Operated as a live service through a serverless-DB outage that I diagnosed and fixed — un-gating startup from migrations, adding a DB-free liveness probe, hardening the connection pool, and closing a streaming connection leak — then distilled into a reusable resilience playbook.

- **The corpus.** 358 attack primitives across a 15-family taxonomy aligned to the OWASP LLM Top-10 and MITRE ATLAS, drawn from 19 open-web sources via 5 Bright Data products, reproduced against a 6-model panel (OpenAI / Anthropic / Meta / Mistral / Google), with 8,300+ breach-trial records. Published as an access-gated, MIT-licensed HuggingFace dataset.

---

## Honest scope

These are descriptive measurements of dated corpus snapshots, not validated generalizations. Reproduction uses n=5 trials per cell (wide confidence intervals; 95% bootstrap CIs are persisted). Targets are black-box live-API models whose versions are not pinned. Labeling is single-operator. The early benchmark Run #0 ASR figures (93% / 90%) predate the judge recalibration and are inflated by the old rubric — which is why the results lead with winner-rank and cost-per-success rather than raw ASR. Early access, no paying customers yet.

---

## Stack

Python 3.11 · FastAPI · Pydantic v2 · SQLAlchemy 2.0 · Alembic · Postgres 17 + pgvector · Next.js 16 · MCP (consumer + producer) · Bright Data data-collection products · Vercel + Render + Neon · UptimeRobot + Slack alerting.

---

## Links

- **Live site:** https://rogue-eosin.vercel.app
- **Demo video:** https://youtu.be/-luwKpfaf2M
- **Open dataset (access-gated, MIT):** https://huggingface.co/datasets/soren19/rogue-attacks-2026-05

ROGUE began as a Bright Data × lablab.ai "Web Data UNLOCKED" hackathon submission (May 2026) and is now developed as a standalone project.

---

## About the author

**Soren Obounou Nguia** — AI / AI-Systems Engineer, Seoul, South Korea. BSc in Computer Science & Engineering, Yonsei University (Feb 2026). Prior work includes "GPTFuzz Optimization for LLM Security," an LLM-security fuzzer that won the Grand Prize at the Yonsei University CS Graduation Exhibition (2024), and LLM-security research with AIM Intelligence.
