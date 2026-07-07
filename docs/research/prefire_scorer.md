# Calibrated Pre-fire Evaluation Gating (Q7)

**The question.** *Can a red-team skip expensive evaluations before firing them — while explicitly
quantifying the recall cost of doing so?* Skipping trials is easy; skipping them with a **measured recall
cost** — a number that says how many real breaches the skip costs — is the part nobody reports. Existing
work evaluates **prediction quality** (AUC, ranking accuracy, F1); we instead evaluate **decision
quality**: how many evaluations can be skipped while holding an explicit, empirically measured
breach-recall target — the operating point a practitioner would actually deploy.

**One line.** A **calibrated pre-fire skip policy**: for each (harvested attack × specific target
config) pair, decide *before firing* whether to spend the target + judge calls on it — defer the pairs
the policy confidently predicts won't breach, keep everything it can't confidently rule out, and account
for every skip. The contribution is a **deployment policy for calibrated pre-fire evaluation gating**,
together with its **empirically characterized recall–budget frontier**.

## The main finding: held to a fixed recall, pre-fire skipping has sharply diminishing returns

The central empirical result — and the number the prior work leaves unmeasured — is that once you hold a
real breach-recall target, **pre-fire skipping has sharply diminishing returns**: aggressive thresholds
skip ~42% of evaluations, but holding a stringent 95% breach recall permits only ~7% skipping.
Sort held-out trials by the calibrated skip score, skip the lowest, and read off how much you can skip at
each recall target (16.5% pair-level breach base rate; `test=552`, group-split by attack):

| Breach recall you insist on | Fraction of evaluations you can skip | Calibrated skip threshold |
|---|---|---|
| 80% | **42%** | — |
| **95%** (conservative operating point) | **~7%** | skip if P < 0.048 |
| 99% | ~1.6% | skip if P < 0.026 |

This is a **decision-quality** result, not a predictor-quality one: it reports the operating point you
would actually deploy and exactly what recall you buy down as you skip more. The shipped default threshold
(0.048) is the conservative 95%-recall point; a cost-tolerant operator raises it and the table says what
it costs. Reproduce with `uv run python scripts/reproduce/replay_prefire.py`.

**Status.** Built + offline back-tested on real historical breach data (free, $0). A prospective live
budget-saved A/B is a separate, deliberately-gated ~$35 reproduce run. Off by default
(`ROGUE_PREFIRE_SKIP`), byte-identical when off. ⚑ possibly publishable as a systems result.

## The problem

ROGUE reproduces each harvested jailbreak against a customer `DeploymentConfig` (model × system_prompt ×
tools) by firing it `n_trials` times and grading every response with an LLM judge. On ROGUE's own
corpus the pair-level breach base rate is **~16.5%** — ~5 of every 6 fired trials land on a pair that
never breaches, each one paying for a target call *and* the per-trial LLM judge (the top marginal cost).
So there is real money in *not firing* the pairs that won't land.

What makes this a systems problem rather than a modelling one: a **hard skip trades money for missed
breaches**, and a red-team that silently drops real breaches to save a few dollars is worse than useless.
A calibrated score does *not* make the skipped pairs "obvious misses" — they are **confidently predicted
low-probability pairs**, and some fraction of them will breach anyway. So the research question is not
whether another classifier can squeeze out 0.3% more ROC-AUC; it is how a benchmark can make pre-fire
skip decisions **under an empirically measured recall target**, with the recall cost of those decisions
measured and bounded. The design follows directly: a **calibrated probability** (so a threshold means a
known thing), a **measured recall floor** as the headline, two **safety rails** that forbid confidently
skipping the out-of-distribution, **visible skip accounting**, and **byte-identical-when-off deployment**.

## How the skip decision is made (the system)

1. **The gate (`gate.py`).** Off unless `ROGUE_PREFIRE_SKIP=on` and a model artifact exists. When on, it
   scores each attack against the target config and defers the ones below the calibrated threshold — each
   recorded as a **visible skipped finding** (`n_prefire_skipped` / `ScanReport.prefire`), never a silent
   drop — and leaves the firing order untouched (ordering is Q11's job; this only *skips*).

2. **Calibration (`model.py`).** A skip threshold is only meaningful against a real probability, so the
   head's raw score is passed through **Platt scaling** fit on a calibration slice group-disjoint from
   both fit and test. Brier **0.1214 → 0.1195**; `a=0.78` (the raw head was mildly over-confident, so
   calibration shrinks it toward the base rate). The calibrated probability is also the uncertainty signal
   the planned Q18 acquisition score consumes (|P−0.5|).

3. **Rail 1 — drift-guard fire-all.** A novel/emergent attack family, or one with
   `family_support < min_support`, is **never skipped**. This is Kirch's out-of-distribution collapse
   (below) made operational: a predictor trained on known families is near-or-below random on unfamiliar
   ones, so a confident skip there would be uncalibrated by construction — fire it and collect the label.

4. **Rail 2 — deterministic canary.** A fixed 15% of otherwise-skippable attacks is force-fired anyway
   (by a stable hash of the primitive id, no RNG), so the gate keeps collecting ground truth on exactly
   the rows it wanted to skip — continuous, free validation of the skip policy in production.

5. **Deployment integration.** Wired into **all three** reproduction surfaces, off by default and
   byte-identical when off: `endpoint_scan.py::scan_endpoint` (public API / `--persist` CLI),
   `scan.py::run_scan` (default `rogue scan` + SDK), and the research sweep `reproduce_once.py`
   (`--prefire-skip`, an **explicit opt-in only** — silently dropping cells in a measurement run would
   corrupt the breach matrix *and* the policy's own future training labels).

The scoring inputs and the serve-time embedding mechanics are deliberately kept out of the main path;
see the [Appendix](#appendix--score-inputs-and-serve-time-mechanics).

## What feeds the score (and an honest ablation)

We intentionally use a **low-capacity calibrated model** — the same L2-logistic head Q11 ships
(numpy-only, deterministic, no new dependency) — so that improvements cannot be attributed to predictor
complexity: the evaluation policy, not the estimator, is the experimental variable, and replacing the
estimator is orthogonal to the policy. Its inputs are structural deployment metadata (primary:
family/vector, `requires_*` flags, provenance scores, target size/context/tools/system-prompt-class) and
an optional semantic-affinity term (secondary). We evaluated whether semantic affinity adds value beyond
structural metadata; it does, but only modestly (**ΔAUC = 0.009**), confirming that **deployment metadata
carries most of the predictive signal on this corpus**.

| Head | ROC-AUC | Precision@10% | Budget-saved @80% recall |
|---|---|---|---|
| structural-only (= Q11's features) | 0.688 | 36.4% | 41.3% |
| + semantic affinity | 0.696 | 41.8% | 42.2% |

**Not yet measured (honest):** a live prospective A/B — a paid reproduce cycle with the gate on,
reporting the realized budget saved *at the realized recall*. That is the gated ~$35 arm; the drift-guard
+ 15% canary give continuous free validation until then.

## Relationship to Q11 (survival predictor)

Q7 and Q11 are two **policies over the same attack budget**, sharing a substrate on purpose (the same
self-labeled `breach_results ⋈ attack_primitives ⋈ deployment_configs` join, logistic head, group-split
back-test, and drift-guard). The difference is the *decision*, not the model:

| | Q11 survival | Q7 pre-fire gating |
|---|---|---|
| Decision | **reorder** — fire likely survivors first | **skip** — don't fire confidently-low pairs at all |
| Output used | a ranking | a *calibrated* probability + a recall-bounded threshold |
| Accounting | deferred tail surfaced | calibrated recall floor + visible skips + canary |

Run them together and you get order-then-skip; the calibrated probability Q7 produces is also the
uncertainty signal the planned Q18 acquisition score needs.

## Why it's novel

**Existing work evaluates predictors; we evaluate deployment policies.** Concretely: existing work
predicts attack success, detects jailbreak inputs, or analyzes prompt representations — **none addresses
calibrated, recall-bounded pre-fire *skipping* inside a live black-box benchmark.** Each of the three
closest papers sits one axis away:

| Prior work | Produces | Missing for pre-fire gating |
|---|---|---|
| attack-success prediction — Zhang (2511.22044) | a relative *ranking* (one attack family) | an absolute, deployable threshold + the recall cost |
| jailbreak detection — Galinkin (2412.01547) | an input *classifier* (F1 0.96) | a *target-conditioned* decision (no target in the loop) |
| representation analysis — Kirch (2411.03343) | *explanations* from white-box activations | a black-box, deployable policy (its finding is the OOD hazard) |
| **this work (Q7)** | a **calibrated skip policy** | — provides recall-bounded deployment |

Zhang's FASC result even supports rank-and-skip (top-20% cut queries-to-first-success 71–88%) — but it
covers a single attack family, predicts a ranking rather than an absolute probability, and **never
measures the recall cost** of a hard skip, which is exactly this build's headline. Kirch's portable
contribution is the hazard, not a predictor: leave-one-attack-out transfer degrades to near-or-below
random on held-out families (§3.3, Fig 4) — the direct justification for the fire-all-on-novel-family
rail.

The research question is not whether another classifier can achieve 0.3% more ROC-AUC, but how a red-team
benchmark can make pre-fire evaluation decisions under an empirically measured recall target. **The
novelty is not the underlying estimator but the deployment policy: a calibrated, recall-bounded pre-fire
evaluation gate with explicit recall accounting, continuous online validation, and production-oriented
integration into a live benchmark.** Concretely: a calibrated, recall-bounded skip threshold with the
recall cost *measured*; a drift-guard that refuses to skip out-of-distribution families (grounded in
Kirch's OOD collapse); a deterministic canary that keeps validating the policy for free; visible skip
accounting so a deferred breach can never hide; and byte-identical-when-off deployment across all three
scan surfaces.
Composes with, and is orthogonal to, Q11 (attack ordering), Q6 (per-cell trial budget), and Q18 (the
acquisition score).

## Status & configuration

All off by default; see `.env.example`. Code: `src/rogue/reproduce/prefire/` · trainer CLI:
`scripts/reproduce/train_prefire_scorer.py` · $0 validator: `scripts/reproduce/replay_prefire.py` ·
live wiring: `reproduce/endpoint_scan.py`, `scan.py::run_scan`, the sweep (`--prefire-skip`) · tests:
`tests/test_prefire_scorer.py`.

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

---

## Appendix — score inputs and serve-time mechanics

*Implementation detail, kept out of the main path; the contribution is the decision policy above, not
this construction.*

**Semantic-affinity feature (`embedding_affinity.py`).** Rather than feed a raw 1536-d embedding into a
head trained on ~1.8k rows (which would overfit, and — per ROGUE's own `payload_embedding_technique_signal`
probe, silhouette ≈ 0 — likely learn noise), the payload embedding is distilled to a compact
breach-affinity signal: at train time, per config sibling class (size × context reach) and globally, the
centroid of breaching payload embeddings and of non-breaching ones; the serve-time feature is the cosine
gap to those two centroids ("does this payload look like the ones that breached targets *like this one*
before?"). A couple of scalars. Centroids are fit on the **train** split only, and the back-test scores
**held-out primitives**, so a test row's embedding never enters a centroid it is later scored against.

**Serve-time embedding.** The scan-time primitive carries no stored embedding, so the gate embeds each
payload once (`text-embedding-3-small`, a fraction of a cent — repaid by skipping even one target+judge
trial). With no key / opted out (`ROGUE_PREFIRE_EMBED=off`) it degrades to the structural signal alone
and logs the fallback, so a scan never fails because embeddings are unreachable.

**Data.** Trained + group-split back-tested on the real `breach_results` (2,179 primitive × config pairs,
1,845 with a stored embedding; 24 configs; 16.5% base rate). `fit=1295 / calib=332 / test=552`.
