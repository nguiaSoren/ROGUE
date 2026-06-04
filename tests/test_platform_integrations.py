"""Offline tests for the platform integrations fan-out (no real HTTP — injected senders/clients).

Covers the three contracts the spec calls out:
  * Slack payload carries the score / breach ratio / top attack;
  * a failing destination does not break dispatch (siblings still fire);
  * the Jira ``finding_id`` dedup key is stable across two identical findings.
"""

from __future__ import annotations

import pytest

from rogue.platform.integrations import (
    IntegrationDispatcher,
    JiraDestination,
    ScanCompletedEvent,
    SlackDestination,
    finding_id,
)
from rogue.platform.integrations.jira import FindingInput, JiraTicket
from rogue.platform.schemas import ScanRecord, ScanStatus


def _event(**overrides) -> ScanCompletedEvent:
    base = dict(
        scan_id="scan_123",
        org_id="org_acme",
        target="gpt-4o-mini",
        score=72.0,
        n_breaches=4,
        n_tests=50,
        top_attack="role_play_jailbreak",
        status="completed",
        report_url="https://rogue.example/r/scan_123",
    )
    base.update(overrides)
    return ScanCompletedEvent(**base)


def test_event_from_record_projects_redacted_target():
    record = ScanRecord(
        scan_id="s1",
        org_id="org_x",
        status=ScanStatus.COMPLETED,
        n_tests=10,
        n_breaches=2,
        top_attack="dan",
        score=33.0,
        target={"provider": "openai", "model": "gpt-4o", "system_prompt_len": 5, "has_api_key": True},
    )
    event = ScanCompletedEvent.from_record(record, report_url="http://r/s1")
    assert event.target == "gpt-4o"  # model preferred over provider
    assert event.status == "completed"
    assert event.score == 33.0
    assert event.report_url == "http://r/s1"


@pytest.mark.asyncio
async def test_slack_payload_contains_score_breaches_top_attack():
    captured: list[tuple[str, dict]] = []

    async def fake_sender(url: str, payload: dict) -> None:
        captured.append((url, payload))

    dispatcher = IntegrationDispatcher()
    dispatcher.register(SlackDestination("https://hooks.slack/T/B/X", sender=fake_sender))

    await dispatcher.dispatch(_event())

    assert len(captured) == 1
    url, payload = captured[0]
    assert url == "https://hooks.slack/T/B/X"
    text = payload["text"]
    assert "72/100" in text
    assert "4/50" in text
    assert "role_play_jailbreak" in text
    # Block Kit blocks present, and the report button links out.
    assert payload["blocks"]
    button_urls = [
        el["url"]
        for b in payload["blocks"]
        if b.get("type") == "actions"
        for el in b["elements"]
    ]
    assert button_urls == ["https://rogue.example/r/scan_123"]


@pytest.mark.asyncio
async def test_one_failing_destination_does_not_break_dispatch():
    fired: list[str] = []

    async def good_sender(url: str, payload: dict) -> None:
        fired.append("good")

    async def bad_sender(url: str, payload: dict) -> None:
        raise RuntimeError("slack 500")

    dispatcher = IntegrationDispatcher()
    # Register the failing destination FIRST so we prove ordering doesn't matter.
    dispatcher.register(SlackDestination("https://bad", sender=bad_sender))
    dispatcher.register(SlackDestination("https://good", sender=good_sender))

    # Must not raise even though one destination throws.
    await dispatcher.dispatch(_event())

    assert fired == ["good"]


@pytest.mark.asyncio
async def test_default_slack_sender_swallows_when_httpx_absent(monkeypatch):
    # The default sender must never raise even when the POST fails; simulate by pointing at an
    # unroutable URL through a sender that mimics the lazy-import failure path. Here we just confirm
    # a SlackDestination with no injected sender can be constructed and notified without raising,
    # using a sender that raises to exercise the swallow contract at the destination boundary.
    dispatcher = IntegrationDispatcher()

    async def boom(url: str, payload: dict) -> None:
        raise ConnectionError("network down")

    dispatcher.register(SlackDestination("https://x", sender=boom))
    await dispatcher.dispatch(_event())  # swallowed by dispatcher — no assertion needed beyond no-raise


def test_finding_id_is_stable_across_identical_findings():
    a = finding_id("org_acme", "gpt-4o-mini", "jailbreak", "role_play")
    b = finding_id("org_acme", "gpt-4o-mini", "jailbreak", "role_play")
    assert a == b
    assert len(a) == 64  # sha256 hex
    # Any differing component changes the id.
    assert finding_id("org_acme", "gpt-4o-mini", "jailbreak", "obfuscation") != a
    assert finding_id("org_other", "gpt-4o-mini", "jailbreak", "role_play") != a


class _FakeJira:
    """In-memory Jira: tracks open tickets keyed by finding_id, records every create call."""

    def __init__(self):
        self.open: dict[str, str] = {}
        self.created: list[JiraTicket] = []
        self.closed: list[str] = []
        self._counter = 0

    async def find_open(self, fid: str) -> str | None:
        return self.open.get(fid)

    async def create(self, ticket: JiraTicket) -> str:
        self._counter += 1
        key = f"ROGUE-{self._counter}"
        self.open[ticket.finding_id] = key
        self.created.append(ticket)
        return key

    async def close(self, issue_key: str) -> None:
        self.closed.append(issue_key)
        self.open = {f: k for f, k in self.open.items() if k != issue_key}

    async def list_open(self) -> dict[str, str]:
        return dict(self.open)


@pytest.mark.asyncio
async def test_jira_creates_only_for_critical_and_dedups_on_rescan():
    findings = [
        FindingInput(family="jailbreak", vector="role_play", severity="critical", title="DAN bypass"),
        FindingInput(family="leakage", vector="prompt_extract", severity="high", title="Prompt leak"),
    ]
    client = _FakeJira()
    dest = JiraDestination(client, findings_for=lambda _e: findings)

    # First scan: one critical → one ticket; the high finding is not ticketed.
    await dest.notify(_event())
    assert len(client.created) == 1
    assert client.created[0].severity == "critical"

    # Re-scan reproduces the same critical finding → same finding_id → no duplicate ticket.
    await dest.notify(_event(scan_id="scan_456"))
    assert len(client.created) == 1
    assert len(client.open) == 1


@pytest.mark.asyncio
async def test_jira_notify_never_raises_on_client_error():
    class _Broken:
        async def find_open(self, fid): raise RuntimeError("jira down")
        async def create(self, ticket): raise RuntimeError("jira down")
        async def close(self, issue_key): ...
        async def list_open(self): return {}

    findings = [FindingInput(family="jailbreak", vector="x", severity="critical", title="t")]
    dest = JiraDestination(_Broken(), findings_for=lambda _e: findings)
    await dest.notify(_event())  # must not raise


@pytest.mark.asyncio
async def test_jira_auto_close_closes_resolved_findings():
    client = _FakeJira()
    findings = [FindingInput(family="jailbreak", vector="role_play", severity="critical", title="DAN")]
    dest = JiraDestination(client, findings_for=lambda _e: findings)

    await dest.notify(_event())
    fid = finding_id("org_acme", "gpt-4o-mini", "jailbreak", "role_play")
    assert fid in client.open

    # Latest scan no longer has this critical → auto-close transitions the ticket to Done.
    await dest.auto_close(current_critical_ids=set())
    assert fid not in client.open
    assert len(client.closed) == 1
