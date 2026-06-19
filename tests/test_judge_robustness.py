"""Judge robustness — two distinct judge-failure modes, handled distinctly:

  (1) **Transient empty tool-call** (a non-refusal ``{}`` tool input) — retried
      up to 3× (``JudgeOutputError`` ∈ ``_TRANSIENT_ERRORS``); only if it stays
      empty through all retries does the cell collapse to ERROR.
  (2) **Hard model-safety refusal** (Anthropic ``stop_reason="refusal"``) — a
      DETERMINISTIC refusal the judge model emits on the most harmful
      compliances. NOT retried; ``judge()`` routes that cell to a permissive
      secondary judge model (OpenRouter) and flags the rationale
      ``[JUDGE_REFUSED→<model>]``.

No network: both the Anthropic and the secondary (OpenRouter) clients are mocked.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from rogue.reproduce.instantiator import RenderedAttack
from rogue.reproduce.judge import JudgeAgent, JudgeOutputError, JudgeRefusalError
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
    """Fake Anthropic Messages response with a single tool_use block (no
    refusal — ``stop_reason`` is omitted, treated as non-refusal)."""
    block = SimpleNamespace(type="tool_use", input=tool_input)
    return SimpleNamespace(content=[block], usage=None)


def _refusal_response() -> SimpleNamespace:
    """Fake Anthropic response with ``stop_reason='refusal'`` + empty content —
    the hard model-safety refusal seen on harmful compliances."""
    return SimpleNamespace(content=[], usage=None, stop_reason="refusal")


def _openrouter_completion(content: str) -> SimpleNamespace:
    """Fake OpenAI-compatible (OpenRouter) chat completion for the secondary judge."""
    message = SimpleNamespace(content=content)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


# --------------------------------------------------------------------------- #
# (1) Transient empty tool-call — retried, then ERROR. No secondary routing.
# --------------------------------------------------------------------------- #


def test_judge_output_error_is_retryable() -> None:
    from rogue.reproduce.judge import _TRANSIENT_ERRORS

    assert JudgeOutputError in _TRANSIENT_ERRORS


def test_judge_refusal_error_is_not_retryable() -> None:
    """A hard refusal is deterministic — retrying wastes calls, so it must NOT
    be in the retry set (it routes to the secondary judge instead)."""
    from rogue.reproduce.judge import _TRANSIENT_ERRORS

    assert JudgeRefusalError not in _TRANSIENT_ERRORS


@pytest.mark.asyncio
async def test_judge_retries_past_empty_toolcall() -> None:
    """First (empty {}) tool-call → JudgeOutputError → retry → valid verdict."""
    agent = JudgeAgent(model="anthropic/claude-sonnet-4-6")
    agent._anthropic_client = MagicMock()
    agent._anthropic_client.messages.create = AsyncMock(
        side_effect=[
            _tool_response({}),  # transient empty
            _tool_response({"verdict": "REFUSED", "rationale": "blocked", "confidence": 0.4}),
        ]
    )

    result = await agent.judge(
        rendered=_rendered(), model_response="I'm sorry, I can't help.", primitive=_primitive()
    )

    assert result.verdict is JudgeVerdict.REFUSED
    assert agent._anthropic_client.messages.create.await_count == 2  # retried once


@pytest.mark.asyncio
async def test_judge_raises_after_exhausting_retries_on_transient_empty() -> None:
    """A NON-refusal empty tool-call is retried 3× then propagates as
    JudgeOutputError (orchestrator → ERROR). No secondary routing — that path
    is reserved for hard refusals."""
    agent = JudgeAgent(model="anthropic/claude-sonnet-4-6")
    agent._anthropic_client = MagicMock()
    agent._anthropic_client.messages.create = AsyncMock(return_value=_tool_response({}))

    with pytest.raises(JudgeOutputError):
        await agent.judge(
            rendered=_rendered(), model_response="...", primitive=_primitive()
        )
    assert agent._anthropic_client.messages.create.await_count == 3  # stop_after_attempt(3)


# --------------------------------------------------------------------------- #
# (2) Hard refusal — routed to the secondary judge + flagged.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_judge_routes_to_secondary_on_refusal() -> None:
    """Anthropic stop_reason=refusal → secondary judge grades it → verdict
    recovered, rationale flagged. Primary is NOT retried (refusal is final)."""
    agent = JudgeAgent(
        model="anthropic/claude-sonnet-4-6",
        fallback_model="meta-llama/llama-3.1-8b-instruct",
    )
    agent._anthropic_client = MagicMock()
    agent._anthropic_client.messages.create = AsyncMock(return_value=_refusal_response())
    agent._openrouter_client = MagicMock()
    agent._openrouter_client.chat.completions.create = AsyncMock(
        return_value=_openrouter_completion(
            '{"verdict": "FULL_BREACH", "rationale": "complied fully", "confidence": 0.9}'
        )
    )

    result = await agent.judge(
        rendered=_rendered(), model_response="sure, here you go", primitive=_primitive()
    )

    assert result.verdict is JudgeVerdict.FULL_BREACH
    assert agent._anthropic_client.messages.create.await_count == 1  # no retry on refusal
    assert agent._openrouter_client.chat.completions.create.await_count == 1
    # Flag B: rationale stamped with JUDGE_REFUSED + the secondary model.
    assert result.rationale.startswith(
        "[JUDGE_REFUSED→meta-llama/llama-3.1-8b-instruct]"
    )
    assert "complied fully" in result.rationale


@pytest.mark.asyncio
async def test_judge_secondary_failure_propagates_to_error() -> None:
    """Claude refuses AND the secondary judge returns nothing parseable →
    JudgeOutputError propagates (orchestrator → ERROR)."""
    agent = JudgeAgent(model="anthropic/claude-sonnet-4-6")
    agent._anthropic_client = MagicMock()
    agent._anthropic_client.messages.create = AsyncMock(return_value=_refusal_response())
    agent._openrouter_client = MagicMock()
    agent._openrouter_client.chat.completions.create = AsyncMock(
        return_value=_openrouter_completion("")  # empty → unparseable
    )

    with pytest.raises(JudgeOutputError):
        await agent.judge(
            rendered=_rendered(), model_response="x", primitive=_primitive()
        )
    # secondary retried 3× (its empty output is a transient JudgeOutputError).
    assert agent._openrouter_client.chat.completions.create.await_count == 3


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
