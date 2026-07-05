"""Phase-2 integration: HybridBackend dispatch (honeytoken vs emulator vs reject).

Exercises the full routing table against the real honeytoken registry + an injected
fake emulator (no network): declared+known → honeytoken, declared+unstubbed → emulator,
undeclared → reject (F8), plus the canonical/sensitivity helpers the Phase-4 judge uses.
"""

from __future__ import annotations

import pytest

from rogue.core.content_blocks import ToolCallBlock
from rogue.reproduce.agent.backends.emulator import EmulatorBackend
from rogue.reproduce.agent.backends.hybrid import HybridBackend
from rogue.reproduce.agent.context import AgentRunContext
from rogue.schemas import ToolBackendKind, ToolSensitivity

_RUN_SECRET = "c" * 64


def _ctx(declared: list[str], forbidden: list[str] | None = None, backend=None) -> AgentRunContext:
    """Build a ctx whose tool_specs mirror what the harness would resolve for `declared`."""
    backend = backend or HybridBackend()
    specs = backend.tool_specs(declared, forbidden or [])
    return AgentRunContext(seed=1, run_secret=_RUN_SECRET, tool_specs={s.name: s for s in specs})


def _call(name: str, args: dict | None = None, cid: str = "call-1") -> ToolCallBlock:
    return ToolCallBlock(id=cid, name=name, arguments=args or {})


async def _fake_emulate(messages, **kwargs):
    from rogue.core.invocation import InvocationResult
    from rogue.core.content_blocks import TextBlock

    return InvocationResult(content=[TextBlock(text='{"result": "emulated ok", "is_error": false}')])


@pytest.mark.asyncio
async def test_declared_known_routes_to_honeytoken():
    hy = HybridBackend()
    ctx = _ctx(["read_file"], backend=hy)  # SOURCE tool
    res = await hy.execute(_call("read_file"), ctx)
    assert res.backend_kind == ToolBackendKind.HONEYTOKEN
    assert res.provenance.canary_ids  # a canary was planted
    assert len(ctx.planted_secrets) == 1


@pytest.mark.asyncio
async def test_alias_of_declared_known_still_routes_to_honeytoken():
    hy = HybridBackend()
    ctx = _ctx(["read_file"], backend=hy)
    # the model calls an alias of the declared canonical tool
    res = await hy.execute(_call("get_file"), ctx)
    assert res.backend_kind == ToolBackendKind.HONEYTOKEN


@pytest.mark.asyncio
async def test_declared_unstubbed_routes_to_emulator():
    emu = EmulatorBackend(invoke_fn=_fake_emulate)
    hy = HybridBackend(emulator=emu)
    ctx = _ctx(["quantum_ledger_lookup"], backend=hy)  # custom tool, no stub
    assert "quantum_ledger_lookup" in ctx.tool_specs  # emulator offered it
    res = await hy.execute(_call("quantum_ledger_lookup"), ctx)
    assert res.backend_kind == ToolBackendKind.EMULATED


@pytest.mark.asyncio
async def test_undeclared_canonical_sensitive_tool_is_rejected_not_run():
    # config declares only a benign tool; model reaches for transfer_funds (F8)
    hy = HybridBackend()
    ctx = _ctx(["read_file"], backend=hy)
    res = await hy.execute(_call("transfer_funds", {"amount": 9999}), ctx)
    assert "not available" in res.result.lower()
    assert res.provenance.is_poisoned is False
    # the judge (Phase 4) can still see it was a canonical CRITICAL tool:
    assert hy.canonical_name("wire") == "transfer_funds"
    assert hy.sensitivity_of("transfer_funds") == ToolSensitivity.CRITICAL


@pytest.mark.asyncio
async def test_fully_invented_tool_is_rejected():
    hy = HybridBackend()  # no emulator
    ctx = _ctx(["read_file"], backend=hy)
    res = await hy.execute(_call("frobnicate_the_widget"), ctx)
    assert "not available" in res.result.lower()
    assert hy.canonical_name("frobnicate_the_widget") is None


def test_tool_specs_merges_known_and_unknown():
    emu = EmulatorBackend(invoke_fn=_fake_emulate)
    hy = HybridBackend(emulator=emu)
    specs = {s.name: s for s in hy.tool_specs(["read_file", "custom_x"], forbidden=["custom_x"])}
    assert specs["read_file"].backend_kind == ToolBackendKind.HONEYTOKEN
    assert specs["custom_x"].backend_kind == ToolBackendKind.EMULATED
    assert specs["custom_x"].forbidden is True  # forbidden stamped through the emulator path too


def test_declared_needs_emulator():
    hy = HybridBackend()
    assert hy.declared_needs_emulator(["read_file"]) is False
    assert hy.declared_needs_emulator(["read_file", "custom_x"]) is True
