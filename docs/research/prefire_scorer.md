# Pre-fire success scorer (Q7)

**One line.** Score every (harvested attack × specific target config) pair with a *calibrated*
probability of breaching **before** firing it, and skip the ones predicted not to breach — so the
expensive target + judge calls are never spent on the obvious misses.

**Status.** Built + offline back-tested on real historical breach data (free, $0). A prospective live
budget-saved A/B is a separate, deliberately-gated ~$35 reproduce run. Off by default
(`ROGUE_PREFIRE_SKIP`), byte-identical when off. ⚑ possibly publishable as a systems result (see
[Why it's novel](#why-its-novel)).

Code: `src/rogue/reproduce/prefire/` · trainer CLI: `scripts/reproduce/train_prefire_scorer.py` ·
$0 validator: `scripts/reproduce/replay_prefire.py` · live wiring: `reproduce/endpoint_scan.py`,
`scan.py::run_scan`, the research sweep (`--prefire-skip`) · tests: `tests/test_prefire_scorer.py`.

**Relationship to Q11 (survival predictor).** Q7 and Q11 share a substrate on purpose — the same
self-labeled `breach_results ⋈ attack_primitives ⋈ deployment_configs` join, the same numpy logistic
head, the same group-split back-test, the same drift-guard. They differ on exactly three axes, and
those three axes *are* Q7:

| | Q11 survival | Q7 pre-fire |
|---|---|---|
| Input signal | structural surface only (embedding-free) | structural surface **⊕ payload-embedding affinity** |
| Output | a *ranking* (fire survivors first) | a *calibrated probability* P(breach) |
| Action | reorder + defer a budget tail | **skip** per-trial below a probability floor |

Q7 answers the question Q11 deliberately does not: **does the semantic content of the attack payload
predict whether it beats this target, above and beyond the attack's metadata?** The trainer reports an
explicit structural-only-vs-embedding **ablation** so the answer is measured, not assumed.

---

## The problem

ROGUE reproduces each harvested jailbreak against a customer `DeploymentConfig` (model × system_prompt ×
tools) by firing it `n_trials` times and grading every response with an LLM judge. On ROGUE's own
corpus the pair-level breach base rate is **~16.5%** — i.e. ~5 of every 6 fired trials land on a pair
that was never going to breach, each one paying for a target call *and* the per-trial LLM judge (the top
marginal cost). If we could estimate P(breach) for a pair *before* firing, we could skip the confident
misses and spend the ~$35/cycle budget where a breach is actually plausible.

The catch is that a *hard skip* trades money for missed breaches — and no prior work measures that
trade. So the design is built around making the skip **honest**: a probability we can threshold, a
measured recall cost, and two rails that stop the gate from ever confidently skipping something it has
no business skipping.

## What it does

1. **Feature row = Q11's structural block ⊕ an embedding-affinity block.** The structural half is
   reused verbatim from `survival.features` (family/vector one-hots, `requires_*` flags, provenance
   scores, target size/context/tools/system-prompt-class). The affinity block is the new content axis
   (below). Dropping the trailing affinity columns recovers Q11's exact vector — which is what makes the
   ablation clean.

2. **Embedding affinity (`embedding_affinity.py`).** Rather than feed a raw 1536-d vector into a head
   trained on ~1.8k rows (which would overfit, and — per ROGUE's own `payload_embedding_technique_signal`
   probe, silhouette ≈ 0 — likely learn noise), we distil the payload embedding to a **breach-affinity**
   signal: at train time, per config **sibling class** (size × context reach) and globally, the centroid
   of breaching payload embeddings and of non-breaching ones; the serve-time feature is the cosine gap to
   those two centroids — "does this payload look like the payloads that have breached targets *like this
   one* before?" A couple of scalars, storable in the artifact, computable from just the payload's own
   embedding. Centroids are fit on the **train** split only and the back-test scores **held-out
   primitives**, so a test row's embedding never enters a centroid it is later scored against.

3. **A calibrated probability (`model.py`).** The base head is the identical L2-logistic IRLS solve Q11
   ships (numpy-only, deterministic, no new dependency). On top we fit **Platt scaling**
   (`P_cal = σ(a·logit(P_raw)+b)`) on a calibration slice group-disjoint from both fit and test, so the
   score is a real probability suitable for thresholding and for the Q18 acquisition score
   (uncertainty = |P−0.5|). We report the Brier score before and after.

4. **The skip gate (`gate.py`).** Off unless `ROGUE_PREFIRE_SKIP=on` and a model artifact exists. When
   on, it scores each attack against the target config and skips the ones below the threshold — recorded
   as a *visible skipped finding*, never a silent drop — leaving the firing order untouched (ordering is
   Q11's job). Two rails, both from the papers:
   - **Drift-guard fire-all.** A novel/emergent family, or one with `family_support < min_support`, is
     never skipped — Kirch's out-of-distribution collapse (below) made operational.
   - **Deterministic canary.** A fixed 15% of otherwise-skippable attacks is force-fired (by a stable
     hash of the primitive id), so the gate keeps collecting ground truth on exactly the rows it wanted
     to skip.

   Serve-time embeddings: the scan-time primitive carries no stored embedding, so the gate embeds each
   payload once (`text-embedding-3-small`, a fraction of a cent — trivially repaid by skipping even one
   target+judge trial). No key / opted out (`ROGUE_PREFIRE_EMBED=off`) ⇒ it degrades to the structural
   signal alone and logs the fallback; a scan never fails because embeddings are unreachable.

Wired into **all three** reproduction surfaces, off by default: `endpoint_scan.py::scan_endpoint`
(public API / `--persist` CLI), `scan.py::run_scan` (the default `rogue scan` + SDK path), and the
research sweep `reproduce_once.py` (`--prefire-skip`, an **explicit opt-in only** — dropping cells in a
measurement run would corrupt the breach matrix and the predictor's own future training labels).

## Measured results (offline, $0)

Trained + group-split back-tested on the real `breach_results` (2,179 primitive × config pairs, 1,845
with a stored embedding; 24 configs; pair breach base rate 16.5%). `fit=1295 / calib=332 / test=552`.

**Ablation — does the payload embedding earn its place?**

| Head | ROC-AUC | Precision@10% | Budget-saved @80% recall |
|---|---|---|---|
| structural-only (= Q11's features) | 0.688 | 36.4% | 41.3% |
| **+ embedding affinity** | **0.696** | **41.8%** | **42.2%** |

The embedding adds a **small but consistent** lift (AUC +0.009, precision@10 +5.5 pts) — *not* the
dominant signal, consistent with ROGUE's own silhouette≈0 result, but nonzero and repeatable. Honest
read: on this corpus the attack's *structure* carries most of the signal; content affinity is a real
but secondary refinement.

**The recall-vs-skip trade — the cost of a hard skip (the number Zhang never measured):**

| Breach recall you insist on | Fraction of trials you can skip | Calibrated P threshold |
|---|---|---|
| 80% (the budget-saved framing) | **42%** | — |
| **95%** (production-safe) | **~7%** | P < 0.048 |
| 99% | ~1.6% | P < 0.026 |

This is the honest headline: the ranking is good enough to skip ~40% of trials **if** you accept missing
one breach in five, but only ~7% at a production-safe 95% breach recall. The default skip threshold
(0.048) is the conservative 95%-recall point; a cost-tolerant operator can raise it.

**Calibration (Platt):** Brier 0.1214 → 0.1195; `a=0.78` (the raw head was mildly over-confident;
Platt shrinks it toward the base rate).

Reproduce any of these with `uv run python scripts/reproduce/replay_prefire.py`.

**Not yet measured (honest):** a live prospective A/B — actually running a paid reproduce cycle with the
gate on and reporting the realized budget saved at a held recall. That is the gated ~$35 arm; the
drift-guard + 15% canary give continuous free validation in the meantime.

## Why it's novel

Three grounding papers, each read in full, and none reaches ROGUE's cell:

- **Kirch, "What Features in Prompts Jailbreak LLMs?" (2411.03343).** Trains probes on **white-box
  internal activations** (Gemma-7B layer-17 residual stream) — a signal ROGUE's closed API targets do
  not expose. Its portable finding is the **hazard**: leave-one-attack-out transfer degrades to
  near-or-below random on held-out families (§3.3, Fig 4), because different jailbreaks work via distinct
  nonlinear features. That is the direct justification for the fire-all-on-novel-family rail, not a
  usable predictor.
- **Zhang, "Distillability of LLM Security Logic" (2511.22044).** Black-box and success-oriented, but a
  **single attack family** (Outline Filling), features = raw prompt text into a fine-tuned Llama-3-8B,
  and it predicts the **relative ranking** of same-question variants, not an absolute probability. Its
  FASC result supports rank-and-skip (top-20% cut queries-to-first-success 71–88%) — but it **never
  measures the recall/missed-breach cost** of a hard skip, which is the number this build earns.
- **Galinkin, "Improved Jailbreak Detection via Pretrained Embeddings" (2412.01547).** Embeddings + a
  light classifier are excellent (RF on Snowflake embeddings, F1 0.96 on JailbreakHub) — but the task is
  **jailbreak detection of the input**, with no target model in the loop and no notion of per-target
  breach.

**The contribution (systems framing):** a **black-box, cross-family, self-labeled, *calibrated* pre-fire
P(breach) scorer for a (harvested-attack × specific deployment-config) pair, with a drift-guarded skip
whose recall cost is measured** — made to work inside a live LLM red-team benchmark without moving its
verdicts (off by default; skips are visible, never silent; a canary keeps validating). The *ingredients*
are each precedented (embeddings→classifier; success-is-predictable; OOD-collapse); their combination
into a target-conditioned, cross-family, calibrated skip-gate — and the honest recall-vs-skip curve — is
not demonstrated by any of the three. Composes with, and is orthogonal to, Q11 (structural survival
ordering), Q6 (per-cell SPRT trial budget), and Q18 (the acquisition score, which consumes this
calibrated probability directly).

## Configuration

All off by default; see `.env.example`.

| Env var | Meaning | Default |
|---|---|---|
| `ROGUE_PREFIRE_SKIP` | master switch (`on`/`off`) | off |
| `ROGUE_PREFIRE_MODEL` | artifact path | `data/models/prefire_scorer.json` |
| `ROGUE_PREFIRE_THRESHOLD` | skip below this calibrated P(breach) | model's 95%-recall point |
| `ROGUE_PREFIRE_MIN_SUPPORT` | families below this many primitives → fire-all (drift-guard) | 8 |
| `ROGUE_PREFIRE_FIRE_ALL_FRAC` | deterministic fraction of skips force-fired (validation canary) | 0.15 |
| `ROGUE_PREFIRE_EMBED` | compute serve-time embeddings (`on`/`off`; off ⇒ structural-only) | on |

Train the artifact (free) then turn the gate on:

```bash
uv run python scripts/reproduce/train_prefire_scorer.py --out data/models/prefire_scorer.json
export ROGUE_PREFIRE_SKIP=on
export ROGUE_PREFIRE_MODEL=data/models/prefire_scorer.json
```
