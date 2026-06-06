"""Grammar component predictive-power analysis (observational study).

Tests the load-bearing hypothesis behind any Technique-AST / synthetic-generation
roadmap: **do grammar components (and their combinations) predict breaches?**

This is an OBSERVATIONAL study over the *existing* corpus only — no generation, no
new API cost. It labels each `AttackPrimitive` with structural ``GrammarNode``s
(derived from family / secondary_families / payload_slots / multi-turn flags),
joins them to breach outcomes from ``breach_matrix``, and measures per-node lift,
pairwise interactions, and — critically — whether any signal survives controlling
for primitive family, target vendor/model, and multiple comparisons.

GrammarNode is a STRUCTURAL layer *below* the frozen ``AttackFamily`` taxonomy
(additive, §13-safe) — it is not a re-taxonomy. Some nodes mirror families (for
family-derived labels); the interesting ones (authority/language/encoding/output)
cut *across* families, which is what makes the analysis non-circular.

Submodules: dataset (primitive↔breach join), labeler (heuristic node derivation),
stats (per-node lift/OR/CI), combinations (pairwise interactions), validation
(collinearity, stratified controls, FDR correction — "don't fool ourselves").
"""
