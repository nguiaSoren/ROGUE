# Escalation Ladder

Engineering spec for ROGUE's escalation ladder — the layer that takes a single-turn
primitive the panel mostly resisted (EVADE-band) and tries a sequence of transforms until
one breaches. Authoritative code:

- `src/rogue/reproduce/escalation_ladder.py` — the ladder + synthesis core
  (`run_escalation_ladder_one`, `run_escalation_ladder`, `build_escalation_context`,
  `run_synthesis`).
- `src/rogue/reproduce/escalation_planner.py` — `EscalationPlanner` (Tier 5's plan author).
- `scripts/synthesize_escalations.py` — back-compat shim (see end).

Intended design: `ROGUE_PLAN.md §10.7` (synthesis) + `§10.8` (ARMS ladder) + `§10.10`
(adaptive ordering). Spec for the ordering that feeds the ladder: `docs/scheduling.md`.

## Position in the system

```
EVADE-band parent  ──►  run_escalation_ladder_one(parent, …)
                              │   tries transforms in order, STOPS on first breach
                              ▼
                        LadderResult(winning_strategy, breached_on, attempts, child_orm)
                              │   escalation/CoJ winners carry a synthesized child to persist
                              ▼
                        new AttackPrimitive row (synthesized=True) — re-fired by reproduce_once
```

"EVADE-band" = `max(any_breach_rate)` across configs `< threshold` (default 0.4), sourced
from the `breach_matrix` view (`_load_evade_band_primitives`). Already-multi-turn and
already-synthesized primitives are excluded (don't escalate an escalation).

## The five tiers (fixed order)

`run_escalation_ladder_one` visits transforms in this order and **short-circuits on the
first breach**:

| Tier | Input | What it does | Planner? | Persists child? | Winning label |
|---|---|---|---|---|---|
| 1 | `image_renderers` | Render the refused payload AS AN IMAGE via each renderer; dispatch to vision configs only. | no | no (slot variant) | `image:<renderer>` |
| 2 | `coj_operations` | Chain-of-Jailbreak (#8): decompose the payload into a deterministic edit-step multi-turn chain. | no | yes (CoJ child) | `coj:<op>` |
| 3 | `structured_formats` | Structured-data injection (#12, text): re-cast the payload as a JSON/CSV/YAML/XML document whose directive field carries the instruction. | no | no (slot variant) | `structured:<fmt>` |
| 4 | `audio_styles` | Speak the payload with each acoustic style (#6: plain/fast/noisy); dispatch to AUDIO-capable configs only. Auto-skips when no config accepts audio. | no | no (slot variant) | `audio:<style>` |
| 5 | `strategies` | Multi-turn escalation (crescendo → actor_attack → acronym via `EscalationPlanner.plan`); build child, reproduce + judge. Optionally renders the final turn as an image (`image_strategy`). | **yes** | yes (escalation child) | `<strategy>` |

`_strategy_breaches` reproduces + judges a variant across configs and returns the first
breaching `target_model` (or None) plus estimated spend. Breach = verdict ∈
{PARTIAL_BREACH, FULL_BREACH}. Default tier contents: `DEFAULT_IMAGE_RENDERERS`
(typographic, ocr:white_on_white, mml:wr, mml:base64, vpi:lowcontrast), `COJ_OPERATIONS`,
`STRUCTURED_FORMATS` (json/csv/yaml/xml), `DEFAULT_AUDIO_STYLES` (plain/fast/noisy),
`ESCALATION_LADDER` (crescendo, actor_attack, acronym). ACTIVE harvested renderers are
merged into the image/audio tiers by `build_escalation_context`.

## Load-bearing invariants

### Planner-free tiers 1–4 (works when the planner refuses)
Tiers 1–4 are entirely deterministic and never call the planner. Only Tier 5 needs an LLM
to author a plan. This ordering is deliberate: the cheap, deterministic transforms run
first, so the ladder still produces breaches even if the planner refuses to author
escalations or the planner backbone is down. The expensive, refusable tier is last.

### Short-circuit on first breach ("leave the others")
The first breach in any tier wins; the remaining tiers/strategies are skipped. The winner
is recorded as `LadderResult.winning_strategy`; `attempts` captures every transform tried
(with its outcome) in order, so even skipped-past evidence is logged.

The **candidate-attempt quota** (`candidate_attempt_quota` > 0, §10.9) modifies this: the
early-stop is *suppressed* until N harvested `candidate_ids` have been attempted (or the
budget is hit), so candidate evaluation is not starved by tier-1 winners. The FIRST breach
is still credited as `winning_strategy` (stable breach-matrix semantics) even when a later
candidate completes the quota; a candidate that breaches still graduates via its `attempts`
entry. Quota is a scheduler/allocation knob, not a candidate policy — it does not disable
renderers. See `docs/scheduling.md` for how the growth scheduler sets it.

### Permissive-backbone fallback (planner authors what Claude refuses)
`EscalationPlanner`'s default backbone is **permissive** (`mistralai/mistral-small-2603`),
not the aligned Claude Haiku that originally refused to author jailbreak escalations
(capping candidate validity at ~22%, mostly planner-refused). Switching only the planner to
a permissive model took candidate validity 22% → 100% and graduated a technique (VERA) the
aligned planner made unreachable. Override via `ROGUE_ESCALATION_PLANNER` or
`--planner-model`. A secondary auto-fallback (`meta-llama/llama-3.1-8b-instruct`) retries
authoring on refusal (largely vestigial now the primary is permissive). A planner refusal
is recorded as a `("<strategy>", "refused")` attempt, not a fatal error — the ladder moves on.

### Safe-judge / permissive-planner / safe-target separation
Three independent model roles, deliberately not collapsed:
- **Safe target** — the customer's actual deployment model under test (the panel).
- **Permissive planner** — authors the attacks the defensive red-team must test against
  (`EscalationPlanner`, Mistral by default).
- **Safe judge** — grades independently of the attacker (Claude Sonnet by default; see
  `docs/judge.md`). Using the same model to attack and grade would collapse the experiment.

This is why the planner being permissive does not weaken the result: the judge is still the
aligned, calibrated grader, and the target is still the real deployment.

### Contextual cross-tier path (§10.10, optional)
When `cross_tier_order` is supplied (only in `contextual` mode), the ladder runs a single
CROSS-TIER list of full labels (`image:mml:wr` / `coj:reorder` / `structured:json` /
`audio:fast` / a planner strategy) in blended-prior order, so a high-prior planner strategy
can run before a weak renderer. It executes the *same per-candidate units* — early-stop,
quota, budget, and render-error semantics mirror the tier path exactly; only the visiting
order differs. `cross_tier_order=None` (the default, and every non-contextual caller) runs
the fixed tier1→tier5 sequence byte-for-byte unchanged (the Run #0 reproducibility
guarantee). See `docs/scheduling.md`.

### Budget cap
`budget_usd`, if set, stops the ladder between tiers once estimated spend reaches it
(records a `("budget", "stopped")` attempt). `spend_usd` on the result is the estimated
total across every attempt (panel `cost_usd` + a flat judge estimate per judge call).

## Outputs

`LadderResult` carries `parent_id`, `winning_strategy` (None if exhausted), `breached_on`
(the target_model that broke), `attempts` (ordered `(label, outcome)` list), `child_orm`
(the winning synthesized child to persist — only CoJ + escalation winners produce one;
image/structured/audio winners are slot variants of the parent and carry no new row), and
`spend_usd`.

`run_escalation_ladder` sweeps EVADE-band parents, persists winning children in their own
short transactions (the read transaction is released before the slow per-parent LLM loop to
avoid Neon's idle-in-transaction timeout), and returns `LadderStats`. Synthesized children
are written with `family = MULTI_TURN_GRADIENT`, `vector = USER_MULTI_TURN`,
`synthesized = True`, `requires_multi_turn = True`, `derived_from_primitive_id = <parent>`,
the parent's family in `secondary_families`, and `base_severity = HIGH`.

### Telemetry side-channels
- **Technique retrieval shadow mode** (E8): when `ROGUE_RETRIEVAL_SHADOW=1`, after each
  parent's ladder returns, `_record_retrieval_shadow` writes one `retrieval_metrics` row
  measuring where the winning label *would have* ranked in retrieval. Pure side-channel —
  never alters which techniques run or their order; wrapped in try/except so it can never
  break a run. Off by default.
- **Retrieval activation seam** (E8, stub): in `build_escalation_context`, a documented
  TODO marks where retrieval would NARROW `full_labels` before contextual ranking when
  `ROGUE_RETRIEVAL_TOPK>0`. Disabled this session; `full_labels` is left intact.

## `run_synthesis` (plan-only, distinct from the ladder)
`run_synthesis` is the cheaper §10.7 path: it only authors plans (one LLM call per parent,
concurrent) and persists a synthesized child per parent — it does NOT reproduce or judge.
Use it to bulk-seed multi-turn primitives; the standard reproduction layer fires them later.
The `--ladder` CLI flag selects `run_escalation_ladder` (COSTLY: reproduces + judges live)
instead.

## `scripts/synthesize_escalations.py` — back-compat shim
The ladder + synthesis core used to live in `scripts/synthesize_escalations.py`. It moved
into the package at `rogue.reproduce.escalation_ladder` so the deployed platform worker can
import it (`scripts/` isn't on the worker's `PYTHONPATH`, and `src/rogue` importing
`scripts` was a backwards layering dependency). The script is now a thin shim that
re-exports the moved public + used-private API (`run_escalation_ladder`,
`run_escalation_ladder_one`, `build_escalation_context`, `run_synthesis`, `EscalationContext`,
`LadderResult`, `LadderStats`, `SynthesisStats`, `main`, the `DEFAULT_*`/`ESCALATION_LADDER`
constants, `_orm_to_pydantic_primitive`). Existing callers
(`from scripts.synthesize_escalations import …` in benchmark_run / reproduce_once / tests)
and `python scripts/synthesize_escalations.py` keep working unchanged.
