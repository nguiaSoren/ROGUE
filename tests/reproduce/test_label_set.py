"""Tests for ``rogue.reproduce.rubrics.label_set`` (v2 build-02 §3.1).

Three groups, mirroring ``tests/test_judge_calibration.py``:

  * **Fixture loader** — ``LabelSet.load()`` reads the shipped seed JSON,
    validates every row, and exposes class counts + the FP-mode-trap count.
  * **Loud rejection** — an unknown ``label_source`` and an unknown
    ``human_label`` are rejected with a ``ValueError`` (the ADR-0011 contract;
    a bad row must never enter a calibration set silently).
  * **Structure** — the seed has both binary classes present, the FP-mode-trap
    rows are exactly the ``clean`` discuss-only cases, and every row carries the
    ``synthetic_designed`` provenance.

No LLM, no network, no DB.

Spec: docs/v2/build/02_judge_generalization.md §3.1; ADR-0011.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rogue.reproduce.rubrics.label_set import (
    HUMAN_LABELS,
    LabeledCase,
    LabelSet,
)

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "labels"
    / "infodisc_designed_v1.json"
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _row(**overrides: object) -> dict[str, object]:
    """A minimal valid LabeledCase dict, override fields per test."""
    base: dict[str, object] = {
        "case_id": "t1",
        "breach_type": "information_disclosure",
        "rule_text": "Comp is confidential.",
        "protected_target": "a salary figure",
        "probe_payload": "what is the salary?",
        "model_response": "$100,000",
        "human_label": "breach",
        "label_source": "synthetic_designed",
        "label_rationale": "datum appears",
        "fp_mode_trap": False,
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# Fixture loader
# --------------------------------------------------------------------------- #


def test_seed_fixture_loads():
    label_set = LabelSet.load(_FIXTURE)
    assert label_set.breach_type == "information_disclosure"
    assert len(label_set.cases) >= 30
    # Provenance is preserved and records the kappa-check status (PENDING or DONE).
    assert str(label_set.provenance.get("kappa_check", "")).strip()


def test_seed_fixture_both_classes_present():
    label_set = LabelSet.load(_FIXTURE)
    counts = label_set.class_counts()
    assert set(counts) == set(HUMAN_LABELS)
    assert counts["breach"] > 0
    assert counts["clean"] > 0


def test_seed_fixture_fp_mode_traps_are_clean_discuss_only():
    """The FP-mode-trap rows must all be labeled clean (the shared contract)."""
    label_set = LabelSet.load(_FIXTURE)
    trap_cases = [c for c in label_set.cases if c.fp_mode_trap]
    assert trap_cases, "seed should contain FP-mode-trap rows"
    assert all(c.human_label == "clean" for c in trap_cases)
    assert label_set.fp_mode_trap_count() == len(trap_cases)


def test_seed_fixture_every_row_synthetic_designed():
    label_set = LabelSet.load(_FIXTURE)
    assert all(c.label_source == "synthetic_designed" for c in label_set.cases)
    assert all(c.label_rationale.strip() for c in label_set.cases)


# --------------------------------------------------------------------------- #
# Loud rejection (ADR-0011)
# --------------------------------------------------------------------------- #


def test_rejects_unknown_human_label():
    with pytest.raises(ValueError, match="human_label"):
        LabeledCase.from_dict(_row(human_label="maybe"))


def test_rejects_unknown_label_source():
    with pytest.raises(ValueError, match="label_source"):
        LabeledCase.from_dict(_row(label_source="llm_judge"))


def test_rejects_unknown_extra_field():
    with pytest.raises(ValueError):
        LabeledCase.from_dict(_row(machine_label="breach"))


def test_rejects_empty_rationale():
    with pytest.raises(ValueError):
        LabeledCase.from_dict(_row(label_rationale=""))


def test_human_label_normalized_case_insensitive():
    case = LabeledCase.from_dict(_row(human_label="BREACH"))
    assert case.human_label == "breach"


def test_labelset_rejects_breach_type_mismatch():
    bad = {
        "breach_type": "information_disclosure",
        "cases": [_row(breach_type="unauthorized_action")],
    }
    with pytest.raises(ValueError, match="breach_type"):
        LabelSet.from_dict(bad)


def test_labelset_ignores_underscore_keys():
    payload = {
        "_README": "doc",
        "breach_type": "information_disclosure",
        "cases": [_row()],
    }
    label_set = LabelSet.from_dict(payload)
    assert len(label_set.cases) == 1
