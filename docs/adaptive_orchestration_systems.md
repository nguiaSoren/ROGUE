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
- **Allocation quality is the real frontier.** Hence the scheduler reframe from "what
  breaches most?" to "what is worth evaluation budget right now?" (EV = effectiveness ×
  viability × freshness × exploration). Then **reachability** ("what could have run but
  didn't") — logged as of migration 0019 — turns "outcomes" telemetry into "opportunities"
  telemetry, the precondition for honest allocation analysis.
- **Per-model technique-effectiveness map (contextual signal).** From 9,192 `breach_results`
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
