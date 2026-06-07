# 0007 — Scheduler reproducibility invariant: "reorder, never exclude"

- **Status:** Binding
- **Date:** 2026-06-08 (retroactive; invariant locked with the contextual scheduler)

## Context

ROGUE's escalation ladder tries strategies across five tiers and stops at the first breach. The contextual scheduler (`ROGUE_LADDER_ORDER`) can change *which strategy is tried first* — including lifting a terminal planner strategy to the front — scored by a scope-widening blend (`0.5·global + 0.3·vendor + 0.2·family + exploration`). The danger: if the scheduler could *drop* strategies, then ASR/cost deltas between ordering modes would be confounded (you'd be comparing different attack sets), destroying benchmark validity and the clean single-variable experiment behind the adaptive-orchestration paper.

## Decision

Every ladder-order mode is a **permutation of the same strategy list** — *reorder, never exclude; same ladder, same attacks, different order, full reachability preserved*. A mode may only change speed-to-breach and what gets reached *under the depth cap*; it can never delete a capability, change the judge, or change which attacks are eventually reachable. The five prior modes (`fixed`, `canonical`, etc.) stay byte-identical; `contextual` is a guarded path. Enforced in `ladder_priors.py`'s `order_by_*` functions and documented in `glossary.md` ("the reorder invariant").

## Consequences

- ASR/cost deltas between modes are attributable to ordering alone — a clean experiment, not a confound (the centerpiece of `docs/adaptive_orchestration_paper.md`).
- Run #0 reproducibility is intact because the prior modes are unchanged byte-for-byte.
- "ASR↑ under contextual" is genuine capability (depth-cap reachability converting held goals into breaches), not a measurement artifact.

## What would reverse this

A deliberate decision to make the scheduler a *filter* (e.g. cost-budget pruning that skips strategies) — which would require explicitly re-baselining benchmarks and abandoning the single-variable claim. Not currently contemplated.
