# 0001 — Python-only, no Rust

- **Status:** Binding (ROGUE engine + product layer)
- **Date:** 2026-06-08 (retroactive; decision frozen Day 0)

## Context

ROGUE is a continuous open-web LLM red-team. The founder maintains Rust work in *separate* projects, so a "rewrite the hot path in Rust" reflex is a standing temptation. `ROGUE_PLAN.md §13 #1` ranks "a Rust port of anything" as the single most expensive temptation ("Faster, zero judging points. Cost: 12+ hours."). The whole stack is LLM-SDK-bound and I/O-bound (HTTP to Bright Data + model providers, Postgres), not CPU-bound — so a systems-language rewrite buys nothing the judges or customers can see.

## Decision

The entire backend is Python 3.11 (FastAPI, Pydantic v2, SQLAlchemy 2.0, `asyncio` + `httpx`). No Rust anywhere in this repo — no native extensions, no PyO3, no "just the embedding loop." Performance concerns are addressed with async I/O, batching, and Postgres indexing, never with a second language. This is explicitly distinct from the founder's separate Rust codebases, which share no code with ROGUE.

## Consequences

- One language, one toolchain (`uv`), one mental model; every LLM SDK is Python-first.
- Concurrency is cooperative `asyncio`, not threads/processes — acceptable because the workload is network-bound.
- If a genuinely CPU-bound bottleneck ever appears, the first move is profiling + vectorized NumPy / a C-backed library, not a Rust module.

## What would reverse this

A profiled, sustained CPU-bound hotpath (not I/O wait) that dominates cost and cannot be removed by batching or a C-backed Python library — and even then, the bar is an isolated extension via PyO3, never a port.
