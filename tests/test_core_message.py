"""Unit tests for :mod:`rogue.core.message` — the CanonicalMessage."""

from __future__ import annotations

from rogue.core.content_blocks import ImageBlock, TextBlock
from rogue.core.message import (
    CanonicalMessage,
    MessageRole,
    from_legacy_messages,
    to_legacy_messages,
)


def test_message_role_values():
    assert MessageRole.SYSTEM == "system"
    assert MessageRole.USER == "user"
    assert MessageRole.ASSISTANT == "assistant"
    assert MessageRole.TOOL == "tool"


def test_message_role_is_str_enum():
    assert isinstance(MessageRole.USER, str)
    assert MessageRole("user") is MessageRole.USER


def test_default_content_is_empty_list():
    m = CanonicalMessage(role=MessageRole.USER)
    assert m.content == []
    # distinct instances must not share the same list
    m2 = CanonicalMessage(role=MessageRole.USER)
    m.content.append(TextBlock(text="x"))
    assert m2.content == []


def test_of_with_enum_role():
    m = CanonicalMessage.of(MessageRole.USER, "hello")
    assert m.role is MessageRole.USER
    assert len(m.content) == 1
    assert isinstance(m.content[0], TextBlock)
    assert m.content[0].text == "hello"


def test_of_with_str_role():
    m = CanonicalMessage.of("assistant", "hi there")
    assert m.role is MessageRole.ASSISTANT
    assert m.text == "hi there"


def test_system_constructor():
    m = CanonicalMessage.system("you are helpful")
    assert m.role is MessageRole.SYSTEM
    assert m.text == "you are helpful"


def test_user_constructor():
    m = CanonicalMessage.user("question?")
    assert m.role is MessageRole.USER
    assert m.text == "question?"


def test_assistant_constructor():
    m = CanonicalMessage.assistant("answer.")
    assert m.role is MessageRole.ASSISTANT
    assert m.text == "answer."


def test_text_joins_multiple_text_blocks_with_newline():
    m = CanonicalMessage(
        role=MessageRole.USER,
        content=[TextBlock(text="line1"), TextBlock(text="line2")],
    )
    assert m.text == "line1\nline2"


def test_text_ignores_non_text_blocks():
    m = CanonicalMessage(
        role=MessageRole.USER,
        content=[
            TextBlock(text="caption"),
            ImageBlock(data=b"\x89PNG", mime_type="image/png"),
        ],
    )
    assert m.text == "caption"


def test_text_empty_when_no_text_blocks():
    m = CanonicalMessage(
        role=MessageRole.USER,
        content=[ImageBlock(url="http://x/y.png")],
    )
    assert m.text == ""


def test_blocks_of_filters_by_type():
    img = ImageBlock(url="http://x/y.png")
    txt = TextBlock(text="hi")
    m = CanonicalMessage(role=MessageRole.USER, content=[txt, img])
    assert m.blocks_of(TextBlock) == [txt]
    assert m.blocks_of(ImageBlock) == [img]


def test_modalities_set():
    m = CanonicalMessage(
        role=MessageRole.USER,
        content=[
            TextBlock(text="hi"),
            ImageBlock(url="http://x/y.png"),
            TextBlock(text="bye"),
        ],
    )
    assert m.modalities == {"text", "image"}


def test_modalities_empty_message():
    m = CanonicalMessage(role=MessageRole.USER)
    assert m.modalities == set()


def test_from_legacy_dict_basic():
    m = CanonicalMessage.from_legacy_dict({"role": "user", "content": "hello"})
    assert m.role is MessageRole.USER
    assert m.text == "hello"


def test_from_legacy_dict_missing_content():
    m = CanonicalMessage.from_legacy_dict({"role": "system"})
    assert m.role is MessageRole.SYSTEM
    assert m.text == ""


def test_from_legacy_dict_none_content_coerced_to_empty():
    m = CanonicalMessage.from_legacy_dict({"role": "assistant", "content": None})
    assert m.text == ""


def test_to_legacy_dict():
    m = CanonicalMessage.user("hi")
    assert m.to_legacy_dict() == {"role": "user", "content": "hi"}


def test_to_legacy_dict_drops_non_text():
    m = CanonicalMessage(
        role=MessageRole.USER,
        content=[TextBlock(text="caption"), ImageBlock(url="http://x/y.png")],
    )
    assert m.to_legacy_dict() == {"role": "user", "content": "caption"}


def test_legacy_dict_round_trip():
    d = {"role": "assistant", "content": "round trip"}
    assert CanonicalMessage.from_legacy_dict(d).to_legacy_dict() == d


def test_from_legacy_messages_multi_turn():
    legacy = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
    ]
    msgs = from_legacy_messages(legacy)
    assert [m.role for m in msgs] == [
        MessageRole.SYSTEM,
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.USER,
    ]
    assert [m.text for m in msgs] == ["sys", "u1", "a1", "u2"]


def test_to_legacy_messages_multi_turn():
    msgs = [
        CanonicalMessage.system("sys"),
        CanonicalMessage.user("u1"),
        CanonicalMessage.assistant("a1"),
    ]
    assert to_legacy_messages(msgs) == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
    ]


def test_module_level_round_trip():
    legacy = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "yo"},
    ]
    assert to_legacy_messages(from_legacy_messages(legacy)) == legacy
