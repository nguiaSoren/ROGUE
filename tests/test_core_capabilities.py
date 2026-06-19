"""Unit tests for :mod:`rogue.core.capabilities` — TargetCapabilities."""

from __future__ import annotations

import dataclasses

import pytest

from rogue.core.capabilities import TargetCapabilities
from rogue.core.content_blocks import (
    AudioBlock,
    ImageBlock,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from rogue.core.message import CanonicalMessage, MessageRole

PNG = b"\x89PNG\r\n\x1a\n"


def test_defaults():
    c = TargetCapabilities()
    assert c.supports_text is True
    assert c.supports_image is False
    assert c.supports_audio is False
    assert c.supports_video is False
    assert c.supports_tools is False
    assert c.supports_system_prompt is True
    assert c.supports_json_mode is False
    assert c.supports_streaming is False
    assert c.supports_function_calling is False
    assert c.max_context_tokens is None
    assert c.max_output_tokens is None
    assert c.max_temperature is None


def test_frozen():
    c = TargetCapabilities()
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.supports_text = False  # type: ignore[misc]


# ---- supports_block ----------------------------------------------------------------------------


def test_supports_block_text():
    assert TargetCapabilities(supports_text=True).supports_block(TextBlock(text="x")) is True
    assert TargetCapabilities(supports_text=False).supports_block(TextBlock(text="x")) is False


def test_supports_block_image():
    blk = ImageBlock(data=PNG)
    assert TargetCapabilities(supports_image=True).supports_block(blk) is True
    assert TargetCapabilities(supports_image=False).supports_block(blk) is False


def test_supports_block_audio():
    blk = AudioBlock(data=b"x", mime_type="audio/wav")
    assert TargetCapabilities(supports_audio=True).supports_block(blk) is True
    assert TargetCapabilities(supports_audio=False).supports_block(blk) is False


def test_supports_block_tool_call_and_result():
    call = ToolCallBlock(id="a", name="b", arguments={})
    result = ToolResultBlock(tool_call_id="a", result="r")
    yes = TargetCapabilities(supports_tools=True)
    no = TargetCapabilities(supports_tools=False)
    assert yes.supports_block(call) is True
    assert yes.supports_block(result) is True
    assert no.supports_block(call) is False
    assert no.supports_block(result) is False


# ---- supports_message --------------------------------------------------------------------------


def test_supports_message_text_only():
    c = TargetCapabilities()
    assert c.supports_message(CanonicalMessage.user("hi")) is True


def test_supports_message_system_gate_off():
    c = TargetCapabilities(supports_system_prompt=False)
    assert c.supports_message(CanonicalMessage.system("sys")) is False
    # a user message is unaffected by the system-prompt gate
    assert c.supports_message(CanonicalMessage.user("hi")) is True


def test_supports_message_system_gate_on():
    c = TargetCapabilities(supports_system_prompt=True)
    assert c.supports_message(CanonicalMessage.system("sys")) is True


def test_supports_message_unsupported_block():
    c = TargetCapabilities(supports_image=False)
    msg = CanonicalMessage(role=MessageRole.USER, content=[ImageBlock(data=PNG)])
    assert c.supports_message(msg) is False


def test_supports_message_empty_content_true():
    c = TargetCapabilities()
    assert c.supports_message(CanonicalMessage(role=MessageRole.USER)) is True


# ---- unsupported_blocks / can_handle -----------------------------------------------------------


def test_unsupported_blocks_mixed_list():
    c = TargetCapabilities(supports_text=True, supports_image=False, supports_audio=False)
    img = ImageBlock(data=PNG)
    aud = AudioBlock(data=b"x", mime_type="audio/wav")
    msgs = [
        CanonicalMessage.user("hi"),
        CanonicalMessage(role=MessageRole.USER, content=[TextBlock(text="ok"), img, aud]),
    ]
    bad = c.unsupported_blocks(msgs)
    assert img in bad
    assert aud in bad
    assert len(bad) == 2


def test_unsupported_blocks_empty_when_all_supported():
    c = TargetCapabilities(supports_text=True, supports_image=True)
    msgs = [
        CanonicalMessage.user("hi"),
        CanonicalMessage(role=MessageRole.USER, content=[ImageBlock(data=PNG)]),
    ]
    assert c.unsupported_blocks(msgs) == []


def test_can_handle_true():
    c = TargetCapabilities(supports_image=True)
    msgs = [CanonicalMessage(role=MessageRole.USER, content=[ImageBlock(data=PNG)])]
    assert c.can_handle(msgs) is True


def test_can_handle_false_on_block():
    c = TargetCapabilities(supports_image=False)
    msgs = [CanonicalMessage(role=MessageRole.USER, content=[ImageBlock(data=PNG)])]
    assert c.can_handle(msgs) is False


def test_can_handle_false_on_system_prompt_gate():
    c = TargetCapabilities(supports_system_prompt=False)
    msgs = [CanonicalMessage.system("sys"), CanonicalMessage.user("hi")]
    assert c.can_handle(msgs) is False


def test_can_handle_empty_list_true():
    assert TargetCapabilities().can_handle([]) is True


# ---- clamp_temperature -------------------------------------------------------------------------


def test_clamp_temperature_no_ceiling():
    c = TargetCapabilities(max_temperature=None)
    assert c.clamp_temperature(5.0) == 5.0
    assert c.clamp_temperature(0.0) == 0.0


def test_clamp_temperature_with_ceiling():
    c = TargetCapabilities(max_temperature=1.0)
    assert c.clamp_temperature(2.0) == 1.0
    assert c.clamp_temperature(0.5) == 0.5
    assert c.clamp_temperature(1.0) == 1.0
