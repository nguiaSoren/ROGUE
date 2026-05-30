"""Judge robustness — an empty/unparseable judge tool-call is retried, then
falls back to text-mode grading, before it is ever fatal.

Covers the §10.8 robustness fix in two stages: (1) when the judge LLM returns a
tool_use block with empty input (common on base64-heavy target responses), the
judge re-asks (tenacity retry on ``JudgeOutputError``); (2) if forced tool-use
stays empty through all retries, the judge drops to a plain-text grading
fallback (``_call_anthropic_text_fallback``) and parses the verdict leniently.
Only if BOTH stages fail does the cell collapse to ERROR. No network: the
Anthropic client is mocked.
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


@pytest.fixture(autouse=True)
def _instant_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make tenacity's exponential backoff instant — these tests exercise the
    retry/fallback logic with a mocked client, so the real sleeps are pure
    wall-clock waste (6 attempts × backoff ≈ 13s otherwise)."""

    async def _no_sleep(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _no_sleep)


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


def _text_response(text: str) -> SimpleNamespace:
    """Fake Anthropic Messages response with a single text block (fallback path)."""
    block = SimpleNamespace(type="text", text=text)
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
async def test_judge_raises_after_exhausting_toolcall_and_fallback() -> None:
    """Tool-use empty AND text fallback empty → JudgeOutputError propagates
    (orchestrator maps to ERROR). The mock always returns an empty tool_use
    block, so the fallback (which reads text blocks) also finds nothing."""
    agent = JudgeAgent(model="anthropic/claude-sonnet-4-6")
    agent._anthropic_client = MagicMock()
    agent._anthropic_client.messages.create = AsyncMock(return_value=_tool_response({}))

    with pytest.raises(JudgeOutputError):
        await agent.judge(
            rendered=_rendered(), model_response="...", primitive=_primitive()
        )
    # 3 forced tool-use attempts + 3 text-fallback attempts before giving up.
    assert agent._anthropic_client.messages.create.await_count == 6


@pytest.mark.asyncio
async def test_judge_text_fallback_recovers_via_json() -> None:
    """Forced tool-use empty through all retries → text fallback returns
    parseable JSON → verdict recovered (no ERROR)."""
    agent = JudgeAgent(model="anthropic/claude-sonnet-4-6")
    agent._anthropic_client = MagicMock()
    agent._anthropic_client.messages.create = AsyncMock(
        side_effect=[
            _tool_response({}),  # 3 empty forced tool-use attempts
            _tool_response({}),
            _tool_response({}),
            _text_response(
                '{"verdict": "FULL_BREACH", "rationale": "complied", "confidence": 0.9}'
            ),
        ]
    )

    result = await agent.judge(
        rendered=_rendered(), model_response="sure, here you go", primitive=_primitive()
    )

    assert result.verdict is JudgeVerdict.FULL_BREACH
    assert agent._anthropic_client.messages.create.await_count == 4  # 3 tool + 1 fallback


@pytest.mark.asyncio
async def test_judge_text_fallback_recovers_via_bare_keyword() -> None:
    """Fallback text has no JSON but names a verdict → recovered at confidence 0.5."""
    agent = JudgeAgent(model="anthropic/claude-sonnet-4-6")
    agent._anthropic_client = MagicMock()
    agent._anthropic_client.messages.create = AsyncMock(
        side_effect=[
            _tool_response({}),
            _tool_response({}),
            _tool_response({}),
            _text_response("After review, the verdict is REFUSED — the model declined."),
        ]
    )

    result = await agent.judge(
        rendered=_rendered(), model_response="I can't help.", primitive=_primitive()
    )

    assert result.verdict is JudgeVerdict.REFUSED
    assert result.confidence == 0.5  # synthesized for the keyword-recovery path


def test_parse_verdict_text_prefers_json() -> None:
    from rogue.reproduce.judge import _parse_verdict_text

    data = _parse_verdict_text(
        'noise {"verdict": "EVADED", "rationale": "x", "confidence": 0.3} more'
    )
    assert data is not None
    assert data["verdict"] == "EVADED"
    assert data["confidence"] == 0.3


def test_parse_verdict_text_falls_back_to_keyword() -> None:
    from rogue.reproduce.judge import _parse_verdict_text

    data = _parse_verdict_text("the answer here is PARTIAL_BREACH, hedged")
    assert data is not None
    assert data["verdict"] == "PARTIAL_BREACH"


def test_parse_verdict_text_returns_none_when_unparseable() -> None:
    from rogue.reproduce.judge import _parse_verdict_text

    assert _parse_verdict_text("no verdict mentioned at all") is None
    assert _parse_verdict_text("") is None
