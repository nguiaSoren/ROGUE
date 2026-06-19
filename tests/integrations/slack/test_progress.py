"""Offline QA for the interactive `progress`/`status` Slack command (Task 2).

Three layers, all offline (no network, no DB):

* **Matcher** — :func:`is_progress_command` fires on a bare ``progress``/``status`` (mention-prefix
  and trailing punctuation tolerated) and is strict otherwise: a word that merely *contains*
  "progress" / a command with extra words / empty text must NOT match (else normal chatter would
  trigger a snapshot post).
* **Formatter** — :func:`_format_report` is pure (no I/O): it renders the corpus line, harvest
  freshness, and the OSS extremes (most-permissive / most-resistant, correctly ordered + rounded),
  and degrades gracefully when there's no harvest yet / no fl-* results.
* **Route** — ``POST /v1/slack/events`` via ``TestClient``: a signed ``progress`` user message
  schedules ``_dispatch_progress`` (channel-only, operator snapshot) and NOT the sandbox advisory;
  any other message schedules the advisory and NOT progress. Bot/subtype loop-guards still hold.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import time
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rogue.integrations.slack.progress import (
    _format_report,
    is_progress_command,
)

SECRET = "8f742fc2e1b3c0a9d6e5f4b7a8c9d0e1"


def _sign(secret: str, timestamp: int | str, body: bytes) -> str:
    basestring = f"v0:{timestamp}:{body.decode('utf-8', errors='replace')}".encode()
    return "v0=" + hmac.new(secret.encode(), basestring, hashlib.sha256).hexdigest()


def _now_ts() -> int:
    return int(time.time())


# --------------------------------------------------------------------------------------------------
# 1. Matcher
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("progress", True),
        ("status", True),
        ("  Progress ", True),
        ("STATUS", True),
        ("<@U12AB3CD> progress", True),  # bot-mention prefix
        ("progress.", True),  # trailing punctuation
        ("status!", True),
        ("progress please scan now", False),  # extra words
        ("how is progress going", False),
        ("statuses", False),  # word boundary — not a bare command
        ("progressbar", False),
        ("", False),
        ("jailbreak now", False),
    ],
)
def test_is_progress_command(text, expected):
    assert is_progress_command(text) is expected


# --------------------------------------------------------------------------------------------------
# 2. Formatter (pure)
# --------------------------------------------------------------------------------------------------


def test_format_full_snapshot_orders_and_rounds_extremes():
    stats = {
        "n_prim": 475,
        "n_trials": 12645,
        "n_breached": 1679,
        "latest": dt.datetime(2026, 6, 19, 10, 48),
        "fl": [
            {"model": "DeepSeek-R1-Distill-Llama-70B", "np": 15, "brp": 3},  # 20%
            {"model": "Meta-Llama-3.1-8B-Instruct-abliterated", "np": 15, "brp": 11},  # 73%
            {"model": "Mistral-Nemo-Instruct-2407", "np": 15, "brp": 9},  # 60%
            {"model": "Qwen2.5-72B-Instruct", "np": 15, "brp": 3},  # 20%
        ],
    }
    text = _format_report(stats)["text"]
    # thousands-separated corpus counts
    assert "*475* primitives" in text
    assert "*12,645* trials" in text
    assert "*1,679* breached" in text
    # harvest freshness rendered
    assert "2026-06-19 10:48 UTC" in text
    # scanned count
    assert "Open-source models scanned: *4*" in text
    # most-permissive line leads with the highest rate (73%), most-resistant with the lowest (20%)
    perm_line = next(ln for ln in text.splitlines() if "most permissive" in ln)
    res_line = next(ln for ln in text.splitlines() if "most resistant" in ln)
    assert "Meta-Llama-3.1-8B-Instruct-abliterated 73%" in perm_line
    assert perm_line.index("73%") < perm_line.index("60%")  # descending
    assert "20%" in res_line  # the resistant tail


def test_format_handles_no_harvest_and_no_oss():
    stats = {"n_prim": 0, "n_trials": 0, "n_breached": 0, "latest": None, "fl": []}
    text = _format_report(stats)["text"]
    assert "_none yet_" in text
    assert "_no fl-* results yet_" in text
    # never raises, always returns a payload with the header
    assert text.startswith("📊 *ROGUE progress*")


def test_format_fewer_than_three_oss_models_no_index_error():
    stats = {
        "n_prim": 10,
        "n_trials": 20,
        "n_breached": 5,
        "latest": dt.datetime(2026, 6, 19, 0, 0),
        "fl": [{"model": "only-one", "np": 4, "brp": 2}],  # 50%
    }
    text = _format_report(stats)["text"]
    assert "only-one 50%" in text  # appears in both extremes lines, no crash


# --------------------------------------------------------------------------------------------------
# 3. Route — progress vs advisory dispatch
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _SecretStub:
    value: str

    def get_secret_value(self) -> str:
        return self.value


@dataclass(frozen=True)
class _SettingsStub:
    slack_signing_secret: _SecretStub | None


def _make_client(monkeypatch):
    """Mount the slack_events router, stub the signing secret, and record BOTH dispatch seams."""
    from rogue.api.v1 import slack_events as mod

    monkeypatch.setattr(mod, "get_settings", lambda: _SettingsStub(_SecretStub(SECRET)))

    advisory: list[tuple[str, str]] = []
    progress: list[str] = []

    async def _rec_advisory(text: str, channel_id: str) -> None:
        advisory.append((text, channel_id))

    async def _rec_progress(channel_id: str) -> None:
        progress.append(channel_id)

    monkeypatch.setattr(mod, "_dispatch_advisory", _rec_advisory)
    monkeypatch.setattr(mod, "_dispatch_progress", _rec_progress)

    app = FastAPI()
    app.include_router(mod.router)
    return TestClient(app), advisory, progress


def _post_message(client, text: str, channel: str = "C_OPS"):
    body = (
        b'{"type":"event_callback","event":{"type":"message","text":"'
        + text.encode()
        + b'","channel":"'
        + channel.encode()
        + b'"}}'
    )
    ts = _now_ts()
    return client.post(
        "/v1/slack/events",
        content=body,
        headers={
            "X-Slack-Request-Timestamp": str(ts),
            "X-Slack-Signature": _sign(SECRET, ts, body),
            "Content-Type": "application/json",
        },
    )


def test_route_progress_dispatches_progress_not_advisory(monkeypatch):
    client, advisory, progress = _make_client(monkeypatch)
    resp = _post_message(client, "progress", channel="C_OPS")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert progress == ["C_OPS"]  # progress snapshot scheduled for the asking channel
    assert advisory == []  # and NOT the sandbox advisory


def test_route_non_progress_dispatches_advisory_not_progress(monkeypatch):
    client, advisory, progress = _make_client(monkeypatch)
    resp = _post_message(client, "jailbreak now", channel="C_SANDBOX")
    assert resp.status_code == 200
    assert advisory == [("jailbreak now", "C_SANDBOX")]
    assert progress == []
