# Figure specs — adaptive-orchestration workshop paper

*Local/WIP. Figures for `adaptive_orchestration_paper.md`. Each spec gives: the claim it carries, the paper section it anchors, plot type + encoding, the exact data source (runnable SQL or script), honest-presentation notes, and priority. Run-ids used below — set once:*

```bash
GREEDY=sweep_p2_1780457963        # canonical / greedy, K=3 quota=0  (the baseline)
STARV=sweep_starv_q3_1780462736   # starvation + quota=3, K=3        (causal test)
GROWTH=sweep_K5_q5_1780477935     # growth, K=5 quota=5              (K experiment)
```

*Three of these are already emitted numerically by `scripts/analyze_sweep.py --run-id <id>` and `scripts/simulate_quota.py --run-id <id>`; the queries below are the plotting-ready forms. Style: colour-blind-safe palette, sample sizes (N) in every caption, no axis truncation that exaggerates an effect.*

> **⚑ FLAG — judge-version staleness (updated 2026-06-07).** The judge was recalibrated to **`judge_v3.md`** (precision 55%→79.5%, agreement 70.3%→89.3%; see `docs/judge_fp_taxonomy.md §6`), and the stored `breach_results` have now been **re-graded under v3 (2026-06-07): breach cells 2,429→1,371 (−43.6%), all ERROR cells resolved.** The two figures whose **absolute breach rates** come from `breach_results` — **F5 (allocation bias, per-model breach rate)** and **F7 (contextual per-model × family heatmap)** — are still plotted on the **old v1/v2 (over-eager) numbers**: the current `docs/figs/F5_allocation_bias.png` and `docs/figs/F7_contextual_heatmap.png` (generated 2026-06-03) are now the **stale artifacts**. **Regenerate F5/F7 from the v3-graded matrix** and update their captions — the −43.6% breach-rate drop changes the absolute rates. The *relative* claims they carry (winner-attribution rank inversion in F5; the family×model spread in F7) survive the judge offset, but the absolute rates will tighten. The remaining figures (F1–F4, F6, F8–F10: reachability, cost-per-graduation, quota sim, repertoire growth, rank-of-winner, schematics) are judge-version-independent and are not affected.

---

## F1 — System pipeline + self-expansion loop (schematic) — MUST-HAVE
- **Claim / anchor:** orients the whole paper; the loop that §7 closes. §2 + §7.
- **Type:** hand-drawn schematic (tikz / draw.io / mermaid), not data. Two coupled diagrams: (a) the reproduction pipeline `harvest → extract(technique vs payload) → lifecycle(candidate→active) → escalation ladder → judge → threat brief`; (b) the self-expansion loop `harvest → pool grows → scheduler: pool≥5? → GROWTH sweep → graduate → pool drains → CANONICAL → (refill)`.
- **Notes:** keep the loop's thermostat arrow (graduation drains the pool) visually prominent — it's the self-regulation. Mark the scheduler box "deterministic rule, no ML."

## F2 — Reachability by ladder tier: greedy vs growth (grouped bar) — MUST-HAVE
- **Claim / anchor:** the causal core — greedy starves the candidate-bearing tier (0.07); the growth config rescues it (0.98). §5 (Table) made visual.
- **Type:** grouped bar. X = tier (image, coj, structured, audio, planner). Y = reachability ∈ [0,1]. Two bars/tier: greedy (`$GREEDY`) vs growth (`$STARV`).
- **Query (run per run-id):**
  ```sql
  SELECT tier,
         sum((eligible AND executed)::int)::float / NULLIF(sum(eligible::int),0) AS reachability,
         sum(eligible::int) AS n_eligible
  FROM ladder_rotation_membership WHERE run_id = :rid GROUP BY tier ORDER BY tier;
  ```
- **Notes:** annotate the planner pair (0.07 → 0.98) — that's the headline. Put N_eligible per bar in the caption. Order tiers by ladder position so "planner = last = most starved" reads spatially.

## F3 — Where eligible opportunities went (stacked bar) — SUPPORTING
- **Claim / anchor:** 85% of eligible appearances were lost to early-stop under greedy; ~1% under growth. §5.
- **Type:** 100%-stacked horizontal bar, one per run. Segments = `executed / early_stop / budget / no_compatible_config / not_reached`.
- **Query:**
  ```sql
  SELECT run_id, COALESCE(skipped_reason,'executed') AS outcome, count(*) AS n
  FROM ladder_rotation_membership WHERE run_id IN (:greedy,:growth)
  GROUP BY run_id, COALESCE(skipped_reason,'executed') ORDER BY run_id, n DESC;
  ```
- **Notes:** this is the "negative space" of F2 — pairs well beside it. Caption the executed% (15% vs 99%).

## F4 — Cost-per-graduation vs K (line, the economic inversion) — MUST-HAVE
- **Claim / anchor:** the surprising result — cost-per-graduation *falls* as K rises ($8.37 → $7.01); the curve will eventually bend up at saturation. §6.
- **Type:** line + markers. X = K (3, 5, [8 = future, dashed/empty marker]). Y = cost-per-graduation ($). Annotate the *unknown* saturation point with a shaded "?" region beyond K=5.
- **Data (derived, not a single query):** `cost_per_grad = escalation_spend ÷ graduations`. From the run `done:` lines + the active-count delta: K=3 → $25.10 ÷ 3 = **$8.37**; K=5 → $28.06 ÷ 4 = **$7.01**. (Both also printed by `analyze_sweep.py` §6 + the graduation query.)
- **Notes:** only two points so far — plot them as data, draw the post-K=5 region as *hypothesized* (dashed), and state N in the caption. Do **not** imply a fitted curve. A small inset can show the mechanism: "ladder = fixed cost, candidate = marginal."

## F5 — Allocation bias: ladder winner-share vs unbiased breach rate, per model (grouped bar) — MUST-HAVE
- **Claim / anchor:** the generalizable systems result — short-circuit winner attribution is nearly inverted from true vulnerability (gpt +51, mistral −37). §5.
- **Type:** grouped bar, X = target model, two bars: "ladder win-share" vs "unbiased breach rate (full matrix)". Sort by Δ. Optionally annotate Δ above each pair.
- **Queries:**
  ```sql
  -- ladder win-share (config_id holds target_model on winner rows — the misnomer)
  SELECT config_id AS model,
         count(*)::float / sum(count(*)) OVER () AS win_share
  FROM ladder_attempts WHERE breached AND config_id IS NOT NULL AND run_id = :rid
  GROUP BY config_id;
  -- unbiased per-model breach rate (full reproduction matrix)
  SELECT dc.target_model,
         sum((br.verdict IN ('partial_breach','full_breach'))::int)::float / count(*) AS breach_rate,
         count(*) AS n_trials
  FROM breach_results br JOIN deployment_configs dc ON dc.config_id = br.deployment_config_id
  GROUP BY dc.target_model ORDER BY 2 DESC;
  ```
- **Notes:** caption must state these measure *different things on different denominators* (winner-of-ladder vs trial-level breach) — the point is the *rank inversion*, not a like-for-like ratio. N_trials per model belongs in the caption (~1,800 each, balanced — that's what makes the matrix unbiased).

## F6 — Quota simulation: candidate reachability & est. cost vs quota (dual-axis) — SUPPORTING
- **Claim / anchor:** the zero-cost replay that pre-screened the paid run; the *binary* cost jump at quota 0→1 vs near-free 1→3. §8 (reproducibility).
- **Type:** dual-axis line. X = quota (0,1,2,3). Left Y = candidate reachability (0.00→1.00). Right Y = est. escalation cost ($2.80→$18.45). Mark the 0→1 jump.
- **Data:** `scripts/simulate_quota.py --run-id $GREEDY` (already prints the table: quota / cand_reach / planner_reach / executions / est_esc_cost).
- **Notes:** label it clearly as a *simulation* (deterministic replay of logged rotations), and state what it cannot predict (whether a reached candidate breaches). This figure is partly *about the method* — that you can answer an allocation question for $0.

## F7 — Per-model × family effectiveness heatmap (the contextual map) — SUPPORTING/APPENDIX
- **Claim / anchor:** strong, free contextual signal; also the reference that makes F5's "bias" interpretable. §5 / §11.
- **Type:** heatmap. Rows = target model, cols = attack family, cell = breach rate (sequential colormap), cell text = `breaches/trials`.
- **Query:**
  ```sql
  SELECT dc.target_model, ap.family,
         sum((br.verdict IN ('partial_breach','full_breach'))::int)::float / count(*) AS rate,
         count(*) AS n
  FROM breach_results br
  JOIN deployment_configs dc ON dc.config_id = br.deployment_config_id
  JOIN attack_primitives ap ON ap.primitive_id = br.primitive_id
  GROUP BY dc.target_model, ap.family;
  ```
- **Notes:** mask cells with N below a floor (say <20) to grey — honesty about sparsity. Caption the spread (Opus 1.4% → Mistral 48.6% overall; mistral×training_data_extraction=0.92).

## F8 — Repertoire growth across sweeps (step / bar) — SUPPORTING
- **Claim / anchor:** the payoff — active repertoire 7 → 10 → 14, and the candidate pool draining/refilling (the loop in data). §6 / §7.
- **Type:** step plot or paired bars across three checkpoints (pre / after-causal-test / after-K5). Series: active count (7→10→14) and candidate count (15→12→8) on a second series to show drain. Overlay graduations-per-sweep (0, 3, 4).
- **Data:** the status snapshots recorded at each sweep (in the lab notes / `analyze_sweep.py` §4); active deltas are the `done:`-line active counts. (A live `SELECT status, count(*) FROM attack_strategies GROUP BY 1` gives only the *current* point.)
- **Notes:** annotate which sweep was canonical (0 graduations) vs growth — the contrast is the message.

## F9 — Lifecycle state machine (schematic) — APPENDIX
- **Claim / anchor:** how a technique moves; supports §2 + the graduation correction (§5).
- **Type:** state diagram: `candidate → active` (on a breach), `candidate/active → retired` (soft-retire: Rule A evidence / Rule B TTL), `retired → active` (resurrection), `→ archived`. Annotate edges with the trigger.
- **Notes:** mark "graduation = any breaching candidate (mode-adaptive), not winner-only" on the candidate→active edge — that's the §5 correction made visual.

## F10 — Rank-of-winner distribution, greedy vs growth (histogram) — OPTIONAL
- **Claim / anchor:** greedy front-loads the winner (spike at rank 0); the quota suppresses early-stop so winners sit deeper (median 1, long tail). §5 / §6.
- **Type:** overlaid/side-by-side histograms of winner rotation-rank, one per run.
- **Query:**
  ```sql
  SELECT rank FROM ladder_rotation_membership
  WHERE run_id = :rid AND executed AND config_id IS NOT NULL ORDER BY rank;
  ```
- **Notes:** caption median/mean/max (greedy 0/3.2/21; growth 1/3.5/26). This is a nuance figure — include only if space allows.

## F11 — Scheduling is capability: order mode × {rank, ASR, cost-per-success} (grouped bars + CDF) — MUST-HAVE
- **Claim / anchor:** the §6b centerpiece — holding repertoire/judge/corpus/target fixed and changing *only* strategy order, cross-tier ordering lifts ASR while lowering rank and cost-per-success simultaneously (rank↓ *caused* ASR↑ via depth-cap reachability). §6b.
- **Type:** two panels. **(a)** grouped bars, X = order mode (`fixed`, `canonical`, `contextual`), three normalized series per mode — median winner-rank, ASR, cost-per-success — each on its own y-axis or shown as a small-multiple of three sub-panels (do NOT co-plot raw $ and % on one axis). **(b)** rank-of-winner CDF (or per-goal paired scatter, `canonical` rank vs `contextual` rank with the y=x diagonal) showing the leftward/downward shift — and, critically, the goals that breach only under `contextual` (held under baseline) marked distinctly, since those are the ASR lift.
- **Data:** **in `benchmark_runs`** under run-labels `p4-fixed-20` / `p4-contextual-20` (pilot, AdvBench, vs `fixed`) and `e-canonical-20` / `e-contextual-20` (Option E, AdvBench+JBB, vs the production `canonical` baseline). Numbers to plot — Pilot: rank 24→11, ASR 30%→45% (6/20→9/20), cost/success $2.32→$1.15, best rank 19→0. Option E: rank (AdvBench 22→13.5, JBB 22→11), ASR 50%→60% (10/20→12/20), cost/success $1.25→$0.74, total $12.49→$8.92, best depth 19/16→1/1. **Generate via `scripts/paper_figs.py` — TODO, not yet rendered** (no `docs/figs/` file exists for this yet; do NOT fabricate one).
- **Notes (honest presentation):** (1) keep the pilot (vs `fixed`) and Option E (vs `canonical`) visually distinct — they have *different baselines*; the production-relevant delta is Option E. (2) State N=20 per run in the caption and that the rank medians are over breached *subsets of unequal size* (so the load-bearing comparison is the paired ASR + cost-per-success, plus the both-datasets consistency), not the medians alone. (3) Caption must note contextual was run **cold** → the effect shown is cross-tier promotion alone, vendor-conditioning not yet contributing. (4) For panel (b), the "breaches only under contextual" markers are the visual statement of the causal mechanism — annotate "depth-cap-unreachable winner now reached." (5) Plot per-dataset (AdvBench / JBB) side by side for Option E to show the effect is not an aggregation artifact. This figure is judge-version-independent (rank/ASR/cost are not `breach_results` absolute rates).

---

## F12 — Recall@K curve for the Technique Retrieval System (line + per-target series) — SYSTEMS CONTRIBUTION

- **Claim / anchor:** the offline deployment gate for retrieval-based scheduling — "does the retrieval layer preserve the information content of full-corpus evaluation?" and "at what K is the 80% coverage threshold met?" This figure is the primary output of `scripts/retrieval_eval.py --deterministic` and gates Weeks 6-7 activation. See `docs/adaptive_orchestration_systems.md §Technique Retrieval Layer §Recall@K offline evaluation methodology`.
- **Type:** line plot with markers. X-axis = K ∈ {10, 25, 50, 100} (log scale optional for readability). Y-axis = Recall@K ∈ [0, 1]. Series: (a) **overall Recall@K** (bold line, all winner events in denominator); (b) **per-vendor series** (one line per target vendor, e.g. claude / openai / google / mistral — lighter weight); (c) **per-model-family series** (one line per family if per-vendor is too sparse); (d) a **horizontal dashed line at y=0.80** labelled "gate (≥80% @ K=50)". Additionally: annotate the **uncovered-winner fraction** as a text box or separate bar below the main plot (e.g. "X% of winners have no profile — excluded from recall denominator; profile completeness is a separate target"). Do NOT fold uncovered winners into the recall denominator — show them as a distinct annotation so the reader can see both the retrieval precision over covered winners and the profile coverage gap separately.
- **Data source:** `scripts/retrieval_eval.py --deterministic` (replay of `ladder_attempts` rows where `is_winner=True`; embed via `deterministic_embed_fn`; retrieve top-{10,25,50,100} by cosine; check winner inclusion). The script prints Recall@K + uncovered-winner count; this figure is the visual form of that output. Run cost: $0. **Not yet generated** — run the script first, then plot.
- **Honest presentation notes:** (1) state the total number of winner events in the caption (the denominator for overall recall); (2) flag if any per-vendor or per-family series has N < 10 winner events — mask or grey those series rather than extrapolating; (3) if the gate is not met (Recall@50 < 80%), the figure should show *where* recall falls short (which vendor/family, at what K) so the diagnosis is visual; (4) annotate whether the eval used deterministic embeddings (baseline) or live embeddings (`--live` flag) — the two can produce materially different curves; (5) include the MIN_K=25 floor as a vertical dashed line at x=25 so the floor is visible relative to the gate.
- **Caption template (fill in after running):** "Recall@K for the Technique Retrieval System evaluated offline over N=<total> historical winner events from `ladder_attempts`. Each point shows the fraction of winners whose technique appears in the top-K retrieved candidates (deterministic embeddings; cosine similarity). Dashed horizontal line: the 80%@50 activation gate. Per-vendor series show whether coverage is uniform across deployment families. Excluded: <X%> of winner events whose technique has no profile (uncovered winners — shown separately; not folded into recall). Eval cost: $0."
- **Priority:** HIGH for a systems paper that includes the retrieval layer. Independently publishable as a methodology figure even if the retrieval layer is not the paper's primary contribution — it demonstrates a $0 deployment gate over stored telemetry, which is itself the key systems-engineering point.

---

---

## F-nodeLift — Grammar-node lift forest plot (#TRS-C) — GRAMMAR STUDY

- **Claim / anchor:** each structural `GrammarNode` label's predictive power over the per-(primitive × target) breach outcome, after collinearity filtering and FDR correction. The primary output of `scripts/grammar_study.py`. Determines whether any grammar component carries marginal signal beyond attack-family membership.
- **Type:** horizontal forest plot. One row per `GrammarNode` label (sorted by odds ratio, descending). X-axis = log odds ratio (centre line at log(1) = 0). Each row: point estimate (odds ratio), Wilson/Wald 95% CI as a horizontal error bar. Visual encoding: FDR-significant nodes (BH q < 0.05, survives family stratification) rendered in solid colour; non-significant nodes in light grey; nodes flagged as circular by Cramér's V (collinear with family) rendered in lighter grey with a dagger annotation. Baseline reference: dashed vertical line at OR = 1 (no lift). Optionally: a secondary panel with raw counts (n_with_node, n_breach_with_node) as a dot-size or inset bar to convey sparse vs dense nodes.
- **Data source:** `scripts/grammar_study.py` — per-node results table (odds_ratio, ci_low, ci_high, fisher_p, bh_q, survives_stratification, is_circular). Run cost: $0.
- **Axes:** x = log(OR) with labelled tick marks at 0.5, 1, 2, 4 (log scale, or arithmetic if the range is narrow). y = node label (text). Title: "Per-node breach lift (per-(primitive × target) unit; BH FDR q < 0.05; MH-stratified by target model; circular nodes greyed)."
- **Honest presentation notes:** caption must state N total per-(primitive × target) cells; flag that these breach rates are v1/v2-graded (the matrix has since been re-judged under v3, 2026-06-07, breach cells −43.6% — regenerate this figure from the v3-graded matrix); state that "circular" means Cramér's V with family exceeds the threshold, not that the node is meaningless — only that it cannot be separated from family collinearity in this corpus. If ALL nodes are non-significant or circular, the figure still ships — a null forest plot IS the result.
- **Priority:** HIGH — the primary deliverable of #TRS-C. Positive or null, this figure is the visual answer to "does grammar predict breaches?"

## F-combo — Grammar-node combination synergy heatmap (#TRS-C) — GRAMMAR STUDY

- **Claim / anchor:** pairwise node co-occurrence synergy — whether having two grammar nodes together lifts breach rate above the no-interaction expectation. Identifies composable node pairs worth targeting in the interventional study (#TRS-A) if any synergy survives.
- **Type:** square heatmap. Rows and columns = `GrammarNode` labels (same set as F-nodeLift). Cell colour = interaction delta (observed P(breach | A ∧ B) − expected under independence), colour scale diverging at 0 (positive = synergy, cool; negative = interference, warm). Cell text: interaction delta to 2 decimal places where n_AB ≥ min_count; cells below min_count masked to grey/hatching. The diagonal is undefined (self-combination); mask it. Optionally: overlay a significance marker (asterisk or bold border) for cells where Fisher exact on (A ∧ B) vs A ∨ B reaches BH-corrected significance.
- **Data source:** `scripts/grammar_study.py` — pairwise synergy matrix (node_A, node_B, n_both, observed_breach_rate, expected_breach_rate, interaction_delta, fisher_p, bh_q). Run cost: $0.
- **Axes:** both axes = node label. Title: "Node-pair breach synergy (observed P(breach|A∧B) − expected; cells with n < min_count masked)." Colorbar labelled "interaction delta (P scale)."
- **Honest presentation notes:** caption must state min_count threshold and total non-masked cells; note that sparse co-occurrences are masked, not counted as zero-synergy; note that the heatmap is symmetric but the upper triangle may be cleaner to show alone. If no cell reaches BH-corrected significance the figure still ships — the absence of synergy is the result.
- **Priority:** MEDIUM — supporting result to F-nodeLift. Most informative if F-nodeLift shows any signal; still ships (showing null) if it doesn't.

## F-strat — Marginal vs within-family lift comparison (#TRS-C) — GRAMMAR STUDY

- **Claim / anchor:** shows which nodes survive family stratification — the test that separates grammar signal from family collinearity. A node with large marginal lift that collapses within-family is a family artifact; a node whose lift holds within-family is a genuine grammar component.
- **Type:** paired horizontal bar chart (or scatter with y=x diagonal). For each `GrammarNode` label that had any marginal lift: two bars side by side (or two points connected by a line) — (a) marginal lift (pooled, ignoring family) and (b) within-family lift (MH-stratified estimate). X-axis = lift (OR, or risk-difference from baseline). Colour-encode nodes where marginal ≠ within-family by a meaningful margin (suggesting family confounding) vs nodes that hold (grammar signal). A y=x line or zero reference helps the scatter version.
- **Data source:** `scripts/grammar_study.py` — marginal odds ratios (from the pooled analysis) and MH-stratified odds ratios (from the within-family stratum combination). Run cost: $0.
- **Axes:** x = odds ratio (or Δ P). y = node label (subset: only those with any marginal lift worth showing, e.g. OR > 1.1). Title: "Grammar-node lift: marginal vs within-family (MH-stratified); nodes that collapse under stratification are family collinearity artifacts."
- **Honest presentation notes:** caption must state which families had enough within-stratum cases to contribute to MH estimates (sparse families may not contribute and are disclosed); note that a within-family OR is inherently noisier (smaller N per stratum) so wider CIs are expected; make clear this is the *stratification step* of the analysis, not an independent test. If only a few nodes survive, show all of them and label the survivors explicitly.
- **Priority:** HIGH if F-nodeLift shows any signal — this is the control figure that distinguishes grammar signal from family collinearity, which is the most important methodological claim. Reduces to a short "all lifts collapsed under stratification" caption note if null.

---

## Recommended set for a workshop paper (≈6 figures)
F1 (loop), F2 (reachability rescue), F4 (economic inversion), F5 (allocation bias), and **F11 (scheduling-is-capability — the §6b centerpiece)** as the load-bearing set; F3 and F6 as the strongest supporting (negative-space + the $0 method). F7–F10 to the appendix/extended version.

## Generation note
A small `scripts/paper_figs.py` could emit all panels (matplotlib, the queries above, pulling `analyze_sweep`/`simulate_quota` for F4/F6) into `docs/figs/`. Not built — say the word and I'll write it so the figures regenerate from live data with one command (read-only, no cost).
