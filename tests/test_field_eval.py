"""Field-level extraction agreement scorer (Q17) — deterministic, $0.

Exercises `rogue.extract.field_eval` with the golden fixtures as a synthetic
"perfect extractor" plus controlled perturbations, so the harness is proven to
produce correct per-field numbers without any live model call.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rogue.extract.field_eval import (
    aggregate,
    grounding_score,
    score_fields,
)
from rogue.schemas import AttackFamily, AttackPrimitive

FIXTURES = Path(__file__).parent / "fixtures"


def _golden(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _prim(golden: dict) -> AttackPrimitive:
    return AttackPrimitive.model_validate(
        {k: v for k, v in golden.items() if k != "is_attack"}
    )


def test_perfect_extractor_scores_structural_agreement_1() -> None:
    g = _golden("01_multilingual_african_languages.json")
    src = (FIXTURES / "multilingual_paper.html").read_text()
    s = score_fields(_prim(g), g, source_text=src, doc="m")
    agg = aggregate([s])
    assert agg["recall"] == 1.0
    # Every structural field agrees with itself.
    assert agg["structural_macro_field_agreement"] == 1.0
    fm = {f.name: f.score for f in s.fields}
    assert fm["family"] == 1.0
    assert fm["vector"] == 1.0
    assert fm["payload_slots"] == 1.0


def test_wrong_family_scores_zero_on_that_field() -> None:
    g = _golden("02_copirate_365_cve_2026_24299.json")
    prim = _prim(g)
    # Perturb the family to a different valid enum value.
    wrong = prim.model_copy(update={"family": AttackFamily.POLICY_ROLEPLAY})
    s = score_fields(wrong, g, source_text="", doc="c")
    fm = {f.name: f.score for f in s.fields}
    assert fm["family"] == 0.0
    # vector untouched -> still agrees
    assert fm["vector"] == 1.0


def test_abstention_scores_recall_zero_no_fields() -> None:
    g = _golden("01_multilingual_african_languages.json")
    s = score_fields(None, g, doc="m")
    assert s.predicted_attack is False
    assert s.fields == []
    agg = aggregate([s])
    assert agg["recall"] == 0.0
    # No fired docs -> conditional agreement is None (not a spurious 1.0).
    assert agg["structural_macro_field_agreement"] is None


def test_grounding_reflects_copied_vs_reconstructed() -> None:
    # A payload copied verbatim from source grounds ~1.0; an invented one ~0.
    src = "the quick brown fox jumps over the lazy sleeping watchdog today"
    assert grounding_score("quick brown sleeping watchdog", src) == 1.0
    assert grounding_score("zzzz qqqq wwww vvvv", src) == 0.0
    # Empty field grounds 1.0 (nothing to fabricate).
    assert grounding_score("", src) == 1.0
    # Slot placeholders are stripped before grounding.
    assert grounding_score("{slot_a} quick {slot_b}", src) == 1.0


def test_set_field_partial_f1() -> None:
    g = _golden("01_multilingual_african_languages.json")
    prim = _prim(g)
    # secondary_families in golden 01 = [multi_turn_gradient, policy_roleplay].
    # Drop one -> recall 0.5, precision 1.0 -> F1 = 0.667.
    dropped = prim.model_copy(
        update={"secondary_families": [AttackFamily.MULTI_TURN_GRADIENT]}
    )
    s = score_fields(dropped, g, source_text="", doc="m")
    fm = {f.name: f.score for f in s.fields}
    assert fm["secondary_families"] == pytest.approx(2 / 3, abs=1e-3)
