# Measured leakage on a privacy-contained agent-skill pool (Surface 3)

*Lab note · ROGUE Surface 3 (agent memory) · build-08 §6 · 2026-06-11. Companion to the oversight-meaningfulness note.*

## The claim
A shared agent-skill pool is a privacy surface: skills distilled from private work, even after the shared layer "strips entities", can leak the protected content under an extraction attack. "We scrub entities" is not a proof — only an adversarial, measured, published leakage rate counts. Surface 3 produces exactly that: fire an extraction pack at a target agent whose skill/memory holds a confidential datum (a planted **canary**) under an explicit never-reveal instruction, and measure how often the attack recovers it. The recovery check is canary-based and deterministic (the canary actually appears in a response), so the number is ground-truthed, not judge-estimated.

## First real measurement (2026-06-11)
Against a weak target agent (Groq `llama-3.1-8b-instant`) holding the canary, hit with the frozen `extraction_pack_v1` (8 templates: direct-extraction / membership-inference / reconstruction / exfiltration-framing): **leakage rate 10% [0%, 25%]** — the agent disclosed the confidential value on **2 of 20** canary skills (`skill-004`, `skill-016`), despite a "never reveal / never reconstruct / never fill in the redaction" instruction. The **35 non-canary controls produced 0 false-positive recoveries**, so the measurement is clean (a recovered marker is unambiguous real leakage, not a scorer artifact — the scrubbing stripped the canary and its distinctive fragments from the shared body).

## Why it matters
The instruction-following defence ("never reveal X") is not a containment guarantee — a weak model leaked 1-in-10 under a *standard* pack. This is the agent-memory analogue of the Surface-1 result: a stated policy is not a measured control. The number is the unit a CISO buys (signed into the attestation chain alongside the other three pool numbers).

## Honest caveats (no overclaim)
- **n = 20 canaries, one weak target model.** The 10% is this target under this pack — not a universal "agent pools leak 10%". A stronger/aligned target would likely leak less; a stronger pack would likely recover more.
- **Marker/fragment-based exact recovery; the paraphrase-judge path was not exercised** this run — for random canary tokens this is the correct, complete measure, but for structured canaries (hostnames, emails) a heavily-paraphrased reconstruction could be undercounted. A judge pass is the next refinement.
- **Coverage: `standard`.** The rate is only as strong as the pack (ADR-0011 coverage calibration) — recorded alongside the number; benchmark vs ClawHavoc/Mitiga/SkillProbe is the path to a comparable figure.

## What would make it a paper
A stronger, coverage-calibrated pack (ClawHavoc/Mitiga-style + a PAIR/iterative attacker) across multiple target models, with the leakage-recovery judge for paraphrase, producing a comparable adversarial leakage rate on a privacy-contained skill pool. ⚑ Possibly publishable.
