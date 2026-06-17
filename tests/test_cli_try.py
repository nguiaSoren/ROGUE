"""Tests for the keyless ``rogue try`` hero command and the tiered ``rogue scan`` judge default.

``rogue try`` is fully offline: it runs a BUNDLED mock attack pack through the keyless
:class:`HeuristicJudge` and overlays ROGUE's REAL bundled per-model stats — no keys, no network,
no real target. These tests drive it through ``cli.main([...])`` and assert it exits 0, prints the
mock run + the real-stats overlay, and writes a share card. A second test asserts ``rogue scan``
defaults to the keyless heuristic judge (so existing keyless callers keep working).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rogue import cli
from rogue.reproduce.heuristic_judge import HeuristicJudge


# --- rogue try --------------------------------------------------------------------------------


def test_try_runs_offline_and_writes_card(tmp_path, capsys, monkeypatch):
    """``rogue try`` exits 0, runs the mock pipeline + the real-stats overlay, writes a card."""
    # Hard guarantee of offline-ness: any accidental network attempt would surface, not silently pass.
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    out_dir = tmp_path / "card"
    rc = cli.main(["try", "--fast", "--out-dir", str(out_dir)])
    assert rc == 0

    out = capsys.readouterr().out
    # The pipeline header + per-stage labels animate.
    assert "ROGUE" in out and "try" in out
    assert "ATTACKER" in out and "MODEL" in out and "JUDGE" in out
    # Every mock attack family ran through the live judge (8 numbered steps).
    assert "[8/8]" in out
    # A judge verdict was rendered for items (defended and breached are both possible).
    assert "DEFENDED" in out or "BREACH" in out
    # The RESULT block summarizes the mock breach rate.
    assert "BREACHED" in out
    # The real-stats overlay close — "here's what this looks like against 8 real models".
    assert "REAL models" in out
    assert "claude-opus-4-8" in out and "voxtral-small-24b-2507" in out
    # The next-step nudge.
    assert "rogue scan" in out

    # A share card was written (svg always; html always; png if cairosvg present).
    svg = out_dir / "breach-card.svg"
    html = out_dir / "breach-card.html"
    assert svg.exists() and svg.stat().st_size > 0
    assert html.exists() and html.stat().st_size > 0


def test_try_json_summary(tmp_path, capsys):
    """``rogue try --json`` emits a machine-readable summary with a realistic verdict mix."""
    rc = cli.main(["try", "--fast", "--no-card", "--json", "--out-dir", str(tmp_path)])
    assert rc == 0
    # The JSON object is the tail of stdout; parse from the first '{'.
    out = capsys.readouterr().out
    payload = json.loads(out[out.index("{"):])
    assert payload["n_tests"] == 8
    assert payload["tier"] == "quick"
    # The bundled fixture is authored + verified to a mixed outcome, never all-or-nothing.
    assert 0 < payload["n_breaches"] < payload["n_tests"]
    assert len(payload["findings"]) == 8


def test_try_fixture_contains_no_harmful_content():
    """Guardrail: the bundled demo pack carries only SANITIZED placeholders — no real payloads."""
    pack = json.loads(cli._TRY_PACK_PATH.read_text(encoding="utf-8"))
    blob = json.dumps(pack).lower()
    # No real working-payload / harmful-output fingerprints (regression guard for sanitization).
    for needle in ("smtplib", "sendmail", "napalm", "customers.csv", "bwfrzsbu", "base64"):
        assert needle not in blob, f"harmful fingerprint leaked into demo pack: {needle!r}"
    # Every attack prompt is a redaction-convention placeholder, not real attack text.
    for atk in pack["attacks"]:
        assert atk["attack_prompt"].lstrip().startswith("[demo attack")


def test_try_real_stats_are_bundled_and_sourced():
    """The overlay stats are REAL (8 models, attributed to the snapshot) — not invented."""
    stats = json.loads(cli._DEMO_STATS_PATH.read_text(encoding="utf-8"))
    assert len(stats["models"]) == 8
    # Provenance is recorded (real snapshot + calibrated judge); the source is not flagged illustrative.
    assert "snapshot" in stats["source"].lower()
    assert "illustrative" not in stats["source"].lower()
    for m in stats["models"]:
        assert 0.0 <= m["mean_breach_rate"] <= 1.0
        assert m["n_trials"] > 0


# --- tiered rogue scan ------------------------------------------------------------------------


class _FakeClient:
    """Records the judge the CLI threads onto it; no network."""

    instances: list["_FakeClient"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self._judge = "UNSET"
        _FakeClient.instances.append(self)

    def scan(self, **kwargs):
        from rogue.report import ScanReport

        return ScanReport(target="x", n_tests=0, n_breaches=0, cost_usd=0.0, findings=[])


@pytest.fixture
def fake_client(monkeypatch):
    _FakeClient.instances = []
    monkeypatch.setattr(cli, "Client", _FakeClient)
    return _FakeClient


def test_scan_defaults_to_heuristic_judge(fake_client, monkeypatch, capsys):
    """``rogue scan`` with no ``--judge`` flag => the keyless HeuristicJudge is threaded onto the
    client, and (keyless) the upgrade hint is printed."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JUDGE_API_KEY", raising=False)

    rc = cli.main(["scan", "--endpoint", "https://gw/v1"])
    assert rc == 0
    client = fake_client.instances[-1]
    assert isinstance(client._judge, HeuristicJudge)
    # Keyless hint surfaces the calibrated upgrade path — on stderr so --json stays clean on stdout.
    assert "quick scan (keyless heuristic judge)" in capsys.readouterr().err


def test_scan_calibrated_judge_defers_to_scan_path(fake_client, capsys):
    """``--judge calibrated`` => the CLI threads ``None`` so the scan path builds the LLM JudgeAgent
    (today's behavior, unchanged)."""
    rc = cli.main(["scan", "--endpoint", "https://gw/v1", "--judge", "calibrated"])
    assert rc == 0
    client = fake_client.instances[-1]
    assert client._judge is None
    # No keyless hint when the user explicitly opts into the calibrated judge.
    captured = capsys.readouterr()
    assert "quick scan (keyless heuristic judge)" not in (captured.out + captured.err)


def test_card_path_offline(tmp_path):
    """Sanity: render_breach_card via `rogue try` produces a self-contained SVG that mentions the
    quick tier and never leaks a payload."""
    out_dir = tmp_path / "c"
    assert cli.main(["try", "--fast", "--out-dir", str(out_dir)]) == 0
    svg_text = (out_dir / "breach-card.svg").read_text(encoding="utf-8").lower()
    assert "smtplib" not in svg_text and "napalm" not in svg_text
