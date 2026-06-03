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
  viability × freshness × exploration). Open: **reachability** (available-but-skipped) is
  not yet measurable without logging rotation-membership.

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
