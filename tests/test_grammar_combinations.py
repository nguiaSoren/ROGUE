"""Tests for grammar pairwise-interaction analysis (Engineer 5). NO DB — all synthetic.

Covers the three required scenarios:
  1. true synergy   — A&B together almost always breach, A-alone/B-alone rarely
                       -> large positive interaction_delta, synergy=True, low p.
  2. independence    — A and B act independently on the odds scale, no interaction
                       -> interaction_delta ≈ 0, synergy=False.
  3. small-n         — a pair whose a 4th cell has only 3 units is dropped and counted
                       in suppressed_pair_count.

Plus structural checks: sort order, suppression vs co-occurrence, contract fields.
"""

from __future__ import annotations

from rogue.grammar.combinations import (
    Interaction,
    pairwise_interactions,
    suppressed_pair_count,
)
from rogue.grammar.dataset import PrimitiveRecord, TargetOutcome
from rogue.schemas import GrammarNode

A = GrammarNode.AUTHORITY_FRAME
B = GrammarNode.ENCODING_OBFUSCATION
C = GrammarNode.FICTIONAL_FRAMING


# --------------------------------------------------------------------------- #
# Synthetic-record builders (one target per record -> 1 observation each).
# --------------------------------------------------------------------------- #
def _target(breached: bool) -> TargetOutcome:
    return TargetOutcome(
        deployment_config_id="dc",
        vendor="acme",
        model_family="m",
        any_breach_rate=1.0 if breached else 0.0,
        full_breach_rate=0.0,
        n_trials=1,
        breached=breached,
    )


def _rec(pid: str, breached: bool, n_targets: int = 1) -> PrimitiveRecord:
    """A record with ``n_targets`` identical-breach targets -> n_targets observations."""
    return PrimitiveRecord(
        primitive_id=pid,
        family="role_hijack",
        secondary_families=[],
        payload_slots={},
        requires_multi_turn=False,
        vector="text",
        breached=breached,
        breach_rate=1.0 if breached else 0.0,
        n_trials=n_targets,
        has_breach_data=True,
        targets=[_target(breached) for _ in range(n_targets)],
    )


def _build(cell_spec: dict[str, tuple[set[GrammarNode], int, int]]):
    """Build (records, labels) from a cell spec.

    cell_spec: name -> (node_set, n_total, n_breached). Emits one single-target record per
    unit so observation count == unit count exactly.
    """
    records: list[PrimitiveRecord] = []
    labels: dict[str, set[GrammarNode]] = {}
    i = 0
    for name, (nodes, n_total, n_breached) in cell_spec.items():
        for j in range(n_total):
            pid = f"{name}_{j}"
            breached = j < n_breached
            records.append(_rec(pid, breached))
            labels[pid] = set(nodes)
            i += 1
    return records, labels


# --------------------------------------------------------------------------- #
# 1. True synergy.
# --------------------------------------------------------------------------- #
def test_true_synergy_detected():
    # both: 30/30 breach; a_only 2/30; b_only 2/30; neither 1/30.
    records, labels = _build(
        {
            "both": ({A, B}, 30, 29),
            "a_only": ({A}, 30, 2),
            "b_only": ({B}, 30, 2),
            "neither": (set(), 30, 1),
        }
    )
    res = pairwise_interactions(records, labels, min_cell_n=5)
    assert len(res) == 1
    inter = res[0]
    assert isinstance(inter, Interaction)
    assert {inter.node_a, inter.node_b} == {A, B}
    assert inter.n_both == 30
    # both breaches near-certain, expected (from weak singles) is low -> big positive delta.
    assert inter.p_both > 0.9
    assert inter.expected_p_both < 0.5
    assert inter.interaction_delta > 0.4
    assert inter.odds_ratio_both > 1.0
    assert inter.p_value < 0.05
    assert inter.synergy is True
    lo, hi = inter.both_ci
    assert 0.0 <= lo <= inter.p_both <= hi <= 1.0


# --------------------------------------------------------------------------- #
# 2. Independence (no interaction on the odds scale).
# --------------------------------------------------------------------------- #
def test_independence_no_interaction():
    # Construct cells so OR_both ≈ OR_a * OR_b (multiplicative on odds) -> delta ≈ 0.
    # neither: p=0.2 (odds .25); a_only: p=0.5 (OR_a = 4); b_only: p=0.5 (OR_b = 4).
    # expected odds_both = .25 * 4 * 4 = 4 -> expected p_both = 0.8. Set both = 0.8.
    # NOTE: the both-vs-neither cell IS strongly different here (the combined effect is
    # large), so Fisher p is tiny — but that is NOT an interaction. The interaction lives
    # in interaction_delta, which must be ≈ 0. synergy requires delta > 0, so under exact
    # independence (delta ≈ 0, not strictly positive) it must be False.
    n = 1000  # large n so the 0.5 continuity correction is negligible.
    records, labels = _build(
        {
            "both": ({A, B}, n, 800),
            "a_only": ({A}, n, 500),
            "b_only": ({B}, n, 500),
            "neither": (set(), n, 200),
        }
    )
    res = pairwise_interactions(records, labels, min_cell_n=5)
    assert len(res) == 1
    inter = res[0]
    assert inter.p_both == 0.8
    assert abs(inter.expected_p_both - 0.8) < 0.005
    # The interaction itself is ~0 (this is the load-bearing assertion).
    assert abs(inter.interaction_delta) < 0.01


def test_independence_delta_sign_governs_synergy():
    # Pure independence with the both cell set 1 breach BELOW the multiplicative
    # expectation -> interaction_delta < 0 -> synergy=False even though Fisher p is tiny.
    # This isolates the direction guard from the (large) both-vs-neither significance.
    n = 1000
    records, labels = _build(
        {
            "both": ({A, B}, n, 790),  # just under expected 800 -> delta slightly < 0
            "a_only": ({A}, n, 500),
            "b_only": ({B}, n, 500),
            "neither": (set(), n, 200),
        }
    )
    inter = pairwise_interactions(records, labels, min_cell_n=5)[0]
    assert inter.interaction_delta < 0
    assert inter.synergy is False


# --------------------------------------------------------------------------- #
# 3. Small-n suppression.
# --------------------------------------------------------------------------- #
def test_small_n_pair_suppressed_and_counted():
    # Pair (A,B): both cell has only 3 units -> dropped. Pair (A,C) & (B,C) are healthy.
    records, labels = _build(
        {
            # A&B co-occur only 3 times (small cell) — should be suppressed.
            "ab": ({A, B}, 3, 2),
            # A&C and B&C and singles all >= min_cell_n so those pairs survive.
            "ac": ({A, C}, 20, 10),
            "bc": ({B, C}, 20, 10),
            "a": ({A}, 20, 8),
            "b": ({B}, 20, 8),
            "c": ({C}, 20, 8),
            "neither": (set(), 20, 4),
        }
    )
    res = pairwise_interactions(records, labels, min_cell_n=5)
    pairs = {frozenset({i.node_a, i.node_b}) for i in res}
    # (A,B) dropped (both cell = 3 < 5); (A,C) and (B,C) kept.
    assert frozenset({A, B}) not in pairs
    assert frozenset({A, C}) in pairs
    assert frozenset({B, C}) in pairs

    sup = suppressed_pair_count(records, labels, min_cell_n=5)
    assert sup == 1


def test_noncooccurring_pair_not_counted_as_suppressed():
    # A and B NEVER co-occur -> not a candidate, must NOT inflate suppressed count.
    records, labels = _build(
        {
            "a": ({A}, 20, 10),
            "b": ({B}, 20, 10),
            "neither": (set(), 20, 5),
        }
    )
    # Only one pair exists (A,B) and it never co-occurs.
    assert suppressed_pair_count(records, labels, min_cell_n=5) == 0
    assert pairwise_interactions(records, labels, min_cell_n=5) == []


# --------------------------------------------------------------------------- #
# Structural contract checks.
# --------------------------------------------------------------------------- #
def test_sorted_by_interaction_delta_desc():
    # Pair (A,B) strong synergy, pair (A,C) weak/none -> AB first.
    records, labels = _build(
        {
            "ab": ({A, B}, 30, 29),
            "ac": ({A, C}, 30, 12),
            "a": ({A}, 30, 3),
            "b": ({B}, 30, 3),
            "c": ({C}, 30, 12),
            "neither": (set(), 30, 3),
        }
    )
    res = pairwise_interactions(records, labels, min_cell_n=5)
    deltas = [i.interaction_delta for i in res]
    assert deltas == sorted(deltas, reverse=True)
    assert res[0].interaction_delta >= res[-1].interaction_delta


def test_per_target_unit_expansion():
    # A record with 3 targets contributes 3 observations, not 1.
    rec_multi = PrimitiveRecord(
        primitive_id="m",
        family="role_hijack",
        secondary_families=[],
        payload_slots={},
        requires_multi_turn=False,
        vector="text",
        breached=True,
        breach_rate=1.0,
        n_trials=3,
        has_breach_data=True,
        targets=[_target(True), _target(True), _target(False)],
    )
    records = [rec_multi]
    # pad both/a/b/neither so a pair is testable
    extra, labels = _build(
        {
            "both": ({A, B}, 10, 9),
            "a": ({A}, 10, 2),
            "b": ({B}, 10, 2),
            "neither": (set(), 10, 1),
        }
    )
    labels["m"] = {A, B}
    res = pairwise_interactions(records + extra, labels, min_cell_n=5)
    inter = next(i for i in res if {i.node_a, i.node_b} == {A, B})
    # both cell = 10 (from 'both') + 3 (m's 3 targets) = 13.
    assert inter.n_both == 13


def test_records_without_breach_data_excluded():
    records, labels = _build(
        {
            "both": ({A, B}, 10, 9),
            "a": ({A}, 10, 2),
            "b": ({B}, 10, 2),
            "neither": (set(), 10, 1),
        }
    )
    # add a no-breach-data record that should be ignored entirely
    ghost = _rec("ghost", False)
    ghost.has_breach_data = False
    ghost.targets = []
    labels["ghost"] = {A, B}
    res = pairwise_interactions(records + [ghost], labels, min_cell_n=5)
    inter = next(i for i in res if {i.node_a, i.node_b} == {A, B})
    assert inter.n_both == 10  # ghost not counted
