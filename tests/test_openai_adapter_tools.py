"""Unit tests for the OpenAI-compat adapter's tool-calling surface (agent harness Phase 1).

All network-free: the wire translation (`_tools_to_openai`), the response parse path
(`_parse_tool_calls`), the `_to_openai_messages` M1 fix, and the `tools=None` byte-identical
request are all exercised against fakes / direct method calls. See `test_adapters_openai_compat.py`
for the broader adapter suite; this file is scoped to the tool seam.
"""

from __future__ import annotations

import pytest

from rogue.adapters import model_specs
from rogue.adapters.base import AdapterConfig
from rogue.adapters.openai import OpenAIAdapter
from rogue.adapters.openai_compat import MALFORMED_ARGS_KEY
from rogue.core import (
    CanonicalMessage,
    MessageRole,
    StopReason,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from rogue.schemas import AgentToolSpec
from rogue.schemas.agent_tool import ToolCategory, ToolSensitivity

PRICED_MODEL = "openai/gpt-5.4-nano"


# --------------------------------------------------------------------------------------------------
# Fakes (mirror test_adapters_openai_compat.py, extended with tool_calls on the message)
# --------------------------------------------------------------------------------------------------


class _FakeFunction:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, id: str, name: str, arguments: str):
        self.id = id
        self.type = "function"
        self.function = _FakeFunction(name, arguments)


class _FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, message: _FakeMessage, finish_reason: str | None):
        self.message = message
        self.finish_reason = finish_reason


class _FakeUsage:
    def __init__(self, prompt_tokens=5, completion_tokens=3):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeResponse:
    def __init__(self, message: _FakeMessage, finish_reason="stop"):
        self.choices = [_FakeChoice(message, finish_reason)]
        self.usage = _FakeUsage()

    def model_dump(self) -> dict:
        return {"id": "resp_1"}


class _FakeCompletions:
    def __init__(self, parent):
        self._parent = parent

    async def create(self, **kwargs):
        self._parent.last_create_kwargs = kwargs
        return self._parent.response


class _FakeChat:
    def __init__(self, parent):
        self.completions = _FakeCompletions(parent)


class FakeClient:
    def __init__(self, response: _FakeResponse):
        self.response = response
        self.last_create_kwargs: dict | None = None
        self.chat = _FakeChat(self)


def _adapter(client: FakeClient, model: str = PRICED_MODEL) -> OpenAIAdapter:
    return OpenAIAdapter(AdapterConfig(model=model, extra={"client": client}))


def _tool(name: str = "read_file") -> AgentToolSpec:
    return AgentToolSpec(
        name=name,
        description=f"{name} description",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        category=ToolCategory.SOURCE,
        sensitivity=ToolSensitivity.SENSITIVE,
        forbidden=True,  # harness-internal: must NOT cross the seam
    )


def _user(text: str = "hi") -> CanonicalMessage:
    return CanonicalMessage(role=MessageRole.USER, content=[TextBlock(text=text)])


# --------------------------------------------------------------------------------------------------
# _tools_to_openai — spec -> OpenAI function wire shape
# --------------------------------------------------------------------------------------------------


def test_tools_to_openai_shape_and_no_harness_leak():
    wire = OpenAIAdapter._tools_to_openai([_tool("send_email")])
    assert wire == [
        {
            "type": "function",
            "function": {
                "name": "send_email",
                "description": "send_email description",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
        }
    ]
    # forbidden / backend_kind / category / sensitivity must never appear on the wire.
    blob = repr(wire)
    for leaked in ("forbidden", "backend_kind", "category", "sensitivity", "source"):
        assert leaked not in blob


# --------------------------------------------------------------------------------------------------
# tools=None byte-identical request (shared contract §1)
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tools_none_request_identical_to_baseline():
    msg = _FakeMessage(content="ok")
    a = _adapter(FakeClient(_FakeResponse(msg)))
    b = _adapter(FakeClient(_FakeResponse(msg)))

    await a.invoke([_user()], temperature=0.3, max_output_tokens=42)
    await b.invoke([_user()], temperature=0.3, max_output_tokens=42, tools=None, tool_choice=None)

    assert a.config.extra["client"].last_create_kwargs == b.config.extra["client"].last_create_kwargs
    # And no tool keys leaked into the request.
    assert "tools" not in a.config.extra["client"].last_create_kwargs
    assert "tool_choice" not in a.config.extra["client"].last_create_kwargs


@pytest.mark.asyncio
async def test_empty_tool_list_is_also_identical():
    """An explicit empty list == None: still a byte-identical no-tools body."""
    client = FakeClient(_FakeResponse(_FakeMessage(content="ok")))
    a = _adapter(client)
    await a.invoke([_user()], tools=[])
    assert "tools" not in client.last_create_kwargs


@pytest.mark.asyncio
async def test_tools_and_tool_choice_reach_the_request():
    client = FakeClient(_FakeResponse(_FakeMessage(content="ok")))
    a = _adapter(client)
    await a.invoke([_user()], tools=[_tool()], tool_choice="required")
    sent = client.last_create_kwargs
    assert sent["tools"][0]["function"]["name"] == "read_file"
    assert sent["tool_choice"] == "required"


# --------------------------------------------------------------------------------------------------
# _parse_tool_calls — response -> ToolCallBlock, in order, with TextBlock
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_tool_calls_into_blocks_in_order():
    message = _FakeMessage(
        content="let me look",
        tool_calls=[
            _FakeToolCall("call_1", "read_file", '{"path": "/etc/passwd"}'),
            _FakeToolCall("call_2", "send_email", '{"to": "a@b.c"}'),
        ],
    )
    client = FakeClient(_FakeResponse(message, finish_reason="tool_calls"))
    result = await _adapter(client).invoke([_user()])

    # Text first, then tool calls, in provider order.
    assert isinstance(result.content[0], TextBlock)
    assert result.content[0].text == "let me look"
    assert [b.name for b in result.content[1:]] == ["read_file", "send_email"]
    assert result.tool_calls[0].id == "call_1"
    assert result.tool_calls[0].arguments == {"path": "/etc/passwd"}
    assert result.stop_reason is StopReason.TOOL_CALL


@pytest.mark.asyncio
async def test_tool_call_without_text_omits_empty_textblock():
    message = _FakeMessage(
        content=None,
        tool_calls=[_FakeToolCall("call_1", "read_file", "{}")],
    )
    client = FakeClient(_FakeResponse(message, finish_reason="tool_calls"))
    result = await _adapter(client).invoke([_user()])
    assert len(result.content) == 1
    assert isinstance(result.content[0], ToolCallBlock)
    assert result.text == ""


@pytest.mark.asyncio
async def test_no_tool_calls_preserves_single_textblock():
    """A plain text response is unchanged: exactly one (possibly empty) TextBlock."""
    client = FakeClient(_FakeResponse(_FakeMessage(content="just text")))
    result = await _adapter(client).invoke([_user()])
    assert len(result.content) == 1
    assert isinstance(result.content[0], TextBlock)
    assert result.content[0].text == "just text"


@pytest.mark.asyncio
async def test_malformed_arguments_recorded_not_leaked():
    message = _FakeMessage(
        content=None,
        tool_calls=[_FakeToolCall("call_1", "read_file", "{not valid json")],
    )
    client = FakeClient(_FakeResponse(message, finish_reason="tool_calls"))
    result = await _adapter(client).invoke([_user()])
    block = result.tool_calls[0]
    # arguments stays a plain dict; malformed-ness is detectable + the raw payload preserved.
    assert isinstance(block.arguments, dict)
    assert MALFORMED_ARGS_KEY in block.arguments
    assert block.arguments[MALFORMED_ARGS_KEY] == "{not valid json"


def test_parse_tool_calls_non_object_json_is_malformed():
    # Valid JSON, but not an object (a bare array) — not usable as arguments → malformed.
    message = _FakeMessage(tool_calls=[_FakeToolCall("c", "f", "[1, 2, 3]")])
    blocks = OpenAIAdapter._parse_tool_calls(message)
    assert blocks[0].arguments == {MALFORMED_ARGS_KEY: "[1, 2, 3]"}


def test_parse_tool_calls_empty_when_none():
    assert OpenAIAdapter._parse_tool_calls(_FakeMessage(content="x", tool_calls=None)) == []


# --------------------------------------------------------------------------------------------------
# _to_openai_messages — M1: tool-result-only message must not emit an empty tool message
# --------------------------------------------------------------------------------------------------


def test_tool_result_only_message_emits_no_empty_tool_message():
    adapter = _adapter(FakeClient(_FakeResponse(_FakeMessage(content="x"))))
    messages = [
        CanonicalMessage(role=MessageRole.USER, content=[TextBlock(text="do it")]),
        CanonicalMessage(
            role=MessageRole.ASSISTANT,
            content=[ToolCallBlock(id="call_1", name="read_file", arguments={"path": "/x"})],
        ),
        # A pure tool-result turn — the M1 regression case.
        CanonicalMessage(
            role=MessageRole.TOOL,
            content=[ToolResultBlock(tool_call_id="call_1", result="file contents")],
        ),
    ]
    out = adapter._to_openai_messages(messages)

    tool_msgs = [m for m in out if m["role"] == "tool"]
    assert len(tool_msgs) == 1  # exactly one, from the ToolResultBlock
    # The single tool message is well-formed: has a tool_call_id and real content.
    assert tool_msgs[0]["tool_call_id"] == "call_1"
    assert tool_msgs[0]["content"] == "file contents"
    # No spurious empty/id-less tool message anywhere.
    assert all("tool_call_id" in m and m["content"] for m in tool_msgs)


def test_multiple_tool_results_each_get_a_message_no_trailing_empty():
    adapter = _adapter(FakeClient(_FakeResponse(_FakeMessage(content="x"))))
    messages = [
        CanonicalMessage(
            role=MessageRole.TOOL,
            content=[
                ToolResultBlock(tool_call_id="c1", result="r1"),
                ToolResultBlock(tool_call_id="c2", result="r2"),
            ],
        ),
    ]
    out = adapter._to_openai_messages(messages)
    assert out == [
        {"role": "tool", "tool_call_id": "c1", "content": "r1"},
        {"role": "tool", "tool_call_id": "c2", "content": "r2"},
    ]


# --------------------------------------------------------------------------------------------------
# capabilities().supports_tools delegates to model_specs
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capabilities_supports_tools_delegates(monkeypatch):
    adapter = _adapter(FakeClient(_FakeResponse(_FakeMessage(content="x"))))

    monkeypatch.setattr(model_specs, "supports_tools", lambda model: False)
    caps = await adapter.capabilities()
    assert caps.supports_tools is False
    assert caps.supports_function_calling is False

    monkeypatch.setattr(model_specs, "supports_tools", lambda model: True)
    caps = await adapter.capabilities()
    assert caps.supports_tools is True
    assert caps.supports_function_calling is True


@pytest.mark.asyncio
async def test_capabilities_unknown_model_reports_no_tools():
    """An unknown model must not over-claim tool support (the fixed over-claim)."""
    adapter = _adapter(
        FakeClient(_FakeResponse(_FakeMessage(content="x"))), model="mystery/unlisted-model"
    )
    caps = await adapter.capabilities()
    assert caps.supports_tools is False
