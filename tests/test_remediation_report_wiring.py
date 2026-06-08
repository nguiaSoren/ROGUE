"""Surface 1b §8 (Surface 1b → report) — the scan report routes a per-finding mitigation through a
PROVEN `RemediationResult` when one is supplied, and is byte-identical to the generic fallback when
none is. Pure render-level wiring: no DB, no request-path.
"""

from __future__ import annotations

from rogue.remediation import (
    MitigationCandidate,
    MitigationType,
    OverBlockCheck,
    RemediationResult,
)
from rogue.report import (
    Finding,
    ScanReport,
    remediation_for,
    remediation_section,
)


def _finding(family: str = "tool_use_hijack") -> Finding:
    return Finding(
        family=family,
        technique="Tool-Use Hijack",
        vector="tool_output",
        severity="high",
        title="Refund tool callable without authorization",
        success_rate=0.8,
        n_trials=10,
        n_breach=8,
    )


def _report(family: str = "tool_use_hijack") -> ScanReport:
    return ScanReport(
        target="openai/gpt-4o-mini",
        n_tests=10,
        n_breaches=8,
        cost_usd=0.42,
        findings=[_finding(family)],
    )


def _proven(family_ref: str = "tool_use_hijack") -> RemediationResult:
    return RemediationResult(
        candidate=MitigationCandidate(
            candidate_id="c1",
            breach_ref="R2",
            mitigation_type=MitigationType.TOOL_PERMISSION_SCOPE,
            artifact="Cap the refund tool at $500 without a manager approval token.",
            generated_by="anthropic/claude-sonnet-4-6@gen-v1",
        ),
        pre_breach_rate=0.8,
        post_breach_rate=0.0,
        post_breach_ci=(0.0, 0.08),
        over_block=OverBlockCheck(
            legitimate_set_ref="legit/R2",
            n_legit=20,
            n_false_block=0,
            over_block_rate=0.0,
            ci_low=0.0,
            ci_high=0.09,
        ),
        accepted=True,
        verified_by="rescan",
    )


# --- remediation_section, directly ---------------------------------------------------------------


def test_section_without_result_equals_generic_fallback() -> None:
    """With no RemediationResult the section is byte-identical to the generic `remediation_for`."""
    for family in ("tool_use_hijack", "__unknown_family__"):
        assert remediation_section(family) == remediation_for(family)
        assert remediation_section(family, None) == remediation_for(family)


def test_section_with_proven_result_renders_evidence_not_generic() -> None:
    text = remediation_section("tool_use_hijack", _proven())
    assert text != remediation_for("tool_use_hijack")
    # The re-test numbers + the honest framing.
    assert "breach 0% (was 80%)" in text
    assert "over-block 0%" in text
    assert "Client deploys; ROGUE re-verifies." in text


def test_section_out_of_band_does_not_fake_a_delta() -> None:
    r = RemediationResult(
        candidate=MitigationCandidate(
            candidate_id="a1",
            breach_ref="R3",
            mitigation_type=MitigationType.ARCHITECTURE_RECOMMENDATION,
            artifact="This agent shouldn't issue legal opinions autonomously.",
            generated_by="remediation.loop@arch-fallback",
        ),
        pre_breach_rate=0.5,
        post_breach_rate=0.5,
        accepted=True,
        verified_by="by_construction_out_of_band",
    )
    text = remediation_section("tool_use_hijack", r)
    assert "Verified by construction / out-of-band" in text
    assert "(was" not in text  # never fakes a re-scan delta
    assert "Client deploys; ROGUE re-verifies." in text


# --- ScanReport.to_dict wiring -------------------------------------------------------------------


def test_to_dict_default_none_is_byte_identical() -> None:
    """The default-None path must be byte-identical to today (no mitigations supplied)."""
    report = _report()
    assert report.to_dict() == report.to_dict(mitigations=None)
    # And the finding's remediation is exactly the generic per-family fallback.
    d = report.to_dict()["findings"][0]
    assert d["remediation"] == remediation_for("tool_use_hijack")


def test_to_dict_routes_proven_result_for_matching_family() -> None:
    report = _report()
    out = report.to_dict(mitigations={"tool_use_hijack": _proven()})
    rem = out["findings"][0]["remediation"]
    # PROVEN evidence, not the generic string.
    assert rem != remediation_for("tool_use_hijack")
    assert "breach 0% (was 80%)" in rem
    assert "Client deploys; ROGUE re-verifies." in rem


def test_to_dict_unmatched_family_falls_back() -> None:
    """A mitigation keyed by a different family leaves this finding on the generic fallback."""
    report = _report()
    out = report.to_dict(mitigations={"some_other_family": _proven()})
    assert out["findings"][0]["remediation"] == remediation_for("tool_use_hijack")


# --- ScanReport.to_html wiring -------------------------------------------------------------------


def test_to_html_default_none_is_byte_identical() -> None:
    report = _report()
    assert report.to_html() == report.to_html(mitigations=None)


def test_to_html_routes_proven_result() -> None:
    report = _report()
    html = report.to_html(mitigations={"tool_use_hijack": _proven()})
    assert "breach 0% (was 80%)" in html
    assert "Client deploys; ROGUE re-verifies." in html
    # The generic fallback string for this family must not also be present.
    assert remediation_for("tool_use_hijack") not in html
