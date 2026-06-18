# Adaptive Attack Orchestration Systems — working draft

> **Status: WIP research-notes skeleton (started 2026-06-03).** Not a paper yet —
> a structured capture of the systems findings so they aren't lost, ready to be
> fleshed out. Framing: this is *adaptive systems engineering*, not prompt
> engineering. The interesting object is the **orchestration system + its telemetry**,
> not any individual jailbreak.

## Thesis

A continuous open-web red-team's growth is not gated by attack cleverness but by
**orchestration**: which techniques get harvested, whether they can be *evaluated*
at all, and how evaluation budget is *allocated*. ROGUE is a case study in moving
each of those from hand-coded/static to **telemetry-driven adaptive control**, and
in the instrumentation required to do so honestly.

## Proposed structure

1. **System overview** — harvest → extract (payload vs *technique*) → lifecycle
   (candidate→active→retired→resurrected) → reproduction ladder → judge → threat brief.
   The two control surfaces: a *harvest* bandit (what to fetch) and a *break* scheduler
   (how to evaluate). "A bandit on each end."
2. **The telemetry substrate** — what must be logged to make orchestration legible:
   `ladder_attempts` (entity × depth × outcome × policy × winner), the valid-trial split
   (`n_attempts_total` vs `n_valid_trials`), rank-of-winner. *The central methodological
   claim: you cannot optimize allocation until orchestration failure is separated from
   capability failure.*
3. **Findings (the substance — see below).**
4. **The lifecycle model** — winner-only graduation; soft retirement on valid-trial
   evidence + time-diversity; resurrection on drift. Why retirement must measure *attack*
   failure, not *orchestration* failure.
5. **Adaptive allocation** — the increment ladder: fixed order → greedy reorder
   (Laplace-smoothed breach rate) → viability-aware EV heuristic → (future) contextual
   Thompson. Why each step waits on telemetry maturity.
6. **Measurements** — before/after on rank-of-winner, call-count, graduation rate,
   validity rate. (TODO: paid runs to populate.)
7. **Related work** — ARMS (strategy library vs agent), Crescendo, PyRIT, bandit RL.
8. **Limitations & honesty ledger** — underpowered A/Bs, unmeasured reachability,
   variance-dominated effects, cost-logging gaps.

## Findings captured so far (raw — to be written up)

- **Planner-willingness as a gating function.** The dominant bottleneck to repertoire
  growth was not technique quality but the *planner refusing to author attacks*: an
  aligned planner capped harvested-candidate validity at **~22%** (mostly refusals).
  Changing **only** the planner backbone to a permissive model took validity **22% → 100%**
  and graduated a technique (VERA) the aligned planner had made *unreachable, not weak*.
  → Architecture response: **safe judge + permissive planner + safe target.**
- **Exploration starvation from greedy early-stop.** A first-breach-wins ladder let
  Tier-1 image renderers absorb nearly every breach before Tier-5 harvested candidates
  ran (`escalation_winners = [image:mml:wr ×8, image:ocr ×2, image:typographic ×2]`;
  candidates `n_times_tried = 0`). Exploitation starved exploration. → Responses:
  candidate-attempt quota (reserve exploration budget) + Laplace-smoothed reorder +
  discovery/UCB mode. **Rich-get-richer is the failure mode naive greedy *amplifies*.**
- **Deterministic grammar orchestration (LLM-as-author → LLM-as-parameterizer).** Moving
  the attack *structure* into versioned `StrategyTemplate` grammars and demoting the model
  to filling typed slots removed the provider-willingness dependency from the *correctness*
  path. Bottleneck shifted from "which provider refuses least this month" (uncontrollable)
  to "grammar coverage" (an engineering problem).
- **Semantic parameterization (slot-fill).** A structurally-gated middle tier where the
  model fills only *semantic slot values* (never turns); total fallback (any failure →
  pure template) makes it **strictly dominate** the template on reliability. Measured:
  1.00 validity / 0 orchestration failures.
- **Breach rate is variance-dominated at small N — and misleading even when stable.** A
  3-arm grammar-efficacy A/B had arms *swap order across runs* (templates 0.25↔0.44,
  freeform 0.44↔0.33): per-arm differences were run-to-run variance, not the arm. Lesson:
  **underpowered A/Bs + the need for paired (McNemar) designs**; and breach rate alone
  hides viability (a strategy that breaks hard but rarely *runs*).
- **The breach signal is a same-instrument constant offset — relative findings hold; the
  judge's absolute quality was measured, found over-eager, and then recalibrated.** Scoring the
  v1/v2 judge against JailbreakBench's `judge_comparison` (300 human-labeled rows, 4 field
  classifiers as the bar) originally put it **last at 70.3% agreement** with the human majority
  (HarmBench 78 / LlamaGuard-2 88 / GPT-4 90 / Llama-3 91), with a clear signature: **recall 98%
  / precision 55%** — it caught nearly every real jailbreak but over-flagged ~46% of
  human-cleared responses. A production-data FP audit (`docs/judge_fp_taxonomy.md`, n=20, 45% FP
  rate) diagnosed the cause as a *rubric* problem: the judge rewarded **engagement with the
  attack frame** (persona acceptance, acknowledgment, format mimicry, conceptual meta-discussion,
  intent-anchoring) over **transfer of harmful content**. The fix landed as **`judge_v3.md`**, a
  content-transfer gate plus four re-scoped anti-bias rules, now the default rubric. On the same
  300-item set the recalibrated judge scores **precision 79.5% / recall 95.5% / agreement 89.3%**
  (`docs/judge_fp_taxonomy.md §6`) — the content-transfer gate bought **+24.5 points of precision
  (FP ~45%→~20%) for −2.5 points of recall** and **+19 points of human agreement**, moving ROGUE's
  judge from **dead-last to 3rd of 5, tied with the frontier LLM-as-judge baselines**. **Why the
  orchestration results survive regardless:** the judge is the *same* instrument across every arm,
  run, and model, so its calibration is a near-constant offset that cancels in the A/B deltas,
  reachability comparisons, and growth-over-time figures this work reports — and that was already
  true under v1. What the recalibration improves is the **absolute** breach rates: the 1.4%→48.6%
  span below was graded by the over-eager v1/v2 judge, so read those as upper-ish estimates on the
  strict-harm construct. **The stored breach matrix has since been re-judged under v3 (2026-06-07; breach
  cells −43.6%); the matrix numbers in this note were captured pre-re-judge and remain v1/v2-graded** — the
  relative orchestration findings are unaffected, but the absolute breach rates would tighten under
  v3. This is also why the external **benchmark layer** (AdvBench/JBB repertoire-replay) measures
  *coverage change over time* rather than an absolute number.
- **Allocation quality is the real frontier.** Hence the scheduler reframe from "what
  breaches most?" to "what is worth evaluation budget right now?" (EV = effectiveness ×
  viability × freshness × exploration). Then **reachability** ("what could have run but
  didn't") — logged as of migration 0019 — turns "outcomes" telemetry into "opportunities"
  telemetry, the precondition for honest allocation analysis.
- **Per-model technique-effectiveness map (contextual signal).** From 10,872 `breach_results`
  rows: per-model breach rates span **1.4% (Claude Opus) → 48.6% (Mistral Small)**, and the
  `(model × family)` matrix is sharp — e.g. `mistral × training_data_extraction = 0.92`,
  `gemini × training_data_extraction = 0.81`, vs the aligned models far lower. This is both
  the bandit's warm-prior and a standalone threat-intel artifact. *Methodological caveat for
  the paper:* per-`(strategy × model)` is NOT measurable from the short-circuiting ladder —
  a genuine instrumentation limit worth stating, not hiding.

## Results — first Phase-2 sweep (2026-06-03, run `sweep_p2_1780457963`)

40 primitives × 6 configs × 5 trials (1,200 baseline cells) + inline escalation
(`ROGUE_LADDER_ORDER=canonical`, `candidate_quota=0`, escalation capped at $25).
Total $30.27; 8 EVADE parents escalated, 8/8 breached. The headline is a **measured
efficiency↔growth tradeoff**, not a point result.

**What greedy reorder bought (efficiency):**
- **rank-of-winner median 0** (min 0 / mean 3.2 / max 21) — the winner was tried
  *first* in most ladders. The reorder front-loaded `image:mml:wr` (the historical
  top winner) and it broke immediately.
- escalation cost **$2.80 for 8 breaches** (≈$0.35/breach); very low ladder work.

**What it sacrificed (growth) — now measurable for the first time:**
- **85% of all eligible strategy-appearances were `early_stop`-starved** (only 15%
  executed). By tier: planner **7% reachability / 93% starvation**, audio/structured
  0.12, coj 0.17, image 0.40.
- **6 high-value / low-reachability strategies** ("invisible candidates"): a harvested
  technique at value 0.68 / reach 0.12, `image:mml:base64` at 0.60 / 0.25, and **three
  candidates at value ≈0.50 / reachability 0.00 / starvation 1.00** — not weak, *never
  reached*.
- **0 new graduations**: candidates got 24 attempts but only 6 valid trials (starved /
  refused), so none could win → none graduated. Efficiency-vs-growth, same story.

**Allocation bias (winner attribution vs the unbiased matrix) — the sharp finding:**
the ladder's winner-model distribution is nearly *inverted* from true vulnerability,
because the short-circuit credits the first-breaching model in config order, not the
most vulnerable one:

| model | ladder win-share | unbiased breach% (breach_results) | Δ |
|---|---|---|---|
| gpt-5.4-nano | 62% | 11% | **+51** |
| mistral-small | 12% | 49% | **−37** |
| gemini-flash-lite | 0% | 29% | −29 |
| llama-3.1-8b | 25% | 16% | +9 |

This is a clean, generalizable systems metric: *short-circuit winner attribution is
unreliable for per-model conclusions; only the full matrix is.*

**Interpretation.** Greedy reorder is a *correct* optimizer of its objective (wasted
ladder work) — and the reachability telemetry shows that objective is in tension with
repertoire growth. The next increment (Phase 2.2) treats reachability as *exploration
pressure* (`value × (1 + starvation_bonus)`), not a multiplier, so strong performers
keep their rank but the monopoly that starves invisible high-value candidates breaks.
*(Caveat: this run used `candidate_quota=0` — the unmitigated worst case for candidate
reachability; the quota is the existing cross-tier counter-lever.)*

## Quota simulation (zero-cost, replayed from the sweep — `scripts/simulate_quota.py`)

Before paying for a second sweep, the candidate-quota effect was estimated by replaying the logged `ladder_rotation_membership` rows (the quota mechanic is deterministic given the rotation). Result: the cost of suppressing early-stop is binary at quota `0 → 1` (`$2.80 → $18.45`, ~6×, because reaching even one starved candidate runs almost the whole ladder), with quota `1 → 3` adding nothing further; planner-tier reachability jumps from `0.07` toward full once the cap lifts. The scheduling rule that falls out: there is no cheap partial quota — if you pay the early-stop-suppression cost at all, run the full quota. What the simulation cannot answer is whether a now-reachable candidate would *breach* (it never ran), so this justifies — but does not replace — the paid `starvation + quota=3` sweep.

## Results — second sweep, the causal test (2026-06-03, run `sweep_starv_q3_1780462736`)

Same 40-primitive set, `ROGUE_LADDER_ORDER=starvation` + `--candidate-quota 3` + `--n-trials 1`, escalation hit the $25 cap (10 ladders, 10/10 breached). This run isolates the single causal question the whole sequence was built around — *if candidates become reachable, do they breach and graduate?* — and the answer is an emphatic yes. Starvation collapsed from 85% to **1%** (planner-tier reachability 0.07 → 0.98), and the candidates that had been invisible at quota=0 broke through: of the 3 candidates the selection cap put in the rotation, all 3 breached and **all 3 graduated** (active 7 → 10, a +43% repertoire jump in one run, versus 0 graduations in the canonical run). The scheduler was never filtering bad candidates; it was preventing their evaluation. Allocation is therefore not merely an efficiency layer — it is a capability-growth mechanism, which is a substantially stronger result than the reachability-telemetry work originally aimed for.

The starvation reorder also visibly de-monopolised the image tier without penalising the strong incumbent: `mml:base64` (previously starved) rose to win 4 ladders alongside `mml:wr`'s 4, where the canonical run had `mml:wr` winning 6 of 8. Cost is the honest counterweight: escalation cost-per-breach rose from $0.35 (greedy) to $2.51 (quota=3 runs the full rotation), so quota=3 is a deliberate periodic "growth sweep", not a default. A correctness check during analysis confirmed the graduation gate is already mode-adaptive by construction — `apply_ladder_outcome` graduates any harvested strategy whose own outcome was a breach, so quota mode naturally graduates every breaching candidate while early-stop mode graduates only the winner (because only the winner runs). The per-sweep graduation ceiling is thus the candidate *selection* cap K (=3), not the attribution rule; the next lever for more graduations is selecting more of the 12 unevaluated candidates per growth sweep, whose payoff — like the quota cost itself — is only knowable by running them.

## Pre-registration — Growth Sweep #2 (K=5, quota=5), written before launch 2026-06-03

Config: `CAND_LADDER_CAP=5`, `ROGUE_LADDER_ORDER=starvation`, `--candidate-quota 5`, `--primitive-limit 40`, `--n-trials 1`, `--escalate-max-spend 28`. Same primitive set as the K=3 causal test; the only changed variables are the candidate selection cap (3→5) and the quota (3→5, raised in lockstep so all selected candidates are actually evaluated — quota must equal K or the extra slots are a second, confounding bottleneck). Projected cost ~$32 total (~$27 escalation, +$2 over K=3 because the extra two candidates are marginal on top of the full-rotation quota tax already paid), ~2.5h.

**H1:** increasing K from 3→5 produces additional graduations at acceptable marginal cost. **Null:** the extra two candidates do not graduate, indicating the remaining candidate pool is substantially weaker than the first three selected. The K=3 run's 3/3 graduation yield does not predict the next two will graduate — selection is least-tried-first, so the next two are not quality-ranked — but it justifies investigating the pool.

Pre-committed metrics and their reading: candidates evaluated (did we hit 5/5 — confirms quota=5 reached all of them), candidate breaches (raw capability), graduations (actual repertoire growth), graduation yield (graduations ÷ candidates evaluated), cost per graduation (the decision metric), reachability (should stay ~1.0, confirming the allocation fix holds at K=5). Interpretation committed in advance: ~5 graduations ⇒ K=3 was too small, growth scales with selection budget, run larger/more frequent growth sweeps; 3–4 ⇒ diminishing returns, K≈3 near-optimal; 0–1 of the new two ⇒ the unevaluated pool is weak and the frontier moves to candidate-quality estimation (better harvesting/filtering), not more slots.

## Result — Growth Sweep #2 (K=5, quota=5), 2026-06-03 (run `sweep_K5_q5_1780477935`)

**H1 supported, Null rejected.** All 5 selected candidates were evaluated (quota=5 reached them; planner-tier reachability held at 0.98), and 4 of the 5 graduated, taking active techniques 10 → 14 (+40%). The decisive number is the combined yield across both growth sweeps: 7 graduations out of 8 evaluated candidates (87.5%). If the candidate pool were mostly junk we would have seen the second batch collapse (e.g. 3/3 then 1/5); instead it held at 4/5. The pool is not exhausted, and selection budget — not candidate quality — remains the binding constraint on growth.

The economic finding is the more important one: cost-per-graduation **improved** as K rose, from $8.37 (K=3, $25.10 ÷ 3) to **$7.01** (K=5, $28.06 ÷ 4). This inverts the usual exploration intuition (immediate diminishing returns). It holds because the quota makes each ladder run the full rotation regardless, so harvested candidates ride along nearly for free — ladder execution is a fixed cost, candidate evaluation a marginal one. As long as candidates keep graduating, raising K monotonically improves graduations-per-dollar by amortizing the fixed full-rotation tax over more graduations. The first hint of a yield bend appeared (100% → 80%), but it is far short of a reason to stop. Caveat: the two sweeps used different candidate batches (the first three graduated and left the pool), so this is "two growth sweeps both succeeded" evidence, not a controlled marginal-K curve on identical candidates; the 87.5% combined yield is the robust figure.

**Core empirical claim now established:** capability growth in this system is constrained more by evaluation *allocation* than by candidate *quality*; raising the selection cap K from 3 to 5 increased repertoire growth while improving cost-per-graduation. Allocation budget is one of the dominant drivers of repertoire growth, not a saturated knob.

## Operating modes (made explicit 2026-06-03)

Two distinct objectives emerged, each with a different optimal configuration; they should not share a default.

- **Canonical mode** — goal: find breaches cheaply (routine reproduction, benchmark/eval). `K=3`, `quota=0`, `order=canonical`. Measured: ~$0.35/escalation-breach, median winner rank 0, 8/8 escalations breached on the baseline sweep. This stays the global `reproduce_once` default; it is not changed.
- **Growth mode** — goal: grow the repertoire. `K=quota`, `order=starvation`, run deliberately. The growth-mode K default is **promoted 3 → 5** on the evidence above. Encoded in `scripts/growth_sweep.sh`, which locks `quota = K` so the K>quota mis-config (which silently evaluates only `quota` of K selected candidates) cannot recur.

**Stopping rule for K.** After each growth sweep, read cost-per-graduation. While it stays flat or improves, raise K next time; when it rises sharply, the saturation point is found — stop there. Current evidence (8 candidates evaluated, 87.5% yield, cost-per-graduation still falling) justifies K=5 and a future probe toward K=8, but not "max everything." Explicitly not done: jumping to K=10/quota=10, which the data does not yet support.

## Growth Scheduler — closing the self-expansion loop (2026-06-03)

With growth mode proven and made explicit, the last piece is deciding *when* to pay for it without a human in the loop. The Growth Scheduler (`reproduce/growth_scheduler.py`) is a deliberately deterministic rule over inventory already tracked — no bandit, no new telemetry: run growth mode when the candidate pool is large enough to justify the fixed full-rotation cost (`candidate_pool ≥ GROWTH_MIN_POOL`, default 5, with an optional age gate), otherwise stay canonical. It is self-regulating in the right direction: a growth sweep graduates candidates, which drains the pool below the threshold, so the scheduler reverts to cheap canonical sweeps until harvesting refills the pool. `scripts/growth_scheduler.py` decides-and-reports by default (read-only, $0) and dispatches only with `--run`, which is the path to wire into cron for genuine automation. This completes the loop the project set out to build — harvest → (scheduler decides) → growth sweep → graduate → repeat — so that ROGUE does not merely *prove* it can self-expand but actually *does*, as system behaviour rather than a manual decision.

## ATP — cross-tier + vendor-conditioned scheduling (2026-06-05, Phase 3 IMPLEMENTED)

The Phase-2.3 contextual prior shipped as an *offline* warm-prior/analysis layer because the ladder runs one global reorder against a multi-model panel and within-tier reordering structurally can't relocate strategies across tiers. **Benchmark Run #0 sharpened exactly why that matters.** Run #0 (frozen, `reorder=canonical=ON`) on Claude Haiku showed **median winner-rank 17–18, mean ladder-depth ~20, best depth 13** across AdvBench/JBB — nothing breached before depth 13, and the winners (crescendo / actor_attack plus cold harvested techniques) sat at the **ladder floor in the unreordered terminal (planner) tier**. The *same* fixed ladder broke **Mistral-Small at rank 0** (`image:mml:wr` at the front wins). So the optimal order is **target-conditional**, and a within-tier reorder cannot capture it — the Claude-favourable winners live in a tier the within-tier reorders never touch.

The response (opt-in mode `ROGUE_LADDER_ORDER=contextual`, the 5 prior modes unchanged → Run #0 reproducibility preserved):

- **Cross-tier ordering.** All strategies across all five tiers are sorted into one execution order by a blend score, so terminal planner strategies can be promoted to the front (a guarded `cross_tier_order` path in `escalation_ladder.py`, built only when `mode=="contextual"`; early-stop / quota / budget semantics all preserved).
- **Vendor-conditioned scoring.** `VendorFamilyStat.blend_score = 0.5·global_rate + 0.3·vendor_rate + 0.2·family_rate + EXPLORE_WEIGHT/√(global_trials+1)` (additive optimism — the blend is a convex sum of rates, not a product). Vendor/family are parsed from the target's `target_model` (`extract_vendor`/`extract_model_family`); **vendor ≠ routing-provider**.
- **Telemetry (migration 0025).** `ladder_attempts.target_vendor/.target_family/.is_winner` + `benchmark_runs.ladder_order` (the resolved mode is now recorded — Run #0's mode previously had to be reverse-engineered).
- **Cold-start (honest).** History can't be backfilled — non-winner `ladder_attempts` rows never recorded which target model they ran against — so on the *first* contextual run the blend ≈ global rate + exploration. The first-run effect is therefore the **cross-tier promotion** (planner strategies rising on their strong global rate); vendor/family conditioning accrues as freshly-tagged telemetry lands.

KPI is **rank-of-winner** (rank↓ ⇒ cost↓ ⇒ latency↓ at constant ASR). The target-conditional-ordering finding (Mistral rank-0 vs Claude rank-17/18 on the identical fixed ladder) is the empirical case for cross-tier + vendor-conditioned scheduling.

**Measured (2026-06-05 pilot, $24.26).** `fixed` vs `contextual` on the identical 20 AdvBench goals against Claude Haiku, with contextual **cold** (no vendor/family telemetry yet — so this isolates the *cross-tier* effect alone, vendor-conditioning not yet contributing):

| metric | `fixed` (reorder off) | `contextual` (cold) | Δ |
|---|---|---|---|
| median winner-rank | 24.0 | 11 | −54% |
| best rank | 19 | 0 (depth 1) | immediate breach now possible |
| ASR | 30% (6/20) | 45% (9/20) | +50% rel |
| mean depth | 30.0 | 22.5 | −25% |
| cost / success | $2.32 | $1.15 | −50% |

The win is two-axis: lower rank **and** more breaches — under the depth/budget cap the legacy order never *reached* the terminal-tier winners, so poor ordering manifested as missed breaches, not just deeper ones. Caveats for honest reading: `fixed` (24) is reorder-OFF, not the production `canonical` baseline (~18), so the production delta is ≈18→11; the median is over breached subsets of unequal size (6 vs 9), so the clean paired metrics are ASR and cost-per-success; contextual was cold, so the vendor-conditioning increment is still unmeasured (a second-wave gain on reruns). A full 3-mode run (`fixed`/`canonical`/`contextual` × both datasets × 100 goals) is ~$280 and would give the canonical baseline + publication-grade numbers + the cold→warm vendor increment.

**Measured — Option E (2026-06-05, $21.41): contextual vs the PRODUCTION baseline.** The pilot's `fixed` arm is reorder-OFF; Option E pins contextual against `canonical` (the actual production baseline of §6 — within-tier greedy, planner tier last) so the delta is production-relevant rather than vs the legacy no-reorder path. 20 goals balanced across two datasets (10 AdvBench + 10 JBB), Claude Haiku, contextual again **cold** (so still the cross-tier effect in isolation, vendor-conditioning not yet contributing):

| metric | `canonical` (production baseline) | `contextual` (cold) | Δ |
|---|---|---|---|
| median winner-rank — AdvBench | 22 | 13.5 | lower |
| median winner-rank — JBB | 22 | 11 | lower |
| ASR | 50% (10/20) | 60% (12/20) | +20% rel |
| cost / success | $1.25 | $0.74 | −41% |
| total cost | $12.49 | $8.92 | lower |
| best depth (AdvBench / JBB) | 19 / 16 | 1 / 1 | immediate breach now possible |

The direction is **consistent across both datasets independently** — cross-tier promotion helps AdvBench and JBB separately, not as an aggregated artifact. So the result survives the move from the weak `fixed` baseline to the real `canonical` one: against production, contextual still raises ASR and halves-ish cost-per-success while lowering rank on both datasets.

**The causal mechanism — rank↓ CAUSED ASR↑ (scheduling is capability, not just optimization).** This is the centerpiece, and it is not the naive "same winner, found earlier." Each scan runs under a per-scan depth/budget cap. Under the old order (`canonical`/`fixed`), the cap was spent on low-yield front tiers and, for a subset of goals, **exhausted before the winning strategy ran** — so the goal was recorded as *held* (unbreached) when a winner actually existed deeper in the ladder the scan never reached. Contextual ordering promotes that winner ahead of the cap, so the goal breaches. Better ordering therefore **converts previously-unreachable winners into realized breaches** — that is the ASR lift, and it is why ASR, cost-per-success, and rank/depth all move the *same* direction at once (no axis is traded away). It is the identical reachability-under-a-cap mechanism as the candidate-starvation finding above, now operating on *strategy order* rather than *candidate admission*: in both, the binding constraint is "the winner was never evaluated," and the fix is to make it reachable. This is the cleanest single-variable result in the project — only `ROGUE_LADDER_ORDER` changed, everything else (repertoire, judge v3, corpus, target) held fixed — so coverage + cost + latency improving together is attributable to ordering alone.

**Why within-tier structurally cannot do this.** `canonical` reorders within tiers and pins the planner tier last; the Claude-favourable winners (crescendo / actor_attack / cold harvested techniques) live in that terminal tier, so no within-tier reorder can relocate them to the front. Only the cross-tier sort reaches them. The optimal order being target-conditional (Mistral rank-0 vs Claude rank-17/18 on the identical fixed ladder, Run #0) is the empirical case: there is no single static order that is good for both targets, and within-tier reordering cannot express the difference.

**⚑ possibly publishable:** the *capability* framing of scheduling — that ordering a fixed repertoire, with no change to the repertoire/judge/corpus/target, raises attack-success rate by making depth-cap-unreachable winners reachable — reframes red-team efficiency from attack *generation* (the dominant literature axis) to *scheduling*, with rank-of-winner and cost-per-breach as the economic KPIs. Proof-of-concept here (N=20, cold); the powered version (≥2 target families, ~100 goals/dataset, full 3-mode, ~$400–700) is parked in `docs/RESEARCH_TODO.md`. Total scheduling-experiment spend to date $45.67.

## Technique Retrieval Layer — the scaling-economics substrate (added 2026-06-06)

### The economic problem retrieval solves

As the technique corpus grows — from the current ~200 active strategies toward the hundreds-to-thousands range that synthetic technique generation and AST composition imply — evaluating every technique against every deployment config in every reproduction cycle becomes prohibitively expensive. The per-run cost of "evaluate all N techniques" scales linearly with N; at N=1,000 and a per-technique cost of even $0.10, a single sweep costs $100+. The retrieval layer changes that cost model: instead of evaluating all N, retrieve the top-K most promising candidates for each target deployment and evaluate only those. Per-run cost becomes O(K) rather than O(N), and K is set by the Recall@K gate rather than corpus size. This is the precondition for any large-scale technique corpus growth to be economically sustainable — without it, growth compounds cost rather than capability.

### Candidate-generator-vs-ranker design

The retrieval layer implements a classic two-stage architecture. The **candidate generator** is a retrieval index over technique profiles (built by `build_technique_profiles`): given a target deployment config (model vendor, model family, system prompt signature, tool configuration), it returns the top-K techniques by embedding similarity in a time-bounded window. The **ranker** is the existing starvation-aware scheduling layer (`ladder_priors.py`, `escalation_ladder.py`): it takes the retrieved top-K and orders them by the EV blend (effectiveness × viability × freshness × exploration). Retrieval reduces the *input* to scheduling from the full corpus to a manageable top-K; scheduling then allocates evaluation budget within that reduced set. These are complements, not substitutes — retrieval without scheduling still evaluates K things in a bad order; scheduling without retrieval evaluates a badly selected N things.

### Embedding and similarity

Technique profiles are embedded with `deterministic_embed_fn` — a hash-based or TF-IDF-style embedding that costs $0 per call and produces deterministic output for the same profile text. This is intentional: the offline evaluation (see §Recall@K offline evaluation) must be reproducible without API calls, so the embed function cannot be a live model endpoint. A `--live` flag in `scripts/retrieval_eval.py` allows swapping in real embeddings for a production-quality index, but the offline gate uses deterministic mode. Similarity is cosine distance over the embedding space; the `MIN_K=25` floor ensures that even in sparse-history regions, at least 25 candidates are retrieved (avoiding the degenerate case where a very short candidate list lets a single bad embed decision dominate).

### MIN_K safety floor and its rationale

The `MIN_K=25` floor is not arbitrary — it is the starvation-reachability floor from §5 above applied to the retrieval setting. In the causal test (§5.3), 3 candidates admitted to the rotation all graduated; this does not mean "always retrieve exactly 3." It means "if K is too small, selection error (retrieving a wrong technique instead of the right one) is unrecoverable — there is no fallback in the rotation." A K=25 floor provides enough redundancy that if 5–10 retrieved techniques are poor matches, the remaining 15–20 still contain the true winning technique. The Recall@50 ≥ 80% KPI is the empirical counterpart: at K=50, at least 80% of historical winners must be retrieved, meaning the floor is adequate at K=25 and the safety margin is verified by the offline eval. If Recall@25 already exceeds 80%, the floor can be lowered; if Recall@50 fails, the embedding or profile construction is the bottleneck to fix.

### Recall@K offline evaluation methodology

The offline eval is a replay over `ladder_attempts.is_winner` rows (the ground-truth winner labels from real reproduction runs). For each historical winner event: (1) identify the winner technique (entity_id) and its target (config_id, target_vendor, target_model_family); (2) build the full technique profile universe (`build_technique_profiles` over all active + candidate techniques); (3) embed both the winner technique and all profiles deterministically; (4) retrieve top-{10,25,50,100} by cosine similarity; (5) check whether the winner appears in each top-K set. The denominator for each @K is the total number of winner events, minus a reported "uncovered winners" count for cases where the winner technique has no profile (no profile = can never be retrieved; counting these as retrieval failures would be dishonest since the retrieval system cannot be blamed for an absent profile). Uncovered winners are reported separately as a metric of profile completeness, not folded into the recall denominator. Per-target (per vendor, per model family) breakdown is mandatory: if retrieval fails systematically for Claude or for a particular attack family, a global Recall@50 that meets the gate can still mask a per-deployment failure mode. The eval runs for $0 in deterministic mode (`--deterministic` flag), is fully reproducible from the stored `ladder_attempts` rows, and produces a report that gates Weeks 6-7 activation without any paid model calls.

### Shadow-mode validation: production recall vs offline recall

Once the retrieval layer is activated in production, a shadow metric tracks whether the offline Recall@K prediction holds in the live system. `retrieval_metrics` (a planned table, see activation roadmap) logs, for each reproduction run, the set of retrieved top-K techniques and whether the eventual winner was in that set. This is the production analog of the offline replay: if offline Recall@50 = 85% but live production recall drops to 60%, the gap diagnoses distribution shift (the production target distribution has drifted from the historical telemetry the offline eval was built on). Shadow-mode runs the retrieval layer in parallel with the current full-corpus scheduling (no change to production behavior) and compares winner-in-top-K rates before any production switch-over.

### Activation roadmap

The retrieval layer activates in three stages gated by measurement, not calendar. **Stage 1 (offline gate, $0):** run `scripts/retrieval_eval.py --deterministic`, check Recall@50 ≥ 80% and per-target breakdown, diagnose any per-vendor/family failures. This is the only hard gate. **Stage 2 (shadow mode, ~$0 incremental):** activate retrieval in shadow mode alongside the existing full-corpus schedule for 2–3 reproduction cycles; compare production recall vs offline recall; check for distribution shift. **Stage 3 (production switch, replaces full-corpus scheduling):** if shadow-mode production recall matches the offline prediction (within 5 points), switch to retrieval-based scheduling. The K parameter for production is set by the Recall@K curve result: use the smallest K where Recall ≥ 80%, with the MIN_K=25 floor as a hard lower bound. This three-stage activation is the mechanism that makes large-scale technique corpus growth economically viable — it is the engineering gate that turns growth into a controllable cost rather than an unbounded one.

### What retrieval does NOT resolve: the authoring-efficacy gate

The retrieval layer scales the *input size* to breach evaluation — it changes "evaluate all techniques" to "evaluate top-K." It does not improve the signal-to-noise of breach evaluation itself, and it does not answer whether structured composition (grammar templates, AST-based technique authoring) predicts breach rate better than freeform model authoring. The §10.9 slot-fill A/B (`docs/scheduler_allocation_study.md §7`) is underpowered and inconclusive on that question; the observed 0.25 (templates) vs 0.44 (freeform) gap is unattributed. Retrieval hands you more candidates at lower cost — but if breach evaluation cannot distinguish them, more candidates do not produce better outcomes. The powered authoring-efficacy experiment (see `docs/RESEARCH_TODO.md #TRS-A`) is the upstream prerequisite before investing in composition-based technique growth, and retrieval does not substitute for it.

## Grammar-Component Predictive-Power Study (#TRS-C) — the empirical gate before grammar/AST investment

### The question

The Technique-AST and synthetic-generation roadmap rests on an assumption that has not been directly tested: does grammar structure — the `GrammarNode` decomposition of a technique into typed structural components — predict breach outcomes beyond what attack-family membership already predicts? If nodes and node combinations carry marginal predictive signal that survives family stratification, then investing in grammar elaboration, AST composition pipelines, and synthetic technique generation is well-founded. If they do not — if any apparent node lift dissolves once family is controlled and FDR is applied — the AST roadmap is academic and engineering effort is better directed elsewhere. This study answers the question for $0, with no generation and no new paid runs, by correlational analysis over the existing primitives × breach-results corpus.

### Why per-(primitive × target) not per-primitive

The natural analysis unit is the per-(primitive × target) outcome (~1,540 cells), not the per-primitive "did any target breach" indicator. The per-primitive outcome saturates near base rate ~0.79 — most primitives breach *something* — which collapses the variance that grammar should predict. The per-(primitive × target) unit preserves variance across the model dimension and creates the degrees of freedom needed to detect node-level signal.

### Lift methodology

For each `GrammarNode` label in the corpus: compute P(breach | node present) vs baseline P(breach), with odds ratio + Wilson/Wald confidence interval and Fisher exact test for significance. For pairwise interactions: compare observed P(breach | A ∧ B) against the stated no-interaction baseline P(breach|A) × P(breach|B) / P(breach), giving a synergy score (positive = co-occurrence lifts beyond independent contributions, negative = interference). Only cells with n ≥ min_count contribute to the interaction analysis to keep estimates stable.

### Confound controls

Four controls are applied in sequence, each targeting a named confound: (1) **Family collinearity via Cramér's V** — a node that is structurally equivalent to a family label shows lift that is family lift, not grammar lift; V > threshold flags the node as circular and greyed in the forest plot. (2) **Mantel–Haenszel stratification by target model** — some models breach far more than others (Claude Opus ~1.4% vs Mistral Small ~48.6%); a node that co-occurs with easy targets looks predictive even if structurally uninformative; MH stratification estimates node effect within each target-model stratum and combines them, killing the target-mix confound. (3) **Within-family lift** — the node must show lift within a family, not just across families; between-family lift is family lift wearing a grammar costume. (4) **Benjamini–Hochberg FDR** — with potentially hundreds of node × pairwise-combo tests, multiple-comparisons inflation is material; BH FDR at q = 0.05 is the final gate before a finding is labelled "signal."

### Verdict criteria and relationship to the AST roadmap

SIGNAL: ≥1 node has an FDR-significant lift that survives family stratification and is not flagged as circular. This identifies which nodes/combos carry real predictive power and points the powered causal experiment (#TRS-A, paired McNemar, N≥60/arm) at specific hypotheses rather than the grammar space in general. NULL: no node clears that bar after controls. This is a valid, positive-information result — it means grammar structure carries little marginal signal once family is controlled, the ~0.79 per-primitive ceiling is mostly a family/target effect, and further investment in AST elaboration should be deprioritized in favor of upstream levers (harvesting, target coverage, evaluation budget). Both directions are publishable (see ⚑ below); the null is cheaper to produce and is the falsification the roadmap needs before scale investment.

### Confound disclosures (cannot fully remove, must report alongside any finding)

Selection bias: which primitives exist reflects harvest history, not a random sample of the grammar space — nodes that appear only in underrepresented families will have inflated apparent lifts from sparse coverage, not grammar structure. Target-mix: MH stratification addresses but does not fully eliminate per-model variance. Family collinearity: Cramér's V flags but cannot algebraically separate a node that is nearly synonymous with a family. Judge version: the stored breach matrix has now been re-judged under v3 (2026-06-07; breach cells 2,429→1,371, −43.6%), so `breach_results` is v3-graded going forward; any node lifts quoted in this note were captured pre-re-judge (v1/v2, over-eager) and should be re-checked under v3. The 0.79 per-primitive ceiling: motivates the per-(primitive×target) unit, but even at that level, model-difficulty variance is large enough that MH stratification is mandatory, not optional.

### Run command and artifacts

`python scripts/grammar_study.py` emits per-node lift table (odds ratios + CIs + FDR q-values), the pairwise synergy matrix, the collinearity flags, and the MH stratified estimates. Figure specs: see `docs/paper_figures.md` (F-nodeLift, F-combo, F-strat). Design entry: `docs/RESEARCH_TODO.md #TRS-C`.

## Figures to draw (TODO)

- The orchestration pipeline (harvest → lifecycle → ladder → judge → brief).
- The lifecycle state machine (candidate/active/retired/archived + resurrection).
- The increment ladder for allocation (fixed → greedy → viability → Thompson).
- A starvation plot (winner-tier distribution under fixed vs reordered ladder) — needs paid runs.

## Open data needs

- Paid before/after runs for rank-of-winner + call-count deltas.
- ~~Rotation-membership logging to measure reachability.~~ **Done (2026-06-03, migration 0019 +
  `ladder_rotation_membership`)** — `reachability` + `starvation_rate` are now queryable
  (`ladder_priors.strategy_reachability`); needs a paid sweep to *populate* the table.
- Repeated A/B runs (or a paired design) to resolve sub-noise effects.
- Honest cost accounting (the Mistral $0 price-log gap).
