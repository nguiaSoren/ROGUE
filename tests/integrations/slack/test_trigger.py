"""§3 EXIT GATE — sandbox-cycle trigger (`run_sandbox_cycle`).

Gate (verbatim): "with fake corpus + fake ScanService, run_sandbox_cycle selects only newly-landed
families for a registered agent and enqueues exactly one sandbox scan per agent (idempotent on
replay). No network, no paid call."

All OFFLINE: an in-memory `corpus=` (no DB), an `InMemorySlackAgentStore`, and a `FakeScanService`
that records `create_scan` calls and honors idempotency keyed on `(org_id, idempotency_key)`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from rogue.integrations.slack import (
    InMemorySlackAgentStore,
    SlackAgentTarget,
    run_sandbox_cycle,
)
from rogue.platform.schemas import ScanRecord, ScanSpec
from rogue.schemas import AttackFamily, AttackPrimitive, SourceProvenance
from rogue.schemas.governance import BreachType, ClientPolicy, PolicyRule

_NOW = datetime(2026, 6, 9, 23, 0, 0, tzinfo=timezone.utc)
_CUTOFF = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fakes / builders
# ---------------------------------------------------------------------------
def _primitive(pid: str, *, family: AttackFamily, discovered_at: datetime) -> AttackPrimitive:
    full_id = f"prim-{pid}-0000000000"
    return AttackPrimitive(
        primitive_id=full_id,
        family=family,
        vector="user_turn",
        title=f"test primitive {pid}",
        short_description="synthetic newly-landed test primitive",
        payload_template="Payload: {target_behavior}",
        reproducibility_score=7,
        sources=[
            SourceProvenance(
                url="https://example.com/fixture",
                source_type="other",
                fetched_at=datetime(2026, 6, 9, tzinfo=timezone.utc),
                archive_hash="sha256:fixture",
                bright_data_product="fixture",
            )
        ],
        discovered_at=discovered_at,
        base_severity="high",
        severity_rationale="synthetic test primitive",
    )


class _MockDecomposer:
    """A `DecomposeAgent` that returns a fixed one-rule policy — no live model call.

    The single rule is enough for the trigger to attach a non-empty `ClientPolicy` to the
    policy-mode spec; the engine (not this trigger) does the per-rule re-aim, so the test only
    needs a valid policy with ≥1 rule.
    """

    def decompose(self, source_text: str) -> ClientPolicy:
        return ClientPolicy(
            policy_id="POL-mock",
            customer_id="unassigned",
            rules=[
                PolicyRule(
                    rule_id="R1",
                    text="Do not hand over operational harm content or hijack the agent's role.",
                    breach_type=BreachType.CAPABILITY_TRANSFER,
                    elicitation_target="operational harm content",
                    consummation_definition="the agent produces actionable harmful instructions",
                    forbidden_examples=["Here are the steps: ..."],
                    allowed_examples=["I can't help with that."],
                )
            ],
            source_text=source_text,
        )


@dataclass
class _Call:
    spec: ScanSpec
    org_id: str
    actor: str | None
    idempotency_key: str | None


@dataclass
class FakeScanService:
    """Records `create_scan` calls; honors idempotency keyed on (org_id, idempotency_key).

    On a repeat key the stored record is returned and NO new call is appended — mirroring the
    durable `ScanService.create_scan` contract the trigger relies on for replay-idempotency.
    """

    calls: list[_Call] = field(default_factory=list)
    _by_key: dict[tuple[str, str | None], ScanRecord] = field(default_factory=dict)
    _seq: int = 0

    async def create_scan(self, spec, *, org_id, actor=None, idempotency_key=None) -> ScanRecord:
        key = (org_id, idempotency_key)
        if idempotency_key is not None and key in self._by_key:
            return self._by_key[key]
        self._seq += 1
        rec = ScanRecord(scan_id=f"scan-{self._seq:04d}", org_id=org_id)
        self.calls.append(_Call(spec=spec, org_id=org_id, actor=actor, idempotency_key=idempotency_key))
        if idempotency_key is not None:
            self._by_key[key] = rec
        return rec


def _target(agent_name: str, *, org_id: str = "orgA", model: str = "gpt-5.4-nano") -> SlackAgentTarget:
    return SlackAgentTarget.create(
        org_id=org_id,
        agent_name=agent_name,
        workspace=f"ws-{agent_name}",
        base_url=f"https://{agent_name}.acme.example/v1",
        model=model,
        system_prompt=f"You are the {agent_name} Slack agent.",
        declared_tools=["web_fetch"],
        sandbox_channel_id="C-SANDBOX-001",
        security_channel_id="C-SECURITY-001",
    )


def _mixed_corpus() -> list[AttackPrimitive]:
    """Two recent (post-cutoff) primitives across two families + one old (pre-cutoff) primitive."""
    return [
        _primitive("recent-a", family=AttackFamily.ROLE_HIJACK, discovered_at=datetime(2026, 6, 9, 18, tzinfo=timezone.utc)),
        _primitive("recent-b", family=AttackFamily.TOOL_USE_HIJACK, discovered_at=datetime(2026, 6, 9, 20, tzinfo=timezone.utc)),
        _primitive("old-c", family=AttackFamily.DAN_PERSONA, discovered_at=datetime(2026, 6, 1, tzinfo=timezone.utc)),
    ]


# ---------------------------------------------------------------------------
# THE GATE: one scan per agent; correct selection/target; idempotent on replay.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_one_scan_per_agent_with_newly_landed_selection():
    store = InMemorySlackAgentStore()
    t1 = _target("support-bot", model="gpt-5.4-nano")
    t2 = _target("ops-bot", model="claude-haiku-4-5")
    store.put(t1)
    store.put(t2)
    corpus = _mixed_corpus()
    fake = FakeScanService()

    records = await run_sandbox_cycle(
        "orgA",
        agent_store=store,
        scan_service=fake,
        since=_CUTOFF,
        now=_NOW,
        corpus=corpus,
        decomposer=_MockDecomposer(),
    )

    # Exactly ONE create_scan per agent (2 agents → 2 calls / 2 records).
    assert len(records) == 2
    assert len(fake.calls) == 2

    # Expected selection: sorted ids of the two RECENT primitives; the OLD one is excluded.
    expected_attacks = sorted(
        p.primitive_id for p in corpus if p.discovered_at >= _CUTOFF
    )
    assert len(expected_attacks) == 2

    by_endpoint = {c.spec.target.endpoint: c for c in fake.calls}
    assert set(by_endpoint) == {t1.base_url, t2.base_url}

    for tgt in (t1, t2):
        call = by_endpoint[tgt.base_url]
        assert call.spec.attacks == expected_attacks  # old primitive excluded
        assert call.spec.mode == "policy"
        assert call.spec.policy is not None
        assert len(call.spec.policy.rules) >= 1
        assert call.spec.target.endpoint == tgt.base_url
        assert call.spec.target.model == tgt.model
        assert call.actor == "slack-sandbox-cycle"


@pytest.mark.asyncio
async def test_idempotent_on_replay():
    """Load-bearing gate assertion: a second identical cycle enqueues nothing new."""
    store = InMemorySlackAgentStore()
    store.put(_target("support-bot"))
    store.put(_target("ops-bot"))
    corpus = _mixed_corpus()
    fake = FakeScanService()

    first = await run_sandbox_cycle(
        "orgA",
        agent_store=store,
        scan_service=fake,
        since=_CUTOFF,
        now=_NOW,
        corpus=corpus,
        decomposer=_MockDecomposer(),
    )
    assert len(fake.calls) == 2

    second = await run_sandbox_cycle(
        "orgA",
        agent_store=store,
        scan_service=fake,
        since=_CUTOFF,
        now=_NOW,
        corpus=corpus,
        decomposer=_MockDecomposer(),
    )

    # No NEW create_scan calls were recorded; the same records come back.
    assert len(fake.calls) == 2  # unchanged
    assert [r.scan_id for r in second] == [r.scan_id for r in first]


# ---------------------------------------------------------------------------
# Skip path: no newly-landed families ⇒ nothing enqueued.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_skip_when_no_newly_landed_families():
    store = InMemorySlackAgentStore()
    store.put(_target("support-bot"))
    store.put(_target("ops-bot"))
    # Corpus has only OLD primitives (all strictly before the cutoff).
    old_only = [
        _primitive("o1", family=AttackFamily.ROLE_HIJACK, discovered_at=datetime(2026, 6, 1, tzinfo=timezone.utc)),
        _primitive("o2", family=AttackFamily.TOOL_USE_HIJACK, discovered_at=datetime(2026, 5, 1, tzinfo=timezone.utc)),
    ]
    fake = FakeScanService()

    records = await run_sandbox_cycle(
        "orgA",
        agent_store=store,
        scan_service=fake,
        since=_CUTOFF,
        now=_NOW,
        corpus=old_only,
        decomposer=_MockDecomposer(),
    )

    assert records == []
    assert fake.calls == []


# ---------------------------------------------------------------------------
# Org scoping: an agent in org B is not scanned for org A.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_org_scoping_excludes_other_orgs():
    store = InMemorySlackAgentStore()
    a_agent = _target("a-bot", org_id="orgA")
    b_agent = _target("b-bot", org_id="orgB")
    store.put(a_agent)
    store.put(b_agent)
    corpus = _mixed_corpus()
    fake = FakeScanService()

    records = await run_sandbox_cycle(
        "orgA",
        agent_store=store,
        scan_service=fake,
        since=_CUTOFF,
        now=_NOW,
        corpus=corpus,
        decomposer=_MockDecomposer(),
    )

    # Only orgA's agent is scanned; orgB's endpoint never appears.
    assert len(records) == 1
    assert len(fake.calls) == 1
    assert fake.calls[0].org_id == "orgA"
    assert fake.calls[0].spec.target.endpoint == a_agent.base_url
    assert b_agent.base_url not in {c.spec.target.endpoint for c in fake.calls}


# ---------------------------------------------------------------------------
# Policy-derivation skip: an agent with no forbidden_topics AND no system_prompt
# (ensure_client_policy raises ValueError) is logged and skipped — no scan, no crash.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_skip_agent_with_no_derivable_policy():
    store = InMemorySlackAgentStore()
    # A normal agent (derivable policy) and a policy-less one (empty system_prompt + no topics).
    ok = _target("ok-bot")
    no_policy = SlackAgentTarget.create(
        org_id="orgA",
        agent_name="bare-bot",
        workspace="ws-bare-bot",
        base_url="https://bare-bot.acme.example/v1",
        model="gpt-5.4-nano",
        system_prompt="",  # nothing to decompose ...
        forbidden_topics=[],  # ... and no forbidden topics either
        sandbox_channel_id="C-SANDBOX-001",
        security_channel_id="C-SECURITY-001",
    )
    store.put(ok)
    store.put(no_policy)
    corpus = _mixed_corpus()
    fake = FakeScanService()

    records = await run_sandbox_cycle(
        "orgA",
        agent_store=store,
        scan_service=fake,
        since=_CUTOFF,
        now=_NOW,
        corpus=corpus,
        decomposer=_MockDecomposer(),
    )

    # Only the derivable agent is scanned; the policy-less one is skipped (no scan, no raise).
    assert len(records) == 1
    assert len(fake.calls) == 1
    assert fake.calls[0].spec.target.endpoint == ok.base_url
    assert no_policy.base_url not in {c.spec.target.endpoint for c in fake.calls}
