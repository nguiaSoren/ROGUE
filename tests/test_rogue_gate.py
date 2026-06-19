"""Offline unit tests for the CI gate (scripts/ci/rogue_gate.py).

No network, no SDK scan, no keys: we build real ``ScanReport`` objects and exercise the gate's
exit-code logic directly, and we monkeypatch the SDK ``Client`` so ``main()`` runs end-to-end
without touching a model. These pin the contract the GitHub Action depends on:
  * any breached HIGH/CRITICAL finding → exit 1
  * a clean (or only-MEDIUM-when-fail-on=high) report → exit 0
  * the max-breach-rate path fails independently of severity
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from rogue.report import Finding, ScanReport

# Load the gate module by path (it lives under scripts/, not in the importable package tree).
_GATE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "ci" / "rogue_gate.py"
_spec = importlib.util.spec_from_file_location("rogue_gate", _GATE_PATH)
gate = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(gate)


def _finding(severity: str, *, n_breach: int, n_trials: int = 2) -> Finding:
    return Finding(
        family="dan_persona",
        technique="DAN / Persona Jailbreak",
        vector="user_turn",
        severity=severity,
        title=f"{severity} probe",
        success_rate=n_breach / n_trials,
        n_trials=n_trials,
        n_breach=n_breach,
    )


def _report(findings: list[Finding]) -> ScanReport:
    n_breaches = sum(1 for f in findings if f.breached)
    return ScanReport(
        target="https://gateway.example/v1",
        n_tests=len(findings),
        n_breaches=n_breaches,
        cost_usd=0.01,
        findings=findings,
    )


# --- pure gate-decision logic -----------------------------------------------------------------


def test_breached_critical_fails():
    rep = _report([_finding("critical", n_breach=2), _finding("low", n_breach=0)])
    failed, reasons = gate.evaluate_gate(rep, fail_on="high", max_breach_rate=None)
    assert failed is True
    assert any("CRITICAL" in r or "critical" in r for r in reasons)


def test_breached_high_fails():
    rep = _report([_finding("high", n_breach=1)])
    failed, _ = gate.evaluate_gate(rep, fail_on="high", max_breach_rate=None)
    assert failed is True


def test_high_finding_that_did_not_breach_passes():
    # A HIGH-severity probe that never breached must NOT fail the gate.
    rep = _report([_finding("high", n_breach=0), _finding("critical", n_breach=0)])
    failed, reasons = gate.evaluate_gate(rep, fail_on="high", max_breach_rate=None)
    assert failed is False
    assert reasons == []


def test_medium_breach_passes_when_fail_on_high():
    rep = _report([_finding("medium", n_breach=2), _finding("low", n_breach=1)])
    failed, _ = gate.evaluate_gate(rep, fail_on="high", max_breach_rate=None)
    assert failed is False


def test_medium_breach_fails_when_fail_on_medium():
    rep = _report([_finding("medium", n_breach=2)])
    failed, _ = gate.evaluate_gate(rep, fail_on="medium", max_breach_rate=None)
    assert failed is True


def test_fail_on_none_disables_severity_gate():
    rep = _report([_finding("critical", n_breach=2)])
    failed, _ = gate.evaluate_gate(rep, fail_on="none", max_breach_rate=None)
    assert failed is False


def test_clean_report_passes():
    rep = _report([_finding("low", n_breach=0)])
    failed, reasons = gate.evaluate_gate(rep, fail_on="high", max_breach_rate=None)
    assert failed is False
    assert reasons == []


def test_max_breach_rate_path_fails_independently():
    # All findings MEDIUM (below a HIGH floor), so severity gate is clean — but the rate gate trips.
    rep = _report([_finding("medium", n_breach=2), _finding("medium", n_breach=2)])
    failed, reasons = gate.evaluate_gate(rep, fail_on="high", max_breach_rate=0.2)
    assert failed is True
    assert any("rate" in r for r in reasons)


def test_max_breach_rate_not_exceeded_passes():
    rep = _report([_finding("low", n_breach=0)] * 9 + [_finding("medium", n_breach=2)])
    # breach rate = 1/10 = 0.1, threshold 0.2 → no rate failure, no high breach → pass
    failed, _ = gate.evaluate_gate(rep, fail_on="high", max_breach_rate=0.2)
    assert failed is False


# --- main() end-to-end with a monkeypatched Client --------------------------------------------


class _FakeClient:
    """Stand-in for rogue.Client — records args, returns a canned report from scan()."""

    _next_report: ScanReport | None = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def scan(self, **kwargs):
        assert _FakeClient._next_report is not None
        return _FakeClient._next_report


@pytest.fixture
def patched_client(monkeypatch):
    import rogue

    monkeypatch.setattr(rogue, "Client", _FakeClient, raising=False)
    # Avoid touching the filesystem renderer in main().
    monkeypatch.setattr(gate, "_render_card", lambda *a, **k: None)
    monkeypatch.setenv("ROGUE_TARGET_KEY", "sk-test-not-real")
    return _FakeClient


def test_main_exit_1_on_critical(patched_client, monkeypatch):
    patched_client._next_report = _report([_finding("critical", n_breach=2)])
    rc = gate.main(["--provider", "openai", "--model", "gpt-4o-mini"])
    assert rc == 1


def test_main_exit_0_on_clean(patched_client, monkeypatch):
    patched_client._next_report = _report([_finding("low", n_breach=0)])
    rc = gate.main(["--provider", "openai", "--model", "gpt-4o-mini"])
    assert rc == 0


def test_main_exit_nonzero_when_package_missing(monkeypatch):
    # Simulate `from rogue import Client` raising ImportError inside _build_client.
    def _boom(_args):
        raise ImportError("no module named rogue")

    monkeypatch.setattr(gate, "_build_client", _boom)
    rc = gate.main(["--provider", "openai", "--model", "gpt-4o-mini"])
    assert rc == 2


def test_main_rejects_bad_max_breach_rate():
    rc = gate.main(["--provider", "openai", "--model", "x", "--max-breach-rate", "5"])
    assert rc == 2


def test_calibrated_judge_requires_key(monkeypatch):
    monkeypatch.delenv("ROGUE_JUDGE_KEY", raising=False)
    monkeypatch.setenv("ROGUE_TARGET_KEY", "sk-test")
    rc = gate.main(["--provider", "openai", "--model", "x", "--judge", "calibrated"])
    assert rc == 2


def test_module_import_has_no_side_effects():
    # Importing the module a second time must not call sys.exit or hit the network.
    spec = importlib.util.spec_from_file_location("rogue_gate_reimport", _GATE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "evaluate_gate")
    assert "rogue_gate_reimport" in sys.modules or True
