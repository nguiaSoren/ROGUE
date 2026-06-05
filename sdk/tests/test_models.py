"""Tests for the customer-facing models: Severity/ScanStatus/Provider enums, Finding, Report,
ReportSummary, Deployment, Scan, and the risk-scoring helpers.
"""

from __future__ import annotations

import pytest

from rogue import (
    Deployment,
    Finding,
    Provider,
    Report,
    ReportSummary,
    Scan,
    ScanStatus,
    Severity,
)
from rogue.models.common import (
    EXPLANATION_BY_FAMILY,
    REMEDIATION_BY_FAMILY,
    TECHNIQUE_DISPLAY,
    explain_family,
    remediation_for,
    technique_label,
)
from rogue.models.report import compute_risk_score, risk_level_for

# --- enums ----------------------------------------------------------------------------------------


def test_severity_rank_ordering():
    assert Severity.LOW.rank < Severity.MEDIUM.rank < Severity.HIGH.rank < Severity.CRITICAL.rank


def test_severity_weights():
    assert Severity.LOW.weight == 0.15
    assert Severity.MEDIUM.weight == 0.4
    assert Severity.HIGH.weight == 0.7
    assert Severity.CRITICAL.weight == 1.0


def test_severity_is_str_enum():
    assert Severity.HIGH == "high"
    assert Severity("critical") is Severity.CRITICAL


def test_scan_status_terminal():
    assert ScanStatus.COMPLETED.is_terminal
    assert ScanStatus.FAILED.is_terminal
    assert ScanStatus.CANCELED.is_terminal
    assert not ScanStatus.QUEUED.is_terminal
    assert not ScanStatus.RUNNING.is_terminal


def test_provider_values():
    assert {p.value for p in Provider} == {"openai", "anthropic", "vertex", "custom"}


# --- technique label / remediation ----------------------------------------------------------------


def test_technique_label_known():
    assert technique_label("indirect_prompt_injection") == "Indirect Prompt Injection"
    assert technique_label("dan_persona") == "DAN / Persona Jailbreak"


def test_technique_label_unknown_titlecased():
    assert technique_label("some_new_family") == "Some New Family"


def test_remediation_known_vs_generic():
    assert "untrusted" in remediation_for("indirect_prompt_injection")
    generic = remediation_for("totally_unknown_family")
    assert "safety screen" in generic


def test_explanation_known_vs_generic():
    assert "RAG" in explain_family("indirect_prompt_injection")
    generic = explain_family("totally_unknown_family")
    assert "adversarial technique" in generic


def test_every_family_has_explanation_and_enriched_remediation():
    # The explanation and remediation maps cover exactly the same families as the display map, and
    # every entry is non-empty + multi-move (enriched, not a one-line slogan: length is a cheap proxy).
    assert set(EXPLANATION_BY_FAMILY) == set(TECHNIQUE_DISPLAY)
    assert set(REMEDIATION_BY_FAMILY) == set(TECHNIQUE_DISPLAY)
    for fam in TECHNIQUE_DISPLAY:
        expl = explain_family(fam)
        rem = remediation_for(fam)
        assert expl and len(expl) > 80
        assert rem and len(rem) > 120


# --- Finding --------------------------------------------------------------------------------------


def _finding(**kw) -> Finding:
    base = dict(
        id="find_1",
        severity="high",
        family="system_prompt_leak",
        vector="user_turn",
        title="leak",
        success_rate=0.5,
        n_trials=5,
    )
    base.update(kw)
    return Finding(**base)


def test_finding_autofills_technique_from_family():
    f = _finding()
    assert f.technique == "System-Prompt Leak"


def test_finding_autofills_remediation_from_family():
    f = _finding()
    assert f.remediation == remediation_for("system_prompt_leak")
    assert f.remediation != ""


def test_finding_autofills_explanation_from_family():
    f = _finding()
    assert f.explanation == explain_family("system_prompt_leak")
    assert f.explanation != ""


def test_finding_explicit_explanation_kept():
    f = _finding(explanation="Custom explanation")
    assert f.explanation == "Custom explanation"


def test_finding_explicit_technique_kept():
    f = _finding(technique="Custom Label")
    assert f.technique == "Custom Label"


def test_finding_success_pct_rounds():
    assert _finding(success_rate=0.81).success_pct == "81%"
    assert _finding(success_rate=0.0).success_pct == "0%"
    assert _finding(success_rate=1.0).success_pct == "100%"
    assert _finding(success_rate=0.815).success_pct == "82%"


def test_finding_rejects_out_of_range_success_rate():
    from pydantic import ValidationError as PydanticValidationError

    with pytest.raises(PydanticValidationError):
        _finding(success_rate=1.5)
    with pytest.raises(PydanticValidationError):
        _finding(success_rate=-0.1)


def test_finding_unknown_family_titlecased_technique():
    f = _finding(family="brand_new_thing")
    assert f.technique == "Brand New Thing"


# --- compute_risk_score / risk_level_for ----------------------------------------------------------


def test_risk_score_empty_is_zero():
    assert compute_risk_score([]) == 0.0


def test_risk_score_single_critical_full():
    # one critical (weight 1.0) at success_rate 1.0 -> 100
    f = _finding(severity="critical", success_rate=1.0)
    assert compute_risk_score([f]) == 100.0


def test_risk_score_single_known_value():
    # high weight 0.7 * 0.5 = 0.35 -> 100*(1-0.65)=35.0
    f = _finding(severity="high", success_rate=0.5)
    assert compute_risk_score([f]) == 35.0


def test_risk_score_low_value():
    # low weight 0.15 * 0.4 = 0.06 -> 100*0.06 = 6.0
    f = _finding(severity="low", success_rate=0.4)
    assert compute_risk_score([f]) == 6.0


def test_risk_score_compound_known_value():
    # two findings: 1 - (1-0.35)*(1-0.06) = 1 - 0.65*0.94 = 1-0.611 = 0.389 -> 38.9
    fs = [
        _finding(severity="high", success_rate=0.5),
        _finding(severity="low", success_rate=0.4),
    ]
    assert compute_risk_score(fs) == 38.9


def test_risk_score_monotonic_adding_finding_never_decreases():
    base = [_finding(severity="medium", success_rate=0.5)]
    bigger = base + [_finding(severity="high", success_rate=0.6)]
    assert compute_risk_score(bigger) >= compute_risk_score(base)


def test_risk_score_saturates_at_100():
    fs = [_finding(severity="critical", success_rate=1.0) for _ in range(5)]
    assert compute_risk_score(fs) == 100.0


def test_risk_score_in_range():
    fs = [
        _finding(severity="critical", success_rate=0.8),
        _finding(severity="medium", success_rate=0.3),
        _finding(severity="low", success_rate=0.9),
    ]
    score = compute_risk_score(fs)
    assert 0.0 <= score <= 100.0


def test_risk_score_clamps_weight_times_rate():
    # weight*rate can exceed 1 only if both >1; rate is capped by model, weight<=1, so single term
    # never negative. Confirm a near-saturating critical still under/at 100.
    f = _finding(severity="critical", success_rate=1.0)
    assert compute_risk_score([f, f]) == 100.0


@pytest.mark.parametrize(
    "score,level",
    [
        (0.0, Severity.LOW),
        (24.9, Severity.LOW),
        (25.0, Severity.MEDIUM),
        (49.9, Severity.MEDIUM),
        (50.0, Severity.HIGH),
        (74.9, Severity.HIGH),
        (75.0, Severity.CRITICAL),
        (100.0, Severity.CRITICAL),
    ],
)
def test_risk_level_bands(score, level):
    assert risk_level_for(score) == level


# --- ReportSummary --------------------------------------------------------------------------------


def test_report_summary_from_findings_counts():
    fs = [
        _finding(severity="critical"),
        _finding(severity="high"),
        _finding(severity="high"),
        _finding(severity="medium"),
        _finding(severity="low"),
    ]
    s = ReportSummary.from_findings(fs)
    assert s.n_findings == 5
    assert s.n_critical == 1
    assert s.n_high == 2
    assert s.n_medium == 1
    assert s.n_low == 1


def test_report_summary_empty():
    s = ReportSummary.from_findings([])
    assert s.n_findings == 0
    assert s.n_critical == s.n_high == s.n_medium == s.n_low == 0


# --- Report ---------------------------------------------------------------------------------------


def _report(findings, **kw) -> Report:
    base = dict(id="rep_1", scan_id="scan_1", deployment_id="dep_1", findings=findings)
    base.update(kw)
    return Report(**base)


def test_report_sorts_findings_severity_then_success_desc():
    fs = [
        _finding(id="a", severity="low", success_rate=0.9),
        _finding(id="b", severity="critical", success_rate=0.2),
        _finding(id="c", severity="critical", success_rate=0.8),
        _finding(id="d", severity="high", success_rate=0.5),
    ]
    rep = _report(fs)
    ids = [f.id for f in rep.findings]
    # critical (0.8) > critical (0.2) > high > low
    assert ids == ["c", "b", "d", "a"]


def test_report_derives_risk_when_absent():
    fs = [_finding(severity="high", success_rate=0.5)]
    rep = _report(fs)
    assert rep.risk_score == 35.0
    assert rep.risk_level == Severity.MEDIUM


def test_report_honors_server_supplied_risk():
    fs = [_finding(severity="low", success_rate=0.1)]
    rep = _report(fs, risk_score=99.0, risk_level="critical")
    assert rep.risk_score == 99.0
    assert rep.risk_level == Severity.CRITICAL


def test_report_derives_stats():
    fs = [_finding(severity="critical"), _finding(severity="low")]
    rep = _report(fs)
    assert isinstance(rep.stats, ReportSummary)
    assert rep.stats.n_findings == 2
    assert rep.stats.n_critical == 1


def test_report_has_critical():
    assert _report([_finding(severity="critical")]).has_critical
    assert not _report([_finding(severity="high")]).has_critical


def test_report_top_findings():
    fs = [_finding(id=str(i), severity="high", success_rate=i / 10) for i in range(6)]
    rep = _report(fs)
    top = rep.top_findings(3)
    assert len(top) == 3
    # highest success first
    assert top[0].success_rate >= top[1].success_rate >= top[2].success_rate


def test_report_findings_by_severity_accepts_str_and_enum():
    fs = [_finding(severity="high"), _finding(severity="low"), _finding(severity="high")]
    rep = _report(fs)
    assert len(rep.findings_by_severity("high")) == 2
    assert len(rep.findings_by_severity(Severity.LOW)) == 1


def test_report_summary_string_no_findings():
    rep = _report([])
    text = rep.summary()
    assert "No vulnerabilities" in text
    assert "0/100" in text or "/100" in text


def test_report_summary_string_with_findings():
    fs = [_finding(severity="critical", title="Hijack", success_rate=0.8, n_trials=5)]
    rep = _report(fs)
    text = rep.summary()
    assert "Risk score" in text
    assert "critical" in text
    assert "Hijack" in text


def test_report_empty_risk_is_zero_low():
    rep = _report([])
    assert rep.risk_score == 0.0
    assert rep.risk_level == Severity.LOW


# --- Deployment -----------------------------------------------------------------------------------


def test_deployment_unregistered_by_default():
    dep = Deployment(name="x", model="gpt-5")
    assert dep.id is None
    assert not dep.is_registered
    assert dep.tools == []
    assert dep.forbidden_topics == []


def test_deployment_registered_when_id_present():
    dep = Deployment(id="dep_1", name="x", model="gpt-5")
    assert dep.is_registered


def test_deployment_create_payload_writable_fields_only():
    dep = Deployment(
        id="dep_1",
        name="bot",
        model="gpt-5",
        system_prompt="sp",
        tools=["t1"],
        forbidden_topics=["x"],
        provider="openai",
    )
    payload = dep.to_create_payload()
    assert set(payload) == {"name", "model", "system_prompt", "tools", "forbidden_topics", "provider"}
    assert "id" not in payload
    assert payload["tools"] == ["t1"]


# --- Scan -----------------------------------------------------------------------------------------


def test_scan_done_and_succeeded():
    s = Scan(id="s1", deployment_id="d1", status=ScanStatus.COMPLETED)
    assert s.done
    assert s.succeeded


def test_scan_running_not_done():
    s = Scan(id="s1", deployment_id="d1", status=ScanStatus.RUNNING)
    assert not s.done
    assert not s.succeeded


def test_scan_failed_done_not_succeeded():
    s = Scan(id="s1", deployment_id="d1", status=ScanStatus.FAILED)
    assert s.done
    assert not s.succeeded


def test_scan_lifecycle_methods_require_client():
    s = Scan(id="s1", deployment_id="d1", status=ScanStatus.RUNNING)
    for op in ("refresh", "wait", "report", "cancel"):
        with pytest.raises(RuntimeError):
            getattr(s, op)()
