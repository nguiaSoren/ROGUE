"""Unit tests for the calibrate_breach_type runner's offline pieces (build-02
§4.2 / §4.3). No network, no paid call — exercises the CI-based gate, the stub
judge wiring, and the smoke short-circuit decision purely in-process.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from rogue.reproduce.calibration.binary_report import BinaryCalibrationReport
from rogue.reproduce.rubrics.label_set import LabelSet

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "calibration" / "calibrate_breach_type.py"
_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "labels" / "infodisc_designed_v1.json"
)


def _load_runner():
    spec = importlib.util.spec_from_file_location("_calib_runner", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


def _report(human, judge, trap):
    return BinaryCalibrationReport.from_axis(
        human_labels=human,
        judge_labels=judge,
        fp_mode_trap=trap,
        breach_type="information_disclosure",
    )


def test_perfect_agreement_no_trap_ships(runner) -> None:
    """High agreement CI-lower + no FP-mode failures → ship."""
    n = 60
    human = ["breach", "clean"] * (n // 2)
    judge = list(human)  # perfect agreement
    trap = [False] * n
    rep = _report(human, judge, trap)
    assert rep.agreement_ci[1] >= 0.90  # CI-lower clears ship threshold
    assert runner._gate(rep) == "ship"


def test_high_fp_mode_forces_refine(runner) -> None:
    """Even at perfect agreement on non-trap rows, a high FP-mode CI-upper
    must force refine (the §4.3 headline veto)."""
    # All trap rows over-flagged → fp_mode_rate 1.0, CI-upper = 1.0 > ceiling.
    human = ["clean"] * 10 + ["breach"] * 10
    judge = ["breach"] * 10 + ["breach"] * 10
    trap = [True] * 10 + [False] * 10
    rep = _report(human, judge, trap)
    assert rep.fp_mode_rate == 1.0
    assert runner._gate(rep) == "refine"


def test_low_agreement_forces_refine(runner) -> None:
    human = ["breach", "clean"] * 10
    judge = ["clean", "breach"] * 10  # always wrong → 0% agreement
    trap = [False] * 20
    rep = _report(human, judge, trap)
    assert runner._gate(rep) == "refine"


def test_stub_judge_overflags_one_trap(runner) -> None:
    """The dry-run stub returns the human label except it over-flags exactly
    one trap row as breach (so the report has a non-trivial FP-mode)."""
    label_set: LabelSet = LabelSet.load(_FIXTURE)
    cases = list(label_set.cases)
    labels = runner._score_stub(cases)
    # Every non-trap row matches its human label.
    for c in cases:
        if not c.fp_mode_trap:
            assert labels[c.case_id] == c.human_label
    # Exactly one trap row was flipped to breach.
    flipped = [
        c.case_id
        for c in cases
        if c.fp_mode_trap
        and c.human_label == "clean"
        and labels[c.case_id] == "breach"
    ]
    assert len(flipped) == 1


def test_build_report_uses_breach_type(runner) -> None:
    label_set = LabelSet.load(_FIXTURE)
    cases = list(label_set.cases)
    labels = runner._score_stub(cases)
    rep = runner._build_report(cases, labels, "information_disclosure")
    assert rep.breach_type == "information_disclosure"
    assert rep.agreement.n == len(cases)  # no errors from the stub


def test_serialize_byte_identical_without_noise_block(runner) -> None:
    """The noise overlay must be additive: OFF ⇒ the report has no extra key."""
    rep = _report(["breach", "clean"], ["breach", "clean"], [False, True])
    off = runner._serialize(rep, tier="smoke", dry_run=True)
    assert "noise_corrected" not in off


def test_serialize_adds_noise_block_when_supplied(runner) -> None:
    """When a block is passed (flag ON), it is the ONLY added key; rest identical."""
    rep = _report(["breach", "clean"], ["breach", "clean"], [False, True])
    off = runner._serialize(rep, tier="smoke", dry_run=True)
    block = runner._noise_block(rep, judge_positive=None, n_judge=None)
    on = runner._serialize(rep, tier="smoke", dry_run=True, noise_corrected=block)
    assert set(on) - set(off) == {"noise_corrected"}
    assert all(on[k] == off[k] for k in off)  # every shared key byte-identical
    assert on["noise_corrected"]["source"] == "self_calibration_set"
