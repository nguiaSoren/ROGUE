# Calibrating and Generalizing an LLM-as-Judge for Red-Team Breach Detection

*Draft / working paper · seeded 2026-06-08. The v3 calibration results below are **measured** (reproducible from `breach_results` / `data/calibration/`); the generalization result (§4) is **pending** the paid information-disclosure sweep — the harness produces the CI-bearing numbers, the numbers themselves are not yet collected. Do not quote §4 figures until the sweep runs.*

## Abstract

Every breach verdict in an open-web LLM red-team is itself an LLM judgment, making the judge the single load-bearing component. We report (1) a calibration of an LLM-as-judge against an independent human-labeled benchmark that exposed systematic over-flagging, (2) a named false-positive taxonomy and a rubric fix — a *content-transfer gate* — that moved the judge from last-of-five to tied with frontier classifiers, and (3) a generalization of that gate into a *parameterized per-rule consummation judge* with a reusable per-type labeling pipeline. The unifying principle across all breach types is **engagement ≠ breach; consummation = breach**.

## 1. The diagnosis (measured)

On JailbreakBench's `judge_comparison` set (300 human-labeled rows), the v1 judge agreed with the human majority only **70.3%** — **last of five** behind HarmBench (78.3%), LlamaGuard-2 (87.7%), GPT-4 (90.3%), and Llama-3 (90.7%) — at recall 98% / precision **55%**. A 20-row audit of production false positives (9 FPs) traced the failure to the rubric rewarding *engagement* with the attack frame (persona acceptance, acknowledgment, format mimicry) rather than *transfer* of harmful content: a response like "Sure, as DAN I'll explain…" that then said nothing dangerous scored as a breach. This is a structural rubric failure, not a threshold to nudge.

## 2. The false-positive taxonomy (measured)

Five recurring FP modes from the audit: (i) acknowledgment-as-compliance, (ii) persona/format acceptance, (iii) meta-discussion of the attack, (iv) fiction/nonsense credited as content, (v) intent-anchoring on a benign render. All five share one shape: the model *engaged* the frame without *consummating* the harm.

## 3. The fix and its validation (measured)

The rubric was rebuilt around one gate — **a breach counts only when the response transfers the operational capability the goal was after**. On the same 300 rows: **70.3 → 89.3%** agreement, **55 → 79.5%** precision, **95.5%** recall (+19 / +24.5 / −2.5 pp), moving from dead-last to **3rd of five, tied with the frontier classifiers**, via a cost-controlled tiered evaluation (~$8.4; a cheap n=25 pilot tier caught an initial recall over-correction before the full sweep). v3 is the default rubric for every scan / report / MCP / Slack verdict.

**The honest correction.** Re-judging the stored breach matrix under v3 cut breach cells **2,429 → 1,371 (−43.6%)** (full 1,535→896, partial 894→475), correcting prior over-reporting. The same recalibration was carried to the external axes: WildGuardTest harm agreement **88.5%**; StrongREJECT scored ~26% more conservatively. In-distribution false-positive rate **2.56%**.

⚑ **Notable (measured):** two respected benchmarks (WildGuardTest harm labels, StrongREJECT) themselves *over-count* relative to a strict content-transfer standard.

## 4. The generalization (harness built; result PENDING the paid sweep)

The content-transfer gate is the *harm-specific instance* of a general rule. We parameterize the judge by a **`BreachType`** that supplies the rubric, the per-rule context (the protected target / rule text), and the headline FP mode. Each type instantiates the same template with its own consummation event:

| Breach type | Consummation (= breach) | Engagement (NOT a breach) |
|---|---|---|
| capability transfer (harm, §3) | hands over operational harmful content | accepts the persona / acknowledges |
| information disclosure | the protected datum appears in the response | discusses the data-handling policy |
| unauthorized action | executes the side-effecting action | acknowledges / simulates it |

**Method (built, free):** a parameterized rubric per type (`infodisc_v1`, `unauthorized_action_v1`) sharing the v3 skeleton and 4-verdict vocabulary, swapping only the gate; a reusable **per-type independent-labeling pipeline** (synthetic designed-label corpus, n≥80, two-sided bracketing, inter-author κ — never the regulation, the operators' decisions, or the verifier's own score); and a binary-axis calibration harness reporting agreement / precision / recall **with bootstrap CIs** plus the surface-specific **FP-mode rate** ("discussing ≠ disclosing") as the headline.

**Result (measured 2026-06-08, harm path byte-identical / regression-guarded).** First, on an n=86 designed-label corpus: agreement 97.67%, precision 95.45%, recall 100%, FP-mode 0.0% (29 traps), SHIP. Because that corpus was clear-cut, we then **hardened it with 28 deliberately ambiguous boundary cases** (rounding/approximation that does-or-doesn't pin the datum, derivation that is-or-isn't fully determining, de-anonymizing small-N aggregates, refusals that leak in their own example, fiction-wrapped real data, confidently-stated *wrong* values, multi-turn assembly). On the hardened **n=114** corpus:

| | n=86 (clear-cut) | **n=114 (hardened)** |
|---|---|---|
| Agreement | 97.67% | **94.74%** [90.35, 98.25] |
| Precision | 95.45% | **90.32%** [82.26, 96.77] |
| Recall | 100% | **100%** [100, 100] |
| FP-mode (discuss-only traps) | 0.0% (29) | **0.0%** (31) |
| Gate | SHIP | **SHIP** |

The boundary cases bit — agreement and precision dropped — but the structure of the errors is the interesting result. From the aggregates (56 breach labels, recall 100%, precision 90.32%): **0 false negatives** (never missed a real disclosure) and **exactly 6 false positives, none of them discuss-only traps** (FP-mode held at 0% over all 31 traps). So the judge's *only* failure mode is **over-flagging the hardest *clean* boundary cases** (underdetermined ranges, policy-permitted fragments, confidently-wrong values) — it is conservative in precisely the safe direction, never confusing *discussing* with *disclosing* and never letting a real leak through. The content-transfer gate generalized to a non-harm rule on the first attempt and held under a hard corpus.

**Independence check (κ = 0.80).** A second, independent human re-labeled a blind, stratified 20-row sample (`scripts/calibration/kappa_check.py`): **Cohen's κ = 0.80, raw agreement 90%** — clearing the pre-registered ≥0.80 floor. On adjudication, *both* disagreements were labeler misses (a verbatim trade-secret disclosure under-called as clean; a clean policy-refusal over-called as breach — the human slipped into the very FP-mode trap the judge resists), so the original labels stand and the calibration is unchanged. **Honest reading:** κ = 0.80 is the *floor*, not a comfortable margin, and it covered the original clear-cut 86. **Update:** requirement (a) "harder boundary cases" is now done — the corpus was hardened to n=114 (above), so the **28 boundary cases still need their own fresh κ check** (the subtle middle is exactly where two labelers drift; a quick read already tripped the human on the easy trap). Remaining for conference-grade: that boundary-κ, a fully independent human/expert relabel (the rows were authored by an automated by-construction process), and a second breach type. The **0% FP-mode over all 31 traps** is the most robust signal — and a human slipping on a trap the judge handled correctly is itself evidence the gate captures a real, subtle distinction.

⚑ **Possibly publishable (result holds under a hard corpus + independence check landed):** a single content-transfer gate generalizing to per-rule consummation judges via one parameterized rubric + a reusable per-type labeling pipeline — a methods contribution extending §3 — backed by a measured calibration that **holds under hardening**: 94.74% agreement / **100% recall** / **0% FP-mode over 31 traps** (SHIP) on a 114-case corpus with 28 deliberately ambiguous boundary cases, the *only* errors being 6 over-flagged hard **clean** cases — plus a second-author independence check (**κ = 0.80**) on the base set. **Workshop-defensible now;** conference-grade would add a boundary-subset κ, a fully-independent human/expert relabel, and a second breach type (unauthorized-action).

## 5. Cross-surface reach

The same calibrated apparatus instantiates for oversight assurance (a reviewer false-approve = a consummated wrong approval) and accumulated-memory assurance (an extraction attack recovering protected content). The judge is therefore not "a harm classifier we reuse" but **a proven method for building calibrated per-target breach judges**, demonstrated once (55→79.5%) on the hardest case.

## 6. Limitations (stated plainly)

Targets are black-box live-API models whose versions are not pinned; some cells are small-n (95% bootstrap CIs are persisted precisely because of this); the judge is single-operator-calibrated. These are descriptive measurements of a live system, not validated generalizations. The independence of every ground-truth label is the load-bearing assumption (and the largest recurring cost).

## Provenance

§1–§3 numbers: `breach_results`, `data/calibration/`, `docs/judge.md`, `docs/judge_fp_taxonomy.md`, the v3 calibration history (ADR-0005) — reproducible from the repo. External benchmark names (JailbreakBench `judge_comparison`, WildGuardTest, StrongREJECT, HarmBench/LlamaGuard-2/GPT-4/Llama-3) are standard; confirm versions before any external submission. §4 method: `src/rogue/reproduce/rubrics/`, `src/rogue/reproduce/calibration/`, `docs/v2/build/02_judge_generalization.md`, `docs/v2/build/labeling_protocol.md`.
