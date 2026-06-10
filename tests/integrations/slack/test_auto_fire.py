"""Surface-1 production auto-fire — offline regression for the worker-finalize → Slack diff path.

Two layers under test, both wired with fakes only at the true boundaries (no DB, no network):

  * :class:`SlackSurface1Delivery.deliver` — the gate + dispatch (delivery.py). Adversarial focus:
    the "best-effort, never raises" invariant (a missing registration, a raising transport, a
    malformed payload all turn into ``None``), and the "post goes to the SECURITY channel and
    NOTHING ELSE" invariant.
  * :class:`ScanWorker.run_once` auto-fire hook (worker.py). Adversarial focus: a non-Slack scan is
    byte-identical to before (no delivery attempted), and — load-bearing — a delivery failure can
    NEVER fail or lose an already-finalized COMPLETED scan (the job still acks).

Mirrors the existing worker test (``tests/test_platform_worker.py``: in-memory store/queue + fake
engine) and the slack e2e fixtures (``tests/integrations/slack/test_change_witness_e2e.py``).
"""

from __future__ import annotations

import pytest

from rogue.integrations.slack import (
    InMemorySlackAgentStore,
    SlackAgentTarget,
    SlackSurface1Delivery,
    register_slack_agent,
)
from rogue.platform.memory import InMemoryJobQueue, InMemoryScanStore, _new_id
from rogue.platform.schemas import ScanRecord, ScanSpec, ScanStatus, TargetSpec
from rogue.platform.snapshot_store import InMemorySnapshotStore
from rogue.platform.worker import ScanWorker
from rogue.report import ScanReport

# ---------------------------------------------------------------------------
# Constants / fixtures
# ---------------------------------------------------------------------------
_ORG = "org-acme"
_AGENT = "it-helpdesk"
_WORKSPACE = "ws-acme"
_SANDBOX_CHANNEL = "C-SANDBOX-001"
_SECURITY_CHANNEL = "C-SECURITY-999"
_OTHER_CHANNEL = "C-RANDOM-555"

_BREACH_RULE_ID = "R-wire-exfil"


def _register_agent(store: InMemorySlackAgentStore) -> SlackAgentTarget:
    """Register one Slack agent with DISTINCT sandbox vs security channels and return its target."""
    reg = register_slack_agent(
        SlackAgentTarget.create(
            org_id=_ORG,
            agent_name=_AGENT,
            workspace=_WORKSPACE,
            base_url="https://it-helpdesk.acme.example/v1",
            model="gpt-5.4-nano",
            system_prompt="You are the ACME #it-helpdesk agent. You may not move money.",
            declared_tools=["wire_transfer"],
            forbidden_topics=["initiating financial transfers"],
            sandbox_channel_id=_SANDBOX_CHANNEL,
            security_channel_id=_SECURITY_CHANNEL,
        ),
        agent_store=store,
    )
    return reg.target


def _surface1_context() -> dict:
    """The frozen surface1_context block the trigger stamps onto a policy ScanSpec/report."""
    return {
        "agent": {
            "org_id": _ORG,
            "agent_name": _AGENT,
            "workspace": _WORKSPACE,
            "config_id": f"slack-{_WORKSPACE}-{_AGENT}",
        },
        "families": ["tool_use_hijack"],
        "ground_truth_refs": {"unauthorized_action": "area02-calibration:unauthorized_action"},
    }


def _rule_breach_report(*, breaching: bool = True) -> dict:
    """A RuleBreachReport.model_dump()-shaped dict; one breaching verdict when ``breaching``."""
    breaching_verdict = {
        "rule_id": _BREACH_RULE_ID,
        "breach_type": "unauthorized_action",
        "attack_family": "tool_use_hijack",
        "n_trials": 8,
        "n_breaches": 3 if breaching else 0,
        "breach_rate": (3 / 8) if breaching else 0.0,
        "ci_low": 0.12,
        "ci_high": 0.71,
        "calibration_status": "calibrated",
        "transcript_refs": [f"{_BREACH_RULE_ID}::prim-wire-exfil::t0"],
    }
    return {
        "policy_id": "slackpol-slack-ws-acme-it-helpdesk",
        "config_id": f"slack-{_WORKSPACE}-{_AGENT}",
        "rule_verdicts": [breaching_verdict],
        "holds_count": 0 if breaching else 1,
        "total_count": 1,
    }


def _report_payload(*, with_context: bool = True, breaching: bool = True) -> dict:
    """Build a ScanReport.to_dict() carrying (optionally) surface1_context + a rule_breach_report.

    Built through the real ``ScanReport`` so to_dict()'s key-emission gates are exercised exactly
    as the worker would feed them."""
    report = ScanReport(
        target="https://it-helpdesk.acme.example/v1",
        n_tests=8,
        n_breaches=3 if breaching else 0,
        cost_usd=0.42,
        findings=[],
        rule_breach_report=_rule_breach_report(breaching=breaching),
        surface1_context=_surface1_context() if with_context else None,
    )
    return report.to_dict()


class _RecordingSender:
    """An async (channel, payload) sender that records every send. Mirrors the §4 e2e fake."""

    def __init__(self) -> None:
        self.sends: list[tuple[str, dict]] = []

    async def __call__(self, channel: str, payload: dict) -> None:
        self.sends.append((channel, payload))


class _RaisingSender:
    """A sender that always raises — proves a transport outage is swallowed (never propagates)."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, channel: str, payload: dict) -> None:
        self.calls += 1
        raise RuntimeError("slack transport exploded")


# ===========================================================================
# Delivery layer (SlackSurface1Delivery.deliver)
# ===========================================================================
@pytest.mark.asyncio
async def test_delivery_happy_path_posts_once_to_security_channel():
    """A breaching Surface-1 scan posts EXACTLY ONE message, to the SECURITY channel only."""
    agent_store = InMemorySlackAgentStore()
    _register_agent(agent_store)
    sender = _RecordingSender()
    delivery = SlackSurface1Delivery(
        agent_store=agent_store, sender=sender, snapshot_store=InMemorySnapshotStore()
    )

    payload = await delivery.deliver(_report_payload(), org_id=_ORG, scan_id="scan-1")

    # Exactly one send.
    assert len(sender.sends) == 1, "auto-fire must post exactly once"
    channel, body = sender.sends[0]
    # ...to the SECURITY channel — never the sandbox, never any other id.
    assert channel == _SECURITY_CHANNEL
    assert channel != _SANDBOX_CHANNEL
    assert channel != _OTHER_CHANNEL
    # The post names the breaching rule (smoke that post_breach_diff actually rendered the diff).
    assert _BREACH_RULE_ID in body["text"]
    assert "breaks 3/8" in body["text"]
    # deliver returns the built payload (the rendered Block Kit message).
    assert payload is not None
    assert payload["text"] == body["text"]


@pytest.mark.asyncio
async def test_gate_non_slack_scan_is_noop():
    """No surface1_context ⇒ returns None and posts nothing (the byte-identical non-Slack gate)."""
    agent_store = InMemorySlackAgentStore()
    _register_agent(agent_store)
    sender = _RecordingSender()
    delivery = SlackSurface1Delivery(agent_store=agent_store, sender=sender)

    result = await delivery.deliver(_report_payload(with_context=False), org_id=_ORG, scan_id="scan-2")

    assert result is None
    assert sender.sends == []


@pytest.mark.asyncio
async def test_agent_gone_returns_none_no_send_no_raise():
    """surface1_context present but the registration is gone ⇒ None, zero sends, no raise."""
    agent_store = InMemorySlackAgentStore()  # deliberately EMPTY — nothing registered
    sender = _RecordingSender()
    delivery = SlackSurface1Delivery(agent_store=agent_store, sender=sender)

    result = await delivery.deliver(_report_payload(), org_id=_ORG, scan_id="scan-3")

    assert result is None
    assert sender.sends == []


@pytest.mark.asyncio
async def test_best_effort_raising_sender_does_not_propagate():
    """A transport that raises must not propagate out of deliver (the send failure is swallowed
    inside post_breach_diff). The payload is still returned (the post was built + attempted)."""
    agent_store = InMemorySlackAgentStore()
    _register_agent(agent_store)
    sender = _RaisingSender()
    delivery = SlackSurface1Delivery(agent_store=agent_store, sender=sender)

    # Must NOT raise.
    result = await delivery.deliver(_report_payload(), org_id=_ORG, scan_id="scan-4a")

    assert sender.calls == 1  # the send was attempted...
    assert result is not None  # ...and the render still produced a payload (failure swallowed below)


@pytest.mark.asyncio
async def test_best_effort_malformed_context_returns_none_no_raise():
    """A malformed surface1_context (missing the `agent` key) makes the lookup raise INSIDE deliver
    — deliver's own try/except must turn that into None, never propagating, and post nothing."""
    agent_store = InMemorySlackAgentStore()
    _register_agent(agent_store)
    sender = _RecordingSender()
    delivery = SlackSurface1Delivery(agent_store=agent_store, sender=sender)

    payload = _report_payload()
    payload["surface1_context"] = {"families": ["x"]}  # truthy but missing "agent" → KeyError inside

    result = await delivery.deliver(payload, org_id=_ORG, scan_id="scan-4b")

    assert result is None
    assert sender.sends == []


@pytest.mark.asyncio
async def test_best_effort_malformed_report_returns_none_no_raise():
    """A malformed rule_breach_report (rule_verdicts not iterable as dicts) makes the render raise
    inside post_breach_diff; deliver's try/except turns it into None and never propagates."""
    agent_store = InMemorySlackAgentStore()
    _register_agent(agent_store)
    sender = _RecordingSender()
    delivery = SlackSurface1Delivery(agent_store=agent_store, sender=sender)

    payload = _report_payload()
    # A verdict that is not a dict → `int(v.get(...))` raises AttributeError inside build/post.
    payload["rule_breach_report"]["rule_verdicts"] = ["not-a-dict-verdict"]

    result = await delivery.deliver(payload, org_id=_ORG, scan_id="scan-4c")

    assert result is None
    assert sender.sends == []


# ===========================================================================
# Worker integration (ScanWorker.run_once auto-fire hook)
# ===========================================================================
class _Surface1Engine:
    """A fake engine returning a ScanReport carrying surface1_context + a breaching rule report."""

    async def run(self, spec, *, progress=None):
        if progress is not None:
            await progress(1, 1, "tool_use_hijack")
        return ScanReport(
            target="https://it-helpdesk.acme.example/v1",
            n_tests=8,
            n_breaches=3,
            cost_usd=0.42,
            findings=[],
            rule_breach_report=_rule_breach_report(breaching=True),
            surface1_context=_surface1_context(),
        )


class _PlainEngine:
    """A non-Slack engine: a normal ScanReport with NO surface1_context (the byte-identical case)."""

    async def run(self, spec, *, progress=None):
        if progress is not None:
            await progress(1, 1, "DAN")
        return ScanReport(target="t", n_tests=2, n_breaches=1, cost_usd=0.01, findings=[])


class _RecordingDelivery:
    """A fake slack_delivery recording deliver(...) calls (the worker's injected seam)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def deliver(self, report_payload, *, org_id: str, scan_id: str):
        self.calls.append((org_id, scan_id))
        return {"text": "posted"}


class _RaisingDelivery:
    """A fake slack_delivery whose deliver raises — the load-bearing best-effort case. (In prod the
    real SlackSurface1Delivery can't raise; this asserts the worker swallows even if it ever did.)"""

    def __init__(self) -> None:
        self.calls = 0

    async def deliver(self, report_payload, *, org_id: str, scan_id: str):
        self.calls += 1
        raise RuntimeError("delivery exploded")


def _spec() -> ScanSpec:
    return ScanSpec(target=TargetSpec(provider="openai", model="gpt-4o"))


async def _seed(store: InMemoryScanStore, queue: InMemoryJobQueue, spec: ScanSpec) -> str:
    scan_id = _new_id("scan")
    await store.create(ScanRecord(scan_id=scan_id, org_id=_ORG, target=spec.target.redacted()))
    await queue.enqueue(scan_id, spec, org_id=_ORG)
    return scan_id


@pytest.mark.asyncio
async def test_worker_auto_fire_triggers_on_completed_surface1_scan():
    """run_once on a Surface-1 scan: finalizes COMPLETED, normal path intact, deliver called once
    with the right org_id/scan_id."""
    store, queue = InMemoryScanStore(), InMemoryJobQueue()
    scan_id = await _seed(store, queue, _spec())
    delivery = _RecordingDelivery()

    worker = ScanWorker(store, queue, _Surface1Engine(), slack_delivery=delivery)
    handled = await worker.run_once()

    assert handled is True
    rec = await store.get(scan_id, org_id=_ORG)
    # Normal finalize path is unaffected by the auto-fire.
    assert rec is not None
    assert rec.status == ScanStatus.COMPLETED
    assert rec.progress == 100
    assert rec.n_breaches == 3
    assert rec.report_id is not None
    # The job acked (not left for redelivery).
    assert queue._jobs == {}
    # Auto-fire fired exactly once with this scan's identity.
    assert delivery.calls == [(_ORG, scan_id)]


@pytest.mark.asyncio
async def test_worker_auto_fire_with_real_delivery_posts_to_security_channel():
    """End-to-end through run_once with the REAL SlackSurface1Delivery + a fake sender — proves the
    worker wiring posts to the security channel for a Surface-1 scan."""
    store, queue = InMemoryScanStore(), InMemoryJobQueue()
    scan_id = await _seed(store, queue, _spec())
    agent_store = InMemorySlackAgentStore()
    _register_agent(agent_store)
    sender = _RecordingSender()
    delivery = SlackSurface1Delivery(
        agent_store=agent_store, sender=sender, snapshot_store=InMemorySnapshotStore()
    )

    worker = ScanWorker(store, queue, _Surface1Engine(), slack_delivery=delivery)
    handled = await worker.run_once()

    assert handled is True
    rec = await store.get(scan_id, org_id=_ORG)
    assert rec.status == ScanStatus.COMPLETED
    assert len(sender.sends) == 1
    channel, _ = sender.sends[0]
    assert channel == _SECURITY_CHANNEL and channel != _SANDBOX_CHANNEL


@pytest.mark.asyncio
async def test_worker_auto_fire_failure_does_not_fail_the_scan():
    """LOAD-BEARING: a delivery that raises must NOT fail or lose the already-finalized COMPLETED
    scan, and the job must still ack. This is the invariant that protects paid scans."""
    store, queue = InMemoryScanStore(), InMemoryJobQueue()
    scan_id = await _seed(store, queue, _spec())
    delivery = _RaisingDelivery()

    worker = ScanWorker(store, queue, _Surface1Engine(), slack_delivery=delivery)
    handled = await worker.run_once()  # must NOT raise

    assert handled is True
    assert delivery.calls == 1  # delivery was attempted...
    rec = await store.get(scan_id, org_id=_ORG)
    # ...and the failure was swallowed: the scan still finalizes COMPLETED.
    assert rec is not None
    assert rec.status == ScanStatus.COMPLETED
    assert rec.progress == 100
    assert rec.n_breaches == 3
    assert rec.report_id is not None
    # The job is acked despite the delivery failure (not redelivered).
    assert queue._jobs == {}


@pytest.mark.asyncio
async def test_worker_no_delivery_is_byte_identical_normal_scan():
    """slack_delivery=None ⇒ a normal scan completes with no delivery attempted and no error
    (the default-constructed worker behaves exactly as before this feature)."""
    store, queue = InMemoryScanStore(), InMemoryJobQueue()
    scan_id = await _seed(store, queue, _spec())

    worker = ScanWorker(store, queue, _PlainEngine())  # no slack_delivery
    handled = await worker.run_once()

    assert handled is True
    rec = await store.get(scan_id, org_id=_ORG)
    assert rec is not None
    assert rec.status == ScanStatus.COMPLETED
    assert rec.progress == 100
    assert rec.n_breaches == 1
    assert rec.report_id is not None
    assert queue._jobs == {}
