# Grammar Component Predictive-Power Study

Design and methodology document for the observational study that gates the Technique-AST / synthetic-generation roadmap. All analysis code lives under `src/rogue/grammar/`; the schema lives in `src/rogue/schemas/grammar_node.py`; the storage side-table is `primitive_grammar_labels` (migration `0027`). Nothing in this study generates new attacks, calls any external API, or modifies the frozen `AttackFamily` taxonomy.

---

## Motivation — why this must precede any AST build

The long-horizon vision for ROGUE's attack repertoire is a **Technique-AST**: a compositional system that assembles new attacks by combining structural grammar components the way a compiler combines AST nodes. The premise is that certain reusable structural components — an authority frame here, an encoding obfuscation there, a multi-turn escalation arc on top — combine synergistically to produce attacks that are more effective than either component alone, and that a generator exploiting this structure will outperform one that samples payloads uniformly.

This premise is plausible but **empirically unverified**. Building a Technique-AST compositor requires months of grammar design, embedding infrastructure, beam-search or MCTS generation logic, judge-in-the-loop evaluation, and human review pipelines. If grammar nodes do not independently predict breach — specifically, if knowing that a primitive carries `AUTHORITY_FRAME` + `TRIGGER_BACKDOOR` does not move the breach probability beyond what `AttackFamily` already captures — then the compositional premise is unfounded and the build should not happen. ROGUE has already learned this lesson several times: the right move before building anything is to measure first.

This study is the measurement. It costs $0 (observational over the existing corpus), takes no API calls, and produces either a go or a no-go signal before any AST engineering begins.

---

## Study design summary

The study is **observational**: it reads the existing `attack_primitives` corpus (298 harvested-canonical primitives) and the existing `breach_matrix` (breach outcomes from ~1540 per-(primitive × target) trials across 6 deployment configs) and asks: do structural grammar labels assigned to each primitive statistically predict breach outcomes?

**What it is NOT:**
- Not a generation study — no new attacks are synthesized.
- Not a paid experiment — $0, pure SELECT queries.
- Not a taxonomy revision — `AttackFamily` is frozen (§13); `GrammarNode` is a separate structural layer below it.
- Not Streamlit — the labeler runs server-free from Python, driven by heuristics on structured fields.

---

## Node taxonomy — the `GrammarNode` enum

`GrammarNode` is a 23-member enum defined in `src/rogue/schemas/grammar_node.py`. Values are lowercase snake_case to match the ROGUE enum convention and to work directly as Postgres enum values.

The 23 nodes split into two categories by design. This split is not cosmetic — it determines which nodes can provide non-circular signal.

### Family-mirroring nodes (11)

These correspond 1:1 to `AttackFamily` values. They exist so that a family-baseline model can be expressed as `GrammarLabel` instances without special-casing — useful as a controlled floor in the analysis. Any lift measured on a family-mirroring node is near-circular (it mostly reflects the family's base breach rate), so it cannot justify AST composition on its own.

`role_hijack` · `dan_persona` · `policy_roleplay` · `refusal_suppression` · `direct_override` · `system_prompt_leak` · `training_data_extraction` · `indirect_injection` · `tool_invocation` · `chain_of_thought_hijack` · `multimodal`

### Cross-family structural nodes (12)

These are derived from `payload_slots` keys and the `requires_multi_turn` flag — not from `family`. They capture *how* an attack is constructed, independently of *what* it attempts. Because they fire across multiple `AttackFamily` values, their lift can be genuinely non-circular — the cross-family firing is exactly the signal that would justify using a node as a composition primitive.

| Node | Derivation | Corpus n (approx.) |
|---|---|---|
| `authority_frame` | `payload_slots` has `authority_claim` (n=60) or `justification` (n=51) non-empty | ~111 |
| `language_shift` | `payload_slots` has `language` non-empty; or `language_switching` family | ~3 |
| `encoding_obfuscation` | `payload_slots` has `encoding_scheme` (n=34) non-empty; or `obfuscation_encoding` family | ~34 |
| `structured_output` | `payload_slots` has `target_output_format` (n=53) or `NewResponseFormat` (n=4) non-empty | ~57 |
| `fictional_framing` | `payload_slots` has role-description referencing narrative; and `{policy_roleplay, dan_persona, role_hijack}` family | — |
| `multi_turn_escalation` | `requires_multi_turn == True` (n=42); or `{multi_turn_gradient, multi_turn_persona_chain}` family | ~42 |
| `trigger_backdoor` | `payload_slots` has `trigger_phrase` (n=59) non-empty | ~59 |
| `exfiltration` | `payload_slots` has `exfil_destination` (n=45) non-empty | ~45 |
| `persona_construction` | `payload_slots` has `role_name` (n=57) and (`role_description` (n=46) or `personality_trait` (n=4)) non-empty | ~57+46 |
| `target_behavior_specification` | `payload_slots` has `target_behavior` (n=206) and/or `target_topic` (n=73) non-empty | ~206 |
| `invisible_injection` | `payload_slots` has `invisible_tag_instruction` (n=4) non-empty; or zero-width Unicode codepoints in payload | ~4 |
| `rag_poisoning` | `payload_slots` has `rag_document` (n=4) or `poison_payload` (n=119) non-empty; and `indirect_prompt_injection` family | ~119 |

Full derivation logic for each node is in `GRAMMAR_NODE_META` (`src/rogue/schemas/grammar_node.py`).

---

## Labeling approach — heuristic from structured fields

Labels are assigned by `src/rogue/grammar/labeler.py` using deterministic heuristic rules over the structured fields of each `AttackPrimitive`: `family`, `secondary_families`, `payload_slots` keys, and `requires_multi_turn`. The labeler is:

- **Server-free** — no LLM calls, no network, no API cost.
- **Deterministic** — same input always produces the same labels.
- **Conservative** — it does not invent labels; it reads structural fields that were already extracted during harvest.
- **Total** — every primitive gets at least its family-mirroring labels; cross-family structural labels are added when the corresponding `payload_slots` keys are non-empty.

The `GrammarLabel.source` field distinguishes heuristic (`"heuristic"`, the default), human-reviewed (`"manual"`), and LLM-assisted (`"llm"`) labels. The storage table allows all three to coexist for the same (primitive, node) pair under the unique constraint `(primitive_id, node, source)`.

Labels are persisted to `primitive_grammar_labels` (migration `0027`) via `src/rogue/grammar/labeler.py`. The labeler can be re-run idempotently (the unique constraint prevents duplication; `ON CONFLICT DO NOTHING` or an upsert is the correct write pattern).

---

## Analysis unit — per-(primitive × target)

The primary analysis unit is the **per-(primitive × target) outcome**: one row per `(primitive_id, deployment_config_id)` pair in `breach_matrix`, each carrying a binary breach outcome.

The per-primitive ANY-breach base rate is ~0.79 in the current 6-model panel: almost every canonical primitive eventually breaches at least one of the 6 models. This near-ceiling washes out all lift signal — a node that fires on 95% of primitives and a node that fires on 30% of primitives would show nearly identical per-primitive breach rates because the "never breached" primitives are a tiny minority. The per-(primitive × target) unit avoids this by exploiting the variation in which models are breached, not just whether any model was.

With ~298 canonical primitives × ~6 configs, the dataset has approximately 1540 observations. The `breach_matrix` view aggregates trial-level results (multiple run dates, multiple trial temperatures) into one row per (primitive, config), so a single observation captures the reproduced breach evidence for that pair.

The per-primitive analysis (`unit="per_primitive"` in `node_lift_table`) is retained for comparison only and is not the headline finding.

---

## Statistics

All statistics are implemented in pure Python + `math` in `src/rogue/grammar/stats.py`. No scipy, no statsmodels — not installed in the project, and these statistics are simple enough to implement precisely by hand, which also makes them unit-testable against textbook reference values.

### Per-node lift

For each `GrammarNode`, the analysis builds a 2×2 contingency table over the per-(primitive × target) observations:

```
                  breach    no_breach
node present        a           b
node absent         c           d
```

From this table the study reports:

- **Absolute lift** — `a/(a+b) − c/(c+d)` (percentage-point difference in breach rate).
- **Relative lift** — `(a/(a+b)) / (c/(c+d))` (multiplicative factor).
- **Odds ratio** — `(a/b) / (c/d)` (standard 2×2 OR), with a 95% Wald CI (`odds_ratio_ci` in `stats.py`). OR > 1 = breach-promoting; OR < 1 = breach-suppressing.
- **Wilson 95% CI** on both cell proportions (`wilson_ci` in `stats.py`), preferred over the normal approximation near p=0 and p=1.
- **Fisher exact two-sided p-value** (`fisher_exact_2x2` in `stats.py`) — distribution-free, no large-sample assumption. Implemented via the hypergeometric PMF.

All p-values produced by `stats.py` are **uncorrected**. The Benjamini–Hochberg FDR correction is applied downstream (see Confound Controls below).

### Pairwise interactions

`src/rogue/grammar/combinations.py` measures whether combining two `GrammarNode`s produces breach rates that exceed the **no-interaction (multiplicative-odds) baseline**. For each unordered node pair `(A, B)`, every observation is partitioned into four cells: `both` (A and B present), `a_only`, `b_only`, `neither`.

The expected probability of the `both` cell under no interaction is computed on the **odds scale**, not on the additive-probability scale:

```
odds_neither = p_neither / (1 − p_neither)
OR_a = (p_a_only / (1 − p_a_only)) / odds_neither
OR_b = (p_b_only / (1 − p_b_only)) / odds_neither
expected_odds_both = odds_neither × OR_a × OR_b
expected_p_both = expected_odds_both / (1 + expected_odds_both)
```

The logistic null is used (not additive probability) because it is bounded in [0, 1], cannot produce nonsensical predictions > 1 at high background rates, and matches the model a Technique-AST compositor would be fit under — so the delta against it is the honest test.

`interaction_delta = p_both − expected_p_both` (> 0 = synergy on the probability scale). The p-value is from Fisher's exact test on the `both`-vs-`neither` 2×2 table. `synergy = interaction_delta > 0 AND p_value < 0.05` is the **pre-FDR** flag; the downstream FDR correction gates the reportable findings.

Node pairs where any of the four cells has fewer than `min_cell_n` observations are skipped (ORs would be unstable); the skip count is surfaced in analysis output.

---

## Confound controls

### 1. Family collinearity / circularity

The 11 family-mirroring nodes (e.g. `ROLE_HIJACK` assigned when `family == 'role_hijack'`) are by construction colinear with `AttackFamily`. Any raw lift on these nodes is near-circular and cannot independently justify AST composition. The validation layer flags all family-mirroring nodes and treats their lift as a family-baseline measure, not an independent finding.

For the 12 cross-family structural nodes, the concern is softer but still present: a node that fires disproportionately within one high-breach family (e.g. `TRIGGER_BACKDOOR` firing heavily in `indirect_prompt_injection`, which already has a high breach rate) could show lift that is confounded by family. **Mantel–Haenszel stratification** addresses this: it computes a family-stratified odds ratio (the MH-pooled OR across all `AttackFamily` strata) and tests whether the node shows lift after family effects are held constant. A cross-family node that shows FDR-significant lift in the raw analysis AND in the MH-stratified analysis has non-circular signal.

### 2. Multiple comparisons — Benjamini–Hochberg FDR

With 23 nodes, the expected number of false discoveries at an uncorrected α=0.05 threshold is over one. The Benjamini–Hochberg procedure is applied across all 23 per-node p-values to control the false discovery rate at q ≤ 0.05. A finding is reported as **FDR-significant** only if its BH-adjusted q-value passes this threshold.

For the pairwise interaction analysis, BH FDR is applied separately across all node-pair p-values (up to 253 pairs for 23 nodes, fewer after small-n suppression).

### 3. Judge-version caveat

`breach_matrix` is graded by the old v1/v2 judge (the standing corpus re-judge is deferred for cost; see CLAUDE.md standing flag). The v1/v2 judge over-reports breaches relative to judge v3 (precision ~55% vs ~79.5%). All breach signals in this dataset inherit v1/v2 bias — absolute breach rates are inflated, and the inflation may not be uniform across `AttackFamily` or `GrammarNode` strata (different attack families may trigger the judge's over-call patterns differently). This is a declared limitation, not a blocking issue: the study is looking for **relative** differences between node-present and node-absent groups, and as long as the judge's false-positive rate is not systematically correlated with node presence (which is unlikely because the judge was calibrated before grammar nodes were defined), the lift comparisons remain interpretable. Any FDR-significant finding should be flagged with this caveat in the write-up.

---

## Success and failure criteria

**Success (go signal):** at least one cross-family structural `GrammarNode` shows (a) FDR-significant absolute lift (q ≤ 0.05) at the per-(primitive × target) unit AND (b) the lift survives MH family stratification (the MH OR is > 1 with 95% CI not crossing 1). This finding would support building a Technique-AST compositor that prioritises combining that node with others.

**Partial success (directional signal):** at least one cross-family node shows FDR-significant lift but the MH-stratified OR is inconclusive (CI crosses 1). This is worth reporting as a directional finding but does not strongly justify a compositor build — it may still reflect family confounding.

**Null result (no-go signal):** no cross-family structural node passes FDR after the MH control, or all significant nodes are family-mirroring. This is a valid and useful outcome: it means the `AttackFamily` taxonomy already captures the predictive structure, grammar nodes add nothing independent, and the Technique-AST build should not happen. The null result saves months of engineering and is not a failure of the study — it is the study working as designed.

**Pairwise synergy finding:** at least one node pair shows FDR-significant positive `interaction_delta` (both nodes together breach more than the multiplicative-odds baseline predicts). This is the direct empirical support for composition — it means "combining these nodes is synergistic, not just additive."

---

## File map

| File | Role |
|---|---|
| `src/rogue/schemas/grammar_node.py` | `GrammarNode` enum (23 members) + `GrammarLabel` Pydantic wire type + `GRAMMAR_NODE_META` derivation rules |
| `src/rogue/grammar/__init__.py` | Package docstring — study overview |
| `src/rogue/grammar/dataset.py` | `build_grammar_analysis_dataset` — joins `attack_primitives` + `primitive_grammar_labels` + `breach_matrix` into `list[PrimitiveRecord]`; per-target granularity via `TargetOutcome`; $0 SELECT-only; logs the v1/v2 judge caveat |
| `src/rogue/grammar/labeler.py` | Heuristic labeler — deterministic `GrammarNode` assignment from `family` / `secondary_families` / `payload_slots` / `requires_multi_turn`; server-free, no API calls |
| `src/rogue/grammar/stats.py` | Pure-Python statistics: `wilson_ci`, `fisher_exact_2x2`, `odds_ratio_ci`, `node_lift_table` — per-node lift / OR / CI / Fisher p; p-values uncorrected (BH FDR applied downstream) |
| `src/rogue/grammar/combinations.py` | Pairwise interaction analysis: four-cell table per node pair, logistic no-interaction baseline, `interaction_delta`, Fisher p, pre-FDR `synergy` flag |
| `src/rogue/db/migrations/versions/0027_primitive_grammar_labels.py` | Creates `primitive_grammar_labels` table and `grammar_node` Postgres enum |
| `scripts/grammar_labels.py` | CLI driver: label the corpus (`assign` subcommand) and inspect assigned labels (`show` subcommand) |

---

## Relationship to the frozen §13 non-goals

`GrammarNode` is purely additive. It adds a structural measurement layer and does not:
- Touch or extend `AttackFamily` (15 families, frozen Day 0, §13).
- Revise the taxonomy — the taxonomy is frozen; `GrammarNode` is a different abstraction.
- Generate new attacks or payloads.
- Add a new bandit, retrieval system, or scheduler.
- Touch any existing migration before `0027`.

The study is the precondition for a future roadmap item (Technique-AST / compositional generation), not the item itself. Nothing in `src/rogue/grammar/` can affect production breach rates until a compositor is built — and the compositor should not be built until this study returns a go signal.

---

## Results & recommendation (RAN 2026-06-06) — VERDICT: weak/none

The study was executed via `scripts/grammar_study.py` over 351 primitives (301 with breach data) and 1,540 per-(primitive × target) units. Full output: `data/grammar_analysis/REPORT.md`.

**Verdict: weak/none — grammar barely predicts breach after controls.** The marginal lift that exists is family-driven, not grammar-driven: the only strong movers — `multimodal` (OR 4.56) and `training_data_extraction` (OR 3.35) — are family-mirroring nodes flagged *circular* by the Cramér's-V collinearity check (the node is essentially the family label, so its lift is family lift). The genuinely cross-family structural nodes (`authority_frame`, `language_shift`, `encoding_obfuscation`, `structured_output`) show negligible lift (~1.0–1.1×, non-significant). The pairwise synergies that looked striking pre-FDR — e.g. `system_prompt_leak + training_data_extraction` (Δ +0.46, OR 16.8, p=0.0006) — survive none of the four control bars (FDR-significant ∧ non-circular ∧ within-family stratification ∧ target Mantel–Haenszel pooling). The originating memo's specific premise, `RoleHijack + AuthorityFrame = 2.5× breach odds`, is unsupported: the `role_hijack` node has OR = 0.95 (no lift) and the composition did not survive controls. **Bottom line: the family label carries the predictive weight; sub-family grammar structure adds little once family is controlled — Family >> Grammar.**

This is a *successful* null: it cheaply falsifies the assumption the Technique-AST / synthetic-generation roadmap rests on, before any of that machinery is built. The result is most trustworthy precisely *because* it is negative — "huge pre-control synergies → nothing survives controls" is what honest analysis looks like.

**Headline recommendation.** **Ship** contextual scheduling as default (the measured winner: rank 22→11, ASR 50%→60%, cost/success 1.25→0.74). **Keep building** Technique retrieval (it solves scaling/cost/latency and is consistent with every measurement). **Park** Technique AST, synthetic techniques, and synthetic primitives — not killed, *parked*, because the current evidence is a weak justification. Do **not** spend the next few months building a grammar engine or synthetic-technique system on this evidence.

**Only revisit AST if one of these happens:**
1. **You manually label a high-quality subset and discover strong signal** — the heuristic labels could be masking real cross-family structure; a curated manual pass (`source="manual"`) is the way to check, but it is not the highest-value work right now.
2. **Retrieval starts exposing latent structure from the data** — for example, a cluster of ~50 techniques that *always retrieve together and always win together*. At that point grammar may *emerge* from the data rather than being imposed by hand, which would re-justify a compositor.

**Caveats bounding this conclusion** (so it is not over-read): the study is observational, not causal (it is the cheap screen; the interventional confirm is `#TRS-A`, the paired-McNemar authoring test); labels are heuristic, not manually validated; `breach_matrix` is graded by the old v1/v2 judge (over-reports vs v3); and the per-primitive base rate hits a 0.79 ceiling (hence the per-(primitive × target) analysis unit).
