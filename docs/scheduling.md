# Scheduling — Contextual Scheduler / Adaptive Technique Prioritization (ATP)

Engineering spec for ROGUE's §10.10 technique-prioritization layer: the thing that
decides, per reproduce sweep, **which escalation strategies to try and in what order**,
and **when to pay for repertoire growth**. Authoritative code:

- `src/rogue/reproduce/ladder_priors.py` — the ranker (statistics + ordering functions).
- `src/rogue/reproduce/escalation_ladder.py` — the candidate generator + ladder executor
  (`build_escalation_context`, `run_escalation_ladder_one`).
- `src/rogue/reproduce/growth_scheduler.py` — the growth-vs-canonical self-regulator.

Intended design: `ROGUE_PLAN.md §10.10`. Where code and plan disagree, the code is
authoritative for current behavior.

## Position in the system

```
EVADE-band parent primitive
        │
        ▼
build_escalation_context(session, configs, …)   ← reads telemetry, ranks strategies
        │   produces EscalationContext (reordered tiers ± cross_tier_order)
        ▼
run_escalation_ladder_one(parent, …, cross_tier_order=…)   ← executes in ranked order
        │
        ▼
LadderResult (winning_strategy, attempts, child_orm)
```

The scheduler is **pure setup** — `build_escalation_context` makes no paid target/judge
calls. It reads aggregate telemetry, computes an order, and hands the ladder a reordered
candidate list. All spend happens later, inside `run_escalation_ladder_one`.

## Candidate generator vs ranker (the load-bearing separation)

These are two distinct responsibilities, deliberately kept apart:

- **Candidate generator** (`escalation_ladder.py`): owns *what the set of strategies is*.
  The five tiers (image renderers, CoJ operations, structured formats, audio styles,
  planner strategies) plus any ACTIVE harvested renderers merged in via
  `renderer_registry.active_dynamic_strategies`. This set is the same regardless of mode.
- **Ranker** (`ladder_priors.py`): owns *the order* of that set. It never adds or removes
  a strategy — it only sorts. Every ordering function takes the elements and returns a
  permutation of them.

This separation is what makes the reproducibility invariant below enforceable: the ranker
physically cannot change which strategies exist, only their priority.

## `ROGUE_LADDER_ORDER` modes

`ladder_order_mode()` resolves `ROGUE_LADDER_ORDER` (default **`contextual`**). Valid modes
(`_VALID_MODES`): `canonical`, `discovery`, `viability`, `starvation`, `contextual`, `fixed`.
An unrecognized value falls back to `contextual`.

| Mode | Ranker fn | Score | Telemetry read | Notes |
|---|---|---|---|---|
| `fixed` | `order_by_prior` (identity) | — | none | Legacy hand-coded order. Ablation / cold-start escape hatch. |
| `canonical` | `order_by_prior` | `BreachStat.smoothed_rate` | `ladder_attempts` | Deterministic greedy "sort by historical breach rate". The exploit order. §10.10 Step 1. |
| `discovery` | `order_by_prior` | `smoothed_rate + C/√(trials+1)` | `ladder_attempts` | Optimism bonus front-loads under-tried strategies. The explore order. `ROGUE_LADDER_DISCOVERY_C` (default 0.5). |
| `viability` | `order_by_value` | `StrategyValue.value_score` = effectiveness × validity × freshness × exploration | `ladder_attempts` (incl. `attempts_total`, `last_tried_at`) | §10.10 Phase 2. Demotes proven-unviable strategies (high breach, low validity). |
| `starvation` | `order_by_starvation` | `value_score × (1 + W·starvation_rate)` | `ladder_attempts` + `ladder_rotation_membership` | §10.10 Phase 2.2. Boosts starved high-value strategies; `ROGUE_LADDER_STARVATION_WEIGHT` (default 1.0). |
| `contextual` | `order_by_blend` | `VendorFamilyStat.blend_score` (see below) | `ladder_attempts` (vendor/family-tagged) | **Default.** The only mode that reorders ACROSS tiers (see cross-tier path). §10.10 ATP. |

**Within-tier vs cross-tier.** Every non-contextual mode reorders *within each tier*
independently (`image:` elements among themselves, etc.) and keeps the fixed
tier1→tier5 visiting sequence. `contextual` additionally collapses all five tiers into a
single full-label list and sorts the whole thing, so a high-prior planner strategy can be
tried before a weak tier-1 renderer. That collapsed order is the `cross_tier_order` field
on `EscalationContext`; it is `None` for every other mode.

## Contextual blend weights

`contextual` scores each strategy as a convex blend of three Laplace-smoothed breach rates
at widening context scope, plus an additive exploration term:

```
blend_score = W_GLOBAL·global_rate
            + W_VENDOR·vendor_rate
            + W_FAMILY·family_rate
            + EXPLORE_WEIGHT / √(global_trials + 1)
```

- `global_rate` — pooled over every target (densest, most reliable signal).
- `vendor_rate` — only attempts against the requested `target_vendor`.
- `family_rate` — only attempts against the requested `target_family`.

Weights (env, with defaults):

| Env var | Default |
|---|---|
| `ROGUE_LADDER_BLEND_W_GLOBAL` | 0.5 |
| `ROGUE_LADDER_BLEND_W_VENDOR` | 0.3 |
| `ROGUE_LADDER_BLEND_W_FAMILY` | 0.2 |

**Invariant: the three weights MUST sum to 1.0.** This is asserted at import time in
`ladder_priors.py` (`abs(sum - 1.0) < 1e-9`); a misconfigured env that breaks the sum
fails the import loudly. Summing to 1.0 keeps the rate part on the probability scale so the
additive exploration term composes correctly, and makes re-tuning one weight visibly trade
off the others.

The exploration term reuses `ROGUE_LADDER_EXPLORE_WEIGHT` (default 0.5). It is **additive**
here (the blend is a convex sum of rates), unlike `StrategyValue.exploration_bonus` which is
a ≥1 *multiplicative* factor (that score is a product). The GLOBAL trial count drives the
decay — vendor/family counts are too sparse to gate exploration reliably.

**Cold-start.** Before vendor/family-tagged telemetry accumulates, both specialised rates
Laplace-smooth to 0.5 and the blend degenerates to `global + exploration`. Expected on the
first contextual run; self-corrects as tagged rows land. A strategy absent from telemetry
gets a fresh zero-stat → all rates 0.5, full exploration bonus, so newly-introduced
strategies keep a fair cold prior and are not buried behind proven-weak incumbents.

The vendor/family for the blend come from the single config under test
(`extract_vendor`/`extract_model_family` in `adapters.model_specs`); a mixed multi-config
panel is ambiguous → `"unknown"`, which forces the vendor/family fall-back to 0.5.

## Smoothing prior (all modes)

Every rate uses a Beta(ALPHA=1, BETA=1) add-1 (Laplace) prior, so an **unseen strategy
scores 0.5** — above most proven-weak incumbents. This is the cold-start survivability
guarantee: without it, raw breach rate would let the historically-dominant image-renderer
tier monopolize the front of the ladder forever (rich-get-richer) and drive every unseen
strategy's rate to 0 → never tried → dead on arrival. Two further exploration floors back
it up: the candidate-attempt quota (reserves exploration regardless of order) and
`discovery`'s optimism bonus.

## Telemetry tables read

- **`ladder_attempts`** — one row per (strategy, ladder) attempt with `outcome` ∈
  {breach, no_breach, refused, render_error}, `breached` bool, `entity_id` (the FULL label,
  e.g. `image:mml:wr` / `coj:reorder` / a planner strategy id), `config_id` (winner rows
  store the winning **target_model** — a legacy column-name misnomer), `target_vendor`,
  `target_family`, `created_at`, `run_id`. The substrate for `strategy_breach_rates`,
  `strategy_values`, `vendor_family_strategy_rates`, `winning_model_distribution`.
  - **Validity split (migration 0018):** "valid trials" = `outcome ∈ {breach, no_breach}`
    only. Orchestration failures (refused / render_error) are excluded from the breach-rate
    denominator so the prior measures attack efficacy, not orchestration health; they
    *are* counted in `attempts_total` so the validity rate can see them.
- **`ladder_rotation_membership`** — per-(strategy, ladder) eligibility/execution record
  with `eligible`, `executed`, `skipped_reason` ∈ {early_stop, budget, …}. Drives
  `strategy_reachability` → `ReachStat.reachability` and `starvation_rate` (fraction of
  eligible appearances lost specifically to early-stop — the reorder-loser signal). Only
  `eligible` rows count toward the denominator.
- **`breach_results`** (via `breach_matrix`) — the full per-(target_model × attack_family)
  matrix feeds `contextual_breach_rates` → `ContextStat`, the unbiased "who would succeed
  if reached" prior (the ladder short-circuits, so it can't give per-model rates itself).

Keying: reward rows store the FULL label in `ladder_attempts.entity_id`. Tier lists hold
bare elements (`mml:wr`), so within-tier reorder passes the tier's `label_prefix`
(`"image:"`) and reconstructs the label for lookup. `order_by_blend` operates on full
labels directly.

## Reproducibility invariant — "reorder, never exclude"

The scheduler changes only the **evaluation priority**, never the candidate set or the
execution semantics. Concretely:

1. Every ranker returns a permutation of its input (`_stable_order` sorts by score
   descending with the original index as a stable tiebreak). Equal scores — and a cold
   all-unseen run — preserve the hand-coded order exactly, so `fixed` mode and a cold start
   reproduce the legacy Run #0 byte-for-byte.
2. `cross_tier_order` is `None` for every non-contextual mode and every legacy caller, so
   the ladder runs its fixed tier1→tier5 sequence unchanged. When non-None, the ladder
   executes the *same per-candidate units* (image/coj/structured/audio/planner) in the
   blended order — early-stop, candidate quota, budget, and render-error semantics are
   identical to the tier path; only the visiting order differs.
3. The ranker cannot drop a strategy. A reorder that buried a winner still records every
   attempt; nothing is silently excluded from evaluability.

This is what lets the breach matrix stay comparable across modes: the same strategies are
reachable under every mode, so an order change is measured as a *time-to-breach* / cost
effect, not a coverage change.

## Growth-scheduler self-regulation

`growth_scheduler.py` answers a separate question from the ranker: **when is it worth paying
for repertoire growth at all?** A growth-mode sweep (quota K, starvation ordering) converts
starved candidates into graduated capabilities at ~$7/graduation but costs ~10× a canonical
sweep, so it must run deliberately.

The policy is a deterministic rule over inventory already tracked in `attack_strategies`
(no bandit, no new telemetry):

```
growth    ⟺  candidate_pool ≥ MIN_POOL  (and avg candidate age ≥ MIN_AGE_DAYS)
canonical ⟺  otherwise
```

`decide_sweep_mode(session, now=…)` → `GrowthDecision(mode, reason, candidate_pool,
avg_age_days, K, quota, order)`. The decision bundles the full parameter set the mode
implies so callers can't re-derive (and drift) them:

- **growth**: `K = GROWTH_K`, `quota = K` (evaluate every selected slot), `order =
  "starvation"`.
- **canonical**: `K = 3`, `quota = 0`, `order = "canonical"`.

`candidate_pool_stats` reads `attack_strategies` filtered to `status == CANDIDATE`
(count + average age from `created_at`).

**Self-regulation:** a growth sweep graduates candidates, draining the pool below
`MIN_POOL`, so the scheduler reverts to canonical until harvesting refills the pool. K is
held at the evidence-backed default (5), not scaled — the saturation point is not yet mapped.

| Env var | Default | Meaning |
|---|---|---|
| `GROWTH_MIN_POOL` | 5 | Minimum candidate inventory to justify a growth sweep. |
| `GROWTH_MIN_AGE_DAYS` | 0 | Age gate (off by default → pool-only rule; set 7 to let candidates age first). |
| `GROWTH_K` | 5 | Growth-mode quota/K. |

## Config-flag summary

| Flag | Default | Layer |
|---|---|---|
| `ROGUE_LADDER_ORDER` | `contextual` | mode selector |
| `ROGUE_LADDER_DISCOVERY_C` | 0.5 | discovery optimism weight |
| `ROGUE_LADDER_FRESHNESS_TAU_DAYS` | 14 | viability freshness horizon |
| `ROGUE_LADDER_FRESHNESS_WEIGHT` | 0.5 | viability freshness weight |
| `ROGUE_LADDER_EXPLORE_WEIGHT` | 0.5 | viability + contextual exploration weight |
| `ROGUE_LADDER_STARVATION_WEIGHT` | 1.0 | starvation boost cap |
| `ROGUE_LADDER_BLEND_W_GLOBAL` | 0.5 | contextual blend (must sum to 1.0) |
| `ROGUE_LADDER_BLEND_W_VENDOR` | 0.3 | contextual blend |
| `ROGUE_LADDER_BLEND_W_FAMILY` | 0.2 | contextual blend |
| `GROWTH_MIN_POOL` / `GROWTH_MIN_AGE_DAYS` / `GROWTH_K` | 5 / 0 / 5 | growth scheduler |

Related: `docs/escalation_ladder.md` (the executor the scheduler feeds), `docs/db_schema.md`
(`ladder_attempts`, `ladder_rotation_membership`, `attack_strategies`).
