"""Phase-1 adapter tool-contract conformance (over the MockAdapter, DB-free / network-free).

Pins the shared spine that the OpenAI + Anthropic adapters compose against:
  (a) the ``tools=None`` path is unchanged (a plain text turn, no tool calls);
  (b) passing ``tools=[AgentToolSpec(...)]`` never errors, and a scripted mock returns
      ``ToolCallBlock``s that surface via ``InvocationResult.tool_calls`` + ``StopReason.TOOL_CALL``;
  (c) ``model_specs.supports_tools`` is the capability source: True for a real function-calling model,
      False (fail-safe) for an unknown model and for meta-llama/*.
"""

from __future__ import annotations

import pytest

from rogue.adapters import model_specs
from rogue.adapters.base import AdapterConfig
from rogue.adapters.mock import MockAdapter
from rogue.core.content_blocks import ToolCallBlock
from rogue.core.invocation import StopReason
from rogue.core.message import CanonicalMessage
from rogue.schemas import AgentToolSpec
from rogue.schemas.agent_tool import ToolCategory


def _user(text: str) -> CanonicalMessage:
    return CanonicalMessage.user(text)


def _tool() -> AgentToolSpec:
    return AgentToolSpec(
        name="read_file",
        description="Read a file from disk.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        category=ToolCategory.SOURCE,
    )


# --- (a) tools=None path is unchanged -----------------------------------------------------------


@pytest.mark.asyncio
async def test_tools_none_path_unchanged():
    mock = MockAdapter()
    baseline = await mock.invoke([_user("hello")])
    with_none = await MockAdapter().invoke([_user("hello")], tools=None, tool_choice=None)

    assert baseline.stop_reason == StopReason.COMPLETE
    assert with_none.stop_reason == StopReason.COMPLETE
    assert baseline.tool_calls == [] == with_none.tool_calls
    assert baseline.text == with_none.text


# --- (b) passing tools + a scripted tool-call turn ----------------------------------------------


@pytest.mark.asyncio
async def test_passing_tools_does_not_error():
    """A tool spec offered to a non-scripted mock is accepted and simply produces a text turn."""
    result = await MockAdapter().invoke([_user("hi")], tools=[_tool()], tool_choice="auto")
    assert result.stop_reason == StopReason.COMPLETE
    assert result.tool_calls == []


@pytest.mark.asyncio
async def test_scripted_tool_call_surfaces():
    call = ToolCallBlock(id="call_1", name="read_file", arguments={"path": "/etc/passwd"})
    mock = MockAdapter(scripted_tool_calls=[[call]])

    result = await mock.invoke([_user("read the file")], tools=[_tool()])

    assert result.stop_reason == StopReason.TOOL_CALL
    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert (tc.id, tc.name, tc.arguments) == ("call_1", "read_file", {"path": "/etc/passwd"})


@pytest.mark.asyncio
async def test_scripted_multi_turn_loop():
    """Turn 1 emits a tool call; the final (empty) turn answers with text — a deterministic loop."""
    call = ToolCallBlock(id="c1", name="read_file", arguments={"path": "a.txt"})
    mock = MockAdapter(scripted_tool_calls=[[call], []])

    turn1 = await mock.invoke([_user("go")], tools=[_tool()])
    assert turn1.stop_reason == StopReason.TOOL_CALL
    assert [b.name for b in turn1.tool_calls] == ["read_file"]

    turn2 = await mock.invoke([_user("continue")], tools=[_tool()])
    assert turn2.stop_reason == StopReason.COMPLETE
    assert turn2.tool_calls == []

    # Running off the end of the script keeps returning text turns.
    turn3 = await mock.invoke([_user("again")], tools=[_tool()])
    assert turn3.stop_reason == StopReason.COMPLETE


@pytest.mark.asyncio
async def test_scripted_via_config_extra():
    """The script can also ride in on AdapterConfig.extra (constructed purely from a config)."""
    call = ToolCallBlock(id="c9", name="read_file", arguments={})
    cfg = AdapterConfig(model="mock/mock-1", extra={"scripted_tool_calls": [[call]]})
    result = await MockAdapter(cfg).invoke([_user("x")], tools=[_tool()])
    assert result.stop_reason == StopReason.TOOL_CALL
    assert result.tool_calls[0].id == "c9"


@pytest.mark.asyncio
async def test_seed_is_accepted_and_recorded():
    result = await MockAdapter().invoke([_user("hi")], seed=1234)
    assert result.raw_response["seed"] == 1234


def test_provider_schema_is_the_only_crossing_subset():
    """Sanity: only {name, description, parameters} crosses the seam — never forbidden/backend_kind."""
    spec = AgentToolSpec(
        name="send_email", description="send", parameters={}, category=ToolCategory.SINK,
        forbidden=True,
    )
    assert set(spec.provider_schema()) == {"name", "description", "parameters"}


# --- (c) model_specs.supports_tools is the capability source -------------------------------------


def test_supports_tools_true_for_real_function_calling_models():
    assert model_specs.supports_tools("openai/gpt-5.4") is True
    assert model_specs.supports_tools("anthropic/claude-sonnet-4-6") is True
    assert model_specs.supports_tools("google/gemini-3.1-flash-lite") is True
    assert model_specs.supports_tools("mistralai/mistral-small-2603") is True


def test_supports_tools_false_fail_safe():
    # Unknown model → False (fail-safe), and meta-llama is deliberately left at default False.
    assert model_specs.supports_tools("who/knows-9000") is False
    assert model_specs.supports_tools("meta-llama/llama-3.1-8b-instruct") is False
