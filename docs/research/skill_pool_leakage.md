# Measured leakage on a privacy-contained agent-skill pool (Surface 3)

*Lab note · ROGUE Surface 3 (agent memory) · build-08 §6 · 2026-06-11. Companion to the oversight-meaningfulness note.*

## The claim
A shared agent-skill pool is a privacy surface: skills distilled from private work, even after the shared layer "strips entities", can leak the protected content under an extraction attack. "We scrub entities" is not a proof — only an adversarial, measured, published leakage rate counts. Surface 3 produces exactly that: fire an extraction pack at a target agent whose skill/memory holds a confidential datum (a planted **canary**) under an explicit never-reveal instruction, and measure how often the attack recovers it. The recovery check is canary-based and deterministic (the canary actually appears in a response), so the number is ground-truthed, not judge-estimated.

## First real measurement (2026-06-12, corrected)
Against a weak target agent (Groq `llama-3.1-8b-instant`) holding the canary, hit with `extraction_pack_v1` (4 templates/skill): **leakage rate 85% [70%, 100%]** — the agent disclosed the confidential value on **17 of 20** canary skills, despite a "never reveal / never reconstruct / never fill in the redaction" instruction. The **12 sampled non-canary controls produced 0 false-positive recoveries**, so the measurement is clean (a recovered marker is unambiguous real leakage — the scrubbing stripped the canary and its distinctive fragments from the shared body).

> **Correction (transparency).** A first run reported **10% [0%, 25%]** (2/20). That was an *artifact*: the Groq client had no retry/backoff, so the sweep rate-limited the API and ~90% of calls returned error JSON that was silently graded as a non-recovery — a dead call can't leak, so the rate was a massive undercount. It was caught when a human labeler noticed the calibration cases were "all neutral" (i.e. all errors). With the runner fixed (retry/backoff + pacing) and a re-run, the true rate is **85%**. Doubly instructive: instruction-following is near-worthless containment here, AND an un-instrumented red-team can dramatically *under*-report risk.

## Why it matters
The instruction-following defence ("never reveal X") is not a containment guarantee — a weak model leaked **17 of 20** under a *standard* pack. This is the agent-memory analogue of the Surface-1 result: a stated policy is not a measured control. The number is the unit a CISO buys (signed into the attestation chain alongside the other three pool numbers).

## Honest caveats (no overclaim)
- **n = 20 canaries, one weak target model.** The 85% is this target under this pack — not a universal "agent pools leak 85%". A stronger/aligned target would likely leak much less; this is a deliberately weak agent. A stronger pack could recover even more.
- **Marker/fragment-based exact recovery; the paraphrase-judge path was not exercised** this run — for random canary tokens this is the correct, complete measure, but for structured canaries (hostnames, emails) a heavily-paraphrased reconstruction could be undercounted. A judge pass is the next refinement.
- **Coverage: `standard`.** The rate is only as strong as the pack (ADR-0011 coverage calibration) — recorded alongside the number; benchmark vs ClawHavoc/Mitiga/SkillProbe is the path to a comparable figure.

## What would make it a paper
A stronger, coverage-calibrated pack (ClawHavoc/Mitiga-style + a PAIR/iterative attacker) across multiple target models, with the leakage-recovery judge for paraphrase, producing a comparable adversarial leakage rate on a privacy-contained skill pool. ⚑ Possibly publishable.
