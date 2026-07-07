# Calibrated Pre-fire Evaluation Gating (Q7)

**The question.** *Can a red-team skip expensive evaluations before firing them — while explicitly
quantifying the recall cost of doing so?* Skipping trials is easy; skipping them **safely**, with a
number that tells you how many real breaches the skip costs, is the part nobody reports. That number is
the contribution here.

**One line.** A **calibrated pre-fire skip policy**: for each (harvested attack × specific target
config) pair, decide *before firing* whether to spend the target + judge calls on it — defer the pairs
the policy confidently predicts won't breach, keep everything it can't confidently rule out, and account
for every skip. Not a new predictor: a deployment gate around a deliberately boring estimator, whose
value is the **decision discipline** (calibration, a measured recall floor, two safety rails, visible
skip accounting) rather than the model.

**Status.** Built + offline back-tested on real historical breach data (free, $0). A prospective live
budget-saved A/B is a separate, deliberately-gated ~$35 reproduce run. Off by default
(`ROGUE_PREFIRE_SKIP`), byte-identical when off. ⚑ possibly publishable as a systems result (see
[Why it's novel](#why-its-novel)).

Code: `src/rogue/reproduce/prefire/` · trainer CLI: `scripts/reproduce/train_prefire_scorer.py` ·
$0 validator: `scripts/reproduce/replay_prefire.py` · live wiring: `reproduce/endpoint_scan.py`,
`scan.py::run_scan`, the research sweep (`--prefire-skip`) · tests: `tests/test_prefire_scorer.py`.

---

## The problem

ROGUE reproduces each harvested jailbreak against a customer `DeploymentConfig` (model × system_prompt ×
tools) by firing it `n_trials` times and grading every response with an LLM judge. On ROGUE's own
corpus the pair-level breach base rate is **~16.5%** — ~5 of every 6 fired trials land on a pair that
never breaches, each one paying for a target call *and* the per-trial LLM judge (the top marginal cost).
So there is real money in *not firing* the pairs that won't land.

The catch is what makes this a systems problem rather than a modelling one: a **hard skip trades money
for missed breaches**, and a red-team that silently drops real breaches to save a few dollars is worse
than useless. A calibrated score does *not* make the skipped pairs "obvious misses" — they are
**confidently predicted low-probability pairs**, and some fraction of them will breach anyway. The whole
design is therefore built around bounding and accounting for that cost:

1. a **calibrated probability**, so a skip threshold means a known thing;
2. a **measured recall floor** — how many trials can we skip at 95% breach recall? — as the headline
   number, not an afterthought;
3. two **safety rails** that forbid the gate from confidently skipping something it has no business
   ruling out;
4. **visible skip accounting** — every deferred pair is surfaced, never silently dropped;
5. **deployment integration** — off by default, byte-identical when off, wired into every path a real
   scan takes.

## The recall–skip tradeoff (the contribution)

This is the number the prior work leaves unmeasured, and the one a practitioner actually decides on.
Sort held-out trials by the calibrated skip score, skip the lowest, and read off how much you can skip at
each breach-recall target:

| Breach recall you insist on | Fraction of trials you can skip | Calibrated skip threshold |
|---|---|---|
| 80% | **42%** | — |
| **95%** (production-safe) | **~7%** | skip if P < 0.048 |
| 99% | ~1.6% | skip if P < 0.026 |

Read plainly: the ranking is good enough to skip **~40% of trials if you accept missing one breach in
five** — but only **~7% at a production-safe 95% breach recall**, and ~1.6% at 99%. That steep curve
*is* the finding. It says pre-fire skipping is a real but modest lever on this corpus at safe recall, and
it hands the operator an explicit dial rather than a vague "we skip the easy ones." The shipped default
threshold (0.048) is the conservative 95%-recall point; a cost-tolerant operator raises it and the table
tells them exactly what recall they are buying down.

Measured on held-out primitives (group-split by attack), `test=552`, 16.5% base rate. Reproduce with
`uv run python scripts/reproduce/replay_prefire.py`.

## How the skip decision is made (the system)

1. **The gate (`gate.py`).** Off unless `ROGUE_PREFIRE_SKIP=on` and a model artifact exists. When on, it
   scores each attack against the target config and defers the ones below the calibrated threshold —
   each recorded as a **visible skipped finding** (`n_prefire_skipped` / `ScanReport.prefire`), never a
   silent drop — and leaves the firing order untouched (ordering is Q11's job; this only *skips*).

2. **Calibration (`model.py`).** A skip threshold is only meaningful against a real probability, so the
   head's raw score is passed through **Platt scaling** (`P_cal = σ(a·logit(P_raw)+b)`) fit on a
   calibration slice group-disjoint from both fit and test. Brier **0.1214 → 0.1195**; `a=0.78` (the raw
   head was mildly over-confident, so calibration shrinks it toward the base rate). The calibrated
   probability is also what the planned Q18 acquisition score consumes (uncertainty = |P−0.5|).

3. **Rail 1 — drift-guard fire-all.** A novel/emergent attack family, or one with
   `family_support < min_support`, is **never skipped**. This is Kirch's out-of-distribution collapse
   (below) made operational: a predictor trained on known families is near-or-below random on unfamiliar
   ones, so a confident skip there would be uncalibrated by construction — fire it and collect the label.

4. **Rail 2 — deterministic canary.** A fixed 15% of otherwise-skippable attacks is force-fired anyway
   (by a stable hash of the primitive id, no RNG), so the gate keeps collecting ground truth on exactly
   the rows it wanted to skip — continuous, free validation of the skip policy in production.

5. **Deployment integration.** Wired into **all three** reproduction surfaces, off by default,
   byte-identical when off: `endpoint_scan.py::scan_endpoint` (public API / `--persist` CLI),
   `scan.py::run_scan` (default `rogue scan` + SDK), and the research sweep `reproduce_once.py`
   (`--prefire-skip`, an **explicit opt-in only** — silently dropping cells in a measurement run would
   corrupt the breach matrix *and* the policy's own future training labels). Serve-time: the scan
   primitive carries no stored embedding, so the gate embeds each payload once (`text-embedding-3-small`,
   a fraction of a cent — repaid by skipping even one target+judge trial); with no key / opted out
   (`ROGUE_PREFIRE_EMBED=off`) it degrades to the structural signal alone, so a scan never fails because
   embeddings are unreachable.

## What feeds the score (and an honest ablation)

The estimator is deliberately the least interesting part: the identical L2-logistic IRLS head Q11 ships
(numpy-only, deterministic, no new dependency). Its inputs, in order of how much they carry:

- **Structural metadata (primary).** Reused verbatim from `survival.features`: family/vector one-hots,
  `requires_*` flags, provenance scores, target size/context/tools/system-prompt-class.
- **Optional semantic affinity (secondary).** A compact content feature: at train time, per config
  sibling class (size × context reach) and globally, the centroid of breaching payload embeddings and of
  non-breaching ones; the serve-time feature is the cosine gap to those two centroids — "does this
  payload look like the ones that have breached targets *like this one* before?" A couple of scalars, so
  it can't overfit a 1536-d vector into a head trained on ~1.8k rows, and it's fit on the train split
  only (a held-out primitive's embedding never enters a centroid it is scored against).

Whether that second input earns its place is **measured, not assumed** — and the honest answer is: it
helps a little.

| Head | ROC-AUC | Precision@10% | Budget-saved @80% recall |
|---|---|---|---|
| structural-only (= Q11's features) | 0.688 | 36.4% | 41.3% |
| + semantic affinity | **0.696** | **41.8%** | **42.2%** |

The affinity adds a **small, consistent** lift (AUC +0.009, precision@10 +5.5 pts) — real and repeatable,
but not the story. This corroborates ROGUE's own prior probe (`payload_embedding_technique_signal`,
silhouette ≈ 0): on this corpus an attack's *structure* carries most of the signal and its *content
embedding* is a secondary refinement. We report the ablation precisely so the semantic feature is one
component among many, not an oversold headline — a calibrated gate whose skip decision happens to have a
small content-aware term, not an "embedding-augmented predictor."

**Not yet measured (honest):** a live prospective A/B — a paid reproduce cycle with the gate on,
reporting the realized budget saved *at the realized recall*. That is the gated ~$35 arm; the drift-guard
+ 15% canary give continuous free validation until then.

## Relationship to Q11 (survival predictor)

Q7 and Q11 share a substrate on purpose — the same self-labeled
`breach_results ⋈ attack_primitives ⋈ deployment_configs` join, the same logistic head, the same
group-split back-test, the same drift-guard. They are two **policies over the same attack budget**, and
the difference is the *decision*, not the model:

| | Q11 survival | Q7 pre-fire gating |
|---|---|---|
| Decision | **reorder** — fire likely survivors first | **skip** — don't fire confidently-low pairs at all |
| Output used | a ranking | a *calibrated* probability + a recall-bounded threshold |
| Extra input | structural surface only | + an optional (small) semantic-affinity term |
| Safety accounting | deferred tail surfaced | calibrated recall floor + visible skips + canary |

Run them together and you get order-then-skip; the calibrated probability Q7 produces is also the
uncertainty signal the planned Q18 acquisition score needs.

## Why it's novel

**Existing work predicts attack success, detects jailbreak inputs, or analyzes prompt representations —
none addresses calibrated, recall-bounded pre-fire *skipping* inside a live black-box benchmark.** Each
of the three closest papers sits one axis away:

- **Zhang, "Distillability of LLM Security Logic" (2511.22044)** — black-box and success-oriented, and
  its FASC result even supports rank-and-skip (top-20% cut queries-to-first-success 71–88%). But it
  covers a **single attack family** (Outline Filling), predicts a **relative ranking** of same-question
  variants rather than an absolute probability, and — critically — **never measures the recall cost** of
  a hard skip. That missing number is exactly this build's headline.
- **Galinkin, "Improved Jailbreak Detection via Pretrained Embeddings" (2412.01547)** — embeddings + a
  light classifier work well (RF on Snowflake embeddings, F1 0.96 on JailbreakHub), but the task is
  **detecting a jailbreak input**, with no target model in the loop and no notion of per-target breach.
- **Kirch, "What Features in Prompts Jailbreak LLMs?" (2411.03343)** — probes **white-box internal
  activations** (Gemma-7B layer-17 residual stream), a signal ROGUE's closed API targets don't expose.
  Its portable finding is the **hazard**, not a predictor: leave-one-attack-out transfer degrades to
  near-or-below random on held-out families (§3.3, Fig 4) — the direct justification for the
  fire-all-on-novel-family rail.

**The contribution is the deployment system, not the estimator.** The estimator is logistic regression
plus Platt scaling — and that is the point: the novelty is doing calibrated pre-fire skipping *safely*
inside a live red-team benchmark without moving its verdicts. Concretely, that is (a) a **calibrated,
recall-bounded skip threshold** — with the recall cost of the skip *measured*, which the prior work does
not report; (b) a **drift-guard** that refuses to skip out-of-distribution families, grounded in Kirch's
measured OOD collapse; (c) a **deterministic canary** that keeps validating the policy in production for
free; (d) **visible skip accounting** so a deferred breach can never hide; and (e) **byte-identical-when-
off deployment** across all three scan surfaces. The ingredients (embeddings→classifier;
success-is-predictable; OOD-collapse) are each precedented; the *decision system* that turns them into a
safe, accountable skip policy is not. Composes with, and is orthogonal to, Q11 (attack ordering), Q6
(per-cell trial budget), and Q18 (the acquisition score).

## Configuration

All off by default; see `.env.example`.

| Env var | Meaning | Default |
|---|---|---|
| `ROGUE_PREFIRE_SKIP` | master switch (`on`/`off`) | off |
| `ROGUE_PREFIRE_MODEL` | artifact path | `data/models/prefire_scorer.json` |
| `ROGUE_PREFIRE_THRESHOLD` | skip below this calibrated probability | model's 95%-recall point |
| `ROGUE_PREFIRE_MIN_SUPPORT` | families below this many primitives → fire-all (drift-guard) | 8 |
| `ROGUE_PREFIRE_FIRE_ALL_FRAC` | deterministic fraction of skips force-fired (validation canary) | 0.15 |
| `ROGUE_PREFIRE_EMBED` | compute serve-time embeddings (`on`/`off`; off ⇒ structural-only) | on |

Train the artifact (free) then turn the gate on:

```bash
uv run python scripts/reproduce/train_prefire_scorer.py --out data/models/prefire_scorer.json
export ROGUE_PREFIRE_SKIP=on
export ROGUE_PREFIRE_MODEL=data/models/prefire_scorer.json
```
