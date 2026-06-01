"""Tests for the §10.9 Phase 1 — the 3-way {payload, technique, commentary} classifier.

ExtractionAgent gained a `kind` discriminator: a document is a *payload* (specific
prompt → AttackPrimitive), a *technique* (reusable method → TechniqueSpec), or
*commentary* (None). `extract()` stays back-compat (payload-only; technique → None);
`extract_any()` returns the full union. The LLM call is mocked — no spend, no prompt
dependency.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from rogue.extract.extraction_agent import (
    _EXTRACTION_TOOL_SCHEMA,
    ExtractionAgent,
    _build_technique_or_none,
)
from rogue.schemas import AttackPrimitive, Modality, StrategyStatus, TechniqueSpec


def _tool_use_response(payload: dict[str, Any]) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.input = payload
    response = MagicMock()
    response.content = [block]
    return response


def _agent_returning(payload: dict[str, Any]) -> ExtractionAgent:
    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=_tool_use_response(payload))
    agent._anthropic_client = mock_client
    return agent


_TECHNIQUE_PAYLOAD = {
    "kind": "technique",
    "technique_name": "Crescendo escalation",
    "modality": "multi_turn",
    "principle": "ask benign, then escalate across turns so no single turn trips a filter",
    "steps": ["open benign", "reference the prior answer", "escalate the ask"],
    "params": {"n_turns": "3"},
    "example": "Turn 1: ask about chemistry broadly; Turn 3: ask the harmful specific.",
}

_IMAGE_TECHNIQUE_PAYLOAD = {
    "kind": "technique",
    "technique_name": "Typographic image smuggling",
    "modality": "image",
    "principle": "render the forbidden text as an image so the text filter never sees it",
    "steps": ["render request as PNG", "send image to the vision model"],
}


# --------------------------------------------------------------------------- #
# The widened tool schema
# --------------------------------------------------------------------------- #


def test_tool_schema_is_widened_superset() -> None:
    props = _EXTRACTION_TOOL_SCHEMA["properties"]
    ap_props = AttackPrimitive.model_json_schema()["properties"]
    assert set(ap_props).issubset(props)  # payload contract preserved
    for f in ("kind", "technique_name", "modality", "principle", "steps", "params"):
        assert f in props
    assert props["kind"]["enum"] == ["payload", "technique", "commentary"]
    assert props["modality"]["enum"] == [m.value for m in Modality]


def test_kind_and_technique_fields_not_required() -> None:
    # The added fields must not be in `required`, so the payload path is the
    # byte-for-byte v3 contract and the technique branch can omit payload fields.
    required = set(_EXTRACTION_TOOL_SCHEMA.get("required", []))
    assert not ({"kind", "technique_name", "modality", "principle"} & required)


# --------------------------------------------------------------------------- #
# extract_any() — the 3-way union
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_extract_any_returns_technique_for_technique_kind() -> None:
    agent = _agent_returning(_TECHNIQUE_PAYLOAD)
    out = await agent.extract_any(
        raw_document="A paper describing the Crescendo multi-turn method.",
        source_url="https://arxiv.org/abs/2606.00001",
        source_type="arxiv",
    )
    assert isinstance(out, TechniqueSpec)
    assert out.name == "Crescendo escalation"
    assert out.modality is Modality.MULTI_TURN
    assert out.steps == ["open benign", "reference the prior answer", "escalate the ask"]
    assert out.params == {"n_turns": "3"}
    # multi_turn needs no new code → enters as candidate (Phase 4 gate).
    assert out.status is StrategyStatus.CANDIDATE
    # Server-assigned identity + provenance, not LLM-supplied.
    assert len(out.technique_id) == 26
    assert out.source_url == "https://arxiv.org/abs/2606.00001"


@pytest.mark.asyncio
async def test_extract_any_image_technique_needs_implementation() -> None:
    agent = _agent_returning(_IMAGE_TECHNIQUE_PAYLOAD)
    out = await agent.extract_any(
        raw_document="A renderer method that hides text in an image.",
        source_url="https://example.com/mml",
        source_type="blog",
    )
    assert isinstance(out, TechniqueSpec)
    assert out.modality is Modality.IMAGE
    # image renderer → spec captured but a human/sandbox writes the code (Phase 3b).
    assert out.status is StrategyStatus.NEEDS_IMPLEMENTATION


@pytest.mark.asyncio
async def test_extract_any_returns_none_for_commentary() -> None:
    agent = _agent_returning({"kind": "commentary", "is_attack": False, "reason": "op-ed"})
    out = await agent.extract_any(
        raw_document="An opinion piece about AI safety.",
        source_url="https://example.com/oped",
        source_type="blog",
    )
    assert out is None


@pytest.mark.asyncio
async def test_extract_any_returns_primitive_for_payload(_golden_payload) -> None:
    agent = _agent_returning(_golden_payload)
    out = await agent.extract_any(
        raw_document="A concrete jailbreak prompt.",
        source_url="https://example.com/jb",
        source_type="blog",
    )
    assert isinstance(out, AttackPrimitive)


# --------------------------------------------------------------------------- #
# extract() — back-compat projection (technique → None)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_extract_drops_technique_to_none() -> None:
    agent = _agent_returning(_TECHNIQUE_PAYLOAD)
    out = await agent.extract(
        raw_document="A paper describing a method.",
        source_url="https://arxiv.org/abs/2606.00002",
        source_type="arxiv",
    )
    assert out is None  # back-compat: payload-only callers never see techniques


@pytest.mark.asyncio
async def test_extract_still_returns_primitive_for_payload(_golden_payload) -> None:
    agent = _agent_returning(_golden_payload)
    out = await agent.extract(
        raw_document="A concrete jailbreak prompt.",
        source_url="https://example.com/jb",
        source_type="blog",
    )
    assert isinstance(out, AttackPrimitive)


# --------------------------------------------------------------------------- #
# _build_technique_or_none — defensive projection
# --------------------------------------------------------------------------- #


def test_build_technique_incomplete_returns_none() -> None:
    # Missing principle → clean skip (None), not a raise.
    assert (
        _build_technique_or_none(
            {"technique_name": "x", "modality": "text"}, source_url="u"
        )
        is None
    )


def test_build_technique_bad_modality_returns_none() -> None:
    assert (
        _build_technique_or_none(
            {"technique_name": "x", "modality": "telepathy", "principle": "p"},
            source_url="u",
        )
        is None
    )


def test_build_technique_coerces_steps_and_params() -> None:
    out = _build_technique_or_none(
        {
            "technique_name": "x",
            "modality": "text",
            "principle": "p",
            "steps": [1, "two"],  # non-str element
            "params": {"k": 3},  # non-str value
        },
        source_url="u",
    )
    assert isinstance(out, TechniqueSpec)
    assert out.steps == ["1", "two"]
    assert out.params == {"k": "3"}


@pytest.fixture
def _golden_payload() -> dict[str, Any]:
    """A minimal valid AttackPrimitive tool-call dict (kind defaults to payload)."""
    import json
    from pathlib import Path

    fixture = (
        Path(__file__).parent / "fixtures" / "01_multilingual_african_languages.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    data["is_attack"] = True
    return data
