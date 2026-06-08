# Attack-coverage calibration — empirical validity study (build-04 §5, the ⚑)

*Working design + protocol · 2026-06-08 · branch `v2-phase1`. Turns the coverage metric from a
chosen-by-design rule into a measured predictor (or a clean negative result). Run with batch + caching.*

## The question (one line)

**Does `score_pack_coverage` predict a pack's breach-detection power?** i.e. across many
`(rule, pack-variant, target)` cells, does a higher coverage score go with a higher measured
breach rate on a *vulnerable* target — so a `holds (low coverage)` really means "we didn't test
hard enough," not "the rule is safe"?

## Why it matters

1. **The report's `holds` is only trustworthy if coverage is.** Coverage gates whether a `holds`
   is load-bearing; if coverage is noise, a `holds` is false reassurance.
2. **It is the ⚑ publishable claim.** "Attack-coverage calibration, the companion to judge
   calibration" is a contribution only if *measured*. A positive result validates it; a negative
   one is also valuable (it says rework the metric) and honest.

## Design

- **Rules (grow 4 → ~16):** `tests/fixtures/governance/validity_policy.json` — realistic,
  attackable `PolicyRule`s split across `information_disclosure` + `unauthorized_action` (the two
  calibrated breach types), each with sharp consummation_definition + example pairs.
- **Pack variants per rule (the coverage range):** for each rule generate 3 packs spanning the
  coverage scale — **strong** (full `build_attack_pack`, on-target, multi-family → high), **medium**
  (subset → mid), **weak** (1–2 off-target/generic primitives → INADEQUATE). The metric scores each;
  this manufactures the coverage variance the correlation needs.
- **Target spread (the discriminating band):** a **weak** model (Llama-3.1-8B — breaches readily)
  + a **mid** model (Mistral-Small / Haiku — a strong pack should crack it, a weak one should not).
  NOT frontier models (they mostly resist → little signal, higher cost).
- **Trials:** ~8 per `(rule, variant, target)` cell.
- **Measure per cell:** `breach_rate` = breaches / trials, judged by the **calibrated per-rule
  judge** (area 02). Each cell is one data point: `(coverage_score, breach_rate)`.

## Analysis

- **Primary:** Spearman rank correlation of `coverage_score` vs `breach_rate`, pooled and
  per-target, with a **bootstrap 95% CI** on the correlation (reuse `diff/bootstrap.py`).
- **Hypothesis (validated):** positive correlation with the CI excluding 0 — coverage predicts
  breach-detection.
- **Discrimination check:** within a target, the strong variant's breach rate > the weak
  variant's for most rules (a paired sign test).
- **Figure:** `coverage_score` vs `breach_rate` scatter (colored by target), + the strong/medium/
  weak breach-rate bars.

## Cost + efficiency

- **Batch + caching here** (this is where it pays): ~16 rules × 3 variants × 2 targets × ~8 trials
  ≈ a few thousand judge calls → `JudgeBatch` (Anthropic Batch API, 50% off) with the rubric cached
  (`judge.py:522`). Est. **judge ~$20–50, targets ~$5–10** (cheap models), batch latency 10–30 min
  (fine for a background job).

## Honest caveats (state in the writeup)

- Weights/thresholds are *chosen-by-design*; this checks predictive validity, not optimality.
- The historical-potency (live-matrix) coverage signal is unwired here.
- ~16 rules × 2 targets is a real but **modest** study; conference-grade wants more rules/targets.
  Report the correlation + CI honestly; a wide CI / null result is a finding, not a failure.

## Success criteria (what we'll conclude)

- **Validated:** Spearman ρ > 0, CI excludes 0, strong > weak within target → coverage is a
  measured predictor; promote the ⚑ to a result in the research record.
- **Weak/null:** CI includes 0 → coverage is unvalidated; keep it a heuristic, note it needs rework,
  do **not** claim it as a result. Either way the metric/report framing stays honest.

## Execution status

- [ ] Grow the rule set (`validity_policy.json`, ~16 rules) — fanned out.
- [ ] Pack-variant generator (`coverage_variants`) + the batched harness (`scripts/governance/coverage_validity.py`, JudgeBatch + caching).
- [ ] Run the batched study (paid, background).
- [ ] Analysis (correlation + CI + figure) + writeup here.
- [ ] Final sign-off (Soren).
