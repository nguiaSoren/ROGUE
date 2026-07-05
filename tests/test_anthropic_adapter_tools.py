"""Tool-surface tests for :class:`rogue.adapters.anthropic.AnthropicAdapter` (Phase-1 harness).

These cover the agent-execution-harness slice the base tests don't: tool-spec translation into
Anthropic's ``input_schema`` wire shape, ``tool_choice`` mapping, ``tool_use`` response parsing into
:class:`ToolCallBlock`, the H8 ``tool``-role round-trip (Anthropic has no ``tool`` role — a result
rides a ``user`` turn as a ``tool_result`` block), the ``tools is None`` byte-identical guarantee, and
``capabilities().supports_tools`` delegating to ``model_specs``. Fully mocked — no network.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from rogue.adapters import model_specs
from rogue.adapters.anthropic import AnthropicAdapter
from rogue.adapters.base import AdapterConfig
from rogue.core import (
    CanonicalMessage,
    MessageRole,
    StopReason,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from rogue.schemas import AgentToolSpec, ToolCategory, ToolSensitivity


# --------------------------------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------------------------------


def _text_response(text: str = "hi", *, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=5, output_tokens=3),
        stop_reason=stop_reason,
        model_dump=lambda: {"stop_reason": stop_reason},
    )


def _tool_use_response(*, text: str | None = "let me check", stop_reason: str = "tool_use"):
    """A response that interleaves a text block then a tool_use block, in that order."""
    blocks = []
    if text is not None:
        blocks.append(SimpleNamespace(type="text", text=text))
    blocks.append(
        SimpleNamespace(
            type="tool_use", id="toolu_01", name="get_weather", input={"city": "Incheon"}
        )
    )
    return SimpleNamespace(
        content=blocks,
        usage=SimpleNamespace(input_tokens=8, output_tokens=6),
        stop_reason=stop_reason,
        model_dump=lambda: {"stop_reason": stop_reason},
    )


class FakeMessages:
    def __init__(self, response):
        self._response = response
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class FakeClient:
    def __init__(self, response):
        self.messages = FakeMessages(response)


def _adapter(client, model="anthropic/claude-haiku-4-5"):
    return AnthropicAdapter(AdapterConfig(model=model, extra={"client": client}))


def _tool(name="get_weather", **overrides) -> AgentToolSpec:
    kwargs = dict(
        name=name,
        description="Look up the weather for a city.",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
        category=ToolCategory.SINK,
        sensitivity=ToolSensitivity.BENIGN,
        forbidden=True,  # harness-internal; must NOT reach the provider request
    )
    kwargs.update(overrides)
    return AgentToolSpec(**kwargs)


# --------------------------------------------------------------------------------------------------
# tools -> Anthropic tool translation
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tools_translate_to_input_schema_shape():
    client = FakeClient(_text_response())
    await _adapter(client).invoke([CanonicalMessage.user("weather?")], tools=[_tool()])
    sent = client.messages.calls[0]["tools"]
    assert sent == [
        {
            "name": "get_weather",
            "description": "Look up the weather for a city.",
            "input_schema": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        }
    ]


@pytest.mark.asyncio
async def test_tool_translation_never_leaks_harness_internal_fields():
    client = FakeClient(_text_response())
    await _adapter(client).invoke([CanonicalMessage.user("x")], tools=[_tool()])
    sent = client.messages.calls[0]["tools"][0]
    # Only the three provider_schema keys cross the seam — no forbidden/backend_kind/sensitivity.
    assert set(sent.keys()) == {"name", "description", "input_schema"}


# --------------------------------------------------------------------------------------------------
# tool_choice mapping
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "choice,expected",
    [
        ("auto", {"type": "auto"}),
        ("any", {"type": "any"}),
        ("required", {"type": "any"}),
        ("none", {"type": "none"}),
        ("get_weather", {"type": "tool", "name": "get_weather"}),
    ],
)
async def test_tool_choice_mapping(choice, expected):
    client = FakeClient(_text_response())
    await _adapter(client).invoke(
        [CanonicalMessage.user("x")], tools=[_tool()], tool_choice=choice
    )
    assert client.messages.calls[0]["tool_choice"] == expected


@pytest.mark.asyncio
async def test_tool_choice_omitted_when_none_even_with_tools():
    client = FakeClient(_text_response())
    await _adapter(client).invoke([CanonicalMessage.user("x")], tools=[_tool()])
    assert "tool_choice" not in client.messages.calls[0]


# --------------------------------------------------------------------------------------------------
# tool_use response parsing
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_use_parsed_into_toolcallblock_in_order():
    client = FakeClient(_tool_use_response())
    result = await _adapter(client).invoke([CanonicalMessage.user("weather?")], tools=[_tool()])
    # Text block precedes the tool_use block, order preserved.
    assert [type(b) for b in result.content] == [TextBlock, ToolCallBlock]
    call = result.content[1]
    assert isinstance(call, ToolCallBlock)
    assert call.id == "toolu_01"
    assert call.name == "get_weather"
    assert call.arguments == {"city": "Incheon"}
    # tool_use stop reason normalizes to TOOL_CALL; the convenience accessor sees the call.
    assert result.stop_reason == StopReason.TOOL_CALL
    assert result.tool_calls == [call]


@pytest.mark.asyncio
async def test_tool_use_only_response_yields_single_toolcallblock():
    client = FakeClient(_tool_use_response(text=None))
    result = await _adapter(client).invoke([CanonicalMessage.user("weather?")], tools=[_tool()])
    assert [type(b) for b in result.content] == [ToolCallBlock]


# --------------------------------------------------------------------------------------------------
# H8 — Anthropic has no `tool` role; full round-trip
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_h8_tool_role_roundtrip_no_tool_role_on_wire():
    client = FakeClient(_text_response("done"))
    messages = [
        CanonicalMessage.system("you are helpful"),
        CanonicalMessage.user("what's the weather in Incheon?"),
        CanonicalMessage(
            role=MessageRole.ASSISTANT,
            content=[ToolCallBlock(id="toolu_01", name="get_weather", arguments={"city": "Incheon"})],
        ),
        CanonicalMessage(
            role=MessageRole.TOOL,
            content=[ToolResultBlock(tool_call_id="toolu_01", result="12C and clear")],
        ),
    ]
    await _adapter(client).invoke(messages, tools=[_tool()])
    wire = client.messages.calls[0]["messages"]

    # No message on the wire carries the (Anthropic-rejected) `tool` role.
    assert all(m["role"] != "tool" for m in wire)

    # Assistant turn carries a tool_use block (no empty leading text part for a pure tool call).
    assistant = wire[1]
    assert assistant["role"] == "assistant"
    assert assistant["content"] == [
        {"type": "tool_use", "id": "toolu_01", "name": "get_weather", "input": {"city": "Incheon"}}
    ]

    # The tool result rides a `user` turn as a tool_result block.
    tool_turn = wire[2]
    assert tool_turn["role"] == "user"
    assert tool_turn["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_01", "content": "12C and clear"}
    ]


# --------------------------------------------------------------------------------------------------
# tools=None byte-identical guarantee
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tools_none_request_is_byte_identical_to_pre_harness():
    client = FakeClient(_text_response())
    await _adapter(client).invoke([CanonicalMessage.user("hi")])
    call = client.messages.calls[0]
    # Exactly the pre-harness key set — no tools / tool_choice keys sneak in.
    assert set(call.keys()) == {"model", "max_tokens", "temperature", "system", "messages"}


@pytest.mark.asyncio
async def test_tools_none_matches_explicit_none():
    """Passing tools=None explicitly builds the same request as omitting it entirely."""
    c1 = FakeClient(_text_response())
    c2 = FakeClient(_text_response())
    await _adapter(c1).invoke([CanonicalMessage.user("hi")])
    await _adapter(c2).invoke([CanonicalMessage.user("hi")], tools=None, tool_choice="auto")
    assert c1.messages.calls[0] == c2.messages.calls[0]


# --------------------------------------------------------------------------------------------------
# capabilities delegation
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capabilities_supports_tools_delegates_to_model_specs():
    model = "anthropic/claude-haiku-4-5"
    caps = await _adapter(FakeClient(_text_response()), model=model).capabilities()
    assert caps.supports_tools == model_specs.supports_tools(model)
    assert caps.supports_tools is True  # this model's spec honors tools


@pytest.mark.asyncio
async def test_capabilities_supports_tools_false_for_unknown_model(monkeypatch):
    """A model with no spec entry (or supports_tools=False) is not over-claimed."""
    monkeypatch.setattr(model_specs, "supports_tools", lambda _m: False)
    caps = await _adapter(FakeClient(_text_response())).capabilities()
    assert caps.supports_tools is False
    assert caps.supports_function_calling is False
