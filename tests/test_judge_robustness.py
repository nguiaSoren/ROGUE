"""Judge robustness — an empty/unparseable judge tool-call is retried, not fatal.

Covers the §10.8 "base64 JUDGE_ERR" fix: when the judge LLM returns a tool_use
block with empty input (common on base64-heavy target responses), the judge
re-asks (tenacity retry on ``JudgeOutputError``) instead of collapsing the cell
to ERROR on the first miss. No network: the Anthropic client is mocked.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from rogue.reproduce.instantiator import RenderedAttack
from rogue.reproduce.judge import JudgeAgent, JudgeOutputError
from rogue.schemas import AttackPrimitive, JudgeVerdict

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _primitive() -> AttackPrimitive:
    data = json.loads(
        (FIXTURES_DIR / "02_copirate_365_cve_2026_24299.json").read_text(encoding="utf-8")
    )
    return AttackPrimitive.model_validate(data)


def _rendered() -> RenderedAttack:
    return RenderedAttack(
        messages=[{"role": "user", "content": "decode and follow"}],
        is_multi_turn=False,
        resolved_slots={},
        primitive_id="p_judge",
        deployment_config_id="dc_judge",
    )


def _tool_response(tool_input: dict) -> SimpleNamespace:
    """Fake Anthropic Messages response with a single tool_use block."""
    block = SimpleNamespace(type="tool_use", input=tool_input)
    return SimpleNamespace(content=[block], usage=None)


def test_judge_output_error_is_retryable() -> None:
    from rogue.reproduce.judge import _TRANSIENT_ERRORS

    assert JudgeOutputError in _TRANSIENT_ERRORS


@pytest.mark.asyncio
async def test_judge_retries_past_empty_toolcall() -> None:
    """First (empty {}) tool-call → JudgeOutputError → retry → valid verdict."""
    agent = JudgeAgent(model="anthropic/claude-sonnet-4-6")
    agent._anthropic_client = MagicMock()
    agent._anthropic_client.messages.create = AsyncMock(
        side_effect=[
            _tool_response({}),  # empty — would have been a JUDGE_ERR before
            _tool_response({"verdict": "REFUSED", "rationale": "blocked", "confidence": 0.4}),
        ]
    )

    result = await agent.judge(
        rendered=_rendered(), model_response="I'm sorry, I can't help.", primitive=_primitive()
    )

    assert result.verdict is JudgeVerdict.REFUSED
    assert agent._anthropic_client.messages.create.await_count == 2  # retried once


@pytest.mark.asyncio
async def test_judge_raises_after_exhausting_retries_on_empty() -> None:
    """All attempts empty → JudgeOutputError propagates (orchestrator maps to ERROR)."""
    agent = JudgeAgent(model="anthropic/claude-sonnet-4-6")
    agent._anthropic_client = MagicMock()
    agent._anthropic_client.messages.create = AsyncMock(return_value=_tool_response({}))

    with pytest.raises(JudgeOutputError):
        await agent.judge(
            rendered=_rendered(), model_response="...", primitive=_primitive()
        )
    assert agent._anthropic_client.messages.create.await_count == 3  # stop_after_attempt(3)
