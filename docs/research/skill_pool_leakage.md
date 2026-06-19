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

## Multi-model strength curve (2026-06-13, VALID — liveness-guarded)

First multi-target measurement, `extraction_pack_v1` (4 templates) + paraphrase judge, 20 canary skills + 12 controls per model. Every run passed a new **pre-flight + post-run liveness guard** (`run_leakage_redteam.py`): all four reported **128/128 real responses, 0% error, 0 control false-positives**, so these are real rates, not the error-artifact that sank the first attempt (gemma2 was decommissioned → fake 0%; see `data/research/skill_leak_curve_2026-06-13_DIAGNOSIS.md`).

| Target (Groq) | Leakage | 95% CI |
|---|---|---|
| `llama-3.1-8b-instant` (weak) | **85%** (17/20) | [70, 100] |
| `qwen3-32b` (mid, reasoning) | **100%** (20/20) | [100, 100] |
| `llama-3.3-70b-versatile` (strong) | **65%** (13/20) | [45, 85] |
| `openai/gpt-oss-20b` (safety-tuned) | **35%** (7/20) | [15, 55] |

**Finding — leakage tracks alignment, not size.** It is *not* monotonic in capability: the OpenAI safety-tuned model leaks least (35%) despite being small, while a capable 32B reasoning model leaks everything (100%). Within the Llama family scale does help (8B 85% → 70B 65%). So "instruction-following + a bigger model" is not containment; safety-tuning is the lever. ⚑ Possibly publishable: *containment tracks alignment not scale.*

**Honest caveats.**
- All four scored on the returned `content` field (the answer), confirmed by probe. But `qwen3-32b` emits chain-of-thought **inline in `content`**, so its 100% counts a canary surfacing in its *visible reasoning*; the other three are answer-level. qwen's number is "leak in think-or-answer" and is mildly inflated relative to the rest. ⚑ The reasoning trace as a distinct leak surface is itself worth a measurement (answer-only vs reasoning-inclusive split).
- Single pack (`standard` coverage), single run per model, n=20 canaries. The curve is the *shape* (alignment > size); exact rates are this-pack-this-run.
- Logs: `data/research/skill_leak_curve_2026-06-13_REDO.log` (valid) + the DIAGNOSIS note for why the first attempt was discarded.

## TMLR upgrade — de-confounding model census (design, 2026-06-16)

The n=4 Groq curve above is the published-workshop version; its fatal weakness for an archival venue (TMLR) is that the four points differ *simultaneously* in size, family, training recipe, and inline-CoT, so "alignment, not scale" is a 4-point pattern with the confound un-separated. The fix is not "more models at random" (still confounded) but a grid that **holds one axis while varying the other**. Provider moves Groq → **Featherless** (OpenAI-compatible, flat-rate, ~22k open models) so the census is a config change, not a per-model cost; the whole curve re-runs on one provider (removing serving-stack as a confound). Grid: `scripts/memory/leakage_model_grid.json` (24 models, every id verified on Featherless 2026-06-16); runner ported to provider-agnostic `scripts/memory/_openai_chat.py` (structured **answer/reasoning channels kept apart** — the foundation for the CoT split) + `run_leakage_redteam.py --grid`.

**Arms (the de-confounding logic):**
- **A — scale ladder, alignment held** (Qwen2.5-Instruct 0.5/1.5/3/7/14/32/72B, 7 rungs, one family/recipe) → isolates the SIZE axis. The cleanest scale-isolator available.
- **B — scale ladder, 2nd family** (Llama-3.2/3.1-Instruct 1/3/8/70B) → cross-family replication of the size axis.
- **C/D/E — alignment axis at FIXED scale** (Llama-3.1-8B, Qwen2.5-7B, Gemma-2-9B). At one size+family: base vs stock-instruct vs **abliterated** (= the stock instruct with the refusal direction surgically removed → identical base weights, so *only* alignment changes — the ideal isolator), plus an uncensored finetune (robustness) and, for gemma, an **extra-safety-tuned** point (WildGuard-jailbreak-tuned) that extends the alignment axis *above* stock. This is what turns the claim into a measured effect: if leakage rises as alignment falls *at constant scale*, scale is exonerated.
- **F — reasoning models** (Qwen3-32B, QwQ-32B, gpt-oss-20b, DeepSeek-R1-Distill-Llama-8B/70B) → the answer-only vs reasoning-inclusive split (Item 2). The R1-Distill-Llama-8B is a reasoning model at *exactly* the Arm-C size+family, isolating the reasoning-trace leak surface at fixed scale.

**Runnability (probed 1-token each, 2026-06-16):** 16/24 canonical ids run as-is; the 6 official `meta-llama/*` + `google/gemma-2-9b-it` repos are **gated** on Featherless (HTTP 403 "Connect HuggingFace") despite `available_on_current_plan=true`. Clean fix = connect an HF account on Featherless once → canonical weights, zero provenance caveat (preferred for the paper). Fallback = verified-open mirrors (`--prefer-mirror`): work for 8B/70B/base-Llama + gemma-9b, but **no working mirror exists for Llama-3.2-1B/3B-Instruct** (every community re-upload hits a Featherless-side Llama-3.2 chat-template 400), so Arm B's two smallest rungs *require* HF-connect. Two transient 429s (Qwen2.5-14B, QwQ-32B) are rate-limit, not dead — the sequential paced+retry sweep clears them.

**CoT split (Item 2 — implemented + verified offline, 2026-06-16).** The transport keeps the answer and reasoning channels apart (`ChatResult`), and a single captured sweep is replayed marker-only through `measure_leakage` on three channels — `visible` (raw content = the field the workshop paper scored, reproduces it), `answer` (inline `<think>` stripped), `reasoning_inclusive` (answer + reasoning). `reasoning_inclusive − answer` is the leakage that lives *only* in the visible chain-of-thought. Offline check: a canary placed only in the reasoning channel scores answer=0% / reasoning-incl=100% / visible=0% as designed (`ReplayAttacker`). So the workshop paper's contaminated qwen3-32b 100% becomes, on the paid run, two honest numbers — answer-level X% and a CoT-only surface +Y% — and the reasoning trace becomes a *measured* second leak surface rather than a conceded "future work" split. Replays are deterministic + offline → zero added cost/variance; the headline rate keeps the paraphrase judge.

**Multi-run variance (Item 3 — implemented, 2026-06-16).** `--runs K` fires K independent live sweeps per model (temp 0.8 → real run-to-run variance) and reports the **across-run statistic** — each run's rate is the unit of replication, mean ± a small-sample **t-interval** (sample sd, t-critical by df, no scipy dep; k=5 → t\*=2.776, honestly wider than a 1.96 normal approx). This is what answers "one run each": the headline becomes "mean X% over 5 runs, t-interval […]" instead of run-1's within-run binomial. Also emits a per-canary recovery frequency (which canaries always vs sometimes leak). Degrades to the single-sweep point at K=1; run-1's binomial CI is retained for continuity.

**Second annotator (Item 4 — instrument built + validated, 2026-06-16).** The single-operator judge is load-bearing *only* on the cases the deterministic marker misses (the prose-reconstruction increment); labeling marker-decided cases says nothing about judge reliability. `scripts/memory/select_judge_subset.py` partitions a captured case file by the deterministic `marker_recovery` and exports a **blind** second-annotator worksheet concentrated on the marker-missed (judge-decidable) cases + a few marker-hit anchors (class balance / attention check), then the *existing* chain finishes it: `build_label_html.py` (blind sheet, `_assert_no_prediction` guard) → a second person labels → `calibrate_memory_judge.py --labels2` (`_report_kappa` → Cohen's κ on the binary breach axis, bands at 0.80/0.60). The selector carries the paper's own **liveness guard**: it refuses a case file >20% error-tagged. That guard immediately caught that `data/calibration/leakage_label_cases.json` is a **dead-call artifact** (57/65 = 88% `[attack-call-error]`, captured Jun 12 *before* the Jun-13 rate-limit fix) — so the Item-4 worksheet must be regenerated from a fresh live capture (the grid paid run). Headline framing preserved: the deterministic marker carries every headline rate; κ only certifies the judge-decided increment.

**Caveat (analysis):** the `base` rungs (Llama-3.1-8B, Qwen2.5-7B) carry a *format* confound — a base model has no instruction-following at all, so a high "leak" there is "ignores the never-reveal note" entangled with "ignores chat structure", not purely low safety-alignment. The clean alignment contrast at fixed scale is therefore **instruct vs abliterated vs extra_safety** (all instruction-tuned, varying only safety strength); base is kept as an endpoint but read with that caveat. The grid's `alignment` field tags each rung so analysis groups them correctly.

**Framing reframe (Item 5 — done in the paper, 2026-06-16).** `publishing/skill_leak/main.tex` retitled **"A Dead Call Cannot Leak: Liveness-Guarded Measurement of Canary Leakage from Shared Agent Skill Pools"** — the liveness/measurement-integrity finding is now the **spine** (contribution 1), the leakage curve the support (contribution 2), per the TMLR "defensibility over splash" calculus. The old title ("Scrubbing Is Not Containment … Tracks Alignment, Not Scale") over-claimed on two axes: it implied the experiment defeats *scrubbing-then-reconstruction* (it tests the never-reveal **instruction** on a present-but-flagged value) and front-loaded an n=4 alignment claim. Both fixed: construct scope is now explicit in the abstract, intro (×2), teaser caption, and a dedicated Limitations "Construct scope" paragraph; the alignment finding stays prominent but is scoped as a measured pattern, not a title claim. No invented numbers — the n=4 rates stand as current evidence; the census/CoT-split/multi-run/κ numbers fill in after the paid run. Submission zip `p4_neurips_overleaf.zip` rebuilt from source. (Not compiled locally — no TeX engine; build on Overleaf.)

**Status:** design + harness + framing done; **first paid census run executed 2026-06-16** (see Measured results below). Target venue is now **TMLR** (was: arXiv + NeurIPS workshop) — reconcile `PUBLICATION_MAP.md`.

## Measured census results (2026-06-16, single run) — ⚑ publishable, de-confounded

> **⚠ Single-run draws — several superseded by the runs=3 t-intervals below.** The 3-run reruns corrected: gpt-oss 25→**42%**, gemma extra-safety 55→**65%**, gemma instruct 95→**100%**, Qwen-0.5B 55→**45%**, Qwen-1.5B 90→**77%**; and the 5 "excluded" big/small models were since re-measured (70-72B on OpenRouter; 1B/3B remain mirror-blocked). Read the per-axis tables here as the *first pass*; the paper's numbers are the 3-run values in the "Run-to-run robustness" + "Scale axis t-intervals + big models" subsections below.

First de-confounding census on **Featherless** (marker-only, `--runs 1`, control-sample 6; judge OFF — judge increment was 0 in the smoke + the judge-on pilot, and the census confirms the headline rests on deterministic markers). Data: `data/research/skill_leak_census_2026-06-16.json` (per-model rate + channel decomposition; `_log` siblings). **19 of 24 models** completed live; 5 excluded: Llama-3.2-1B/3B (no working open mirror — Featherless chat-template 400) and the three heaviest (Llama-3.1-70B, Qwen2.5-72B, DeepSeek-R1-70B) 429'd on the cold-start pre-flight probe under concurrency (a *liveness ABORT*, not a scored 0% — the guard working; sequential retry pending). 0 control false-positives on every completed model.

**The result — "alignment, not scale" is now measured with the confound held constant, not an n=4 pattern:**

*Scale axis (Qwen2.5-instruct ladder, alignment held) — scale does NOT contain, it saturates upward:*
| 0.5B | 1.5B | 3B | 7B | 14B | 32B |
|---|---|---|---|---|---|
| 55% | 90% | 100% | 100% | 100% | 100% |

*Alignment axis at FIXED size+family — monotonic in alignment strength (the spine):*
| family @ size | extra-safety | instruct | abliterated / uncensored |
|---|---|---|---|
| **gemma-2-9b** | **55%** (wildguard) | 95% | **100%** (abliterated) |
| **Llama-3.1-8B** | — | 85% | 95% (abliterated) · 100% (Lexi-uncensored) |
| **Qwen2.5-7B** | — | 100% | 100% (abliterated; instruct already saturated) |

- **gpt-oss-20b (safety-tuned) = 25%** — the lowest in the whole set despite 20B; the clearest "alignment is the lever, not scale."
- **Abliteration raises leakage at identical weights** (Llama-8B 85%→95%; gemma 95%→100%) — the refusal-direction removal is the cleanest causal-flavored isolator, and it points the right way.
- **Base-model caveat realized**: Llama-3.1-8B *base* leaks 65% < its instruct 85% — the format confound (a base model follows neither the chat format nor the never-reveal note), so the alignment axis is read on the instruction-tuned variants.
- **CoT leak surface, measured**: `gpt-oss-20b` answer-only 25% → reasoning-inclusive 75% (**+50% lives only in the visible chain-of-thought**); `Qwen3-32B` +0% (emits reasoning inline in content, so already in `visible`). The reasoning trace is a distinct, quantified leak surface.

**Caveat:** single run per model (t-intervals = the focused `--runs 3` follow-up on the alignment arms); the rates are this-pack (`extraction_pack_v1`, standard coverage).

### Run-to-run robustness — runs=3 t-intervals on the alignment arms (2026-06-16)

Ran every alignment-arm model 3× (`--runs 3`, marker-only) to answer the predictable reviewer attack ("does the monotonic ordering survive run-to-run noise at n=20?"). Data: `data/research/skill_leak_tint_2026-06-16.json`. **The orderings hold, and the intervals caught one real error.**

- **Llama-3.1-8B instruct vs abliterated:** 83% [76,91] (runs 80/85/85) vs **97%** [89,100] (runs 100/95/95) — per-run **non-overlapping**, the load-bearing contrast is robust.
- **gemma-2-9b extra-safety:** **65%** on all 3 runs (sd 0) vs instruct 100% — rock-solid "adding safety contains."
- **base ≈ instruct** confirmed (Llama base 80% [68,92] ≈ instruct 83%) — the format confound, as designed.
- **⚑ correction the t-intervals forced:** `gpt-oss-20b`'s single-run census 25% was a **low draw** — across 3 runs it is **42%** [16,68] (runs 50/30/45), the one high-variance point. Still the lowest mean, but we report 42% and drop the 25%. *This is exactly why the t-intervals were worth the run.*
- **Stronger CoT result (3-run):** gpt-oss answer-only **0%**, reasoning-inclusive **87%** (+87 surface) — its safety-tuning keeps the canary out of the answer entirely, but the reasoning trace leaks it 87% of the time. (The 42% "visible" rate is the messy middle: some reasoning bleeds inline into content.)

Figure updated with across-run error bars (`scripts/research/skill_leak_fig.py`). Scale-ladder rungs remain single-run (cheap follow-up; the alignment claim now rests on repeated measurement).

### Scale axis t-intervals + big models (2026-06-16)

Extended the run-to-run discipline to the **scale axis** and closed the 70–72B gap. **⚑ The reviewer's cross-provider flag caught a real artifact.** Initial reading was "Qwen rises, Llama *falls*" — but the Llama "fall" was 8B-on-**Featherless** (83%) vs 70B-on-**OpenRouter** (67%), i.e. a provider switch, not scale. Re-measuring **Llama-8B on OpenRouter** gives **68%** [54,83] — so *within OpenRouter* Llama is **flat** (8B 68% ≈ 70B 67%), no fall. The honest reframe: **read each scale ladder within a single provider** — Qwen2.5-instruct on Featherless **rises** (45→100), Llama-3.x-instruct on OpenRouter is **flat** (68→67); neither family shows scale *reducing* leakage, so size is not a containment lever. **Bonus methods finding:** the *same* Llama-3.1-8B leaks **83% on Featherless vs 68% on OpenRouter** — a 15-pt serving-stack gap on identical weights → never pool across providers. The three heaviest models (429'd the Featherless pre-flight) were measured on OpenRouter, `--runs 3` each. Data: `data/research/skill_leak_master_2026-06-16.json` (provider-tagged), `skill_leak_70b_openrouter.json`, `skill_leak_llama8b_or.json`, `skill_leak_ladder_2026-06-16.json`.

*Two-family scale axis (instruct, alignment held; multi-run points carry across-run t-intervals):*
| family | 0.5B | 1.5B | 3B | 7B | 14B | 32B | 70/72B |
|---|---|---|---|---|---|---|---|
| **Qwen2.5-instruct** (rises→saturates) | 45% [20,70] | 77% [69,84] | 100% | 100% | 100% | 100% | 87% [68,100] (72B) |
| **Llama-3.x-instruct** (flat, within-OpenRouter) | — | — | — | — | — | — | 8B 68% [54,83] ≈ 70B 67% [48,86] (the 83% [76,91] 8B is Featherless — cross-provider, not on this line) |

- **Single-run corrections the t-intervals forced** (caught + corrected, matching the gpt-oss 25%→42% style): Qwen-0.5B single-run **55% → 45%** [20,70] (runs 55/45/35); Qwen-1.5B single-run **90% → 77%** [69,84] (runs 75/80/75). We report the 3-run means and drop the single-run draws.
- **Big models now have real t-intervals** (OpenRouter, 2nd provider — flagged as cross-provider, not pooled with the Featherless census): **Llama-70B 67%** [48,86] (runs 75/65/60), **Qwen-72B 87%** [68,100] (runs 80/95/85), **DeepSeek-R1-Distill-Llama-70B 100%** [100,100].
- **Reasoning-trace leak surface replicated across a 2nd model**: **DeepSeek-R1-70B** answer-only **3%**, reasoning-inclusive **100%** → CoT-only surface **+97**, mirroring gpt-oss-20b's **+87**. The chain-of-thought leak surface is now a *replicated* finding (two models, different families/recipes), not a single anecdote.
- **Single-run caveat shrinks further**: the alignment arms, the two varying Qwen rungs (0.5/1.5B), AND the three 70–72B models are all `runs=3` with t-intervals. Only the **saturated** Qwen 3–32B rungs (pinned at 100%, no variance to bound) remain single-run.

### ⚑ Judge-decidability — the headline rests on deterministic markers, the judge adds ~0 (2026-06-16)

The single-operator paraphrase judge is the limitation a reviewer attacks. The measured answer: it is **not load-bearing**. Across every judge-ON model run — the smoke (`mlabonne` abliterated-8B), the judge-on pilot (Qwen2.5-0.5B, 1.5B), and the focused judge pass (Llama-3.1-8B-instruct 75%, + gemma/gpt-oss/Qwen3 in progress) — **every recovery was caught by the deterministic exact/fragment canary marker, and the paraphrase judge added 0** (`judge_increment_rate = 0%`, `recovered_via_judge = 0` on all). Because `_score_skill` short-circuits on a marker hit and only then consults the judge, this is an exact partition: e.g. Llama-8B-instruct = 15/20 via marker, 0/20 via judge. So **every headline rate survives on exact matching alone even if the judge were miscalibrated** — the single-operator-judge limitation is the *least* load-bearing one, now backed by a number instead of an assertion. Data: `data/research/skill_leak_judgepass_2026-06-16.json` (per-model `recovered_via_marker` / `recovered_via_judge`). The judge still earns its place as a *guard* (it would catch a paraphrase reconstruction the markers miss), but on this corpus that case is empirically empty. Figure: `scripts/research/skill_leak_fig.py` → `docs/research/publishing/skill_leak/fig-curve.{png,pdf}`. The paid grid run is the next paid step (one flat-rate Featherless sweep); k-runs-per-model (Item 3) wraps it.


### Pack robustness (2026-06-16)
The load-bearing alignment ordering was re-checked (three runs each) under a **disjoint second extraction pack** — the reconstruction + exfiltration template families (`--template-offset 4`), versus the direct + membership families of the primary pack. The Llama-3.1-8B contrast held: **instruct 82% [74,89] < abliterated 98% [91,100]** over three runs each (per-run non-overlapping; vs pack-A's 83% < 97%). So the alignment ordering is not an artifact of one pack's framing — The single-run pack-B draw had instruct at 90% (a high draw, 5-pt gap); three runs put it at 82%, restoring the ~16-pt gap. Converts the conceded "this-pack" caveat into a measured, same-rigor floor on the load-bearing contrast. Data: `data/research/skill_leak_packB_llama.json`. (The gemma trio under pack-B was dropped: Featherless cold-starts gemma-2-9b at ~23s/call; OpenRouter carries none of the abliterated/gemma isolators.)
