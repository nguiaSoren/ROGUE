# The grey-literature reproducibility gap — study skeleton (the ⚑)

*Working design + protocol · 2026-06-12 · branch `v2-phase1`. Tests whether publicly-claimed jailbreaks survive transfer to current, independently-judged deployments — reframed after a fan-out scoop check (Jailbreak Foundry, StrongREJECT) from "claimed-vs-measured ASR gap" to a carrier-mechanism reproduction audit stratified by source type. Core analysis runs on the 11,098 breach rows already collected; likely zero new paid runs.*

## The thesis (one line)

**Most grey-literature-claimed jailbreak techniques (Reddit / GitHub / blogs / X) do not survive as a working *carrier mechanism* under conservative independent judging in a realistic deployment context — and community-sourced attacks reproduce materially worse than paper-sourced ones, where prior work already showed the gap is near-zero.** A source's claimed potency does not predict whether its mechanism reproduces.

## Why it matters

1. **It is uniquely ROGUE.** The differentiator is the corpus: 459 primitives across six source types, harvested continuously from the open web, reproduced against real `DeploymentConfig`s (model × system_prompt × tools). No prior reproducibility study covers the grey literature where inflated claims actually live, and none reproduces in deployment context rather than against bare AdvBench/HarmBench prompts.
2. **It is ⚑ publishable as a negative/measurement result** — and the core is computable from data already collected, so it is the cheapest high-value paper in the queue after the K-saturation hardener.

## Positioning vs prior art (what is scooped, what is open)

- **Jailbreak Foundry** (arXiv 2602.24009, Feb 2026) — a continuous papers→runnable-attacks framework, reproduces 30 *published* jailbreaks across 10 models and reports the claimed-vs-reproduced ASR gap directly, finding it ≈0. **Scoops** the generic "continuous reproduction audit of the literature." **Leaves open:** academic-paper sources only — no community/grey-literature population, no deployment-config context, conventional (non-conservative) judges.
- **StrongREJECT** (Souly et al., arXiv 2402.10260, NeurIPS 2024) — establishes that published ASRs are inflated by weak judges, owns the Scots-Gaelic exemplar. **Scoops** "judges inflate ASR." **Leaves open:** it is a judge/metric paper, not a cross-source population audit; ROGUE's calibrated-conservative judge is the *answer* to its critique, not a competing claim.
- **JailbreakRadar** (Shen et al., arXiv 2402.05668) and **"Do Anything Now"** (Shen et al., CCS 2024, arXiv 2308.03825) — unified re-measurement of academic attacks; the latter measures 1,405 in-the-wild prompts but does **not** frame it as a claimed-vs-measured replication audit (in-the-wild prompts rarely carry a quantified source claim). **Leaves open** the claim-vs-reproduction audit on the grey literature.

**Residual defensible novelty:** the source-heterogeneity contrast (community gap ≫ paper gap ≈ 0), in deployment context, re-judged by a judge calibrated to *under*-count. Do **not** lead with "continuous" or "we found jailbreaks are inflated" — both are spent.

## Corpus (live Neon, 2026-06-12)

| Quantity | Value |
|---|---|
| Total primitives | 459 |
| Primitives with measured (non-error) breaches | 369 |
| Breach rows collected (all non-error) | 11,098 |
| Distinct primitive × config cells | 1,834 |
| Primitives with a numeric `claimed_success_rate` | 70 |
| **…that also have measured breaches (the C2 sample)** | **56** |

**Claimed-rate distribution skews implausibly high:** a spike at `1.000 ×22` plus a fat tail at 0.95–0.99 — twenty-two sources claim *perfect* success. This is a figure in itself.

**Source-type coverage (distinct primitives / how many carry a claimed number):**

| source_type | primitives | with claimed rate |
|---|---|---|
| github | 149 | 3 |
| reddit | 91 | 13 |
| arxiv | 81 | 33 |
| blog | 60 | 15 |
| huggingface | 7 | 6 |
| x | 3 | 0 |

So the paper-vs-community contrast runs on **two axes**: binary reproduction (303 grey-lit vs 81 arxiv primitives) and the claimed-number subset (33 arxiv-claimed vs ~28 community-claimed: reddit 13 + blog 15).

## Design — three claims, each confound-controlled

**Unit of analysis:** the `(primitive × panel-model)` cell, N≥5 trials, Wilson CI per cell. Aggregate to per-primitive "reproduces as carrier" = `any_breach_rate ≥ τ` on ≥1 panel model, τ pre-registered at 0.4 (matches the existing threat-brief breached-set threshold), sensitivity sweep over τ ∈ {0.2, 0.4, 0.6}.

- **C1 — binary carrier reproduction (headline, well-powered, runs on the full 369-primitive measured set).** Does the technique's *carrier* (its family/vector structure) still bypass a current model at all, toward a neutral objective? Report the fraction reproducing, pooled and **stratified by source_type** (the grey-lit-vs-arxiv contrast). Behavior-agnostic, so it never compares ASR magnitudes → immune to the proxy confound.
- **C2 — claimed potency does not predict reproduction (the ⚑ null, now powered at n=56).** Among primitives carrying a numeric claim, is `claimed_success_rate` correlated with measured `any_breach_rate`? Spearman ρ + bootstrap 95% CI (reuse `diff/bootstrap.py`). Hypothesis: **null/weak** — a source claiming 95% reproduces no better than one claiming 50%. A null is publishable and is immune to the level-shift confound. Sub-cut: arxiv-claimed vs community-claimed.
- **C3 — measured family ordering ≠ the literature's implied ordering.** Rank families by measured carrier-reproduction; show the most-claimed/most-cited families are not the most reproducible. Ordering claims survive the proxy confound (techniques compared to each other under one fixed measurement).

### Confound controls

1. **Proxy behavior (harmful goal → neutral goal).** ROGUE substitutes only the `{target_behavior}`/`{target_topic}` slots with a neutral objective (system-prompt exfiltration, the `slot_defaults.json` default) while holding the harvested family/vector/template fixed. Frame C1 as *carrier viability*, not harm ASR: proxy **failure ⇒ strong evidence of carrier death** (system-prompt disclosure is less hardened than CBRN, so a carrier that can't even get the easy neutral behavior almost certainly fails the harder one). State explicitly in the abstract: "we measure whether the delivery mechanism still defeats alignment, not whether the harmful payload reproduces — the latter we deliberately do not test."
2. **Panel / version drift ("models got safer" vs "claim was inflated").** Cannot run the exact (often deprecated) claimed model black-box, so do **not** claim to separate inflation from patching. Instead: include **Llama-3.1-8B as a frozen open-weight anchor** — a carrier that fails there cannot be blamed on a silent hosted-endpoint patch. Report C1 pooled *and* Llama-anchor-only (the patch-immune number). Stratify by `target_models_claimed ∩ panel`.
3. **Judge mismatch — ROGUE's asset, lead with it.** Use the v3 consummation-gated judge (89.3–91.0% JBB human agreement, 2.56% in-dist FP-breach, κ≥0.80, and measured **more conservative** than WildGuardTest and StrongREJECT). If a judge calibrated to *under*-count says a technique doesn't reproduce while a lenient source judge called it a success, the discrepancy is itself part of the gap story. Cite `judge_calibration_paper.md` Table 1 verbatim; pre-register the 4-way→binary map (`verdict_projection.py`).
4. **Augmentation OFF for the primary measurement.** Reproduce the harvested primitive as-is — no PAIR, no escalation children, no slot-fill A/B (augmentation swings breach rate 1.6%→68%, which would make "does it reproduce" unfalsifiable). Single-turn primitives judged single-turn; `requires_multi_turn` run their `multi_turn_sequence`. Temperature pinned, N≥5, per-cell Wilson CI.

## Figures

- **Figure 1 — the reproduction funnel (headline).** Horizontal waterfall: *N harvested → N with extractable claim → fraction reproducing as carrier on ≥1 current model → fraction on the open-weight anchor (patch-immune) → fraction on the most-robust model (Claude Haiku).* The collapse from "claimed working" to "still a working carrier under conservative judging" is the paper. Draw it **twice, side by side: arxiv vs grey-literature.**
- **Table 1 — carrier reproduction by family, stratified.** Rows = `AttackFamily`; cols = [n, % reproduce pooled (Wilson CI), % Llama-anchor, % Claude-Haiku, median claimed rate where available]. Carries C3 + model-dependence.
- **Figure 2 — claimed vs measured scatter (C2, n=56).** x = `claimed_success_rate`, y = measured `any_breach_rate`, colored by source_type; show the Spearman ρ + CI. The `1.000 ×22` cluster will be a vertical stack at x=1.0 — annotate "22 sources claim 100% success; k reproduce."

## Cost + data status

- **C1, C2, C3 core analysis: $0 new spend — confirmed by coverage audit (2026-06-12).** Of 301 baseline (non-synthesized) measured primitives, **291 have ≥5 baseline (non-PAIR) trials on ≥1 panel model** (all 301 have ≥3); **all 56 claimed+measured primitives clear N≥5**. Augmentation contamination is negligible (92 PAIR rows + 764 synthesized-primitive rows of 11,098; baseline filter keeps 10,244). The **Llama-3.1-8B open-weight anchor is fully covered (298 primitives, 1,917 rows)** → the patch-immune stratum is powered. Panel = 5 consistent configs (claude-haiku, gemini-flash-lite, gpt-5.4-nano, mistral-small, llama3, all 2026-05-26, ~300 prims each); claude-opus (2026-05-31) covers only 38 → bonus column, not the robust anchor (use claude-haiku). **Both contrast axes survive the N≥5 filter:** C1 binary = grey-lit 205 (github 101 + reddit 65 + blog 38 + x 1) vs arxiv 79; C2 claimed = arxiv 33 vs community 23 (blog 8 + reddit 7 + hf 6 + github 2). No targeted `reproduce_once` top-up required for the headline.
- **Optional C2 strengthener (LLM cost only, $0 Bright Data):** re-run extraction with a claimed-ASR-targeted prompt over stored `raw_document`s to lift the 70 claimed-rate primitives higher and tighten the correlation.

## Honest residual risks (state in the writeup)

1. **The neutral proxy is load-bearing and one-dimensional** — all neutral testing routes to system-prompt exfiltration; a carrier specialized to harmful-content elicitation could fail here for unrelated reasons. C1 measures carrier viability against *one* neutral objective; a multi-objective neutral panel is future work.
2. **Version drift is bounded, not eliminated** — the open-weight anchor isolates *some* of the patch confound; for techniques claimed only against a hosted model, inflation and patching remain inseparable. Concede this stratum is interpretively capped.
3. **Survivorship / extraction bias** — the corpus is "techniques expressible in ROGUE's 14-slot grammar"; bespoke/image-only/model-internal techniques are under-represented, and non-reproduction could partly reflect lossy extraction. Condition C1 on the extraction `reproducibility_score` distribution and concede the scope.
4. **"Reproducibility gap" invites the strong (inflation) reading** even though we license only the weak (carrier non-transfer) reading. Pre-empt in the first two sentences of the abstract.
5. **Coverage adequacy** — a `holds`/non-reproduction is only trustworthy if tested hard enough; cite the coverage-validity result (`coverage_validity_study.md`, ρ=0.35, strong>weak monotone, 0 reversals) to argue non-reproductions are adequately tested, not weakly tested.

## Success criteria

- **Result (expected):** grey-lit carrier-reproduction fraction ≪ arxiv fraction (Fig 1 contrast clean); C2 ρ near 0 with CI including 0 (claimed potency is not portable signal); C3 ordering mismatch visible. → promote the ⚑ to a measured result.
- **Surprise (also publishable):** community attacks reproduce *as well as* paper attacks → overturns the expectation, equally a finding.
- **Underpowered:** if the N≥5-with-augmentation-off coverage audit guts the usable n → lead with C1 binary on whatever survives, report C2 as descriptive, flag the top-up run needed.

## Results — first run (2026-06-12, $0, collected data)

`scripts/research/reproducibility_gap.py` over 301 baseline primitives / 10,244 baseline rows / 5-model panel. All three claims came back as hypothesized. The harness is pinned to this frozen snapshot (`SNAPSHOT="2026-06-12"`, an exclusive `ran_at` cutoff) so it reproduces these aggregates bit-for-bit regardless of later DB writes; the per-primitive (claimed, measured) table is released as `data/research/reproducibility_gap_pairs.csv`, from which the C2 null and the C1 funnel recompute without database access.

**C1 — the reproduction collapse (the spine, unambiguous).** Carrier reproduction at τ=0.4 falls sharply as the target gets harder, with non-overlapping CIs:

| set | n | reproduces on ≥1 of 5 models | on frozen Llama-8B anchor | on robust Claude-Haiku |
|---|---|---|---|---|
| ALL | 301 | 0.405 [0.352, 0.462] | 0.090 [0.060, 0.123] | 0.037 [0.017, 0.060] |
| arxiv | 79 | 0.519 [0.405, 0.620] | 0.139 [0.076, 0.215] | 0.089 [0.025, 0.152] |
| grey-lit | 222 | 0.365 [0.302, 0.428] | 0.072 [0.041, 0.108] | 0.018 [0.005, 0.041] |

So a technique's "works on at least one of five models" rate (40.5%) collapses ~4.5× to the frozen open-weight anchor (9.0%) and ~11× to the robust model (3.7%) — the "best-of-5" figure is inflated by the weakest target; the fixed-target numbers are the honest carrier-viability rates. Robust to threshold: any-model reproduction is 56.5% at τ=0.2 and 31.2% at τ=0.6.

**Source heterogeneity (directionally clean, widens on hard targets).** arxiv-sourced techniques reproduce better than grey-literature ones at every stage, and the gap *grows* as the target hardens: ~1.4× on best-of-5, ~1.9× on the Llama anchor, **~5× on the robust model (8.9% vs 1.8%)**. The gap approaches significance only at the robust anchor (CIs [2.5,15.2] vs [0.5,4.1] just touch); a larger arxiv n (currently 79) would confirm it. Stratification is clean — 0 primitives carry both an arxiv and a community source.

**C2 — the ⚑ null holds (n=56).** Claimed potency does **not** predict measured reproduction: Spearman(claimed, measured pooled) = **−0.098, 95% CI [−0.374, +0.171]** (includes 0, slightly negative); max-rate variant −0.137. The CI rules out any correlation stronger than ρ≈0.17 — claimed numbers are not portable signal. Holds in both strata (arxiv-claimed +0.10, community-claimed −0.18, both CIs include 0). **The money shot:** of the 17 techniques claiming ~100% success, only **7 reproduce at τ=0.4** and their **mean measured breach rate is 13.3%**.

**C3 — family ordering ⊥ claimed ordering (descriptive, underpowered).** Spearman between the measured-reproduction family ordering and the mean-claimed-potency ordering = **−0.044 [−0.73, +0.55]** over the 12 families carrying claims — i.e. no relationship, but the CI is wide (only 12 families). Extremes illustrate it: `training_data_extraction` reproduces 100% (claimed 0.98), while `chain_of_thought_hijack` reproduces **0%** despite a mean claim of 0.955, and `system_prompt_leak` (claimed 1.000) reproduces 0.370.

**Result-specific caveats (beyond the design risks above):**
- **Temperature — checked, not a confound (2026-06-12).** Baseline rows span T=0.7–1.1 (not pinned per cell, so a single-temperature subset can't keep N≥5), but the breach rate is near-flat across the band (9.1% at T=0.7 → 12.7% at T=1.1, lowest temp most conservative). Recomputing the ALL-set funnel on temperature subsets confirms the collapse is not a temperature artifact: pooled 40.5/9.0/3.7%, **T=0.70-only 36.5/8.6/2.7%, T≥0.80 38.0/7.0/3.2%** (any-model / Llama-anchor / robust). The headline funnel shape and magnitude are stable; the unpinned-temperature pooling does not bias C1.
- The **source gap is only borderline-significant** (clean direction, overlapping-at-the-edges CIs); state it as "consistent and growing on hard targets," not "established," pending more arxiv primitives.
- **C2's null** rules out a *strong* claimed→measured correlation at n=56, not a weak one. **An attempt to grow n confirmed the n is data-limited, not extraction-limited (2026-06-12, ~$3):** re-fetching all 142 arxiv/blog/hf candidate sources and re-extracting with Sonnet 4.6 (Batch API, prompt-cached; `scripts/research/grow_claimed_rates.py`) recovered a rate for only **1 of 89 currently-null** candidates — the other 88 sources genuinely state no success rate even under a stronger extractor reading the full document. Quantified claims are arxiv-concentrated and largely absent from grey-literature, so the small claimed-rate sample is a property of the corpus, not of the (Haiku) extractor.
- **Claimed-rate values carry extraction noise — C2 is a qualitative null, not a precise ρ.** The same re-extraction is a uniformity check on the existing 56: Sonnet agrees with the original (Haiku) value on **33/40 (82%)** of the overlap, but **7/40 disagree materially (>0.07)** — mostly the original being inflated/unsourced (e.g. 0.72→0.30 where the source says "23.0%–30.2%"), though Sonnet also errs (an "0% refusal" polarity flip). Neither extraction is ground truth, so the claimed axis has ~17% material noise; this attenuates any true correlation toward 0 and means the −0.10 estimate should be read as "no predictive signal," not a point estimate. Bulk-overwriting with the Sonnet values was **declined** (it would trade one noise source for another); the 7 disagreements are flagged for optional manual adjudication. Results: `data/research/reextracted_claims.json`.

**⚑ Publishable.** The reproduction collapse + the "claims 100%, delivers 13%" null + the conservative-judge/open-weight-anchor method are a clean, mostly-negative result on the open-web grey literature, computed entirely on collected data. Results JSON: `data/research/reproducibility_gap_results.json`.

## Execution status

- [x] Scope + scoop check (5-agent fan-out, 2026-06-12) — reframe locked, prior art mapped.
- [x] Corpus sizing on live Neon — 459 / 369 / 56 / 11,098, source-type + claimed-rate distributions captured (above).
- [x] **Coverage audit (2026-06-12):** 291/301 baseline primitives ≥5 trials, 56/56 claimed ≥5, Llama anchor 298 prims, both contrast axes powered → **no paid top-up needed for the core**.
- [x] **Build the analysis harness (2026-06-12)** — `scripts/research/reproducibility_gap.py` (bootstrap CI on fractions via `diff/bootstrap.py`; self-contained Spearman + paired-bootstrap CI; source strata; τ sweep). First run complete, results above + `data/research/reproducibility_gap_results.json`. Remaining: render the three figures.
- [x] **Temperature-robustness confirmation (2026-06-12)** — funnel stable across T=0.7-only / T≥0.8 / pooled; C1 is not a temperature artifact (results above).
- [x] **Claimed-ASR re-extraction (2026-06-12, ~$3, Sonnet 4.6 Batch + cached):** re-fetched 142 arxiv/blog/hf sources, re-extracted — **+1 newly-claimed** (n data-limited, not extraction-limited) and a uniformity audit (33/40 agree, 7 material disagreements). `--apply` to Neon **declined** (n-gain negligible; bulk overwrite trades noise for noise). Findings folded into the C2 caveat. `scripts/research/grow_claimed_rates.py`.
- [ ] Write up against `judge_calibration_paper.md` + `coverage_validity_study.md`; do not reinvent the judge-credibility numbers.
- [ ] Sign-off (Soren).
