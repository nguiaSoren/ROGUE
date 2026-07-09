# Hybrid-Acquisition Budget Ordering (Q18)

**What it is.** ROGUE has a fixed paid budget: hundreds of harvested attacks and money to fire only a fraction. Which fire *first*? Today the answer is the static, config-blind `reproducibility_score` order — a harvest-time self-rating that knows nothing about the target in front of it. Q18 replaces that, behind an off-by-default flag, with an **active-learning acquisition function** that spends the budget on the most *informative* attacks:

```
score(p) = w·value(p,c) + α·uncertainty(p,c) + β·diversity(p | already-chosen) + γ·info_gain(p,c)
```

Each term is a different *reason* to spend a dollar. It is not a new algorithm — uncertainty sampling, diversity sampling and expected-information-gain are textbook active learning. The contribution is a **systems** one: making a hybrid acquisition ordering work *inside a live LLM red-team* — composed from signals ROGUE already computes (Q7's calibrated P(breach), the pgvector payload embeddings, the breach-matrix cell counts), off by default, byte-identical when off, wired into all three fire surfaces, and measured against the order that actually ships.

## The four terms and their grounding

Every term has a home in the literature (verified from the full papers, not the survey brief that seeded them):

| term | what it rewards | tradition | grounding |
|---|---|---|---|
| **value** = P(breach) | attacks likely to breach *this* config (exploitation) | active **testing** — sample ∝ expected loss; a breach *is* the loss of the target's safety | Kossen *Active Testing* (2103.05331) §3.3 |
| **uncertainty** = `1 − 2·|P−0.5|` | attacks whose outcome we genuinely don't know (learning) | active **learning** — the prediction-probability distance to the decision boundary | Ma *Test Selection for DL Systems* (1904.13195): prediction-probability is "among the most effective" selection metrics |
| **diversity** = min cosine distance to the chosen set | coverage — don't burn budget on thirty near-identical DAN clones | Kossen tactic (b): decorrelate the chosen set; Chung names the same failure as *redundancy* | Kossen (2103.05331) §3.4; Chung (2405.07440) §2.2 |
| **info-gain** = `1/(n_cell + 1)` | attacks in an under-sampled `(target_model, family)` cell — a first Bengali many-shot jailbreak teaches more than the tenth DAN variant | expected reduction in the cell's breach-rate posterior variance (experimental design) | Chung *Maximizing Information Gain* (2405.07440): info-gain = model uncertainty − labeler uncertainty |

The key subtlety Kossen makes explicit and Ma corroborates: **active-testing acquisitions differ from active-learning ones**. `value` (∝ P(breach)) is the active-testing term; `uncertainty` (peaks at P≈0.5) is the active-learning term. They are the *same probability, opposite goals* — exploit vs learn. That is exactly why the uncertainty term is the one the **long-context robustness leaderboard** needs: the "breaks at N tokens" boundary sits where breach_prob ≈ 0.5, precisely where the uncertainty term is maximal.

**One honest omission.** Kossen's LURE importance-weighting exists to keep an *unbiased statistic estimate* under active selection. ROGUE's objective is discovery + learning, not an unbiased breach-rate estimate — so we deliberately do **not** apply LURE and do **not** sample stochastically. We sort deterministically (highest acquisition first), which preserves the canonical/discovery reproducibility contract (§10.3): the same corpus + telemetry snapshot always yields the same fire order.

## The system

`src/rogue/reproduce/acquisition/gate.py` — a sibling of the `survival` (Q11) and `prefire` (Q7) gates, deliberately mirroring their three-part contract so the wiring is uniform:

- `AcquisitionGate.rank(primitives, config)` runs a **greedy maximal-marginal-relevance** loop: value/uncertainty/info-gain are static per primitive; diversity is `1 − max cosine similarity to the already-chosen set`, updated **incrementally** with one numpy matrix-vector product per pick — O(n²·d), not the O(n³·d) a naive per-candidate recompute would cost (measured: 400 primitives in ~66 ms). The greedy pick order *is* the fire order.
- `resolve_acquisition_gate(session=…)` reads the env, or returns `None` when off → the caller falls back to today's order (a single uniform surface, byte-identical). It **composes existing artifacts rather than owning one**: value/uncertainty come from the Q7 pre-fire model (`ROGUE_ACQUISITION_MODEL`, defaulting to the shared `prefire_scorer.json`); a missing model is not fatal — value degrades to `reproducibility_score/10`, so the gate is still a working diversity + info-gain ordering.
- A **drift-guard** force-keeps novel / low-support families past any budget cap (Kirch 2411.03343: probes transfer *below random* to held-out families, so we never defer a family we lack in-distribution evidence about).
- Every deferral is surfaced (`ScanReport.acquisition`, `EndpointScanReport.n_acquisition_deferred`) — never a silent cut.

**Wired into all three fire surfaces**, off by default so a flag-off run is byte-for-byte unchanged:
- `scan.py::run_scan` (default `rogue scan` + SDK) and `reproduce/endpoint_scan.py::scan_endpoint` (public API / persist path) — reorders the survivors, before pre-fire skip.
- `scripts/reproduce/reproduce_once.py` (the research sweep) — reorders the flat `(primitive × config)` pair set; **ordering-only, never drops a cell** (an early `primitive_limit`/budget cutoff has already fired the most informative pairs, so the breach matrix and the predictor's own future labels stay complete). Diversity there is measured **within each config group** — firing the same payload against config A and config B is the matrix we want, not a redundancy.

## What the offline back-test shows (and doesn't)

`scripts/reproduce/replay_acquisition.py` — a **$0**, leak-free ranking replay over the pairs ROGUE has already paid to fire. The pairs are split by *primitive*; the Q7 value model and the info-gain cell counts are built from the **train fold only** and score held-out primitives they never saw; diversity uses stored embeddings (geometry, no labels). Three orderings ranked within each config's budget, macro-averaged across configs, percentile-bootstrap CI over configs (default split: 16 configs, 862 held-out pairs, 16.9% base rate):

| budget | ordering | breaches captured | families covered |
|---|---|---|---|
| 25% | `reproducibility_score` (shipped) | 39.8% | 31.2% |
| 25% | **acquisition** | **48.1% [42.2, 53.1]** | **44.9%** |
| 50% | `reproducibility_score` (shipped) | 46.1% | 47.4% |
| 50% | **acquisition** | **55.6% [51.4, 60.7]** | **67.0%** |

So at a quarter of the budget the acquisition order surfaces **~+8 pts more breaches and ~+14 pts more distinct attack families** than the order that ships today; at half the budget, **~+9 pts breaches and ~+20 pts families** (robust in sign across 0.35/0.4/0.5 splits; magnitudes vary with the config count).

**The honest attribution** — and the reason this is a component, not a headline algorithm: the **breach-capture** lift is *dominated by the value term* (Q7's config-aware P(breach)) over the config-blind `reproducibility_score`; value-only ≈ full at 25% budget. The novel **learning terms** (uncertainty + diversity + info-gain) are what earn the **coverage** gain — which is their entire purpose (learning the model's safety profile for the robustness leaderboard, and not re-firing near-duplicates), exactly the active-testing-vs-active-learning split above. Do not sell the learning terms as a breach-yield win; they are a coverage/learning win.

**Caveats, stated plainly.** (1) This is a re-ranking of an already-fired set — labels exist only for fired pairs — not a counterfactual over unfired primitives. (2) The **live** breaches-per-dollar number needs the gated paid A/B (acquisition order vs the shipped order over a fresh cycle), which folds into the queued ~$32 long-context sweep rather than a standalone spend.

## Relationship to Q7 and Q11

Q18 is the umbrella that unifies the sibling acquisition signals ROGUE already built:
- **Q7 pre-fire scorer** supplies the calibrated P(breach) that becomes the `value` and `uncertainty` terms. (Q18 consumes Q7; it does not retrain it.)
- **Q11 survival predictor** is an *alternate* acquisition signal (near-death configs) — a caller can run survival ordering first, and Q18 reorders its survivors.
- All three share the same `breach_results ⋈ attack_primitives ⋈ deployment_configs` substrate, the same Beta(1,1) smoothing convention (`ladder_priors`), and the same env-gated / byte-identical-when-off / injectable-gate discipline.

The decision boundaries differ and compose: **Q11** = "among things we'll test, what first (survival)?"; **Q7** = "before paying, what to skip?"; **Q18** = "order the whole fire-set by a hybrid of yield *and* learning value." Q18 is the allocation-layer generalization of the pure expected-breach order.

## Status & configuration

- **BUILT** + wired into `run_scan` / `scan_endpoint` / `reproduce_once`, off by default, byte-identical when off; 17 gate unit tests + a DB-gated end-to-end reproduce-splice test; real-Neon data-path verified (which caught an info-gain key-order bug a unit test alone missed). **$0 offline back-test done** (above). The **live** budget/coverage-per-dollar number is the one pending measurement — the gated paid A/B, folded into the ~$32 sweep.
- Env flags (all off / defaulted):
  - `ROGUE_ACQUISITION_ORDER` — master on/off (unset = off = today's order).
  - `ROGUE_ACQUISITION_MODEL` — P(breach) model path (defaults to the shared `data/models/prefire_scorer.json`; absent → reproducibility-score value fallback).
  - `ROGUE_ACQ_W_VALUE` / `ROGUE_ACQ_ALPHA` / `ROGUE_ACQ_BETA` / `ROGUE_ACQ_GAMMA` — the four term weights (defaults 0.60 / 0.25 / 0.10 / 0.05).
  - `ROGUE_ACQ_MIN_SUPPORT` — drift-guard family-support floor.
  - `ROGUE_ACQ_EMBED` — compute serve-time embeddings for diversity (on by default; off → diversity neutral, no network).
- Reproduce the offline number: `uv run python scripts/reproduce/replay_acquisition.py` (reads `$DATABASE_URL`; Neon, since the local DB is a redacted snapshot).

## Why it's a systems contribution, not a new algorithm

The acquisition function is standard active learning; none of its ingredients is novel. What is unreached by Kossen (image-classifier test-set labeling), Ma (DL retraining selection) and Chung (email-anomaly labeling) is the **combination**: a hybrid acquisition order that (a) runs *inside a continuous, black-box LLM red-team* against real customer configs, (b) composes a *calibrated cross-family P(breach)* with pgvector payload diversity and breach-matrix info-gain, (c) is proven **not to move the verdicts** (byte-identical when off, deferrals surfaced), and (d) is measured against the order that actually ships — with the breach-yield vs coverage tradeoff reported honestly rather than collapsed into one number. That framing — "we made a hybrid acquisition ordering work in a live red-team without moving its answers, and measured what it buys per budget" — is the P1 allocation paper's ordering-policy result, a sibling to Q11's survival signal, not a standalone paper.
