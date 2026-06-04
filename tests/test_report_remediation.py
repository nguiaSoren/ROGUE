"""Customer reports must (a) tell the reader *what to do* about each finding and (b) explain the
0–100 risk number. `remediation_for` maps every `AttackFamily` to a concrete, vendor-neutral
mitigation (generic fallback otherwise); the renderers surface it per-finding and surface the
score-methodology caption next to the headline number.
"""

from __future__ import annotations

import pytest

from rogue.report import (
    SCORE_METHODOLOGY,
    Finding,
    ScanReport,
    remediation_for,
)
from rogue.schemas.attack_primitive import AttackFamily


@pytest.mark.parametrize("family", [f.value for f in AttackFamily])
def test_remediation_for_covers_every_family(family: str) -> None:
    text = remediation_for(family)
    assert isinstance(text, str)
    assert text.strip()
    # A real per-family one-liner, not the generic fallback.
    assert text != remediation_for("__definitely_not_a_family__")


def test_remediation_for_unknown_is_generic_nonempty() -> None:
    text = remediation_for("__definitely_not_a_family__")
    assert isinstance(text, str)
    assert text.strip()


def _report() -> ScanReport:
    return ScanReport(
        target="openai/gpt-4o-mini",
        n_tests=5,
        n_breaches=2,
        cost_usd=0.05,
        findings=[
            Finding(
                family="dan_persona",
                technique="DAN / Persona Jailbreak",
                vector="user_turn",
                severity="critical",
                title="DAN persona overrides safety policy",
                success_rate=1.0,
                n_trials=5,
                n_breach=5,
            ),
            Finding(
                family="system_prompt_leak",
                technique="System-Prompt Leak",
                vector="user_turn",
                severity="high",
                title="System prompt echoed verbatim",
                success_rate=0.6,
                n_trials=5,
                n_breach=3,
            ),
        ],
    )


def test_to_dict_findings_carry_remediation() -> None:
    d = _report().to_dict()
    for finding in d["findings"]:
        assert "remediation" in finding
        assert finding["remediation"].strip()
    # Per-family: the two findings get distinct remediations.
    rems = [f["remediation"] for f in d["findings"]]
    assert rems[0] == remediation_for("dan_persona")
    assert rems[1] == remediation_for("system_prompt_leak")
    assert rems[0] != rems[1]


def test_to_html_has_remediation_line_and_methodology_caption() -> None:
    page = _report().to_html()
    assert "Remediation:" in page
    assert remediation_for("dan_persona") in page
    # Score-methodology caption present (use a stable fragment, robust to HTML-escaping the en dash).
    assert "weighted by severity" in page
    assert "≥75 critical" in page


def test_score_methodology_matches_bands() -> None:
    # The caption must name the actual scoring bands (scoring.py: 75 / 50 / 25).
    assert "≥75 critical" in SCORE_METHODOLOGY
    assert "≥50 high" in SCORE_METHODOLOGY
    assert "≥25 medium" in SCORE_METHODOLOGY
