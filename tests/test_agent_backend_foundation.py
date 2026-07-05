"""Phase-2 foundation gate: canary minting + AgentRunContext + ToolBackend protocol.

Locks the properties the honeytoken/emulator backends depend on: canaries match the
judge's secret regexes (so signal (b) fires), are neutral (M6/F7), and are
deterministic-given-run_secret but unguessable-without it (H4). No DB, no network.
"""

from __future__ import annotations

from rogue.reproduce.agent import (
    CANARY_KINDS,
    AgentRunContext,
    InjectionPayload,
    is_neutral,
    mint_canary,
    new_run_secret,
)
from rogue.reproduce.agent.backends import ToolBackend
from rogue.reproduce.judge import (
    _RE_AWS_AKIA,
    _RE_BEARER,
    _RE_EMAIL,
    _RE_OPENAI_KEY,
    _RE_PRIVATE_KEY,
    _RE_SSN,
)
from rogue.schemas import (
    AgentToolSpec,
    InjectionGoal,
    InjectionGoalKind,
    PlantedSecret,
    ToolCategory,
)

_RUN_SECRET = "a" * 64  # a fixed run_secret for deterministic assertions


def test_every_canary_kind_matches_its_judge_regex():
    checks = {
        "aws_akia": _RE_AWS_AKIA,
        "bearer": _RE_BEARER,
        "api_key": _RE_OPENAI_KEY,
        "private_key": _RE_PRIVATE_KEY,
        "email": _RE_EMAIL,
        "pii": _RE_SSN,
    }
    for kind, rx in checks.items():
        val = mint_canary(_RUN_SECRET, "sec-1", kind)
        assert rx.search(val), f"{kind} canary {val!r} does not match its judge regex"


def test_all_kinds_covered():
    assert set(CANARY_KINDS) == {"aws_akia", "bearer", "api_key", "private_key", "email", "pii"}


def test_canaries_are_neutral_no_project_tell():
    # review M6/F7 — no rogue/canary/honeytoken/.test literal in any minted canary
    for kind in CANARY_KINDS:
        val = mint_canary(_RUN_SECRET, "sec-x", kind)
        assert is_neutral(val), f"{kind} canary leaked an identifying/gameable token: {val!r}"


def test_deterministic_given_run_secret():
    for kind in CANARY_KINDS:
        assert mint_canary(_RUN_SECRET, "sec-1", kind) == mint_canary(_RUN_SECRET, "sec-1", kind)


def test_unguessable_across_run_secrets_and_ids():
    other = "b" * 64
    for kind in CANARY_KINDS:
        assert mint_canary(_RUN_SECRET, "sec-1", kind) != mint_canary(other, "sec-1", kind)
        assert mint_canary(_RUN_SECRET, "sec-1", kind) != mint_canary(_RUN_SECRET, "sec-2", kind)


def test_run_secret_is_high_entropy_and_unique():
    a, b = new_run_secret(), new_run_secret()
    assert a != b
    assert len(a) >= 64  # 256-bit hex


def test_context_helpers():
    spec = AgentToolSpec(
        name="transfer_funds", description="move money", category=ToolCategory.ACTION, forbidden=True
    )
    goal = InjectionGoal(
        goal_kind=InjectionGoalKind.INVOKE_TOOL, carrier_tool="read_email", target_tool="transfer_funds"
    )
    ctx = AgentRunContext(
        seed=7,
        run_secret=_RUN_SECRET,
        tool_specs={"transfer_funds": spec},
        injections=[InjectionPayload(injection_id="i1", carrier_tool="read_email", payload_text="…", goal=goal)],
    )
    assert ctx.spec_for("transfer_funds") is spec
    assert ctx.spec_for("nope") is None
    assert ctx.is_forbidden("transfer_funds") is True
    assert ctx.injection_for_tool("read_email").injection_id == "i1"
    assert ctx.injection_for_tool("other") is None
    # deterministic RNG
    assert ctx.rng().random() == ctx.rng().random()
    ctx.record_planted_secret(
        PlantedSecret(secret_id="s1", kind="aws_akia", value="AKIA…", planted_in="tool_return")
    )
    assert len(ctx.planted_secrets) == 1


def test_toolbackend_protocol_is_runtime_checkable():
    # a non-implementer must not satisfy the protocol
    assert not isinstance(object(), ToolBackend)
