"""Calibration package — promoted from the single ``judge_calibration`` module
now that calibration is per-breach-type and multi-axis (v2 §4.1).

Back-compat contract (build 02 §4.1 EXIT GATE): the harm-judge calibration
machinery still lives in :mod:`rogue.reproduce.judge_calibration` (unchanged,
so every stored verdict that cites it stays valid). This package re-exports its
public surface so BOTH import paths resolve to the same objects::

    from rogue.reproduce.judge_calibration import CalibrationReport   # legacy
    from rogue.reproduce.calibration import CalibrationReport          # new

New v2 surfaces (binary breach axis + bootstrap CIs) are added here as
submodules — :mod:`.bootstrap` (the one new piece of math) and
:mod:`.binary_report` (the per-type binary-axis report) — without touching the
harm path.
"""

from __future__ import annotations

# Re-export the existing harm-calibration public symbols verbatim. These are
# the source of truth; we do not redefine them here (no drift).
from rogue.reproduce.judge_calibration import (
    AGREEMENT_REFINE_THRESHOLD,
    AGREEMENT_SHIP_THRESHOLD,
    CALIBRATION_FIXTURE_PATH,
    CalibrationCase,
    CalibrationReport,
    calibrate,
    load_calibration_pairs,
)

# New v2 binary-axis calibration surface.
from rogue.reproduce.calibration.binary_report import BinaryCalibrationReport
from rogue.reproduce.calibration.bootstrap import bootstrap_ci

__all__ = [
    # back-compat re-exports from judge_calibration
    "AGREEMENT_REFINE_THRESHOLD",
    "AGREEMENT_SHIP_THRESHOLD",
    "CALIBRATION_FIXTURE_PATH",
    "CalibrationCase",
    "CalibrationReport",
    "calibrate",
    "load_calibration_pairs",
    # new v2 surface
    "BinaryCalibrationReport",
    "bootstrap_ci",
]
