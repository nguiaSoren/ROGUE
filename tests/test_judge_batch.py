"""Tests for ``rogue.reproduce.judge_batch`` — the Batch-API judge path.

Mocks the Anthropic batches client (create/retrieve/results) and the OpenRouter
fallback, so no network. Covers: request shape (cached system + tool), primary
verdict collection, and the refusal → secondary-judge fallback with the flag.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from rogue.reproduce.instantiator import RenderedAttack
from rogue.reproduce.judge import JudgeAgent
from rogue.reproduce.judge_batch import BatchGradeItem, JudgeBatch
from rogue.schemas import AttackPrimitive, JudgeVerdict

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _primitive() -> AttackPrimitive:
    data = json.loads(
        (FIXTURES_DIR / "02_copirate_365_cve_2026_24299.json").read_text(encoding="utf-8")
    )
    return AttackPrimitive.model_validate(data)


def _item(cid: str) -> BatchGradeItem:
    return BatchGradeItem(
        custom_id=cid,
        rendered=RenderedAttack(
            messages=[{"role": "user", "content": "do the thing"}],
            is_multi_turn=False,
            resolved_slots={},
            primitive_id="p",
            deployment_config_id="c",
        ),
        model_response="sure, here you go",
        primitive=_primitive(),
    )


def _tool_msg(verdict: str) -> SimpleNamespace:
    block = SimpleNamespace(
        type="tool_use",
        input={"verdict": verdict, "rationale": "r", "confidence": 0.9},
    )
    return SimpleNamespace(stop_reason="tool_use", content=[block])


def _refusal_msg() -> SimpleNamespace:
    return SimpleNamespace(stop_reason="refusal", content=[])


async def _aiter(entries):
    for e in entries:
        yield e


def _wire_batches(client, entries) -> None:
    client.messages.batches.create = AsyncMock(return_value=SimpleNamespace(id="b1"))
    client.messages.batches.retrieve = AsyncMock(
        return_value=SimpleNamespace(processing_status="ended", request_counts={})
    )
    client.messages.batches.results = AsyncMock(return_value=_aiter(entries))


def test_requires_anthropic_primary() -> None:
    with pytest.raises(ValueError, match="Anthropic primary"):
        JudgeBatch(JudgeAgent(model="openrouter/deepseek/deepseek-v3.2"))


def test_request_has_custom_id_cached_system_and_tool() -> None:
    jb = JudgeBatch(JudgeAgent(model="anthropic/claude-sonnet-4-6"))
    req = jb._request(_item("cell_1"))
    assert req["custom_id"] == "cell_1"
    assert req["params"]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert req["params"]["tool_choice"]["name"] == "emit_verdict"


@pytest.mark.asyncio
async def test_grade_collects_primary_verdicts() -> None:
    jb = JudgeBatch(JudgeAgent(model="anthropic/claude-sonnet-4-6"))
    jb.judge._anthropic_client = MagicMock()
    entries = [
        SimpleNamespace(
            custom_id="cell_1",
            result=SimpleNamespace(type="succeeded", message=_tool_msg("FULL_BREACH")),
        )
    ]
    _wire_batches(jb.judge._anthropic_client, entries)

    verdicts = await jb.grade([_item("cell_1")])
    assert verdicts["cell_1"].verdict is JudgeVerdict.FULL_BREACH


@pytest.mark.asyncio
async def test_grade_refusal_falls_back_to_secondary_and_flags() -> None:
    jb = JudgeBatch(JudgeAgent(model="anthropic/claude-sonnet-4-6"))
    jb.judge._anthropic_client = MagicMock()
    # primary refuses this cell in the batch
    entries = [
        SimpleNamespace(
            custom_id="cell_1",
            result=SimpleNamespace(type="succeeded", message=_refusal_msg()),
        )
    ]
    _wire_batches(jb.judge._anthropic_client, entries)
    # secondary judge grades it
    jb.judge._grade_via_openrouter = AsyncMock(
        return_value={"verdict": "FULL_BREACH", "rationale": "complied", "confidence": 0.9}
    )

    verdicts = await jb.grade([_item("cell_1")])
    assert verdicts["cell_1"].verdict is JudgeVerdict.FULL_BREACH
    assert verdicts["cell_1"].rationale.startswith("[JUDGE_REFUSED→")
    jb.judge._grade_via_openrouter.assert_awaited_once()


@pytest.mark.asyncio
async def test_grade_errored_entry_also_falls_back() -> None:
    jb = JudgeBatch(JudgeAgent(model="anthropic/claude-sonnet-4-6"))
    jb.judge._anthropic_client = MagicMock()
    entries = [
        SimpleNamespace(
            custom_id="cell_1",
            result=SimpleNamespace(type="errored", error=SimpleNamespace(type="x")),
        )
    ]
    _wire_batches(jb.judge._anthropic_client, entries)
    jb.judge._grade_via_openrouter = AsyncMock(
        return_value={"verdict": "REFUSED", "rationale": "declined", "confidence": 0.8}
    )

    verdicts = await jb.grade([_item("cell_1")])
    assert verdicts["cell_1"].verdict is JudgeVerdict.REFUSED


@pytest.mark.asyncio
async def test_grade_empty_is_noop() -> None:
    jb = JudgeBatch(JudgeAgent(model="anthropic/claude-sonnet-4-6"))
    assert await jb.grade([]) == {}
