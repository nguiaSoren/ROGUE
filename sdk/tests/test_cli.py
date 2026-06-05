"""Tests for the ``rogue`` CLI (Deliverable 9).

Self-contained: no conftest. Every test drives :func:`rogue.cli.main.main` with an injected
:class:`MockTransport` so multi-command flows share one in-memory backend (create a deployment,
then scan *that* deployment with the same transport). ``ROGUE_CONFIG_DIR`` is pointed at a tmp dir
for any test that touches stored credentials, so the real home dir is never written.
"""

from __future__ import annotations

import json

import pytest

from rogue import MockTransport
from rogue.cli.main import main

# --- helpers --------------------------------------------------------------------------------------


def _create_deployment(mt: MockTransport, capsys, name: str = "Support Bot", model: str = "gpt-5") -> str:
    """Create a deployment via the CLI and return its id (parsed from --json output)."""
    rc = main(
        ["--json", "deployment", "create", "--name", name, "--model", model],
        transport=mt,
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    return out["id"]


# --- login / status / logout ----------------------------------------------------------------------


def test_login_status_logout_flow(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ROGUE_CONFIG_DIR", str(tmp_path))
    mt = MockTransport()

    rc = main(["login", "--api-key", "secret-key"], transport=mt)
    assert rc == 0
    assert "saved" in capsys.readouterr().out.lower()
    assert (tmp_path / "credentials.json").exists()

    rc = main(["status"], transport=mt)
    assert rc == 0
    out = capsys.readouterr().out
    assert "api_key_configured: yes" in out
    assert "sdk_version" in out

    rc = main(["logout"], transport=mt)
    assert rc == 0
    assert "logged out" in capsys.readouterr().out.lower()
    assert not (tmp_path / "credentials.json").exists()

    # After logout, status reports no key.
    rc = main(["status"], transport=mt)
    assert rc == 0
    assert "api_key_configured: no" in capsys.readouterr().out


def test_login_persists_base_url(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ROGUE_CONFIG_DIR", str(tmp_path))
    mt = MockTransport()
    rc = main(
        ["login", "--api-key", "k", "--base-url", "https://example.test"],
        transport=mt,
    )
    assert rc == 0
    saved = json.loads((tmp_path / "credentials.json").read_text())
    assert saved["api_key"] == "k"
    assert saved["base_url"] == "https://example.test"


def test_login_reads_key_from_stdin(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ROGUE_CONFIG_DIR", str(tmp_path))
    # getpass raises EOFError under capsys (no tty) -> falls back to stdin read.
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: (_ for _ in ()).throw(EOFError()))
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("piped-key\n"))
    mt = MockTransport()
    rc = main(["login"], transport=mt)
    assert rc == 0
    assert json.loads((tmp_path / "credentials.json").read_text())["api_key"] == "piped-key"


def test_status_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ROGUE_CONFIG_DIR", str(tmp_path))
    rc = main(["--json", "status"], transport=MockTransport())
    assert rc == 0
    info = json.loads(capsys.readouterr().out)
    assert info["api_key_configured"] is False
    assert set(info) >= {"sdk_version", "api_version", "base_url", "api_key_configured"}


# --- deployments -----------------------------------------------------------------------------------


def test_deployment_create_human_output(capsys):
    mt = MockTransport()
    rc = main(
        ["deployment", "create", "--name", "Bot", "--model", "gpt-5"],
        transport=mt,
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Created deployment" in out
    assert "dep_" in out


def test_deployment_create_json(capsys):
    mt = MockTransport()
    rc = main(
        [
            "--json",
            "deployment",
            "create",
            "--name",
            "Bot",
            "--model",
            "gpt-5",
            "--tools",
            "search,refund",
            "--forbidden-topics",
            "medical,legal",
        ],
        transport=mt,
    )
    assert rc == 0
    dep = json.loads(capsys.readouterr().out)
    assert dep["name"] == "Bot"
    assert dep["model"] == "gpt-5"
    assert dep["tools"] == ["search", "refund"]
    assert dep["forbidden_topics"] == ["medical", "legal"]


def test_deployment_list_and_get(capsys):
    mt = MockTransport()
    dep_id = _create_deployment(mt, capsys)

    rc = main(["deployment", "list"], transport=mt)
    assert rc == 0
    assert dep_id in capsys.readouterr().out

    rc = main(["deployment", "get", dep_id], transport=mt)
    assert rc == 0
    out = capsys.readouterr().out
    assert dep_id in out
    assert "model:" in out


def test_deployment_list_json_is_array(capsys):
    mt = MockTransport()
    _create_deployment(mt, capsys)
    _create_deployment(mt, capsys, name="Second")
    rc = main(["--json", "deployment", "list"], transport=mt)
    assert rc == 0
    items = json.loads(capsys.readouterr().out)
    assert isinstance(items, list)
    assert len(items) == 2


# --- scans -----------------------------------------------------------------------------------------


def test_scan_start_no_wait(capsys):
    mt = MockTransport(complete_after_polls=2)  # stays running so status is observable
    dep_id = _create_deployment(mt, capsys)
    rc = main(["scan", "start", "--deployment", dep_id], transport=mt)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Started scan" in out
    assert "scan_" in out


def test_scan_start_wait_prints_report(capsys):
    mt = MockTransport()  # completes on creation -> wait returns immediately
    dep_id = _create_deployment(mt, capsys)
    rc = main(["scan", "start", "--deployment", dep_id, "--wait"], transport=mt)
    assert rc == 0
    out = capsys.readouterr().out
    assert "completed" in out
    assert "Risk score:" in out


def test_scan_start_wait_json(capsys):
    mt = MockTransport()
    dep_id = _create_deployment(mt, capsys)
    rc = main(["--json", "scan", "start", "--deployment", dep_id, "--wait"], transport=mt)
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert "risk_score" in report
    assert "findings" in report


def test_scan_status(capsys):
    mt = MockTransport(complete_after_polls=3)
    dep_id = _create_deployment(mt, capsys)
    rc = main(["--json", "scan", "start", "--deployment", dep_id], transport=mt)
    assert rc == 0
    scan_id = json.loads(capsys.readouterr().out)["id"]

    rc = main(["scan", "status", scan_id], transport=mt)
    assert rc == 0
    out = capsys.readouterr().out
    assert scan_id in out
    assert "status=" in out


# --- reports ---------------------------------------------------------------------------------------


def _completed_scan_id(mt: MockTransport, capsys) -> str:
    dep_id = _create_deployment(mt, capsys)
    rc = main(["--json", "scan", "start", "--deployment", dep_id], transport=mt)
    assert rc == 0
    return json.loads(capsys.readouterr().out)["id"]


def test_report_open_markdown_by_scan(capsys):
    mt = MockTransport()
    scan_id = _completed_scan_id(mt, capsys)
    rc = main(["report", "open", "--scan", scan_id], transport=mt)
    assert rc == 0
    out = capsys.readouterr().out
    assert "# ROGUE Threat Report" in out
    assert "Risk score" in out


def test_report_open_json_by_scan(capsys):
    mt = MockTransport()
    scan_id = _completed_scan_id(mt, capsys)
    rc = main(["report", "open", "--scan", scan_id, "--format", "json"], transport=mt)
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["scan_id"] == scan_id
    assert "findings" in report


def test_report_open_by_report_id(capsys):
    mt = MockTransport()
    scan_id = _completed_scan_id(mt, capsys)
    # Resolve the report id via the scan, then open it directly by id.
    rc = main(["--json", "report", "open", "--scan", scan_id], transport=mt)
    assert rc == 0
    report_id = json.loads(capsys.readouterr().out)["id"]

    rc = main(["report", "open", report_id], transport=mt)
    assert rc == 0
    assert "# ROGUE Threat Report" in capsys.readouterr().out


def test_report_open_writes_file(tmp_path, capsys):
    mt = MockTransport()
    scan_id = _completed_scan_id(mt, capsys)
    out_path = tmp_path / "report.md"
    rc = main(
        ["report", "open", "--scan", scan_id, "--output", str(out_path)],
        transport=mt,
    )
    assert rc == 0
    assert "Wrote Markdown report" in capsys.readouterr().out
    assert out_path.exists()
    assert "# ROGUE Threat Report" in out_path.read_text()


def test_report_open_pdf_requires_output(capsys):
    mt = MockTransport()
    scan_id = _completed_scan_id(mt, capsys)
    rc = main(["report", "open", "--scan", scan_id, "--format", "pdf"], transport=mt)
    assert rc == 1
    assert "requires --output" in capsys.readouterr().err


# --- error handling --------------------------------------------------------------------------------


def test_unknown_deployment_id_is_clean_error(capsys):
    mt = MockTransport()
    rc = main(["deployment", "get", "dep_does_not_exist"], transport=mt)
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "not found" in err


def test_scan_unknown_deployment_is_error(capsys):
    mt = MockTransport()
    rc = main(["scan", "start", "--deployment", "dep_nope"], transport=mt)
    assert rc == 1
    assert capsys.readouterr().err.startswith("error:")


def test_no_command_returns_usage_code(capsys):
    rc = main([], transport=MockTransport())
    assert rc == 2


def test_report_open_without_id_or_scan_errors(capsys):
    mt = MockTransport()
    rc = main(["report", "open"], transport=mt)
    assert rc == 1
    assert "report id or --scan" in capsys.readouterr().err


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
