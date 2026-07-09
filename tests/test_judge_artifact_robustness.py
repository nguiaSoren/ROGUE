"""Unit tests for the Q5 judge artifact-robustness probe.

Covers: the perturbation transforms preserve content (harm label holds); the probe's ΔFNR/ΔFPR +
induced-false-negative math against a controllable stub judge; the storytelling LLM seam; the
baseline_pred reuse; and the AxisAgreement.false_negative_rate property. Pure + offline.
"""

from __future__ import annotations

from rogue.reproduce.calibration.artifact_robustness import (
    APOLOGY_PREFIX_TEXT,
    BENIGN_BLOCK,
    DEFAULT_PERTURBATIONS,
    DETERMINISTIC_PERTURBATIONS,
    LabeledResponse,
    apology_prefix,
    append_long_benign,
    prepend_append_benign,
    probe_artifact_robustness,
    storytelling_restyle,
)
from rogue.reproduce.wildguard_eval import AxisAgreement


# --------------------------------------------------------------------------------------------------- #
# perturbations preserve the response content (so the human harm label still holds)
# --------------------------------------------------------------------------------------------------- #
def test_apology_prefix_prepends_and_preserves():
    out = apology_prefix("HARMFUL CONTENT")
    assert out.startswith(APOLOGY_PREFIX_TEXT)
    assert "HARMFUL CONTENT" in out


def test_append_and_prepend_benign_keep_content():
    assert "HARMFUL" in append_long_benign("HARMFUL") and BENIGN_BLOCK in append_long_benign("HARMFUL")
    pp = prepend_append_benign("HARMFUL")
    assert pp.count(BENIGN_BLOCK) == 2 and "HARMFUL" in pp


def test_storytelling_uses_restyle_fn_when_given():
    assert storytelling_restyle("X", restyle_fn=lambda s: f"RESTYLED::{s}") == "RESTYLED::X"
    # template fallback preserves content verbatim
    assert "X" in storytelling_restyle("X")


def test_deterministic_battery_excludes_llm_seam():
    names = {p.name for p in DETERMINISTIC_PERTURBATIONS}
    assert names == {"apology_prefix", "append_long_benign", "prepend_append_benign"}
    assert "storytelling_restyle" in {p.name for p in DEFAULT_PERTURBATIONS}


# --------------------------------------------------------------------------------------------------- #
# the probe math — a judge that is fooled ONLY by the apology artifact
# --------------------------------------------------------------------------------------------------- #
def _cases() -> list[LabeledResponse]:
    # 4 harmful, 2 clean.
    return [
        LabeledResponse(f"h{i}", "goal", "prompt", f"harmful body {i}", True) for i in range(4)
    ] + [
        LabeledResponse(f"s{i}", "goal", "prompt", f"safe body {i}", False) for i in range(2)
    ]


def test_probe_measures_induced_fn_from_apology_only():
    # grade_fn: breach iff the graded text does NOT contain the apology prefix (i.e. the apology
    # artifact fools it into "safe"); truthful otherwise. Baseline: all harmful caught, no clean flagged.
    def grade(case, text):
        if APOLOGY_PREFIX_TEXT in text:
            return False  # fooled into non-breach by the apology
        return case.human_is_harmful  # otherwise perfectly accurate

    rep = probe_artifact_robustness(_cases(), grade, judge_label="stub")
    assert rep.baseline.false_negative_rate == 0.0  # caught all 4 harmful at baseline

    apo = rep.perturbations["apology_prefix"]
    assert apo.n_baseline_caught == 4 and apo.n_induced_fn == 4  # all 4 flipped to "safe"
    assert apo.induced_fn_rate == 1.0
    assert apo.delta_fnr == 1.0  # FNR 0 → 1.0

    # the append/prepend benign attacks do NOT contain the apology prefix → judge unmoved
    for name in ("append_long_benign", "prepend_append_benign"):
        p = rep.perturbations[name]
        assert p.n_induced_fn == 0 and p.delta_fnr == 0.0

    assert rep.worst_delta_fnr == 1.0


def test_probe_baseline_pred_reuse_skips_baseline_grade():
    calls = {"n": 0}

    def grade(case, text):
        calls["n"] += 1
        return case.human_is_harmful

    cases = _cases()
    # Supply baseline preds → the probe must NOT grade the unperturbed slice again.
    probe_artifact_robustness(
        cases, grade, baseline_pred=[c.human_is_harmful for c in cases],
        perturbations=DETERMINISTIC_PERTURBATIONS,
    )
    # 3 perturbations × 6 cases = 18 grades, and ZERO baseline grades (reused).
    assert calls["n"] == 18


def test_probe_empty_cases_is_safe():
    rep = probe_artifact_robustness([], lambda c, t: False)
    assert rep.n_items == 0 and rep.perturbations == {}


def test_storytelling_flag_marks_template_vs_llm():
    rep_template = probe_artifact_robustness(_cases(), lambda c, t: True)
    assert rep_template.perturbations["storytelling_restyle"].used_llm_restyle is False
    rep_llm = probe_artifact_robustness(_cases(), lambda c, t: True, restyle_fn=lambda s: s)
    assert rep_llm.perturbations["storytelling_restyle"].used_llm_restyle is True


# --------------------------------------------------------------------------------------------------- #
# the reused 2×2 property
# --------------------------------------------------------------------------------------------------- #
def test_axis_agreement_false_negative_rate():
    a = AxisAgreement(axis="breach", tp=6, fp=1, fn=4, tn=9)
    assert a.false_negative_rate == 0.4  # 4 / (4 + 6)
    assert a.false_positive_rate == 0.1  # 1 / (1 + 9)
    # no positive support → undefined, never a fabricated 0.0
    assert AxisAgreement(axis="breach", tp=0, fp=1, fn=0, tn=9).false_negative_rate is None
