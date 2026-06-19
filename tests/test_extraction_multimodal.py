"""Tests for multimodal ingestion in the extraction + reproduce layers (Feature A).

Three-case decision (extraction_v3.md): a harvested image may be (1) a
screenshot whose TEXT is the payload, (2) the payload ITSELF (verbatim), or (3)
a supplement. These tests cover the wiring that supports that decision:

  * the extraction LLM call carries image content blocks (Anthropic + OpenAI);
  * a Case-2 ``image_strategy=verbatim`` output resolves to a multimodal-image
    primitive whose ``base_image`` points at the ingested image's cached path;
  * a Case-1 text output is unaffected by the presence of images;
  * the reproduce layer sends those exact bytes (no synthetic re-render);
  * the X scraper adapter lifts ``photos`` into ``XPost.media_urls``.

Offline: the provider SDK clients are mocked; no network, no DB, no keys.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from rogue.extract.extraction_agent import (
    ExtractionAgent,
    ExtractionImage,
    _resolve_image_payload_slots,
)
from rogue.harvest.bright_data_client import (
    _record_to_hf_discussion,
    _record_to_reddit_post,
    _record_to_x_post,
)
from rogue.reproduce.instantiator import _IMAGE_CARRIER_PROMPT, render
from rogue.schemas import AttackPrimitive, AttackVector, demo_deployment_configs

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_PNG = b"\x89PNG\r\n\x1a\n" + b"ingested-payload-bytes"
_PNG_B64 = base64.b64encode(_PNG).decode("ascii")


def _golden_dict() -> dict[str, Any]:
    return json.loads(
        (FIXTURES_DIR / "01_multilingual_african_languages.json").read_text(encoding="utf-8")
    )


def _tool_use_response(payload: dict[str, Any]) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.input = payload
    response = MagicMock()
    response.content = [block]
    return response


def _image(path: str | None = None) -> ExtractionImage:
    return ExtractionImage(
        b64=_PNG_B64, media_type="image/png", source_url="https://pbs.twimg.com/media/a", path=path
    )


# --------------------------------------------------------------------------- #
# A. The extraction LLM call carries image content blocks
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_anthropic_call_carries_image_blocks() -> None:
    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")
    payload = _golden_dict()
    payload["is_attack"] = True
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=_tool_use_response(payload))
    agent._anthropic_client = mock_client

    await agent.extract(
        raw_document="A screenshot post.",
        source_url="https://x.com/elder_plinius/status/1",
        source_type="x",
        images=[_image(), _image()],
    )

    _, kwargs = mock_client.messages.create.call_args
    content = kwargs["messages"][0]["content"]
    assert isinstance(content, list)
    # text + (marker + image) * 2
    image_blocks = [b for b in content if b.get("type") == "image"]
    assert len(image_blocks) == 2
    assert image_blocks[0]["source"]["media_type"] == "image/png"
    assert image_blocks[0]["source"]["data"] == _PNG_B64
    markers = [b["text"] for b in content if b.get("type") == "text" and b["text"].startswith("[image index")]
    assert markers == ["[image index 0]", "[image index 1]"]


@pytest.mark.asyncio
async def test_openai_call_carries_image_url_blocks() -> None:
    agent = ExtractionAgent(model="openai/gpt-5.4-mini")
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.parsed = AttackPrimitive.model_validate(_golden_dict())
    mock_client = MagicMock()
    mock_client.beta.chat.completions.parse = AsyncMock(return_value=completion)
    agent._openai_client = mock_client

    await agent.extract(
        raw_document="A screenshot post.",
        source_url="https://x.com/p/status/1",
        source_type="x",
        images=[_image()],
    )

    _, kwargs = mock_client.beta.chat.completions.parse.call_args
    user_content = kwargs["messages"][1]["content"]
    assert isinstance(user_content, list)
    parts = [p for p in user_content if p.get("type") == "image_url"]
    assert len(parts) == 1
    assert parts[0]["image_url"]["url"] == f"data:image/png;base64,{_PNG_B64}"


@pytest.mark.asyncio
async def test_text_only_extract_keeps_string_content() -> None:
    """Regression: no images → user content stays a plain string (pre-Feature-A shape)."""
    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")
    payload = _golden_dict()
    payload["is_attack"] = True
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=_tool_use_response(payload))
    agent._anthropic_client = mock_client

    await agent.extract(
        raw_document="text only", source_url="https://x/y", source_type="blog"
    )
    _, kwargs = mock_client.messages.create.call_args
    assert isinstance(kwargs["messages"][0]["content"], str)


# --------------------------------------------------------------------------- #
# B. Case-2 (image IS the payload) resolution
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_case2_verbatim_resolves_to_multimodal_primitive(tmp_path) -> None:
    img_path = tmp_path / "payload.png"
    img_path.write_bytes(_PNG)

    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")
    payload = _golden_dict()
    payload["is_attack"] = True
    payload["vector"] = "user_turn"  # LLM under-specifies; resolver corrects it
    payload["requires_multimodal"] = False
    payload["payload_slots"] = {"image_strategy": "verbatim", "payload_image_index": "0"}
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=_tool_use_response(payload))
    agent._anthropic_client = mock_client

    primitive = await agent.extract(
        raw_document="image jailbreak",
        source_url="https://x.com/p/status/1",
        source_type="x",
        images=[_image(path=str(img_path))],
    )

    assert primitive is not None
    assert primitive.vector == AttackVector.MULTIMODAL_IMAGE
    assert primitive.requires_multimodal is True
    assert primitive.payload_slots["base_image"] == str(img_path)
    assert primitive.payload_slots["image_strategy"] == "verbatim"
    # The LLM-facing index slot is consumed during resolution.
    assert "payload_image_index" not in primitive.payload_slots


def test_resolve_demotes_when_no_usable_image() -> None:
    data = {
        "is_attack": True,
        "payload_slots": {"image_strategy": "verbatim", "payload_image_index": "0"},
    }
    out = _resolve_image_payload_slots(data, [_image(path=None)])
    assert out.get("is_attack") is False


def test_resolve_is_noop_without_verbatim_strategy() -> None:
    data = {"is_attack": True, "payload_slots": {"mml_method": "base64"}}
    assert _resolve_image_payload_slots(data, [_image(path="/x.png")]) is data


def test_resolve_clamps_out_of_range_index(tmp_path) -> None:
    p = tmp_path / "only.png"
    p.write_bytes(_PNG)
    data = {
        "is_attack": True,
        "payload_slots": {"image_strategy": "verbatim", "payload_image_index": "9"},
    }
    out = _resolve_image_payload_slots(data, [_image(path=str(p))])
    assert out["payload_slots"]["base_image"] == str(p)  # clamped to the only image


# --------------------------------------------------------------------------- #
# C. Case-1 (text-in-image) is unaffected by image presence
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_case1_text_primitive_unaffected_by_images(tmp_path) -> None:
    img_path = tmp_path / "shot.png"
    img_path.write_bytes(_PNG)
    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")
    payload = _golden_dict()  # a normal text primitive, no image_strategy
    payload["is_attack"] = True
    original_vector = payload["vector"]
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=_tool_use_response(payload))
    agent._anthropic_client = mock_client

    primitive = await agent.extract(
        raw_document="Pliny screenshot of a text jailbreak",
        source_url="https://x.com/p/status/1",
        source_type="x",
        images=[_image(path=str(img_path))],
    )
    assert primitive is not None
    assert primitive.vector.value == original_vector
    assert "base_image" not in primitive.payload_slots


@pytest.mark.asyncio
async def test_unhelpful_image_yields_no_primitive(tmp_path) -> None:
    """Case 3 / not-useful: an image with no technique → the LLM returns
    is_attack:false → extract() returns None (no junk multimodal primitive)."""
    img_path = tmp_path / "meme.png"
    img_path.write_bytes(_PNG)
    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=_tool_use_response(
            {"is_attack": False, "reason": "image is a meme; no technique disclosed"}
        )
    )
    agent._anthropic_client = mock_client

    result = await agent.extract(
        raw_document="lol look at this",
        source_url="https://x.com/p/status/9",
        source_type="x",
        images=[_image(path=str(img_path))],
    )
    assert result is None


# --------------------------------------------------------------------------- #
# D. Reproduce sends the verbatim bytes (no re-render)
# --------------------------------------------------------------------------- #


def test_verbatim_render_sends_exact_bytes(tmp_path) -> None:
    img_path = tmp_path / "verbatim.png"
    img_path.write_bytes(_PNG)
    data = _golden_dict()
    data["vector"] = AttackVector.MULTIMODAL_IMAGE.value
    data["requires_multimodal"] = True
    data["payload_slots"] = {"image_strategy": "verbatim", "base_image": str(img_path)}
    primitive = AttackPrimitive.model_validate(data)

    config = demo_deployment_configs()[1]  # anthropic/claude-haiku-4-5 (vision)
    rendered = render(primitive, config)

    # Exact ingested bytes, NOT a synthetic typographic PNG.
    assert rendered.image_b64 is not None
    assert base64.b64decode(rendered.image_b64) == _PNG
    assert rendered.image_media_type == "image/png"
    user_turns = [m for m in rendered.messages if m["role"] == "user"]
    assert user_turns[-1]["content"] == _IMAGE_CARRIER_PROMPT


def test_verbatim_render_sniffs_jpeg_media_type(tmp_path) -> None:
    jpeg = b"\xff\xd8\xff\xe0" + b"jpeg-bytes"
    img_path = tmp_path / "verbatim.jpg"
    img_path.write_bytes(jpeg)
    data = _golden_dict()
    data["vector"] = AttackVector.MULTIMODAL_IMAGE.value
    data["requires_multimodal"] = True
    data["payload_slots"] = {"image_strategy": "verbatim", "base_image": str(img_path)}
    primitive = AttackPrimitive.model_validate(data)
    rendered = render(primitive, demo_deployment_configs()[1])
    assert rendered.image_media_type == "image/jpeg"
    assert base64.b64decode(rendered.image_b64) == jpeg


# --------------------------------------------------------------------------- #
# E. X scraper adapter lifts `photos` → media_urls
# --------------------------------------------------------------------------- #


def test_record_to_x_post_lifts_photos_excludes_video_and_avatar() -> None:
    post = _record_to_x_post(
        {
            "url": "https://x.com/elder_plinius/status/1",
            "user_posted": "elder_plinius",
            "description": "jb",
            "date_posted": "2026-05-30T00:00:00.000Z",
            "photos": ["https://pbs.twimg.com/media/a.jpg", "not-a-url", 42],
            "videos": ["https://video.twimg.com/v.mp4"],
            "profile_image_link": "https://pbs.twimg.com/profile/x.jpg",
        }
    )
    assert post.media_urls == ["https://pbs.twimg.com/media/a.jpg"]


def test_record_to_x_post_text_only_has_empty_media() -> None:
    post = _record_to_x_post(
        {
            "url": "https://x.com/u/status/2",
            "user_posted": "u",
            "description": "text",
            "date_posted": "2026-05-30T00:00:00.000Z",
            "photos": None,
        }
    )
    assert post.media_urls == []


def test_record_to_reddit_post_lifts_photos() -> None:
    """Reddit is a JSON source — its image-only posts must be captured
    structurally (the body-img extractor can't see a JSON body)."""
    post = _record_to_reddit_post(
        {
            "post_id": "abc",
            "title": "image jailbreak",
            "description": "",
            "url": "https://www.reddit.com/r/ChatGPTJailbreak/comments/abc/",
            "date_posted": "2026-05-30T00:00:00.000Z",
            "photos": ["https://i.redd.it/jail.png"],
            "videos": [],
        },
        subreddit_fallback="ChatGPTJailbreak",
    )
    assert post.media_urls == ["https://i.redd.it/jail.png"]


def test_record_to_hf_discussion_walks_post_bodies_for_images() -> None:
    """HF is a JSON source whose images live as markdown inside post bodies
    under best-guess field names — captured by the JSON walk, avatars dropped."""
    hf = _record_to_hf_discussion(
        {
            "model_id": "org/model",
            "thread_id": "42",
            "title": "vision jb",
            "started_at": "2026-05-30T00:00:00Z",
            "posts": [
                {
                    "author_avatar": "https://hf.co/avatars/u.png",  # dropped
                    "content": "PoC ![x](https://cdn-uploads.huggingface.co/poc.png)",
                },
            ],
        },
        model_id_fallback="org/model",
    )
    assert hf.media_urls == ["https://cdn-uploads.huggingface.co/poc.png"]
