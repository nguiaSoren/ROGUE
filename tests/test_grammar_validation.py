"""Tests for the grammar-study research-validation layer (Engineer 6).

NO DB. Pure-Python / numpy. The headline test is the SYNTHETIC CONFOUNDED dataset:
node X looks predictive marginally, but the effect is entirely explained by family —
the stratified control must collapse it (survives_stratification=False). That proves
the "don't fool ourselves" control actually works.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from rogue.grammar.validation import (
    benjamini_hochberg,
    controlled_analysis,
    cramers_v,
    node_family_collinearity,
    raw_node_lift,
    stratified_node_lift,
)


# --------------------------------------------------------------------------- #
# Lightweight local stand-ins for the frozen dataset dataclasses (no DB import).
# Field names match rogue.grammar.dataset.PrimitiveRecord / TargetOutcome.
# --------------------------------------------------------------------------- #
@dataclass
class FakeTarget:
    deployment_config_id: str
    vendor: str
    model_family: str
    breached: bool
    any_breach_rate: float = 0.0
    full_breach_rate: float = 0.0
    n_trials: int = 10


@dataclass
class FakeRecord:
    primitive_id: str
    family: str
    breached: bool
    has_breach_data: bool = True
    secondary_families: list = field(default_factory=list)
    payload_slots: dict = field(default_factory=dict)
    requires_multi_turn: bool = False
    vector: str = "single_prompt"
    breach_rate: float = 0.0
    n_trials: int = 0
    targets: list = field(default_factory=list)


# ===========================================================================
# benjamini_hochberg
# ===========================================================================
def test_bh_known_vector():
    # Classic BH example. m=5, alpha=0.05.
    # thresholds (k/m)*alpha: .01, .02, .03, .04, .05
    # p:                       .001 .008 .039 .041 .9
    # largest k with p_(k) <= (k/m)*alpha is k=4 (.041 <= .04? no; .039 <= .03? no).
    # Recompute carefully below; whatever the math says, the helper must match step-up.
    p = [0.001, 0.008, 0.039, 0.041, 0.9]
    rej = benjamini_hochberg(p, alpha=0.05)
    # Step-up: ranks sorted = same order. thresholds .01,.02,.03,.04,.05.
    #   .001<=.01 ✓  .008<=.02 ✓  .039<=.03 ✗  .041<=.04 ✗  .9<=.05 ✗
    # largest passing rank = 2 -> reject first two only.
    assert rej == [True, True, False, False, False]


def test_bh_step_up_property():
    # A p-value that individually fails its threshold is still rejected if a
    # larger-ranked p passes (the step-up "rescue").
    # p_(3)=.03 fails (.03<=.03? equal -> passes). Use a case where middle fails but tail passes.
    p = [0.001, 0.04, 0.005, 0.045]  # m=4, alpha=.05 -> thresholds .0125,.025,.0375,.05
    # sorted: .001(.0125✓) .005(.025✓) .04(.0375✗) .045(.05✓) -> largest passing rank=4
    # so ALL four reject (step-up rescues .04 even though .04>.0375).
    rej = benjamini_hochberg(p, alpha=0.05)
    assert rej == [True, True, True, True]


def test_bh_empty_and_nan():
    assert benjamini_hochberg([]) == []
    rej = benjamini_hochberg([float("nan"), 0.001], alpha=0.05)
    # nan treated as 1.0 (never reject); .001 <= (rank/m)*alpha rejects.
    assert rej[0] is False
    assert rej[1] is True


def test_bh_all_reject_when_tiny():
    rej = benjamini_hochberg([1e-9, 1e-9, 1e-9], alpha=0.05)
    assert rej == [True, True, True]


# ===========================================================================
# cramers_v
# ===========================================================================
def test_cramers_v_perfect_association():
    # node present iff category == "A": perfect 1:1 association -> V ~ 1.0
    present = [True, True, False, False, True, False]
    cat = ["A", "A", "B", "B", "A", "B"]
    v = cramers_v(present, cat)
    assert v == pytest.approx(1.0, abs=1e-9)


def test_cramers_v_independent():
    # node presence orthogonal to category -> V ~ 0.0
    present = [True, False, True, False, True, False, True, False]
    cat = ["A", "A", "B", "B", "A", "A", "B", "B"]
    v = cramers_v(present, cat)
    assert v == pytest.approx(0.0, abs=1e-9)


def test_cramers_v_single_category():
    # Only one category -> no association measurable -> 0.0
    assert cramers_v([True, False, True], ["A", "A", "A"]) == 0.0


def test_cramers_v_length_mismatch():
    with pytest.raises(ValueError):
        cramers_v([True, False], ["A"])


# ===========================================================================
# THE KEY TEST — synthetic confounded dataset.
# Node X is present ONLY in the "easy" family, which breaches at high rate.
# Marginally X looks predictive; within-family / MH it collapses to ≈0.
# ===========================================================================
def _confounded_dataset():
    """Build records where node X == "appears only in family EASY".

    EASY family breaches ~always; HARD family breaches ~never. Node X is assigned
    to every EASY primitive and no HARD primitive. So X is perfectly confounded with
    family: marginal lift huge, within-family lift undefined/≈1 (no X-variation inside
    a family), MH pooled OR collapses.

    To make within-family/MH meaningful we also put a CONTROL node Y that varies
    WITHIN both families and is INDEPENDENT of breach — Y must NOT survive either.
    """
    records: list[FakeRecord] = []
    labels: dict[str, set] = {}

    # EASY family: 20 primitives, breach ~always, all carry node "X".
    for i in range(20):
        pid = f"easy_{i:02d}"
        # vary node Y within the family, independent of outcome
        y = (i % 2 == 0)
        targets = [
            FakeTarget("dc_openai", "openai", "gpt", breached=True),
            FakeTarget("dc_anthropic", "anthropic", "claude", breached=(i % 5 != 0)),
        ]
        records.append(
            FakeRecord(pid, family="easy", breached=True, targets=targets)
        )
        nodes = {"x_node"}
        if y:
            nodes.add("y_node")
        labels[pid] = nodes

    # HARD family: 20 primitives, breach ~never, NONE carry node "X".
    for i in range(20):
        pid = f"hard_{i:02d}"
        y = (i % 2 == 0)
        targets = [
            FakeTarget("dc_openai", "openai", "gpt", breached=(i % 7 == 0)),
            FakeTarget("dc_anthropic", "anthropic", "claude", breached=False),
        ]
        records.append(
            FakeRecord(pid, family="hard", breached=(i % 7 == 0), targets=targets)
        )
        nodes: set = set()
        if y:
            nodes.add("y_node")
        labels[pid] = nodes

    return records, labels


def test_confounded_node_collapses_under_stratification():
    records, labels = _confounded_dataset()

    # 1) Marginally, X looks strongly predictive.
    raw = raw_node_lift(records, labels)
    assert raw["x_node"]["rate_present"] > raw["x_node"]["rate_absent"]
    assert raw["x_node"]["lift"] > 1.5  # clearly "predictive" on the surface

    # 2) X is flagged circular (entirely inside the EASY family).
    coll = node_family_collinearity(records, labels)
    assert coll["x_node"]["circular"] is True
    assert coll["x_node"]["overlap_frac"] == pytest.approx(1.0)

    # 3) Within-family stratification: X has NO within-family variation, so the
    #    pooled OR cannot show a within-family effect -> survives_stratification False.
    strat_family = stratified_node_lift(records, labels, by="family")
    assert strat_family["x_node"]["survives_stratification"] is False

    # 4) The control node Y (varies within family, independent of breach) must also
    #    NOT survive — it isn't real signal either.
    assert strat_family["y_node"]["survives_stratification"] is False


def test_confounded_master_verdict_is_weak_none():
    records, labels = _confounded_dataset()
    result = controlled_analysis(records, labels)
    # The only marginally-strong node is the confounded X, which must be killed.
    assert result["verdict"] == "weak/none"
    assert result["surviving_nodes"] == []


# ===========================================================================
# A genuine cross-family signal SHOULD survive (positive control).
# ===========================================================================
def _genuine_signal_dataset():
    """Node Z is cross-family AND independently raises breach within every family.

    Z appears in BOTH families (non-circular), and within each family the Z-present
    units breach more than Z-absent units. This should survive all controls.
    """
    records: list[FakeRecord] = []
    labels: dict[str, set] = {}
    fams = ["fam_a", "fam_b"]
    # Base breach rate per family kept moderate (avoid ceiling). Z lifts it.
    for fam_i, fam in enumerate(fams):
        for i in range(40):
            pid = f"{fam}_{i:02d}"
            has_z = (i % 2 == 0)
            # Z present -> high breach on both targets; Z absent -> low (nonzero) breach.
            if has_z:
                br_o, br_a = True, (i % 3 != 0)
            else:
                br_o, br_a = (i % 5 == 0), (i % 10 == 0)
            targets = [
                FakeTarget("dc_openai", "openai", "gpt", breached=br_o),
                FakeTarget("dc_anthropic", "anthropic", "claude", breached=br_a),
            ]
            agg = br_o or br_a
            records.append(FakeRecord(pid, family=fam, breached=agg, targets=targets))
            labels[pid] = {"z_node"} if has_z else set()
    return records, labels


def test_genuine_signal_survives_controls():
    records, labels = _genuine_signal_dataset()
    coll = node_family_collinearity(records, labels)
    # Z spans both families -> not circular.
    assert coll["z_node"]["circular"] is False

    strat_family = stratified_node_lift(records, labels, by="family")
    assert strat_family["z_node"]["survives_stratification"] is True

    strat_model = stratified_node_lift(records, labels, by="model_family")
    assert strat_model["z_node"]["survives_stratification"] is True

    result = controlled_analysis(records, labels)
    assert result["verdict"] == "signal"
    surviving = {r["node"] for r in result["surviving_nodes"]}
    assert "z_node" in surviving


# ===========================================================================
# controlled_analysis shape contract.
# ===========================================================================
def test_controlled_analysis_shape():
    records, labels = _confounded_dataset()
    result = controlled_analysis(records, labels)
    for key in (
        "verdict",
        "verdict_note",
        "surviving_nodes",
        "dataset_summary",
        "node_family_collinearity",
        "raw_node_lift",
        "within_family_stratification",
        "target_mh_model_family",
        "target_mh_vendor",
        "node_rows",
        "fdr",
        "caveats",
    ):
        assert key in result, f"missing key {key}"
    assert result["verdict"] in {"signal", "weak/none"}
    assert isinstance(result["caveats"], list) and len(result["caveats"]) >= 5
    # The judge-version confound MUST be disclosed.
    assert any("v1/v2" in c for c in result["caveats"])
    # The ceiling effect MUST be disclosed.
    assert any("ceiling" in c.lower() or "0.79" in c for c in result["caveats"])
    # dataset summary carries the non-saturated unit.
    ds = result["dataset_summary"]
    assert ds["n_target_units"] > 0
    assert "ceiling_note" in ds


def test_empty_dataset_is_safe():
    result = controlled_analysis([], {})
    assert result["verdict"] == "weak/none"
    assert result["surviving_nodes"] == []
    assert result["dataset_summary"]["n_target_units"] == 0
