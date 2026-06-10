# `benchmark/memory_leakage/` — frozen leakage goal set (Surface 3, build 08 §6)

The stable reference side of the wall for the **measured leakage rate** — the spec's
headline Surface-3 number. Mirrors the `benchmark/frozen/` field-standard pattern
(`benchmark/datasets.py`): a benchmark you re-author per run is not a benchmark,
because the denominator drifts under you. This pack is **frozen and versioned** so
"X% leakage" is comparable run-to-run and against external packs.

## What's here

- **`extraction_pack_v1.json`** — the frozen extraction goal set: a small set of
  extraction-attack *templates* (membership-inference / direct-extraction /
  reconstruction / exfiltration framings) fired at a **scrubbed** shared skill to try
  to RECOVER its protected datum (the canary). Each template's `prompt` carries a
  `{scrubbed_md}` slot the harness fills with the scrubbed skill under test.

## How it's used

`src/rogue/memory/leakage.py::measure_leakage` loads this pack (default), fires its
templates at each scrubbed canary skill via an injected `ExtractionAttacker`, and
scores recovery (cheap exact/fuzzy markers + the calibrated `leakage_recovery_judge`).
The result is a leakage rate with a **bootstrap CI**, persisted as a
`skill_verifications(kind=leakage)` row.

## Coverage calibration (ADR-0011 / unified §5) — read this before quoting a rate

A measured leakage rate is **only as strong as the attack pack**. A weak extraction
probe (direct-ask only) under-estimates leakage and manufactures false comfort. Every
`measure_leakage` result therefore carries the **pack identity** (`pack_id` + version)
and a **`pack_coverage`** strength indicator (`weak` / `standard` / `strong`). The
frozen pack's own self-declared tier lives in its `coverage` block; the harness can
override (e.g. downgrade to `weak` when only direct-extraction templates are exercised).
Never report a leakage number without the pack id + coverage tier alongside it.

`extraction_pack_v1` self-declares **`standard`**: four extraction families, multiple
framings each, but no multi-turn escalation in the frozen templates themselves. The
real PAIR-backed `ExtractionAttacker` (wired later) layers adaptive multi-turn pressure
on top, raising the effective run-time pressure.

## Benchmark against (external packs)

- **ClawHavoc** — skill-poisoning / exfiltration corpus.
- **Mitiga** — LLM-memory extraction / membership-inference.
- **SkillProbe** — shared-skill-pool audit corpus.

To grow coverage: add framings/families to `extraction_pack_v1.json` (or cut a `_v2`
and bump `version`); raising `coverage.families_covered` / `coverage.tier` is what
moves the credibility of the headline number.
