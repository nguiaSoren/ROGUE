"""Tests for ``rogue.reproduce.calibration.binary_report`` (build 02 §4.1).

A small hand-built binary breach axis exercises: agreement/precision/recall
each emit a CI; the FP-mode headline is computed on the trap subset only;
errored judge calls are excluded and counted (honest n); bad labels raise.
"""

from __future__ import annotations

import pytest

from rogue.reproduce.calibration.binary_report import BinaryCalibrationReport


def _ci_ok(ci):
    point, lo, hi = ci
    assert 0.0 <= lo <= point <= hi <= 1.0


def test_perfect_agreement_report():
    human = ["breach", "breach", "clean", "clean"]
    judge = ["breach", "breach", "clean", "clean"]
    trap = [False, False, True, True]
    r = BinaryCalibrationReport.from_axis(human, judge, trap)

    assert r.agreement.n == 4
    assert r.agreement.tp == 2
    assert r.agreement.tn == 2
    assert r.agreement.fp == 0
    assert r.agreement.fn == 0
    assert r.agreement_ci[0] == pytest.approx(1.0)
    assert r.precision_ci[0] == pytest.approx(1.0)
    assert r.recall_ci[0] == pytest.approx(1.0)
    # FP-mode: 2 trap rows, judge said clean on both → 0 FP-mode.
    assert r.fp_mode_n == 2
    assert r.fp_mode_rate == pytest.approx(0.0)
    for ci in (r.agreement_ci, r.precision_ci, r.recall_ci, r.fp_mode_ci):
        _ci_ok(ci)


def test_fp_mode_headline_counts_only_trap_subset():
    # 4 clean-by-discuss traps; judge over-calls breach on 3 of them.
    # Plus a real breach the judge gets right, and a non-trap clean.
    human = ["clean", "clean", "clean", "clean", "breach", "clean"]
    judge = ["breach", "breach", "breach", "clean", "breach", "clean"]
    trap = [True, True, True, True, False, False]
    r = BinaryCalibrationReport.from_axis(human, judge, trap)

    # FP-mode is conditioned on the 4 trap rows only (not the non-trap clean).
    assert r.fp_mode_n == 4
    assert r.fp_mode_rate == pytest.approx(3 / 4)
    _ci_ok(r.fp_mode_ci)
    # Overall precision = tp/(tp+fp) = 1/(1+3) = 0.25 (3 trap FPs + 1 real tp).
    assert r.precision_ci[0] == pytest.approx(0.25)
    # Recall = tp/(tp+fn) = 1/1 = 1.0.
    assert r.recall_ci[0] == pytest.approx(1.0)


def test_errored_judge_calls_excluded_and_counted():
    human = ["breach", "clean", "breach", "clean"]
    judge = ["breach", "error", "error", "clean"]
    trap = [False, True, False, True]
    r = BinaryCalibrationReport.from_axis(human, judge, trap)

    assert r.n_errors == 2
    # Only 2 substantive rows survive into the axis.
    assert r.agreement.n == 2
    assert r.agreement.tp == 1  # row 0
    assert r.agreement.tn == 1  # row 3
    # FP-mode denominator counts only substantive trap rows; row 1 errored,
    # row 3 is a clean trap the judge got right → denominator 1, numerator 0.
    assert r.fp_mode_n == 1
    assert r.fp_mode_rate == pytest.approx(0.0)


def test_no_trap_rows_gives_none_fp_mode():
    human = ["breach", "clean"]
    judge = ["breach", "clean"]
    trap = [False, False]
    r = BinaryCalibrationReport.from_axis(human, judge, trap)
    assert r.fp_mode_rate is None
    assert r.fp_mode_ci is None
    assert r.fp_mode_n == 0


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        BinaryCalibrationReport.from_axis(["breach"], ["breach", "clean"], [True])


def test_unknown_human_label_raises():
    with pytest.raises(ValueError):
        BinaryCalibrationReport.from_axis(["nope"], ["breach"], [False])


def test_unknown_judge_label_raises():
    with pytest.raises(ValueError):
        BinaryCalibrationReport.from_axis(["breach"], ["maybe"], [False])


def test_label_normalization_case_insensitive():
    r = BinaryCalibrationReport.from_axis(
        ["BREACH", "Clean"], [" breach ", "CLEAN"], [False, True]
    )
    assert r.agreement.tp == 1
    assert r.agreement.tn == 1


def test_summary_line_smoke():
    human = ["breach", "clean", "clean"]
    judge = ["breach", "breach", "clean"]
    trap = [False, True, True]
    r = BinaryCalibrationReport.from_axis(human, judge, trap)
    line = r.summary_line()
    assert "information_disclosure" in line
    assert "fp_mode=" in line
    assert "agreement=" in line
