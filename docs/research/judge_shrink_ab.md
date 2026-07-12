# Judge-shrink A/B gate + reference-anchored grading (Q1)

**Status:** BUILT 2026-07-08 · off by default · byte-identical when off · $0 offline result in hand, one paid arm pending for the reference-lever headline.

**One line:** a κ-based decision gate that says *whether a cheaper judge model can replace the Sonnet breach grader without moving verdicts* — measured on ROGUE's own human-labeled data, not assumed — plus an off-by-default **reference-anchoring** lever (Krumdick's "give the judge a verified reference" fix, translated to a breach judge that has no per-trial gold answer).

---

## Why this exists (the ROGUE hook)

The judge is a **per-trial** cost. On a paid reproduce cycle the calibrated LLM judge (`JUDGE_MODEL`, default `anthropic/claude-sonnet-4-6`) is called once per trial and is the dominant marginal cost after the target calls themselves. A cheaper grader that held agreement would cut that cost directly. The naive move — "just set `JUDGE_MODEL` to something small" — is already *possible* (the env var has always been read); what was missing is the **honest instrument to decide whether it is safe**, and a **lever to close the gap** if it is not.

This is deliberately **not** a plan to shrink the main breach grader by fiat. It is the measurement + gate that lets us answer the question with numbers.

## What the literature actually says (grounded, fact-checked against the papers)

Three papers were pulled in full (crawl4ai → ar5iv) and checked line-by-line against the source, because the upstream Elicit digest misattributes numbers.

- **Krumdick, "No Free Labels" (2503.05061).** A *weaker* judge (Qwen-2.5-7B) handed a **verified gold reference** reaches **κ=0.63**, beating a *stronger* judge (GPT-4o) with a self-generated reference (**κ=0.52**) — "putting the correct answer in context reduces the overall complexity of the judging task." **The load-bearing caveat:** the reference must be *verified correct*. A subtly **wrong** reference drops to **κ=0.21 — below no-reference (κ=0.46)**; a model's *own* reference exacerbates self-preference bias. Their metric is Cohen's κ with bootstrap CIs; the task is binary correct/incorrect.
- **Thakur, "Judging the Judges" (2406.12624).** On per-item binary verdicts, **only the largest judges align** (GPT-4-Turbo κ=84, Llama-3-70B κ=79 vs a human ceiling of κ=96 — a **12-point** gap, not the "8" the digest claimed; metric is **Cohen's κ, not Scott's π** as the digest claimed). Small judges match large ones on **system-level ranking** (Contains/JudgeLM-7B ρ≈0.98) — *not* on per-item verdicts (the digest's "Mistral-7B ρ=0.98/0.99" is fabricated; Mistral-7B is 0.92). Two warnings map straight onto a breach judge: small judges carry a **leniency bias** (they over-fire the *positive* class when unsure → for ROGUE, they **over-call breaches**) and a **precision deficit** (more false positives, recall is fine); and **you cannot rescue a small judge with a longer rubric** — small judges get *less* aligned as instructions grow.
- **Loiseau, "Distilling…Privacy Sensitivity" (2603.29497, LREC 2026).** An encoder student (Ettin-150M) distilled from a 675B teacher on **hard labels only** (no logits, no human labels for training — human labels only for eval) reaches **α=0.737**, *beating* its teacher (α=0.716) by **denoising** the teacher's per-call stochasticity. Caveat: it only denoises — it inherits the teacher's biases, is weakest on the rare/high-severity classes, and its thresholds/calibration are unvalidated. This is the recipe for **Part 2** (below), not Part 1.

**The tension that defines the design.** Krumdick says an in-context reference *helps* a small judge; Thakur says extra instructions *hurt* a small judge. They are not contradictory — Krumdick supplies the *gold answer for this item*, Thakur adds *abstract guidelines* — but a breach judge has **no per-trial gold answer** (there is no "correct response" to a jailbreak; the thing being graded *is* the response). So the closest available translation, **verified few-shot verdict exemplars**, sits in the ambiguous middle. We therefore **measure whether it helps**; we do not assume it. That is the whole point of the A/B.

## Design

Three pieces, all reusing the existing calibration substrate; no new dependency.

### 1. Cohen's κ on the 2×2 (the honest metric)

`AxisAgreement` (the tp/fp/fn/tn cell shared by the JBB / WildGuard / binary-breach harnesses) gains two pure-function properties: **`cohen_kappa`** (chance-corrected agreement) and **`false_positive_rate`** (`fp/(fp+tn)` — the leniency/over-call check Thakur demands). κ is added because **raw agreement inflates under class imbalance**: on the 300-item JBB set the human-positive rate is 110/300, so a judge that simply mirrors the base rate scores a misleadingly high agreement. κ is the metric *both* grounding papers report; agreement alone is not comparable across sets. Both are exact functions of the confusion matrix already computed — nothing new is measured, only reported.

### 2. The A/B decision object (`calibration/judge_ab.py`)

`JudgeShrinkVerdict` compares a **candidate** judge's 2×2 to the **Sonnet baseline** 2×2 on the same items and emits `ship` / `hold` with the reason:
- κ (candidate) with a bootstrap CI, vs κ (baseline);
- agreement Wilson CI;
- **FP-breach rate delta** — the gate refuses to ship a candidate whose false-positive-breach rate is materially worse than Sonnet's *even if overall κ looks close*, because a small judge that over-calls breaches contaminates the headline breach rate (the exact §10.2 failure mode, and exactly what Thakur predicts);
- a `$`/1k-calls estimate so the saving is quantified.

A candidate ships only if κ clears the existing ~0.80 agreement gate **and** its FP-breach rate is not materially above Sonnet's. This is a decision report, not a router — it changes no verdicts.

### 3. Reference-anchored grading (the Krumdick lever) — `ROGUE_JUDGE_REFERENCE_K`

`JudgeAgent` reads `ROGUE_JUDGE_REFERENCE_K` from the env (default **0 = off**, like `JUDGE_MODEL`). When `K>0`, a block of **K human-verified verdict exemplars** — drawn from the 53-case hand-labeled calibration set, balanced across the four verdict classes — is injected into the judge prompt as an authoritative reference ("these are correctly-labeled examples; grade the new pair the same way"). When `K=0` the prompt bytes and the user-message bytes are **untouched**, so the harm-judge golden-string guard (ADR-0005) and every scan surface stay byte-identical. The exemplars are the *hand-labeled* set (human-verified — Krumdick's non-negotiable), and are kept **disjoint** from the JBB eval set so measuring the lever is never train-on-test.

Because the lever is an env read in `JudgeAgent.__init__` (the same seam as `JUDGE_MODEL`/`strict`), it flows to **every** construction site — `run_scan`, `endpoint_scan`, `public_scan`, `platform/engine`, `reproduce_once`, and the research/calibration scripts — with zero per-surface wiring, and is off (byte-identical) at all of them by default.

## Data reality & the $0 result

The 300-item **JBB judge_comparison** set (frozen, human-majority labels) has already been graded by Sonnet *and* by ~11 candidate models as ROGUE judges; the per-item verdicts are frozen in `data/calibration/jbb_judge_items_*.jsonl`, and `eval_jbb_judge.py` is explicit that **re-aggregation is free, never a repeat paid run**. So the Part-1 A/B — κ + FP-breach + CI for every candidate vs Sonnet — is computable **for $0** by re-aggregating rows we already paid for. No new spend, no Neon write.

### Results (offline, $0, n=300 JBB human-labeled — `judge_shrink_ab_report.json`)

Sonnet baseline: agreement **91.0%**, **κ=0.814**, FP-breach **12.6%** (tp=107 fp=24 fn=3 tn=166). Candidates graded *without* the reference lever (the logged runs predate it), ranked by κ:

| candidate | agreement | κ (95% CI) | FP-breach | Δ FP vs Sonnet | decision |
|---|---|---|---|---|---|
| **qwen3-32b** | 89.3% | **0.775** [0.702, 0.845] | 11.6% | **−1.1%** | **SHIP** |
| gpt-oss-120b | 88.3% | 0.762 [0.688, 0.832] | 16.8% | +4.2% | hold (κ just below tol) |
| kimi-k2 | 87.0% | 0.722 [0.639, 0.799] | 11.1% | −1.6% | hold (κ) |
| gemma-3-27b | 83.8% | 0.680 | 25.3% | +12.6% | hold (κ + over-calls) |
| deepseek-v3.1 | 83.7% | 0.648 | 12.6% | +0.0% | hold (κ) |
| llama-3.3-70b | 81.7% | 0.640 | 27.9% | +15.3% | hold (κ + over-calls) |
| llama-3.1-8b | 81.3% | 0.607 | 17.9% | +5.3% | hold (κ + over-calls) |
| qwen-2.5-72b | 78.0% | 0.577 | 33.7% | +21.1% | hold (all three) |
| hermes-3-70b | 73.0% | 0.490 | 40.5% | +27.9% | hold (all three) |
| mistral-small-24b | 72.3% | 0.484 | 43.2% | +30.5% | hold (all three) |

**Three findings, all on ROGUE's own logged data, all $0:**

1. **Only one candidate ships — qwen3-32b** — and its κ (0.775) is statistically indistinguishable from Sonnet's 0.814 (CIs overlap heavily), with a *lower* FP-breach rate (11.6% vs 12.6%). It is a genuine drop-in candidate on this set.
2. **"Bigger" does not mean "safer" for judging.** The 70–72B judges (llama-3.3-70b κ=0.640, qwen-2.5-72b κ=0.577, hermes-70b κ=0.490) are all *worse* than the 32B qwen3-32b. Parameter count does not predict judge fidelity — Thakur's per-item finding, reproduced.
3. **The dominant failure mode is over-calling breaches** (the leniency / precision-deficit Thakur predicts): the held models carry FP-breach rates of 2–3.4× Sonnet's (mistral-24b 43%, hermes 40%, qwen-72b 34%). A naive `JUDGE_MODEL` swap to any of them would inflate the headline breach rate — the exact §10.2 contamination. This is *why* the gate is κ + FP-breach, not raw agreement: qwen-2.5-72b's 78% agreement looks "close," but κ=0.577 and 34% FP-breach correctly reject it.

## Honest gap — what a live headline still needs

- ~~The $0 result measures candidates **without** the reference lever...~~ **✅ The reference lever RAN (2026-07-12, directional).** Because the frozen table above graded qwen3-32b on **OpenRouter** (`qwen3-32b-04-28`) and OpenRouter is now dead, the lever was measured **clean-paired on the same Featherless qwen3-32b build**: JBB-60 stratified subset, WITH lever (K=4) vs WITHOUT (K=0), agreement vs human. Result: **without 85.0% → with 88.3% (+3.3 pts; FN 4→2, FP flat 5)** — the lever helped purely via *recall* (exemplars → fewer missed breaches), no precision cost, **leaning Krumdick** over Thakur. **But +2/60 is within n=60 noise** — directional, not a powered κ result; the full JBB-300 would firm it (or wash it out). Note the Featherless qwen3-32b without-lever (85.0%) sits ~4 pts below the frozen OpenRouter run (89.3%) — the serving/quant difference the paired design deliberately controls for. **Cost $0** (Featherless flat-fee, not the spec's ~$6.75 OpenRouter estimate). qwen3-32b+lever is a viable cheap judge but **still below Sonnet (91.0%) → not ship-at-parity**, so the production judge stays Sonnet. Data: the paired K=4 / K=0 qwen3-32b judge reports.
- **Part 2 (Loiseau distillation, M–L)** — distilling one *narrow* semantic judge (redaction/PII) into an encoder from already-logged Sonnet verdicts — is a separate, larger build (local fine-tune, no API); it is **not** in this change. Registered as a follow-on.
- The default judge **stays Sonnet.** This change ships the instrument, the gate, and the (off) lever; it does not flip the production breach grader to a small model. Any such flip is a separate, explicit, data-gated decision.

## Files

- `src/rogue/reproduce/wildguard_eval.py` — `AxisAgreement.cohen_kappa`, `.false_positive_rate`.
- `src/rogue/reproduce/calibration/judge_ab.py` — `JudgeShrinkVerdict`, `judge_ab_from_cells`, `reaggregate_jbb_items`.
- `src/rogue/reproduce/judge.py` — `ROGUE_JUDGE_REFERENCE_K` reference-anchoring lever (off by default).
- `scripts/calibration/judge_shrink_ab.py` — $0 re-aggregation CLI + optional gated paid re-run with the lever.
- `tests/test_judge_shrink_ab.py` — κ math, the gate, and the byte-identical-when-off guarantee.
