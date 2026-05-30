"""Tests for the non-paid logic of the Workstream-A scripts:
``scripts/sample_calibration_set.py`` (worksheet blinding) and
``scripts/run_calibration.py`` (label validation, fixture merge, report
serialization). No DB, no judge calls.

Spec: ROGUE_PLAN.md §10.2 + judge-calibration plan (Workstream A).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rogue.reproduce.calibration_sampling import CandidateRow
from rogue.reproduce.judge_calibration import CalibrationReport
from rogue.schemas import JudgeVerdict
from scripts.run_calibration import (
    _load_labeled_cases,
    _merge_into_fixture,
    _serialize_report,
)
from scripts.sample_calibration_set import _full_entry, _worksheet_entry

V = JudgeVerdict


def _candidate(verdict: str = "full_breach") -> CandidateRow:
    return CandidateRow(
        breach_id="01HBREACHXYZ",
        primitive_id="01HPRIMXYZ",
        verdict=verdict,
        target_model="anthropic/claude-haiku-4-5",
        family="jailbreak",
        rendered_payload="do the bad thing",
        model_response="sure, here is the bad thing",
    )


# --------------------------------------------------------------------------- #
# Worksheet blinding — the judge verdict must NOT leak to the labeler
# --------------------------------------------------------------------------- #


def test_worksheet_entry_withholds_judge_verdict_and_blanks_human() -> None:
    row = _candidate("full_breach")
    entry = _worksheet_entry(row)
    # Judge's call is absent; human_verdict is blank for the labeler.
    assert "judge_verdict" not in entry
    assert entry["human_verdict"] == ""
    # Field names the fixture loader expects are present.
    assert entry["rendered_payload_excerpt"] == row.rendered_payload
    assert entry["primitive_id"] == row.primitive_id


def test_full_entry_keeps_judge_verdict_as_answer_key() -> None:
    row = _candidate("partial_breach")
    entry = _full_entry(row)
    assert entry["judge_verdict"] == "partial_breach"
    assert entry["source_breach_id"] == row.breach_id


# --------------------------------------------------------------------------- #
# Label validation
# --------------------------------------------------------------------------- #


def _write_worksheet(path: Path, pairs: list[dict]) -> None:
    path.write_text(json.dumps({"pairs": pairs}, indent=2), encoding="utf-8")


def test_load_labeled_cases_accepts_fully_labeled_worksheet(tmp_path: Path) -> None:
    ws = tmp_path / "worksheet.json"
    _write_worksheet(
        ws,
        [
            {
                "case_id": "cal_full_breach_aaaa",
                "primitive_id": "p1",
                "rendered_payload_excerpt": "x",
                "model_response": "y",
                "human_verdict": "full_breach",
                "label_rationale": "complied",
            }
        ],
    )
    cases = _load_labeled_cases(ws)
    assert len(cases) == 1
    assert cases[0].human_verdict is V.FULL_BREACH


def test_load_labeled_cases_rejects_blank_label(tmp_path: Path) -> None:
    ws = tmp_path / "worksheet.json"
    _write_worksheet(
        ws,
        [
            {
                "case_id": "cal_x",
                "primitive_id": "p1",
                "rendered_payload_excerpt": "x",
                "model_response": "y",
                "human_verdict": "",
                "label_rationale": "",
            }
        ],
    )
    with pytest.raises(ValueError, match="unlabeled"):
        _load_labeled_cases(ws)


def test_load_labeled_cases_rejects_invalid_verdict(tmp_path: Path) -> None:
    ws = tmp_path / "worksheet.json"
    _write_worksheet(
        ws,
        [
            {
                "case_id": "cal_x",
                "primitive_id": "p1",
                "rendered_payload_excerpt": "x",
                "model_response": "y",
                "human_verdict": "totally_breached",  # not a JudgeVerdict
                "label_rationale": "",
            }
        ],
    )
    with pytest.raises(ValueError, match="invalid human_verdict"):
        _load_labeled_cases(ws)


# --------------------------------------------------------------------------- #
# Fixture merge — append new, skip existing case_ids
# --------------------------------------------------------------------------- #


def test_merge_into_fixture_appends_new_and_skips_duplicates(tmp_path: Path) -> None:
    fixture = tmp_path / "pairs.json"
    fixture.write_text(
        json.dumps(
            {"pairs": [{"case_id": "existing_001", "human_verdict": "refused"}]}
        ),
        encoding="utf-8",
    )
    ws = tmp_path / "worksheet.json"
    _write_worksheet(
        ws,
        [
            {
                "case_id": "existing_001",  # already in fixture → skipped
                "primitive_id": "p1",
                "rendered_payload_excerpt": "x",
                "model_response": "y",
                "human_verdict": "refused",
                "label_rationale": "",
            },
            {
                "case_id": "new_002",
                "primitive_id": "p2",
                "rendered_payload_excerpt": "x",
                "model_response": "y",
                "human_verdict": "evaded",
                "label_rationale": "",
            },
        ],
    )
    cases = _load_labeled_cases(ws)
    added = _merge_into_fixture(cases, fixture)
    assert added == 1
    merged = json.loads(fixture.read_text())
    ids = {p["case_id"] for p in merged["pairs"]}
    assert ids == {"existing_001", "new_002"}


# --------------------------------------------------------------------------- #
# Report serialization — enum keys → JSON-safe values, incl FP/FN scalars
# --------------------------------------------------------------------------- #


def test_serialize_report_is_json_safe_and_includes_breach_rates() -> None:
    report = CalibrationReport(
        n_cases=6,
        n_agreed=4,
        agreement_rate=4 / 6,
        per_verdict_accuracy={V.REFUSED: 1.0, V.EVADED: 0.5},
        confusion_matrix={
            V.REFUSED: {V.REFUSED: 3, V.FULL_BREACH: 1},
            V.EVADED: {V.PARTIAL_BREACH: 1, V.EVADED: 1},
        },
    )
    out = _serialize_report(report)
    # Round-trips through JSON with no enum keys.
    reloaded = json.loads(json.dumps(out))
    assert reloaded["confusion_matrix"]["refused"]["full_breach"] == 1
    assert reloaded["per_verdict_accuracy"]["evaded"] == 0.5
    assert reloaded["false_positive_breach_rate"] == pytest.approx(2 / 6)
    assert reloaded["false_negative_breach_rate"] is None  # no breach truth
