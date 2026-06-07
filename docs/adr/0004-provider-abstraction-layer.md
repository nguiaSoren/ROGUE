# 0004 — Provider-abstraction layer; no provider SDK types above the adapter boundary

- **Status:** Binding
- **Date:** 2026-06-08 (retroactive; decision 2026-06-04, startup track)

## Context

ROGUE's reproduce layer fans out across many model providers (OpenAI, Anthropic, Groq, OpenRouter, Gemini, and arbitrary customer HTTP endpoints via `rogue scan <url>`). Before the provider-abstraction layer, provider-specific request/response shapes risked leaking throughout `reproduce/target_panel.py` and beyond, coupling business logic to vendor SDKs and making "add a provider" or "scan a custom endpoint" expensive and error-prone.

## Decision

Introduce a provider-abstraction substrate: `src/rogue/core/` defines the vendor-neutral types — `CanonicalMessage`, `InvocationResult`, `TargetCapabilities`, content blocks, attachments, errors — plus the `TargetAdapter` interface, an `AdapterRegistry`, and a conformance suite. `src/rogue/adapters/` holds the per-vendor implementations (`openai`, `anthropic`, `gemini`, `openrouter`, `openai_compat`, `custom`, `mock`). An AST-enforced rule forbids importing provider SDK types **above** `adapters/`: everything upstream speaks only canonical types. `target_panel.py` was migrated onto this with its public `ModelResponse`/`run_attack` contract unchanged; `CustomHTTPAdapter` (driven by `DeploymentConfig.base_url`) implements the `rogue scan <url>` capability (verified live, 1 row to Neon, ~$0.02).

## Consequences

- Adding a provider = one adapter + registry entry + conformance pass; no engine changes.
- Multimodal capability gating (`supports_image`/`supports_audio`) is expressed once in `TargetCapabilities`, consumed uniformly.
- The AST guard is a hard CI-style invariant: a leaked `openai.*`/`anthropic.*` type above the boundary is a build-breaking violation, not a style nit.

## What would reverse this

A single provider monopolizing the product such that the abstraction is pure overhead — not foreseeable, since custom-endpoint scanning structurally requires a vendor-neutral core.
