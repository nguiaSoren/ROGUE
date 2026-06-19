"""Tests for the opt-in anonymous telemetry module (Deliverable 12).

Self-contained: no conftest. ``ROGUE_CONFIG_DIR`` is sandboxed to a tmp dir via
``monkeypatch`` so client_id persistence never touches the real home directory,
and the telemetry env vars are cleared per test for isolation.
"""

from __future__ import annotations

import platform

import pytest

from rogue.utils.telemetry import DEFAULT_ENDPOINT, Telemetry, _sanitize

_TELEMETRY_ENV_VARS = (
    "ROGUE_TELEMETRY",
    "ROGUE_TELEMETRY_ENDPOINT",
    "DO_NOT_TRACK",
    "ROGUE_DO_NOT_TRACK",
)


@pytest.fixture(autouse=True)
def _sandbox(monkeypatch, tmp_path):
    """Sandbox config dir + clear telemetry env so each test is isolated."""
    monkeypatch.setenv("ROGUE_CONFIG_DIR", str(tmp_path))
    for name in _TELEMETRY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    yield


# --- from_env / enablement --------------------------------------------------


def test_disabled_by_default():
    tel = Telemetry.from_env(sdk_version="0.1.0")
    assert tel.enabled is False


def test_disabled_emit_is_noop():
    seen: list[dict] = []
    tel = Telemetry.from_env(sdk_version="0.1.0")
    # Force a sender in — it must still never be called while disabled.
    tel._sender = seen.append
    tel.emit("scan_started")
    assert seen == []


def test_rogue_telemetry_1_enables(monkeypatch):
    monkeypatch.setenv("ROGUE_TELEMETRY", "1")
    assert Telemetry.from_env(sdk_version="0.1.0").enabled is True


@pytest.mark.parametrize("value", ["1", "true", "YES", "On", "TRUE"])
def test_truthy_values_enable(monkeypatch, value):
    monkeypatch.setenv("ROGUE_TELEMETRY", value)
    assert Telemetry.from_env().enabled is True


@pytest.mark.parametrize("value", ["0", "false", "off", "no", ""])
def test_falsy_values_stay_disabled(monkeypatch, value):
    monkeypatch.setenv("ROGUE_TELEMETRY", value)
    assert Telemetry.from_env().enabled is False


def test_do_not_track_forces_disabled(monkeypatch):
    monkeypatch.setenv("ROGUE_TELEMETRY", "1")
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    assert Telemetry.from_env().enabled is False


def test_rogue_do_not_track_forces_disabled(monkeypatch):
    monkeypatch.setenv("ROGUE_TELEMETRY", "1")
    monkeypatch.setenv("ROGUE_DO_NOT_TRACK", "1")
    assert Telemetry.from_env().enabled is False


def test_endpoint_from_env(monkeypatch):
    monkeypatch.setenv("ROGUE_TELEMETRY", "1")
    monkeypatch.setenv("ROGUE_TELEMETRY_ENDPOINT", "https://example.test/e")
    assert Telemetry.from_env().endpoint == "https://example.test/e"


def test_endpoint_default_when_unset(monkeypatch):
    monkeypatch.setenv("ROGUE_TELEMETRY", "1")
    assert Telemetry.from_env().endpoint == DEFAULT_ENDPOINT


# --- payload shape & privacy ------------------------------------------------


def test_injected_sender_captures_payload():
    seen: list[dict] = []
    tel = Telemetry(enabled=True, sdk_version="0.1.0", sender=seen.append)
    tel.emit("scan_completed", n_findings=3)
    assert len(seen) == 1
    payload = seen[0]
    assert payload["event"] == "scan_completed"
    assert payload["sdk_version"] == "0.1.0"
    assert payload["python_version"] == platform.python_version()
    assert payload["os"] == platform.system()
    assert "client_id" in payload and "ts" in payload
    assert payload["n_findings"] == 3


def test_payload_excludes_sensitive_keys():
    seen: list[dict] = []
    tel = Telemetry(enabled=True, sdk_version="0.1.0", sender=seen.append)
    tel.emit(
        "scan_completed",
        n_findings=3,
        api_key="LEAK",
        system_prompt="LEAK",
        access_token="LEAK",
        password="LEAK",
    )
    payload = seen[0]
    for forbidden in ("api_key", "system_prompt", "access_token", "password"):
        assert forbidden not in payload
    assert payload["n_findings"] == 3


# --- _sanitize unit ---------------------------------------------------------


def test_sanitize_drops_sensitive_keys():
    out = _sanitize(
        {
            "system_prompt": "secret instructions",
            "api_key": "sk-123",
            "auth_token": "t",
            "my_secret": "s",
            "user_password": "p",
            "credential_id": "c",
            "authorization": "Bearer x",
            "n": 1,
        }
    )
    assert out == {"n": 1}


def test_sanitize_drops_non_scalars():
    out = _sanitize(
        {
            "good_int": 1,
            "good_float": 1.5,
            "good_str": "hi",
            "good_bool": True,
            "bad_list": [1, 2, 3],
            "bad_dict": {"a": 1},
            "bad_bytes": b"x",
            "bad_none": None,
        }
    )
    assert out == {
        "good_int": 1,
        "good_float": 1.5,
        "good_str": "hi",
        "good_bool": True,
    }


def test_sanitize_truncates_long_strings():
    out = _sanitize({"note": "x" * 500})
    assert len(out["note"]) == 120


def test_sanitize_drops_reserved_keys():
    out = _sanitize({"event": "x", "client_id": "y", "ts": "z", "keep": 1})
    assert out == {"keep": 1}


# --- crash safety -----------------------------------------------------------


def test_emit_never_raises_when_sender_throws():
    def boom(_payload):
        raise RuntimeError("network down")

    tel = Telemetry(enabled=True, sdk_version="0.1.0", sender=boom)
    # Must not propagate.
    tel.emit("scan_started")


def test_emit_never_raises_on_bad_field_types():
    seen: list[dict] = []
    tel = Telemetry(enabled=True, sdk_version="0.1.0", sender=seen.append)

    class Weird:
        def __repr__(self):
            raise RuntimeError("nope")

    tel.emit("evt", obj=Weird(), n=2)
    assert seen[0]["n"] == 2
    assert "obj" not in seen[0]


# --- client_id stability ----------------------------------------------------


def test_client_id_stable_across_instances():
    a = Telemetry(enabled=True, sdk_version="0.1.0", sender=lambda _p: None)
    b = Telemetry(enabled=True, sdk_version="0.1.0", sender=lambda _p: None)
    assert a.client_id is not None
    assert a.client_id == b.client_id


def test_explicit_client_id_used():
    tel = Telemetry(enabled=True, client_id="fixed-id", sender=lambda _p: None)
    assert tel.client_id == "fixed-id"
