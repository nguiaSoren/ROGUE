# Adaptive Budget Allocation for Continuous LLM Red-Teaming (Q18)

*The problem is **budget allocation**; the mechanism is a hybrid **acquisition** order. Framing the module by the problem, not the mechanism, keeps it honest about what it is: a controller, not a new algorithm.*

**What it is.** ROGUE has a fixed paid budget: hundreds of harvested attacks and money to fire only a fraction. Which fire *first*? Today the answer is the static, config-blind `reproducibility_score` order — a harvest-time self-rating that knows nothing about the target in front of it. Q18 replaces that, behind an off-by-default flag, with an **active-learning acquisition function** that spends the budget on the most *informative* attacks:

```
score(p) = w·value(p,c) + α·uncertainty(p,c) + β·diversity(p | already-chosen) + γ·support(p,c)
```

Each term is a different *reason* to spend a dollar. It is **not a new algorithm** — uncertainty sampling, diversity sampling and an exploration/low-support bonus are textbook active learning. The contribution is a **systems** one: adapting active-learning acquisition to continuously prioritize attacks under a fixed evaluation budget, integrating a model-specific breach predictor, payload diversity, and an exploration bonus **without changing evaluation semantics** — composed from signals ROGUE already computes (Q7's calibrated P(breach), the pgvector payload embeddings, the breach-matrix cell counts), off by default, byte-identical when off, wired into all three fire surfaces, and measured against the order that actually ships.

**Scope (read this first).** The *thesis* here — allocation under a budget cap is a capability lever — is **not new to ROGUE**: its scheduler already demonstrates it, with paid data, at the escalation-**strategy** layer (which strategies to admit, and what order to run them). Q18 is a **primitive-layer instance** of the same thesis (which harvested *attacks* to fire first, vs which escalation *strategies* to try first), adding the active-learning terms the strategy scheduler's breach-rate blend lacks. So it is a controller and a shipped feature, not a new algorithm. **And a caveat that colours everything downstream:** the current evidence is an *offline replay*, which has a structural selection-bias limit (you only have labels for attacks that were actually fired), so it cannot answer the counterfactual — what if the policy had picked attacks that were never executed? Only the live experiment can. See both points, in full, below.

## The four terms and their grounding

Every term has a home in the literature (verified from the full papers, not the survey brief that seeded them):

| term | what it rewards | tradition | grounding |
|---|---|---|---|
| **value** = P(breach) | attacks likely to breach *this* config (exploitation) | active **testing** — sample ∝ expected loss; a breach *is* the loss of the target's safety | Kossen *Active Testing* (2103.05331) §3.3 |
| **uncertainty** = `1 − 2·|P−0.5|` | attacks whose outcome we genuinely don't know (learning) | active **learning** — the prediction-probability distance to the decision boundary | Ma *Test Selection for DL Systems* (1904.13195): prediction-probability is "among the most effective" selection metrics |
| **diversity** = min cosine distance to the chosen set | coverage — don't burn budget on thirty near-identical DAN clones | Kossen tactic (b): decorrelate the chosen set; Chung names the same failure as *redundancy* | Kossen (2103.05331) §3.4; Chung (2405.07440) §2.2 |
| **support** (exploration) = `1/(n_cell + 1)` | attacks in an under-sampled `(target_model, family)` cell — a first Bengali many-shot jailbreak is worth more than the tenth DAN variant | an inverse-support / low-support exploration bonus (Chung's *representativeness* / experimental-design motivation) | Chung *Maximizing Information Gain* (2405.07440) §2.2 |

**Naming honesty — this term is *not* expected information gain.** `1/(n_cell + 1)` is an **inverse sampling frequency** (a low-support / exploration bonus): it is monotone in how little we've sampled a cell, and it is *inspired by* expected-information-gain, but it is **not** EIG. True EIG would be the expected entropy reduction of the cell's Beta posterior over a fired outcome — a strictly larger computation we deliberately approximate with the cheap monotone proxy. Earlier drafts called it "expected posterior-variance reduction"; that overstated it. Read it as **exploration insurance for under-evidenced cells**, and if you want the principled version, computing the Beta-posterior EIG per cell is the drop-in upgrade. (The env var is the neutral `ROGUE_ACQ_GAMMA`, so no rename is forced by this correction.)

The key subtlety Kossen makes explicit and Ma corroborates: **active-testing acquisitions differ from active-learning ones**. `value` (∝ P(breach)) is the active-testing term; `uncertainty` (peaks at P≈0.5) is the active-learning term. They are the *same probability, opposite goals* — exploit vs learn. That is exactly why the uncertainty term is the one the **long-context robustness leaderboard** needs: the "breaks at N tokens" boundary sits where breach_prob ≈ 0.5, precisely where the uncertainty term is maximal.

**One honest omission.** Kossen's LURE importance-weighting exists to keep an *unbiased statistic estimate* under active selection. ROGUE's objective is discovery + learning, not an unbiased breach-rate estimate — so we deliberately do **not** apply LURE and do **not** sample stochastically. We sort deterministically (highest acquisition first), which preserves the canonical/discovery reproducibility contract (§10.3): the same corpus + telemetry snapshot always yields the same fire order.

## The system

`src/rogue/reproduce/acquisition/gate.py` — a sibling of the `survival` (Q11) and `prefire` (Q7) gates, deliberately mirroring their three-part contract so the wiring is uniform:

- `AcquisitionGate.rank(primitives, config)` runs a **greedy maximal-marginal-relevance** loop: value/uncertainty/support are static per primitive; diversity is `1 − max cosine similarity to the already-chosen set`, updated **incrementally** with one numpy matrix-vector product per pick — O(n²·d), not the O(n³·d) a naive per-candidate recompute would cost (measured: 400 primitives in ~66 ms). The greedy pick order *is* the fire order.
- `resolve_acquisition_gate(session=…)` reads the env, or returns `None` when off → the caller falls back to today's order (a single uniform surface, byte-identical). It **composes existing artifacts rather than owning one**: value/uncertainty come from the Q7 pre-fire model (`ROGUE_ACQUISITION_MODEL`, defaulting to the shared `prefire_scorer.json`); a missing model is not fatal — value degrades to `reproducibility_score/10`, so the gate is still a working diversity + support ordering.
- A **drift-guard** force-keeps novel / low-support families past any budget cap (Kirch 2411.03343: probes transfer *below random* to held-out families, so we never defer a family we lack in-distribution evidence about).
- Every deferral is surfaced (`ScanReport.acquisition`, `EndpointScanReport.n_acquisition_deferred`) — never a silent cut.

**Wired into all three fire surfaces**, off by default so a flag-off run is byte-for-byte unchanged:
- `scan.py::run_scan` (default `rogue scan` + SDK) and `reproduce/endpoint_scan.py::scan_endpoint` (public API / persist path) — reorders the survivors, before pre-fire skip.
- `scripts/reproduce/reproduce_once.py` (the research sweep) — reorders the flat `(primitive × config)` pair set; **ordering-only, never drops a cell** (an early `primitive_limit`/budget cutoff has already fired the most informative pairs, so the breach matrix and the predictor's own future labels stay complete). Diversity there is measured **within each config group** — firing the same payload against config A and config B is the matrix we want, not a redundancy.

## What the offline back-test shows (and doesn't)

**The structural limit, up front (a reviewer will raise it immediately).** This is a *replay*, and every replay shares one weakness: **you only have labels for attacks that were actually fired.** So it re-ranks an already-fired set and asks "were the true breaches surfaced earlier?" — it **cannot** answer the real counterfactual, *what if the acquisition policy had selected different attacks that were never executed?* That is selection bias, and no replay design (however leak-free) escapes it. It is exactly what the live experiment below removes: with a hard budget cap, the two orders fire *different* primitives, so a breach the baseline never reached becomes observable. Read every number below as "surfaces known breaches earlier," not "finds breaches that were unfindable."

`scripts/reproduce/replay_acquisition.py` — a **$0**, leak-free ranking replay over the pairs ROGUE has already paid to fire. Within that limit it is careful: the pairs are split by *primitive*; the Q7 value model and the support cell counts are built from the **train fold only** and score held-out primitives they never saw; diversity uses stored embeddings (geometry, no labels). Three orderings ranked within each config's budget, macro-averaged across configs, percentile-bootstrap CI over configs (default split: 16 configs, 862 held-out pairs, 16.9% base rate):

| budget | ordering | breaches captured | families covered |
|---|---|---|---|
| 25% | `reproducibility_score` (shipped) | 39.8% | 31.2% |
| 25% | **acquisition** | **48.1% [42.2, 53.1]** | **44.9%** |
| 50% | `reproducibility_score` (shipped) | 46.1% | 47.4% |
| 50% | **acquisition** | **55.6% [51.4, 60.7]** | **67.0%** |

So at a quarter of the budget the acquisition order surfaces **~+8 pts more breaches and ~+14 pts more distinct attack families** than the order that ships today; at half the budget, **~+9 pts breaches and ~+20 pts families** (robust in sign across 0.35/0.4/0.5 splits; magnitudes vary with the config count).

**The honest attribution** — and the reason this is a component, not a headline algorithm: the **breach-capture** lift is *dominated by the value term* (Q7's config-aware P(breach)) over the config-blind `reproducibility_score`; value-only ≈ full at 25% budget. The novel **learning terms** (uncertainty + diversity + support) are what earn the **coverage** gain — which is their entire purpose (learning the model's safety profile for the robustness leaderboard, and not re-firing near-duplicates), exactly the active-testing-vs-active-learning split above. Do not sell the learning terms as a breach-yield win; they are a coverage/learning win. This yield-vs-coverage separation — yield from a calibrated breach predictor, coverage from diversity + exploration — is what makes the module technically coherent and appropriately scoped.

**The other caveat.** The **live** breaches-per-dollar number needs a gated paid A/B (acquisition order vs the shipped order over a fresh cycle), which rides a scheduled paid sweep rather than a standalone spend — and doubles as the experiment that removes the selection-bias limit above.

## Relationship to Q7 and Q11

Q18 is the umbrella that unifies the sibling acquisition signals ROGUE already built:
- **Q7 pre-fire scorer** supplies the calibrated P(breach) that becomes the `value` and `uncertainty` terms. (Q18 consumes Q7; it does not retrain it.)
- **Q11 survival predictor** is an *alternate* acquisition signal (near-death configs) — a caller can run survival ordering first, and Q18 reorders its survivors.
- All three share the same `breach_results ⋈ attack_primitives ⋈ deployment_configs` substrate, the same Beta(1,1) smoothing convention (`ladder_priors`), and the same env-gated / byte-identical-when-off / injectable-gate discipline.

The decision boundaries differ and compose: **Q11** = "among things we'll test, what first (survival)?"; **Q7** = "before paying, what to skip?"; **Q18** = "order the whole fire-set by a hybrid of yield *and* learning value." Q18 is the allocation-layer generalization of the pure expected-breach order.

## The live experiment that would prove capability (not just ranking)

The offline replay proves ranking quality, not capability, and carries the selection-bias limit above. One paid experiment fixes both — it shows the acquisition order breaches goals the shipped order leaves unbreached under the same budget, which no replay can:

- **The single variable — fire-order under a hard budget cap.** Impose a fixed primitive budget (fire the top-K per target, or stop at $X). Ordering-only "never drop a cell" makes order pure *latency* if both arms eventually fire everything; the cap is what makes it a *capability* lever — a breach the acquisition order surfaces inside K but the baseline pushes past K is a breach the baseline never reached under the same budget. This is also what closes the selection-bias hole: the two orders fire *different* primitives within K.
- **Arms** (same corpus, judge, targets, budget, trials; change only the order): `reproducibility_score` DESC (shipped baseline) · **value-only** (`w=1, α=β=γ=0`) · **full acquisition** (default weights). The value-only arm is non-negotiable — it is what *shows*, rather than asserts, that yield comes from the value signal and the learning terms buy coverage (the same overclaim guard as this doc).
- **Breadth.** ≥2–3 target families across the alignment axis (an aligned Claude-class target, a permissive open-weight one, ideally a mid), reported **per target**: the value term should help the *aligned* target most, because `reproducibility_score` is most wrong there — the optimal order is target-conditional.
- **Scale.** ~100 primitives/target under the cap, enough that the breach-capture-at-budget delta's CI excludes 0 per family, with consistency across families.
- **Metrics.** Primary/capability: breaches within budget + the mechanism check that the extras are goals the baseline pushed past the cap (not the same winners found sooner). Coverage: distinct families / (family×model) cells within budget (the learning terms' axis). Cost/success: $ per breach. Ablation: value-only vs full, per target — the attribution guard.
- **Cost.** Ordering-only + a cap ⇒ near-**$0 marginal** riding a scheduled paid sweep (three toggles over one corpus pass); modest standalone.

Even powered, the honesty travels with it: lead the ablation, credit yield to the value predictor, credit the learning terms with coverage only.

## Status & configuration

- **BUILT** + wired into `run_scan` / `scan_endpoint` / `reproduce_once`, off by default, byte-identical when off; 17 gate unit tests + a DB-gated end-to-end reproduce-splice test; real-Neon data-path verified (which caught a support-term `(model, family)` cell key-order bug a unit test alone missed). **$0 offline back-test done** (above). The **live** budget/coverage-per-dollar number is the one pending measurement — a gated paid A/B that rides a scheduled paid sweep.
- Env flags (all off / defaulted):
  - `ROGUE_ACQUISITION_ORDER` — master on/off (unset = off = today's order).
  - `ROGUE_ACQUISITION_MODEL` — P(breach) model path (defaults to the shared `data/models/prefire_scorer.json`; absent → reproducibility-score value fallback).
  - `ROGUE_ACQ_W_VALUE` / `ROGUE_ACQ_ALPHA` / `ROGUE_ACQ_BETA` / `ROGUE_ACQ_GAMMA` — the four term weights (defaults 0.60 / 0.25 / 0.10 / 0.05).
  - `ROGUE_ACQ_MIN_SUPPORT` — drift-guard family-support floor.
  - `ROGUE_ACQ_EMBED` — compute serve-time embeddings for diversity (on by default; off → diversity neutral, no network).
- Reproduce the offline number: `uv run python scripts/reproduce/replay_acquisition.py` (reads `$DATABASE_URL`; Neon, since the local DB is a redacted snapshot).

## Why it's a systems contribution, not a new algorithm

The acquisition function is standard active learning; none of its ingredients is novel. And the *thesis* — that ordering under a budget cap is a capability lever — is **not new to ROGUE either.** ROGUE's escalation-strategy scheduler already shows, with paid data, that reordering the escalation **strategies** (holding repertoire, judge, corpus, and target fixed) converts budget-cap-unreached winners into breaches. So Q18 does **not** establish the ordering-as-capability finding.

What Q18 is, honestly, is a **primitive-layer instance of that same lever**, differing in exactly two ways: (1) the **layer** — the strategy scheduler reorders escalation *strategies within one attack's ladder* (a pure breach-rate exploitation blend); Q18 reorders the *primitive fire-set across the whole budget* (which harvested attacks to spend on first); (2) the **score** — Q18 adds the active-learning terms that blend lacks (uncertainty / diversity / exploration). Everything else is the same thesis.

Two honest caveats keep this from being oversold. First, the offline replay here is **weaker evidence than the strategy scheduler's paid result**, and the breach-capture lift is *dominated by the value term* — the same exploitation signal ROGUE's scheduler already uses; only the learning terms are genuinely new here, and they buy **coverage, not breach yield** (unmeasured live). Second, this is therefore **a shipped product feature and a controller, not a standalone research contribution** — the live experiment above is what would raise it to a capability result and let it stand beside the strategy-layer finding as a demonstration that the allocation-as-capability thesis holds across layers. The credible framing is exactly the reviewer's: *ROGUE adapts active-learning acquisition to continuously prioritize attacks under a fixed evaluation budget, integrating a model-specific breach predictor, diversity, and exploration without changing evaluation semantics.*
