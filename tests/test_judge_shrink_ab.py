"""Tests for the judge-shrink A/B gate (Q1) + the reference-anchoring lever.

Covers three things the feature promises:
  1. Cohen's κ + FP-breach on the 2×2 (the honest metric) are correct + degenerate-safe.
  2. The ship/hold gate fires on κ AND FP-breach, with reasons.
  3. The ``ROGUE_JUDGE_REFERENCE_K`` lever is byte-identical when off and append-only when on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rogue.reproduce.calibration.judge_ab import (
    AGREEMENT_GATE,
    judge_ab_from_cells,
    kappa_bootstrap_ci,
    reaggregate_jbb_items,
)
from rogue.reproduce.wildguard_eval import AxisAgreement


# ---- 1. κ + FP-breach on the 2×2 --------------------------------------------------------- #


def test_cohen_kappa_perfect_and_chance():
    # Perfect agreement → κ = 1.0.
    assert AxisAgreement("x", tp=10, fp=0, fn=0, tn=10).cohen_kappa == pytest.approx(1.0)
    # Sonnet's JBB cells → the known 0.814 (chance-corrected, vs 0.910 raw agreement).
    son = AxisAgreement("breach", tp=107, fp=24, fn=3, tn=166)
    assert son.agreement_rate == pytest.approx(0.910, abs=1e-3)
    assert son.cohen_kappa == pytest.approx(0.814, abs=1e-3)
    assert son.false_positive_rate == pytest.approx(24 / (24 + 166), abs=1e-6)


def test_cohen_kappa_degenerate_is_none():
    # One class empty on a marginal (all predicted+true positive) → κ undefined, not a crash.
    assert AxisAgreement("x", tp=10, fp=0, fn=0, tn=0).cohen_kappa is None
    assert AxisAgreement("x", tp=0, fp=0, fn=0, tn=0).cohen_kappa is None
    # FP-rate undefined when there is no human-negative support.
    assert AxisAgreement("x", tp=5, fp=0, fn=5, tn=0).false_positive_rate is None


def test_kappa_matches_paired_formula():
    # κ from cells must equal κ computed from the reconstructed paired lists.
    tp, fp, fn, tn = 40, 12, 8, 60
    pairs_pred = [True] * tp + [True] * fp + [False] * fn + [False] * tn
    pairs_true = [True] * tp + [False] * fp + [True] * fn + [False] * tn
    n = len(pairs_pred)
    po = sum(1 for a, b in zip(pairs_pred, pairs_true) if a == b) / n
    p_pred = sum(pairs_pred) / n
    p_true = sum(pairs_true) / n
    pe = p_pred * p_true + (1 - p_pred) * (1 - p_true)
    expected = (po - pe) / (1 - pe)
    assert AxisAgreement("x", tp, fp, fn, tn).cohen_kappa == pytest.approx(expected)


def test_kappa_bootstrap_ci_brackets_point_and_is_deterministic():
    point, lo, hi = kappa_bootstrap_ci(107, 24, 3, 166, iters=500)
    assert lo <= point <= hi
    # Same seed → identical interval (reproducible).
    again = kappa_bootstrap_ci(107, 24, 3, 166, iters=500)
    assert (point, lo, hi) == again


# ---- 2. the ship/hold gate --------------------------------------------------------------- #


def _sonnet() -> AxisAgreement:
    return AxisAgreement("breach", tp=107, fp=24, fn=3, tn=166)


def test_gate_ships_near_baseline_candidate():
    # qwen3-32b-like cells: κ within tol, FP-breach not worse.
    cand = AxisAgreement("breach", tp=100, fp=22, fn=10, tn=168)
    v = judge_ab_from_cells(cand, _sonnet(), candidate_name="qwen3-32b")
    assert v.ship, v.reasons
    assert v.reasons == ()


def test_gate_holds_on_breach_over_caller():
    # mistral-24b-like: high FP-breach (over-calls breaches) → hold with the FP reason.
    cand = AxisAgreement("breach", tp=109, fp=82, fn=1, tn=108)
    v = judge_ab_from_cells(cand, _sonnet(), candidate_name="mistral-24b")
    assert not v.ship
    assert any("over-calls breaches" in r for r in v.reasons)


def test_gate_holds_below_agreement_floor():
    # A candidate under the §10.2 agreement floor is held with the agreement reason.
    cand = AxisAgreement("breach", tp=90, fp=60, fn=20, tn=130)  # ~73% agreement
    v = judge_ab_from_cells(cand, _sonnet(), candidate_name="weak")
    assert not v.ship
    assert any("gate" in r for r in v.reasons)
    assert cand.agreement_rate < AGREEMENT_GATE


def test_verdict_summary_and_deltas():
    cand = AxisAgreement("breach", tp=100, fp=22, fn=10, tn=168)
    v = judge_ab_from_cells(
        cand, _sonnet(), candidate_name="qwen3-32b",
        cand_cost_per_1k=1.0, base_cost_per_1k=22.5,
    )
    assert v.fpr_delta is not None and v.fpr_delta < 0  # fewer false-positive breaches
    assert v.cost_saving_pct == pytest.approx(1 - 1.0 / 22.5)
    assert "SHIP" in v.summary_line()


# ---- reaggregation of frozen items ------------------------------------------------------- #


def test_reaggregate_jbb_items(tmp_path: Path):
    rows = [
        {"index": 0, "human_majority": True, "rogue_breach": True},   # tp
        {"index": 1, "human_majority": False, "rogue_breach": True},  # fp
        {"index": 2, "human_majority": True, "rogue_breach": False},  # fn
        {"index": 3, "human_majority": False, "rogue_breach": False}, # tn
        {"index": 4, "human_majority": True, "rogue_breach": None},   # errored → excluded
    ]
    f = tmp_path / "items.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    agg = reaggregate_jbb_items(f)
    assert (agg.tp, agg.fp, agg.fn, agg.tn) == (1, 1, 1, 1)
    assert agg.n == 4  # errored row excluded


# ---- 3. the reference-anchoring lever ---------------------------------------------------- #


def _raw_rubric() -> str:
    return (
        Path(__file__).resolve().parent.parent
        / "src" / "rogue" / "reproduce" / "prompts" / "judge_v3.md"
    ).read_text(encoding="utf-8")


def test_reference_lever_off_is_byte_identical(monkeypatch):
    from rogue.reproduce.judge import JudgeAgent

    monkeypatch.delenv("ROGUE_JUDGE_REFERENCE_K", raising=False)
    j = JudgeAgent(model="anthropic/claude-sonnet-4-6")
    assert j.reference_k == 0
    assert j.reference_exemplars == []
    assert j.prompt == _raw_rubric()  # byte-identical to today


def test_reference_lever_on_is_append_only_and_balanced(monkeypatch):
    from collections import Counter

    from rogue.reproduce.judge import JudgeAgent

    monkeypatch.delenv("ROGUE_JUDGE_REFERENCE_K", raising=False)
    j = JudgeAgent(model="anthropic/claude-sonnet-4-6", reference_k=4)
    assert len(j.reference_exemplars) == 4
    # Append-only: rubric bytes are a prefix; nothing above is mutated.
    assert j.prompt.startswith(_raw_rubric())
    assert len(j.prompt) > len(_raw_rubric())
    assert "REFERENCE EXAMPLES" in j.prompt
    # Balanced across the four verdict classes (round-robin).
    verdicts = Counter(e.human_verdict.value for e in j.reference_exemplars)
    assert len(verdicts) == 4


def test_reference_lever_env_read(monkeypatch):
    from rogue.reproduce.judge import JudgeAgent

    monkeypatch.setenv("ROGUE_JUDGE_REFERENCE_K", "4")
    j = JudgeAgent(model="anthropic/claude-sonnet-4-6")
    assert j.reference_k == 4
    assert len(j.reference_exemplars) == 4


def test_reference_lever_garbage_env_is_off(monkeypatch):
    from rogue.reproduce.judge import JudgeAgent

    monkeypatch.setenv("ROGUE_JUDGE_REFERENCE_K", "not-an-int")
    j = JudgeAgent(model="anthropic/claude-sonnet-4-6")
    assert j.reference_k == 0
    assert j.prompt == _raw_rubric()  # malformed → off, never a crash


def test_reference_exemplars_injectable_seam_and_exclusion(monkeypatch):
    # An injected exemplar list bypasses the fixture load (the A/B runner's disjoint-fold seam).
    from rogue.reproduce.judge import JudgeAgent
    from rogue.reproduce.judge_calibration import load_calibration_pairs

    monkeypatch.delenv("ROGUE_JUDGE_REFERENCE_K", raising=False)
    two = load_calibration_pairs()[:2]
    j = JudgeAgent(model="anthropic/claude-sonnet-4-6", reference_exemplars=two)
    assert len(j.reference_exemplars) == 2
    assert j.prompt.startswith(_raw_rubric())
    assert "REFERENCE EXAMPLES" in j.prompt
