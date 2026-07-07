# System-prompt-transfer survival predictor (Q11)

**One line.** Rank every harvested attack by its *predicted* probability of surviving a
system-prompt / context change, so a scan fires the likely survivors first and defers the rest —
instead of spending most of the reproduce budget on attacks that won't transfer.

**Status.** Built + offline back-tested on real historical breach data (free). A prospective live A/B
to publish a budget-saved headline is a separate, deliberately-gated ~$35 reproduce run. ⚑ possibly
publishable (see [Why it's novel](#why-its-novel)).

Code: `src/rogue/reproduce/survival/` · trainer CLI: `scripts/reproduce/train_survival_model.py` ·
live wiring: `reproduce/endpoint_scan.py` (the survival gate) · tests: `tests/test_survival_predictor.py`.

**Contribution (paper framing).** The contribution is *not* "we trained a model that predicts jailbreak
success" — that is crowded and weak. It is that **jailbreak evaluation implicitly assumes exhaustive
reproduction, and we show cross-deployment transfer is sparse (~14%) and predictable enough to make
evaluation budget-aware.** Four ingredients, in order of what a reviewer should care about: (1) a **new
prediction axis** — does an attack *survive a deployment change*, from its own surface features — which
the cited work leaves open; (2) a **leakage-safe evaluation protocol** (group-split by attack); (3) an
**operational drift-guard** that makes deferral safe under distribution shift; and (4) a **budget-saved
metric** measured on a real reproduction corpus, integrated into the live scan path. The estimator
itself is deliberately the least interesting part. External working title: *"Survival Ranking: Adaptive
Jailbreak Evaluation Under Deployment Shift"* (or *"Predicting Jailbreak Transferability Across LLM
Deployment Configurations for Budget-Efficient Security Evaluation"*) — "survival" is our internal term
and needs the deployment-shift gloss for an outside reader.

---

## The problem

ROGUE harvests jailbreaks from the open web and reproduces each one against a customer's
`DeploymentConfig` (model × system_prompt × tools). But a jailbreak that worked in the wild — under
*its* author's model and framing — usually does **not** survive being re-hosted in a different
deployment context. Most of a reproduce cycle's spend (Bright Data + the target panel + the LLM judge,
≈ $35 a cycle) therefore lands on attacks that were never going to transfer. The measured cross-config
survival base rate in ROGUE's own corpus is **~14%** (1,939 primitive × config pairs; see
[Measured results](#measured-results)) — i.e. the majority of fired trials are predictably dead on
arrival.

If we could *rank* attacks by predicted survival before firing, we would fire the survivors first and
defer the tail — recovering most of the real breaches for a fraction of the budget.

> Note on the "~4%" figure. The Elicit brief that seeded this quoted "~4% survive." That number is
> **Kirch's** dataset median ASR (2411.03343), a different quantity — the median attack-*method*
> success rate on one white-box model. ROGUE's *measured* cross-config survival base rate is ~14%. We
> report our own number, not the brief's.

## Why it's novel

The three load-bearing papers all answer a *neighbouring* question, and all with signals ROGUE's
closed API targets don't expose:

| Paper | What it predicts | Signal | Fits ROGUE? |
|---|---|---|---|
| **Kirch et al.** 2411.03343 — *What Features in Prompts Jailbreak LLMs?* | will *this attack* succeed on *this (one) model* | **white-box** probes on hidden activations | No — needs internals; and probes transfer *below random* to held-out attack families |
| **Ball et al.** 2406.09289 — *Understanding Jailbreak Success: Latent Space Dynamics* | shared latent mechanism (harmfulness-feature suppression) across classes | **white-box** residual-stream steering vectors | No — needs activations |
| **Helm et al.** 2605.26409 — *Jailbreak susceptibility via behavioral geometry* | how susceptible a *whole config* is (incl. 100 system-prompt configs) | **black-box** but embeds the *model's responses* (must still probe each config) | Partial — predicts per-**config** susceptibility, the *transpose* of our question, and still spends probe budget |

None predicts, from an **attack's own surface features**, whether it will **survive a system-prompt
change** — the exact axis ROGUE needs, and the one all three leave open. Kirch's central finding is
the governing caveat, not a blocker: probes trained on known attack families transfer *below random*
to held-out families. We inherit that as a **drift-guard** (fire-all for novel/low-support families),
not as a reason to give up — because ROGUE's question is not "understand the mechanism" but "rank what
to fire first," and for that a calibrated black-box ranker over features we already own is enough.

## Method

**Black-box, embedding-free at serve time.** Every feature is something ROGUE already has for free when
a scan starts — no model internals, no embedding API call in the hot path, no probe spend. This is also
corroborated by ROGUE's own prior negative result
([`payload_embedding_technique_signal.md`](payload_embedding_technique_signal.md)): the payload
*embedding* carries only a faint, non-separating technique signal (silhouette ≈ 0), i.e. the attack's
**surface** dominates — exactly what this predictor keys on.

- **Features** (`survival/features.py`, 54 dims, fixed-order + versioned):
  - *Attack surface*: family / vector one-hots over the frozen §4.2 taxonomy (+ a trailing "unknown"
    slot), `requires_multi_turn / _system_prompt_access / _tools / _multimodal`, `synthesized`,
    has-generator, has-multi-turn-sequence, a novel-family flag, `reproducibility_score`,
    `authorship_score` (+ a missing flag), payload length, turn count.
  - *Target-config descriptor*: size class × context bucket (reused from `config_features.py`),
    tools/multimodal, and a **system-prompt class** — `none | permissive | guarded-short |
    guarded-long` (keyword heuristic) plus forbidden-topic / declared-tool counts. This is the axis
    survival hinges on.
- **Label**: for each (primitive × config) pair in `breach_results`, did it breach (any-breach rate ≥
  the same 0.4 threshold the threat brief uses)?
- **Survival estimator** (`survival/model.py`) — *deliberately the least interesting part; the
  contribution is above the model, not in it.* A strong-L2-regularized linear head fit deterministically
  (numpy-only, Newton/IRLS, no random init → identical weights across runs). The estimator is chosen to
  be *boring on purpose*: on thousands of rows (not millions) a heavily-regularized linear model
  out-generalizes a boosted forest and won't memorize a few prolific primitives; it adds **no new
  dependency**; and its coefficients are inspectable, so "why did this rank high" is a dot product —
  which matters for a security tool whose users must trust the order. Swapping in a gradient-boosted or
  neural head is a free future ablation; it would not change the paper, because the paper is the axis
  and the protocol, not the function class.
- **Training + back-test** (`survival/train.py`): the join `breach_results ⋈ attack_primitives ⋈
  deployment_configs`. Headline metric is **budget-saved** = 1 − (trials fired, in survival-rank order,
  to recover 80% of true survivors) / (fire-all).

**The one methodological choice reviewers check first: the split is group-aware by primitive.** Every
trial of a given attack is *entirely* in train or *entirely* in test — never the leakage pattern
"attack A × config 1 → train, attack A × config 2 → test," which would let the model memorize attack A
and report an inflated number. That split is the difference between measuring *"will a **new** attack
survive a deployment change"* and accidentally measuring *"can we recognize an attack we've already
seen."* The reported AUC is the former; it is the number that has to hold for the feature to be worth
shipping.

## The drift-guard (why this is honest)

The failure mode identified by Kirch et al. (probes trained on known families transferring below random
to held-out ones), made operational. Two rails in `survival/gate.py`:

1. **Fire-all for novel / low-support families.** A family with fewer than `min_support` (default 8)
   distinct training primitives, or a technique the frozen taxonomy doesn't cover
   (`taxonomy_fit == "novel"` or an `emergent_label`), is **never deferred** — it is fired regardless
   of score. We only ever skip attacks we have in-distribution evidence about. This is exactly ROGUE's
   harvest-new-attacks regime: a freshly-harvested family always gets a real reproduction until enough
   labels accumulate to trust a skip.
2. **Deterministic canary sampling.** Even among skippable low-score attacks, a fixed fraction
   (default 15%, stable hash of the primitive id — no RNG state) is force-kept, so the gate keeps
   collecting ground truth on the exact rows it wanted to skip. Continuous free validation; a
   reproducible scan.

## Live wiring

Off by default; a pure reprioritization when on. The **same** `apply_survival_order` call is spliced
into **both** reproduction entry points, once each, right before the fire loop — so the gate is live on
every scan surface, not one:

- `src/rogue/scan.py::run_scan` — the **default `rogue scan` + SDK `Client.scan`** path (surfaces the
  decision on `ScanReport.survival` → `to_dict()["survival"]`).
- `src/rogue/reproduce/endpoint_scan.py::scan_endpoint` — the **public scan API**, the `--persist`
  CLI, retest, and the scan scripts (surfaces it on `EndpointScanReport.n_deferred` / `survival_note`).
- `scripts/reproduce/reproduce_once.py::run_reproduction` — the **research reproduce sweep** (the paid
  arms). Here it is **ordering-only by default** (`apply_survival_order_pairs`): the cartesian
  (primitive × config) fan-out is reordered survivors-first, so an early `primitive_limit`/budget
  cutoff or an interrupted run has already measured the survivors — but **no cell is ever dropped**, so
  the breach matrix and the predictor's own training labels stay complete. Dropping the predicted-dead
  tail is an explicit opt-in (`--survival-skip` + `ROGUE_SURVIVAL_SKIP_THRESHOLD`), reserved for a
  deliberate Arm-13 A/B — never a normal measurement run.

Behaviour:

- `ROGUE_SURVIVAL_ORDER` unset → identity order → today's behaviour byte-for-byte (the report dicts are
  byte-identical — the `survival` key is emitted only when the gate ran).
- `ROGUE_SURVIVAL_ORDER=on` + a model artifact present → the corpus is reordered so predicted survivors
  fire first. Two ways to actually **defer** the predicted-dead tail (both surfaced, never a silent
  cut): a **score floor** via `ROGUE_SURVIVAL_SKIP_THRESHOLD` (env-only, reachable from every surface
  including the bare CLI), or a **top-k cap** via the `survival_max_primitives` param (library/SDK/API
  callers that pass the full corpus).
- No model / stale artifact → the gate quietly no-ops (keeps default order). It is an optimization,
  never a dependency of a scan completing.

```bash
# Train (free — reads only already-paid breach history):
uv run python scripts/reproduce/train_survival_model.py --out data/models/survival_predictor.json

# Turn the gate on for scans (works on both run_scan and scan_endpoint):
export ROGUE_SURVIVAL_ORDER=on
export ROGUE_SURVIVAL_MODEL=data/models/survival_predictor.json
# optional: defer everything the model scores below 0.15 (env-reachable on every surface incl. CLI)
export ROGUE_SURVIVAL_SKIP_THRESHOLD=0.15
```

### What was actually executed (wired ≠ run)

Both splices were run end-to-end with the **real trained artifact** and the env-resolver (no injected
gate), against `$0` fake panel/judge so there is no spend but the real code path fires:

- `scan_endpoint` — env-resolved gate fired; reordered + deferred; `n_deferred`/`survival_note` set.
- `run_scan` — env-resolved gate fired; `ROGUE_SURVIVAL_SKIP_THRESHOLD` deferral bit; `ScanReport.survival`
  populated and emitted in `to_dict()`.
- `run_reproduction` (the sweep) — ran the **real sweep body** against the local Postgres with the gate
  on: ordering-only emitted `survival sweep-order: 24 pairs ranked, 0 deferred (ordering-only)`, and
  `--survival-skip` emitted `24 deferred (skip on)` + the honest `deferred N/M pairs` log. Re-verified
  2026-07-07 with **no stub**: `run_reproduction` ran against the real local Postgres via a `$0` mock
  panel/judge (`--primitive-limit 1` → 1 primitive × 24 configs) — gate-off persisted 24/24 real pairs,
  ordering-only fired 24/24, `--survival-skip` deferred all 24; the 48 rows written across the three modes
  were deleted afterward (DB restored to its prior 12,650). The ORM→Pydantic converter converts all
  635/559 (total/canonical) primitives cleanly — the earlier "0/40 converter drift" note was **not
  reproducible and is retracted**; no sweep blocker is known.
- The **trainer** ran against the real local Postgres (`train_from_db`, 1,939 real pairs) — a genuine
  end-to-end DB read, not a fixture.

Not yet executed (honestly): a **paid** `rogue scan` / public-API HTTP call with the gate on against a
real endpoint — that is the gated live A/B. The fakes above cover the exact `scan_endpoint` /
`run_scan` calls those surfaces make; what they do **not** cover is real target/judge latency and the
HTTP/auth layer of the API front.

## Measured results

Trained on the local breach history: **1,939 (primitive × config) pairs, 278 survivors (14.3% base
rate), 15 families, 8 configs.** Group-split by primitive (1,473 train / 466 test):

| Metric | Value | Meaning |
|---|---|---|
| ROC-AUC (held-out) | **0.77** | ranks a random survivor above a random non-survivor 77% of the time |
| Precision@10% | **0.62** | of the top-ranked 10%, 62% actually survive |
| Lift@10% | **4.2×** | vs the 14.6% test base rate |
| **Budget-saved @80% recall** | **0.39** | recover 80% of survivors after firing only 61% of trials → defer 39% |

Reproduce: `uv run python scripts/reproduce/train_survival_model.py` (the artifact carries these
numbers inline in `.metrics`).

**Honesty caveats.** (1) One DB, 8 configs — the cross-*system-prompt* signal is real but the config
diversity is modest; a wider config population would sharpen it. (2) These are **offline back-test**
numbers on already-paid data; the *live* budget-saved figure (predictor-ranked top-k vs random,
measured on a fresh paid cycle) is the headline-eligible number and is gated. (3) The shipped serving
model is surface-features-only; adding the DB payload embedding is a plausible accuracy ceiling-raise
(the training path can already featurize it) but was kept out of the serving hot path to guarantee
zero-cost, no-API-call ranking.

### Strengthening experiments (measured, `$0`)

Three offline experiments a security reviewer asks for, all on the already-paid corpus — reproduce with
`scripts/reproduce/survival_experiments.py` (read-only, no spend):

**1. Leave-one-family-out (LOFO) — generalization to an unseen family.** Retraining with an *entire
attack family* held out and testing on it, mean held-out **AUC = 0.62** (median 0.60, 13 evaluable
families) — down from the in-distribution 0.77, the honest degradation expected when the test family
was never seen. The tail is the point: `tool_use_hijack` lands at **AUC 0.49 — below random**, which is
consistent with the failure mode Kirch et al. identify (probes collapsing below random on held-out
families) and is the direct empirical justification for the **drift-guard**: generalization across
*primitives* of a known family is strong (0.77), but across an
*unseen family* it is partial and can collapse — so the gate defers only within-distribution and fires
every novel / low-support family unconditionally.

| held-out family (n / survivors) | AUC |
|---|---|
| policy_roleplay (30 / 2) | 0.79 |
| training_data_extraction (89 / 57) | 0.68 |
| refusal_suppression (188 / 22) | 0.62 |
| indirect_prompt_injection (570 / 77) | 0.60 |
| direct_instruction_override (267 / 33) | 0.54 |
| tool_use_hijack (60 / 6) | **0.49 (below random)** |
| **13 families (mean)** | **0.62** |

**2. Calibration — the scores are trustworthy, not just monotone.** On the held-out set predicted
survival tracks observed across the range (0.10→0.09, 0.26→0.36, 0.50→0.56, 0.86→0.92), giving
**ECE = 0.026**. The budget policy only needs the *ranking*, but a low ECE means a score can be read as
a probability — useful if the gate ever surfaces "P(survive)" to an operator.

**3. Baselines — the lift is the learned axis, not any ordering.** Budget-saved @80% recall: survival
**0.391**, random **0.199** (≈ 2× survival), and the reproducibility-score heuristic **0.056 — *worse*
than random.** A single hand-picked feature *hurts*: an attack's in-the-wild `reproducibility_score`
does not predict *cross-config* survival (if anything it anti-correlates), which is exactly why the
learned survival axis is needed. Survivors recovered vs budget fired makes the separation visible:

| budget fired | survival | reproducibility | random |
|---|---|---|---|
| 10% | 43% | 1% | 10% |
| 20% | 53% | 13% | 20% |
| 40% | 76% | 29% | 40% |
| 50% | 79% | 38% | 50% |

Of the four experiments a main-conference bar wants, three are done here; only the **live A/B**
(predictor-ranked top-k vs random on a fresh paid cycle) remains the one gated number.

## Publishability

The paper is *not* publishable because "the classifier works." It is publishable because it names a
**missing axis in jailbreak evaluation — transfer survival under deployment shift — and builds a
budget-aware evaluation system around it.** A black-box, per-*attack* predictor of cross-system-prompt
survival is the gap Kirch (white-box, same-model), Ball (white-box, mechanism) and Helm (black-box but
per-*config*, the transpose of our question) all leave open, and ROGUE provides an uncommon asset they
lack: a table of *the same attacks reproduced across many deployment configs*. The measured
budget-saved curve on a real reproduction corpus (not a static benchmark) is a first-of-its-kind
artifact, and it composes with the P1 allocation-scheduler paper (survival rank is a new acquisition
signal for the allocator).

**Venue fit.** This is a *security-systems* contribution, not an ML-algorithm one — so a security venue
(USENIX Security / NDSS / CCS) is the right home, where "a real system + an expensive evaluation problem
+ operational deployment + an honest threat model" reads as strength. An ML-conference reviewer
(NeurIPS/ICML) would fixate on "logistic regression on handcrafted features / small dataset" and miss
the point; TMLR is a plausible fit once the experiments below are added.

**Current state → strengthening path.** As written this is a strong workshop / applied-security paper —
the framing, the leakage-safe protocol, and the honest caveats are here. Of the four experiments a
main-conference security bar wants, **three are now measured** (see [Strengthening experiments
above](#strengthening-experiments-measured-0), all `$0` on already-paid data):

1. ✅ **Leave-one-family-out** — mean held-out **AUC 0.62**, with one family (`tool_use_hijack`) **below
   random**: consistent with the failure mode Kirch et al. identify, and the empirical case for the drift-guard.
2. ✅ **Calibration** — **ECE 0.026**; the scores are trustworthy, not just monotone.
3. ✅ **Baselines** — survival budget-saved **0.391 vs random 0.199 (≈2×)**; the `reproducibility_score`
   heuristic is **worse than random**, so the lift is the *learned* survival axis, not any ordering.
4. ⏳ **Live budget-saved A/B (the headline)** — predictor-ranked top-k vs. random on a fresh paid cycle,
   prospective confirmation of the offline 0.39. This is the one gated number (a dedicated paid A/B);
   until it lands, "39% budget saved" is an offline back-test result, not a deployment claim.

The sentence that carries it: *this is not "the classifier works," it is "cross-deployment jailbreak
transfer is a predictable axis, and evaluation can be made budget-aware around it."*

## Grounding

Papers read in full via crawl4ai (ar5iv HTML): Kirch 2411.03343, Helm 2605.26409, Ball 2406.09289.
