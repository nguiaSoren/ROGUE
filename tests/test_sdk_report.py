"""Report objects — ``ScanReport`` / ``Finding`` / ``ValidationResult`` / ``BenchmarkReport``.

Pure data objects: no network, no DB. Tests pin the exact ``summary()`` text, the dict/JSON
round-trips, HTML rendering, ordering, and the derived properties.

Run from project root::

    uv run pytest tests/test_sdk_report.py -v
"""

from __future__ import annotations

import json

from rogue import BenchmarkReport, Finding, ScanReport, ValidationResult


def _finding(*, family="dan_persona", technique="DAN / Persona Jailbreak", severity="high", n_breach=2, rate=0.5, title="t"):
    return Finding(
        family=family,
        technique=technique,
        vector="single_turn",
        severity=severity,
        title=title,
        success_rate=rate,
        n_trials=4,
        n_breach=n_breach,
        example_attack="do the thing",
        example_response="okay here",
    )


def _report_with_breach():
    return ScanReport(
        target="https://api.acme.com/v1",
        n_tests=3,
        n_breaches=1,
        cost_usd=1.2345,
        findings=[
            _finding(technique="DAN / Persona Jailbreak", severity="high", n_breach=2, rate=0.5),
            _finding(technique="Crescendo", severity="critical", n_breach=0, rate=0.0),
            _finding(technique="Role Hijack", severity="low", n_breach=0, rate=0.0),
        ],
    )


# --- summary() exact format -------------------------------------------------------------------


def test_summary_exact_labeled_format():
    report = _report_with_breach()
    lines = report.summary().split("\n")
    assert lines == [
        "Target:",
        "  https://api.acme.com/v1",
        "Tests:",
        "  3",
        "Breaches:",
        "  1",
        "Rate:",
        "  33%",
        "Top Attack:",
        "  DAN / Persona Jailbreak",
        "Cost:",
        "  $1.23",
    ]


def test_summary_none_breached_shows_placeholder():
    report = ScanReport(
        target="t",
        n_tests=2,
        n_breaches=0,
        cost_usd=0.0,
        findings=[_finding(n_breach=0, rate=0.0), _finding(n_breach=0, rate=0.0)],
    )
    assert report.top_attack is None
    lines = report.summary().split("\n")
    # The "Top Attack:" label is followed by the placeholder value line.
    idx = lines.index("Top Attack:")
    assert lines[idx + 1] == "  — (none breached)"


# --- dict / json round-trip -------------------------------------------------------------------


def test_to_dict_and_to_json_roundtrip(tmp_path):
    report = _report_with_breach()
    d = report.to_dict()
    assert d["target"] == "https://api.acme.com/v1"
    assert d["n_tests"] == 3
    assert d["n_breaches"] == 1
    assert d["top_attack"] == "DAN / Persona Jailbreak"
    assert len(d["findings"]) == 3

    path = tmp_path / "report.json"
    text = report.to_json(path)
    assert json.loads(text) == d
    assert json.loads(path.read_text()) == d


# --- html -------------------------------------------------------------------------------------


def test_to_html_contains_target_and_html_tag(tmp_path):
    report = _report_with_breach()
    out = report.to_html()
    assert "<html" in out
    assert "https://api.acme.com/v1" in out

    path = tmp_path / "report.html"
    report.to_html(path)
    assert "<html" in path.read_text()


# --- ordering / props -------------------------------------------------------------------------


def test_top_findings_orders_by_severity_then_rate():
    report = ScanReport(
        target="t",
        n_tests=3,
        n_breaches=2,
        cost_usd=0.0,
        findings=[
            _finding(technique="low-but-high-rate", severity="low", rate=0.9, n_breach=4),
            _finding(technique="critical", severity="critical", rate=0.1, n_breach=1),
            _finding(technique="medium", severity="medium", rate=0.5, n_breach=2),
        ],
    )
    top = report.top_findings(3)
    assert [f.technique for f in top] == ["critical", "medium", "low-but-high-rate"]


def test_breached_findings_filters():
    report = _report_with_breach()
    breached = report.breached_findings()
    assert len(breached) == 1
    assert breached[0].breached is True


def test_finding_success_pct_and_breached():
    f = _finding(rate=0.5, n_breach=2)
    assert f.success_pct == "50%"
    assert f.breached is True
    clean = _finding(rate=0.0, n_breach=0)
    assert clean.breached is False


def test_scan_report_breach_rate_and_pct():
    report = _report_with_breach()
    assert report.breach_rate == 1 / 3
    assert report.breach_pct == "33%"


# --- ValidationResult -------------------------------------------------------------------------


def test_validation_result_ok_and_summary():
    ok = ValidationResult(
        target="https://x/v1",
        reachable=True,
        authenticated=True,
        model_responds=True,
        supports_image=True,
        supports_audio=False,
    )
    assert ok.ok is True
    s = ok.summary()
    assert "https://x/v1" in s
    assert "Ready to scan" in s

    not_ok = ValidationResult(
        target="https://x/v1",
        reachable=True,
        authenticated=False,
        model_responds=False,
        supports_image=False,
        supports_audio=False,
        error="401 unauthorized",
    )
    assert not_ok.ok is False
    assert "401 unauthorized" in not_ok.summary()
    assert not_ok.to_dict()["authenticated"] is False
    assert json.loads(not_ok.to_json())["error"] == "401 unauthorized"


# --- BenchmarkReport --------------------------------------------------------------------------


def test_benchmark_report_asr_and_cost_per_success():
    report = BenchmarkReport(
        dataset="advbench_100",
        target="https://x/v1",
        n_goals=20,
        n_success=5,
        cost_usd=2.0,
        winner_rank=3,
    )
    assert report.asr == 0.25
    assert report.cost_per_success == 2.0 / 5
    s = report.summary()
    assert "advbench_100" in s
    assert "25%" in s
    assert "#3" in s
    assert report.to_dict()["asr"] == 0.25


def test_benchmark_report_zero_success_cost_per_success_none():
    report = BenchmarkReport(
        dataset="jbb",
        target="t",
        n_goals=10,
        n_success=0,
        cost_usd=1.0,
    )
    assert report.asr == 0.0
    assert report.cost_per_success is None
    assert "—" in report.summary()
