"""Unit tests for :mod:`rogue.core.invocation` — StopReason / UsageMetrics / InvocationResult."""

from __future__ import annotations

import pytest

from rogue.core.content_blocks import TextBlock, ToolCallBlock
from rogue.core.invocation import InvocationResult, StopReason, UsageMetrics
from rogue.core.message import MessageRole


# ---- StopReason.from_provider ------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        ("stop", StopReason.COMPLETE),
        ("end_turn", StopReason.COMPLETE),
        ("stop_sequence", StopReason.COMPLETE),
        ("complete", StopReason.COMPLETE),
        ("length", StopReason.LENGTH),
        ("max_tokens", StopReason.LENGTH),
        ("tool_calls", StopReason.TOOL_CALL),
        ("tool_use", StopReason.TOOL_CALL),
        ("function_call", StopReason.TOOL_CALL),
        ("content_filter", StopReason.SAFETY),
        ("refusal", StopReason.SAFETY),
        ("safety", StopReason.SAFETY),
        ("error", StopReason.ERROR),
    ],
)
def test_from_provider_known(value, expected):
    assert StopReason.from_provider(value) is expected


def test_from_provider_case_insensitive():
    assert StopReason.from_provider("END_TURN") is StopReason.COMPLETE
    assert StopReason.from_provider("Max_Tokens") is StopReason.LENGTH


def test_from_provider_none():
    assert StopReason.from_provider(None) is StopReason.COMPLETE


def test_from_provider_empty_string():
    assert StopReason.from_provider("") is StopReason.COMPLETE


def test_from_provider_unknown():
    assert StopReason.from_provider("totally_unknown") is StopReason.COMPLETE


def test_stop_reason_is_str_enum():
    assert StopReason.SAFETY == "safety"
    assert isinstance(StopReason.COMPLETE, str)


# ---- UsageMetrics ------------------------------------------------------------------------------


def test_usage_defaults():
    u = UsageMetrics()
    assert u.input_tokens == 0
    assert u.output_tokens == 0
    assert u.total_tokens == 0
    assert u.estimated_cost_usd is None


def test_usage_total_auto_derived_when_zero():
    u = UsageMetrics(input_tokens=10, output_tokens=5)
    assert u.total_tokens == 15


def test_usage_explicit_total_respected():
    u = UsageMetrics(input_tokens=10, output_tokens=5, total_tokens=99)
    assert u.total_tokens == 99


def test_usage_total_derives_with_zero_io():
    u = UsageMetrics(input_tokens=0, output_tokens=0)
    assert u.total_tokens == 0


def test_usage_from_io():
    u = UsageMetrics.from_io(7, 3)
    assert u.input_tokens == 7
    assert u.output_tokens == 3
    assert u.total_tokens == 10
    assert u.estimated_cost_usd is None


def test_usage_from_io_with_cost():
    u = UsageMetrics.from_io(7, 3, estimated_cost_usd=0.0042)
    assert u.estimated_cost_usd == 0.0042
    assert u.total_tokens == 10


def test_usage_cost_preserved():
    u = UsageMetrics(input_tokens=1, output_tokens=1, estimated_cost_usd=1.5)
    assert u.estimated_cost_usd == 1.5
    assert u.total_tokens == 2


# ---- InvocationResult --------------------------------------------------------------------------


def test_invocation_result_defaults():
    r = InvocationResult()
    assert r.content == []
    assert isinstance(r.usage, UsageMetrics)
    assert r.stop_reason is StopReason.COMPLETE
    assert r.latency_ms == 0
    assert r.raw_response == {}


def test_invocation_result_defaults_not_shared():
    r1 = InvocationResult()
    r2 = InvocationResult()
    r1.content.append(TextBlock(text="x"))
    r1.raw_response["k"] = 1
    assert r2.content == []
    assert r2.raw_response == {}


def test_invocation_result_text():
    r = InvocationResult(content=[TextBlock(text="a"), TextBlock(text="b")])
    assert r.text == "a\nb"


def test_invocation_result_text_ignores_tool_calls():
    r = InvocationResult(
        content=[TextBlock(text="hello"), ToolCallBlock(id="1", name="t", arguments={})]
    )
    assert r.text == "hello"


def test_invocation_result_tool_calls():
    call = ToolCallBlock(id="1", name="search", arguments={"q": "x"})
    r = InvocationResult(content=[TextBlock(text="t"), call])
    assert r.tool_calls == [call]


def test_invocation_result_tool_calls_empty():
    r = InvocationResult(content=[TextBlock(text="t")])
    assert r.tool_calls == []


def test_is_refusal_true():
    r = InvocationResult(stop_reason=StopReason.SAFETY)
    assert r.is_refusal is True


def test_is_refusal_false():
    assert InvocationResult(stop_reason=StopReason.COMPLETE).is_refusal is False
    assert InvocationResult(stop_reason=StopReason.LENGTH).is_refusal is False


def test_to_message():
    r = InvocationResult(content=[TextBlock(text="hi")])
    m = r.to_message()
    assert m.role is MessageRole.ASSISTANT
    assert m.text == "hi"


def test_to_message_copies_content_list():
    block = TextBlock(text="hi")
    r = InvocationResult(content=[block])
    m = r.to_message()
    # the message's content must be a new list (mutating it must not affect the result)
    m.content.append(TextBlock(text="more"))
    assert r.content == [block]
