"""Unit tests for rogue.grammar.stats — pure stats, NO DB, NO network.

Validates the three low-level helpers against hand-computed / textbook reference
values, then exercises node_lift_table on a synthetic (records, labels) corpus where a
node perfectly predicts breach (large lift, tiny Fisher p) and an inert node does not
(lift≈0, OR≈1, p≈1). Also checks min_n flagging and per_target vs per_primitive counts.
"""

from __future__ import annotations

import math

from rogue.grammar.dataset import PrimitiveRecord, TargetOutcome
from rogue.grammar.stats import (
    NodeLift,
    fisher_exact_2x2,
    node_lift_table,
    odds_ratio_ci,
    wilson_ci,
)
from rogue.schemas import GrammarNode


# --------------------------------------------------------------------------- #
# wilson_ci
# --------------------------------------------------------------------------- #
def test_wilson_ci_reference_8_of_10():
    lo, hi = wilson_ci(8, 10)
    # Textbook Wilson(8,10) ≈ (0.490, 0.943).
    assert abs(lo - 0.490) < 0.01
    assert abs(hi - 0.943) < 0.01


def test_wilson_ci_clamped_and_degenerate():
    # n == 0 → maximally uninformative.
    assert wilson_ci(0, 0) == (0.0, 1.0)
    # p = 1 stays <= 1; p = 0 stays >= 0.
    lo1, hi1 = wilson_ci(10, 10)
    assert hi1 <= 1.0 and lo1 > 0.0
    lo0, hi0 = wilson_ci(0, 10)
    assert lo0 == 0.0 and 0.0 < hi0 < 1.0


def test_wilson_ci_half_is_symmetric():
    lo, hi = wilson_ci(5, 10)
    assert abs((lo + hi) / 2 - 0.5) < 1e-9


# --------------------------------------------------------------------------- #
# fisher_exact_2x2
# --------------------------------------------------------------------------- #
def test_fisher_lady_tasting_tea():
    # Classic strong-association table [[1, 9], [11, 3]].
    # R's fisher.test() two-sided p = 0.002759 (sums BOTH tails with PMF <= observed:
    # x in {0, 1, 9, 10}). The frequently-quoted 0.00137 is the *one-sided* lower-tail
    # p (P(X <= 1) = 3.37e-5 + 0.001346). Our helper is two-sided, so it must match the
    # two-sided value; we also check the one-sided sum to anchor the PMF internals.
    p = fisher_exact_2x2(1, 9, 11, 3)
    assert abs(p - 0.002759) < 1e-4
    # Smaller strongly-associated table where two-sided is clearly < 0.05.
    assert fisher_exact_2x2(8, 2, 1, 5) < 0.05


def test_fisher_balanced_table_is_one():
    assert abs(fisher_exact_2x2(10, 10, 10, 10) - 1.0) < 1e-9


def test_fisher_perfect_separation_small_p():
    # Strong association → very small p; bounded in (0, 1].
    p = fisher_exact_2x2(20, 0, 0, 20)
    assert 0.0 < p < 1e-6


def test_fisher_empty_table():
    assert fisher_exact_2x2(0, 0, 0, 0) == 1.0


# --------------------------------------------------------------------------- #
# odds_ratio_ci
# --------------------------------------------------------------------------- #
def test_odds_ratio_balanced_is_one_ci_straddles():
    orat, lo, hi = odds_ratio_ci(10, 10, 10, 10)
    assert abs(orat - 1.0) < 1e-9
    assert lo < 1.0 < hi  # CI straddles 1


def test_odds_ratio_known_value():
    # [[2, 1], [1, 4]] → OR = (2*4)/(1*1) = 8.0
    orat, lo, hi = odds_ratio_ci(2, 1, 1, 4)
    assert abs(orat - 8.0) < 1e-9
    assert lo < orat < hi


def test_odds_ratio_haldane_on_zero_cell():
    # Zero cell → Haldane-Anscombe +0.5 all cells, OR finite, not inf/nan.
    orat, lo, hi = odds_ratio_ci(10, 0, 0, 10)
    assert math.isfinite(orat) and orat > 1.0
    assert math.isfinite(lo) and math.isfinite(hi)
    assert lo > 0.0


# --------------------------------------------------------------------------- #
# node_lift_table — synthetic corpus
# --------------------------------------------------------------------------- #
def _target(breached: bool) -> TargetOutcome:
    rate = 1.0 if breached else 0.0
    return TargetOutcome(
        deployment_config_id="dc",
        vendor="v",
        model_family="m",
        any_breach_rate=rate,
        full_breach_rate=rate,
        n_trials=10,
        breached=breached,
    )


def _record(pid: str, target_breaches: list[bool]) -> PrimitiveRecord:
    targets = [_target(b) for b in target_breaches]
    any_breach = any(target_breaches)
    return PrimitiveRecord(
        primitive_id=pid,
        family="role_hijack",
        secondary_families=[],
        payload_slots={},
        requires_multi_turn=False,
        vector="text",
        breached=any_breach,
        breach_rate=1.0 if any_breach else 0.0,
        n_trials=10 * len(target_breaches),
        has_breach_data=True,
        targets=targets,
    )


def _synthetic_corpus():
    """20 primitives × 2 targets. PREDICTIVE node present on the 10 that breach all
    targets; absent on the 10 that breach none. INERT node present on every other
    primitive regardless of outcome (no association).
    """
    records = []
    labels: dict[str, set[GrammarNode]] = {}
    for i in range(20):
        breaches = [True, True] if i < 10 else [False, False]
        pid = f"p{i}"
        records.append(_record(pid, breaches))
        nodes: set[GrammarNode] = set()
        if i < 10:
            nodes.add(GrammarNode.DIRECT_OVERRIDE)  # predictive
        if i % 2 == 0:
            nodes.add(GrammarNode.LANGUAGE_SHIFT)  # inert (half, balanced across breach)
        labels[pid] = nodes
    return records, labels


def test_node_lift_predictive_node():
    records, labels = _synthetic_corpus()
    table = node_lift_table(records, labels, unit="per_target", min_n=5)
    by_node = {nl.node: nl for nl in table}

    pred = by_node[GrammarNode.DIRECT_OVERRIDE]
    # Present on 10 primitives × 2 targets = 20 units, all breached.
    assert pred.n_with == 20
    assert pred.k_with == 20
    assert abs(pred.p_with - 1.0) < 1e-9
    # Baseline = 20 breached / 40 units = 0.5 → relative lift ≈ 2.0.
    assert abs(pred.baseline - 0.5) < 1e-9
    assert abs(pred.lift_rel - 2.0) < 1e-9
    assert pred.lift_abs > 0.4
    assert pred.odds_ratio > 1.0
    assert pred.p_value < 1e-6
    assert not pred.flagged


def test_node_lift_inert_node():
    records, labels = _synthetic_corpus()
    table = node_lift_table(records, labels, unit="per_target", min_n=5)
    by_node = {nl.node: nl for nl in table}

    inert = by_node[GrammarNode.LANGUAGE_SHIFT]
    # Present on even-indexed primitives: 5 breach-all + 5 breach-none → balanced.
    assert abs(inert.p_with - 0.5) < 1e-9
    assert abs(inert.lift_rel - 1.0) < 1e-9
    assert abs(inert.odds_ratio - 1.0) < 1e-9
    assert inert.p_value > 0.5


def test_node_lift_sorted_by_lift_rel_desc():
    records, labels = _synthetic_corpus()
    table = node_lift_table(records, labels, unit="per_target")
    rels = [nl.lift_rel for nl in table]
    assert rels == sorted(rels, reverse=True)
    # Predictive node should outrank the inert node.
    nodes_order = [nl.node for nl in table]
    assert nodes_order.index(GrammarNode.DIRECT_OVERRIDE) < nodes_order.index(
        GrammarNode.LANGUAGE_SHIFT
    )


def test_node_lift_min_n_flagging():
    records, labels = _synthetic_corpus()
    # min_n high enough that the 20-unit predictive node is still NOT flagged...
    table = node_lift_table(records, labels, unit="per_target", min_n=21)
    by_node = {nl.node: nl for nl in table}
    assert by_node[GrammarNode.DIRECT_OVERRIDE].flagged  # 20 < 21
    # ...and low enough that it's not.
    table2 = node_lift_table(records, labels, unit="per_target", min_n=5)
    by_node2 = {nl.node: nl for nl in table2}
    assert not by_node2[GrammarNode.DIRECT_OVERRIDE].flagged


def test_per_target_vs_per_primitive_unit_counts():
    records, labels = _synthetic_corpus()
    pt = node_lift_table(records, labels, unit="per_target")
    pp = node_lift_table(records, labels, unit="per_primitive")
    pred_pt = next(nl for nl in pt if nl.node == GrammarNode.DIRECT_OVERRIDE)
    pred_pp = next(nl for nl in pp if nl.node == GrammarNode.DIRECT_OVERRIDE)
    # per_target doubles every count (2 targets per primitive).
    assert pred_pt.n_with == 2 * pred_pp.n_with
    assert pred_pt.n_with + pred_pt.n_without == 40
    assert pred_pp.n_with + pred_pp.n_without == 20


def test_node_lift_breach_threshold():
    # Build a record whose target rate is 0.6: at threshold 0.0 the dataset's own
    # `breached` flag (set True here) decides; at threshold 0.7 it's NOT a breach.
    t = TargetOutcome(
        deployment_config_id="dc",
        vendor="v",
        model_family="m",
        any_breach_rate=0.6,
        full_breach_rate=0.6,
        n_trials=10,
        breached=True,
    )
    rec = PrimitiveRecord(
        primitive_id="x",
        family="role_hijack",
        secondary_families=[],
        payload_slots={},
        requires_multi_turn=False,
        vector="text",
        breached=True,
        breach_rate=0.6,
        n_trials=10,
        has_breach_data=True,
        targets=[t],
    )
    labels = {"x": {GrammarNode.DIRECT_OVERRIDE}}
    lo_thr = node_lift_table([rec], labels, unit="per_target", min_n=1, breach_threshold=0.0)
    hi_thr = node_lift_table([rec], labels, unit="per_target", min_n=1, breach_threshold=0.7)
    assert lo_thr[0].k_with == 1  # counts as breach via flag
    assert hi_thr[0].k_with == 0  # 0.6 <= 0.7 → not a breach


def test_node_lift_is_nodelift_instances():
    records, labels = _synthetic_corpus()
    table = node_lift_table(records, labels)
    assert table and all(isinstance(nl, NodeLift) for nl in table)
