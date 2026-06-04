"""Unit tests for :mod:`rogue.core.content_blocks`."""

from __future__ import annotations

import base64

import pytest

from rogue.core.attachment import Attachment
from rogue.core.content_blocks import (
    AudioBlock,
    ContentBlock,
    ImageBlock,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"payload"


def test_base_content_block_modality_unknown():
    assert ContentBlock().modality == "unknown"


def test_text_block_modality():
    b = TextBlock(text="hi")
    assert b.modality == "text"
    assert b.text == "hi"


def test_image_block_default_mime():
    b = ImageBlock(data=PNG)
    assert b.mime_type == "image/png"
    assert b.modality == "image"


def test_audio_block_default_mime():
    b = AudioBlock(data=b"RIFF....WAVE")
    assert b.mime_type == "audio/wav"
    assert b.modality == "audio"


def test_image_block_url_only():
    b = ImageBlock(url="http://x/y.png")
    assert b.url == "http://x/y.png"
    assert b.data is None


def test_media_requires_exactly_one_of_data_or_url_neither():
    with pytest.raises(ValueError):
        ImageBlock()


def test_media_requires_exactly_one_of_data_or_url_both():
    with pytest.raises(ValueError):
        ImageBlock(data=PNG, url="http://x/y.png")


def test_media_requires_nonempty_mime():
    with pytest.raises(ValueError):
        ImageBlock(data=PNG, mime_type="")


def test_audio_requires_one_of_data_or_url():
    with pytest.raises(ValueError):
        AudioBlock()
    with pytest.raises(ValueError):
        AudioBlock(data=b"x", url="http://x/y.wav")


def test_to_base64_inline():
    b = ImageBlock(data=PNG)
    assert b.to_base64() == base64.b64encode(PNG).decode("ascii")


def test_to_base64_url_only_raises():
    b = ImageBlock(url="http://x/y.png")
    with pytest.raises(ValueError):
        b.to_base64()


def test_from_attachment_inline():
    att = Attachment(mime_type="image/jpeg", data=b"\xff\xd8\xffrest")
    b = ImageBlock.from_attachment(att)
    assert isinstance(b, ImageBlock)
    assert b.data == b"\xff\xd8\xffrest"
    assert b.mime_type == "image/jpeg"
    assert b.url is None


def test_from_attachment_url():
    att = Attachment(mime_type="image/png", url="http://x/y.png")
    b = ImageBlock.from_attachment(att)
    assert b.url == "http://x/y.png"
    assert b.data is None


def test_to_attachment_round_trip_inline():
    b = ImageBlock(data=PNG, mime_type="image/png")
    att = b.to_attachment()
    assert isinstance(att, Attachment)
    assert att.data == PNG
    assert att.mime_type == "image/png"
    back = ImageBlock.from_attachment(att)
    assert back.data == b.data
    assert back.mime_type == b.mime_type


def test_to_attachment_round_trip_url():
    b = AudioBlock(url="http://x/y.wav", mime_type="audio/wav")
    att = b.to_attachment()
    assert att.url == "http://x/y.wav"
    back = AudioBlock.from_attachment(att)
    assert back.url == b.url
    assert back.mime_type == b.mime_type


def test_audio_from_attachment_via_audioblock():
    att = Attachment(mime_type="audio/mpeg", data=b"ID3xx")
    b = AudioBlock.from_attachment(att)
    assert b.modality == "audio"
    assert b.mime_type == "audio/mpeg"


def test_tool_call_block():
    b = ToolCallBlock(id="c1", name="search", arguments={"q": "hi"})
    assert b.modality == "tool_call"
    assert b.id == "c1"
    assert b.name == "search"
    assert b.arguments == {"q": "hi"}


def test_tool_result_block():
    b = ToolResultBlock(tool_call_id="c1", result="42")
    assert b.modality == "tool_result"
    assert b.tool_call_id == "c1"
    assert b.result == "42"


def test_all_modality_values_distinct():
    modalities = {
        TextBlock(text="x").modality,
        ImageBlock(data=PNG).modality,
        AudioBlock(data=b"x", mime_type="audio/wav").modality,
        ToolCallBlock(id="a", name="b", arguments={}).modality,
        ToolResultBlock(tool_call_id="a", result="b").modality,
    }
    assert modalities == {"text", "image", "audio", "tool_call", "tool_result"}
