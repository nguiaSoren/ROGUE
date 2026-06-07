# 0003 — No LangChain/LangGraph; hand-rolled agents

- **Status:** Binding
- **Date:** 2026-06-08 (retroactive; decision frozen Day 0)

## Context

ROGUE has real agentic loops: the `DiscoveryAgent` (epsilon-greedy bandit over a 52-query SERP pool, learning yield-per-dollar across runs), the `ExtractionAgent` (structured-output field selection), the escalation planner, and the reproduce/judge panel. The reflex for "agent" + "tool use" + "multi-step" work is to adopt LangChain/LangGraph. `docs/architecture.md` ("No LangChain / LangGraph. Adds an abstraction layer we fight more than benefit from.") and `ROGUE_PLAN.md` (async orchestration = "`asyncio` + `httpx.AsyncClient`; LangGraph adds complexity without payoff") lock against it. Provider structured output (Pydantic v2) and tool-calling are already first-class in the native SDKs.

## Decision

Agents are hand-rolled over `asyncio` + `httpx` + Pydantic v2 with direct provider SDK calls (routed through the adapter layer, see ADR-0004). No LangChain, LangGraph, LlamaIndex, or comparable agent framework anywhere. State (discovery memory, bandit posteriors, ladder telemetry) lives in Postgres, not a framework's memory abstraction. MCP is used directly (ROGUE is both an MCP consumer for Bright Data and an MCP producer for its threat DB), not via a framework wrapper.

## Consequences

- Full control over control flow, retries, cost accounting, and prompt construction; no framework version churn or leaky abstraction to debug.
- More glue code written in-house (bandit, escalation ladder, conformance) — accepted as the cost of transparency, and these are the project's differentiators anyway.
- Reproducibility is exact: every step is explicit Python, which the scheduler reproducibility invariant (ADR-0007) depends on.

## What would reverse this

Nothing short of a framework becoming the *only* practical way to reach a required provider capability — and even then, isolated behind the adapter boundary, never threaded through the engine.
