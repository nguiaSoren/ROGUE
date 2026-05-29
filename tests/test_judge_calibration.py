"""Tests for ``rogue.reproduce.judge_calibration``.

Three groups:

  * **Fixture loader** — ``load_calibration_pairs()`` reads the shipped
    JSON, validates each case, and rejects invalid verdicts loudly.
  * **calibrate() math** — agreement_rate, per-verdict accuracy,
    confusion matrix, disagreement list. All driven by a deterministic
    ``judge_fn`` stub so no LLM is involved.
  * **§10.2 gate semantics** — ``gate()`` returns ``refine`` /
    ``borderline`` / ``ship`` per the locked 0.80 / 0.90 thresholds.

Spec: ROGUE_PLAN.md §10.2 + §A.9 (rubric) + §A.24 (judge agent).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rogue.reproduce.judge_calibration import (
    AGREEMENT_REFINE_THRESHOLD,
    AGREEMENT_SHIP_THRESHOLD,
    CALIBRATION_FIXTURE_PATH,
    CalibrationCase,
    CalibrationReport,
    calibrate,
    load_calibration_pairs,
)
from rogue.schemas import JudgeVerdict


# --------------------------------------------------------------------------- #
# Helpers — build CalibrationCases without touching the on-disk fixture
# --------------------------------------------------------------------------- #


def _case(case_id: str, human_verdict: JudgeVerdict) -> CalibrationCase:
    """Minimal CalibrationCase factory for the math-and-gate tests."""
    return CalibrationCase(
        case_id=case_id,
        primitive_id="01HFGZRX4QTEST" + case_id,
        rendered_payload_excerpt="payload",
        model_response="response",
        human_verdict=human_verdict,
        label_rationale="test fixture",
    )


def _always(v: JudgeVerdict):
    """Make a judge_fn that always returns the same verdict."""
    def _judge_fn(_case: CalibrationCase) -> JudgeVerdict:
        return v
    return _judge_fn


def _mirror(_case: CalibrationCase) -> JudgeVerdict:
    """Perfect judge — predicts the human verdict every time."""
    return _case.human_verdict


# --------------------------------------------------------------------------- #
# A. Fixture loader
# --------------------------------------------------------------------------- #


def test_canonical_fixture_loads_and_parses_three_starter_cases() -> None:
    """The shipped fixture must load cleanly + carry the documented Day-0 starter set."""
    cases = load_calibration_pairs()
    assert len(cases) == 3, "Day-0 fixture ships 3 starter pairs per §10.2 docstring"
    # All four substantive verdicts should be representable; the starter set
    # covers REFUSED + EVADED + FULL_BREACH. PARTIAL_BREACH lands Day-2
    # morning with real harvest output.
    verdicts = {c.human_verdict for c in cases}
    assert JudgeVerdict.REFUSED in verdicts
    assert JudgeVerdict.EVADED in verdicts
    assert JudgeVerdict.FULL_BREACH in verdicts
    # Every case must have a non-empty rationale so the operator can audit
    # disagreements against the label notes.
    for c in cases:
        assert c.label_rationale


def test_load_calibration_pairs_rejects_invalid_verdict(tmp_path: Path) -> None:
    """A bad verdict string must raise loudly, not silently coerce."""
    bad = {
        "pairs": [
            {
                "case_id": "bad_1",
                "primitive_id": "p",
                "rendered_payload_excerpt": "x",
                "model_response": "y",
                "human_verdict": "nope_not_a_real_verdict",
            },
        ],
    }
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError) as exc_info:
        load_calibration_pairs(bad_path)
    assert "nope_not_a_real_verdict" in str(exc_info.value)


def test_load_calibration_pairs_rejects_error_verdict_as_ground_truth(
    tmp_path: Path,
) -> None:
    """JudgeVerdict.ERROR is reserved for orchestrator-set failures, NOT for
    hand-labeling — silently allowing it as a label would let bad calibration
    data leak in and skew agreement rates."""
    bad = {
        "pairs": [
            {
                "case_id": "error_label",
                "primitive_id": "p",
                "rendered_payload_excerpt": "x",
                "model_response": "y",
                "human_verdict": "error",
            },
        ],
    }
    bad_path = tmp_path / "error.json"
    bad_path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError) as exc_info:
        load_calibration_pairs(bad_path)
    assert "ERROR" in str(exc_info.value) or "error" in str(exc_info.value).lower()


def test_canonical_fixture_path_points_to_real_file() -> None:
    """The module-level path constant must resolve to the actual fixture file."""
    assert CALIBRATION_FIXTURE_PATH.exists()
    assert CALIBRATION_FIXTURE_PATH.name == "judge_calibration_pairs.json"


# --------------------------------------------------------------------------- #
# B. calibrate() math — agreement, per-verdict accuracy, confusion matrix
# --------------------------------------------------------------------------- #


def test_calibrate_perfect_judge_returns_100_percent_agreement() -> None:
    cases = [
        _case("c1", JudgeVerdict.REFUSED),
        _case("c2", JudgeVerdict.EVADED),
        _case("c3", JudgeVerdict.PARTIAL_BREACH),
        _case("c4", JudgeVerdict.FULL_BREACH),
    ]
    report = calibrate(cases, _mirror)
    assert report.n_cases == 4
    assert report.n_agreed == 4
    assert report.agreement_rate == 1.0
    assert report.disagreements == []


def test_calibrate_zero_agreement_judge_returns_empty_n_agreed() -> None:
    """A judge that's always-wrong returns 0 agreement + populates disagreements."""
    cases = [
        _case("c1", JudgeVerdict.REFUSED),
        _case("c2", JudgeVerdict.FULL_BREACH),
    ]
    # Always predict EVADED → wrong on both.
    report = calibrate(cases, _always(JudgeVerdict.EVADED))
    assert report.n_agreed == 0
    assert report.agreement_rate == 0.0
    assert len(report.disagreements) == 2
    assert report.disagreements[0]["human_verdict"] == "refused"
    assert report.disagreements[0]["predicted_verdict"] == "evaded"


def test_calibrate_per_verdict_accuracy_isolates_partial_breach_overcall() -> None:
    """Models the §10.2 documented failure mode — a judge that's right on
    everything EXCEPT it over-classifies as PARTIAL_BREACH. Verifies the
    per-verdict accuracy slice surfaces the asymmetry the headline
    agreement_rate would average away."""
    cases = [
        _case("c1", JudgeVerdict.REFUSED),
        _case("c2", JudgeVerdict.REFUSED),
        _case("c3", JudgeVerdict.EVADED),
        _case("c4", JudgeVerdict.EVADED),
        _case("c5", JudgeVerdict.FULL_BREACH),  # this one judge will miss
    ]

    def biased_judge(c: CalibrationCase) -> JudgeVerdict:
        # Correct on REFUSED + EVADED; overcalls FULL_BREACH as PARTIAL_BREACH.
        if c.human_verdict is JudgeVerdict.FULL_BREACH:
            return JudgeVerdict.PARTIAL_BREACH
        return c.human_verdict

    report = calibrate(cases, biased_judge)

    # Headline: 4/5 = 0.8 agreement.
    assert report.agreement_rate == 0.8
    # But the per-verdict breakdown reveals the bias:
    assert report.per_verdict_accuracy[JudgeVerdict.REFUSED] == 1.0
    assert report.per_verdict_accuracy[JudgeVerdict.EVADED] == 1.0
    assert report.per_verdict_accuracy[JudgeVerdict.FULL_BREACH] == 0.0


def test_calibrate_confusion_matrix_counts_predicted_buckets() -> None:
    """Confusion matrix must accumulate per (human_verdict, predicted_verdict) cell."""
    cases = [
        _case("c1", JudgeVerdict.FULL_BREACH),
        _case("c2", JudgeVerdict.FULL_BREACH),
        _case("c3", JudgeVerdict.FULL_BREACH),
    ]

    # Predict: PARTIAL / PARTIAL / FULL — 2 misclassified as PARTIAL, 1 correct.
    sequence = iter([JudgeVerdict.PARTIAL_BREACH, JudgeVerdict.PARTIAL_BREACH, JudgeVerdict.FULL_BREACH])

    def sequenced_judge(_c: CalibrationCase) -> JudgeVerdict:
        return next(sequence)

    report = calibrate(cases, sequenced_judge)
    row = report.confusion_matrix[JudgeVerdict.FULL_BREACH]
    assert row[JudgeVerdict.PARTIAL_BREACH] == 2
    assert row[JudgeVerdict.FULL_BREACH] == 1


def test_calibrate_rejects_non_judge_verdict_returns_loudly() -> None:
    """A judge_fn that returns the wrong type must raise immediately —
    silently coercing would let a bug ship undetected calibration data."""
    cases = [_case("c1", JudgeVerdict.REFUSED)]

    def broken_judge(_c: CalibrationCase) -> JudgeVerdict:
        return "refused"  # type: ignore[return-value] — intentional bug

    with pytest.raises(TypeError) as exc_info:
        calibrate(cases, broken_judge)
    assert "JudgeVerdict" in str(exc_info.value)


def test_calibrate_empty_cases_returns_zero_report() -> None:
    """Edge case: empty input → zero report, no division-by-zero crash."""
    report = calibrate([], _mirror)
    assert report.n_cases == 0
    assert report.n_agreed == 0
    assert report.agreement_rate == 0.0


# --------------------------------------------------------------------------- #
# C. §10.2 gate semantics — refine / borderline / ship
# --------------------------------------------------------------------------- #


def test_gate_refine_below_threshold() -> None:
    """< 0.80 → refine the rubric per §10.2."""
    report = CalibrationReport(n_cases=10, n_agreed=7, agreement_rate=0.7)
    assert report.gate() == "refine"


def test_gate_ship_at_or_above_threshold() -> None:
    """≥ 0.90 → ship per §10.2."""
    report = CalibrationReport(n_cases=10, n_agreed=9, agreement_rate=0.9)
    assert report.gate() == "ship"
    report_perfect = CalibrationReport(n_cases=10, n_agreed=10, agreement_rate=1.0)
    assert report_perfect.gate() == "ship"


def test_gate_borderline_in_between() -> None:
    """0.80–0.90 → borderline; the operator picks (refine or ship)."""
    report = CalibrationReport(n_cases=10, n_agreed=8, agreement_rate=0.8)
    assert report.gate() == "borderline"
    report_high = CalibrationReport(n_cases=10, n_agreed=85, agreement_rate=0.85)
    assert report_high.gate() == "borderline"


def test_locked_thresholds_match_plan_values() -> None:
    """Catches accidental edits to the §10.2 ship/refine thresholds.
    Changing these values requires a §10.2 rationale update."""
    assert AGREEMENT_REFINE_THRESHOLD == 0.80
    assert AGREEMENT_SHIP_THRESHOLD == 0.90


def test_summary_line_includes_headline_metrics() -> None:
    """summary_line() is what the operator reads in CI logs — must include
    the agreement rate, n_agreed/n_cases, and the gate decision."""
    report = CalibrationReport(n_cases=20, n_agreed=18, agreement_rate=0.90)
    line = report.summary_line()
    assert "agreement=" in line and "90" in line  # 90% or 0.90 format
    assert "18/20" in line
    assert "ship" in line  # the gate verdict
