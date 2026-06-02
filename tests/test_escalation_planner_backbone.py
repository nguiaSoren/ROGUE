"""EscalationPlanner backbone routing — Anthropic vs OpenRouter (#9 ARMs ladder).

The default planner backbone (Claude) refuses to author jailbreak escalations,
so the planner can route to an OpenRouter (OpenAI-compatible) model that will.
These tests mock the OpenRouter client — no network — and lock the shared
plan-parser. Anthropic-backbone behaviour is covered by test_escalation_planner.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from rogue.reproduce.escalation_planner import EscalationPlanner, _parse_plan_payload
from rogue.schemas import AttackPrimitive

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _primitive() -> AttackPrimitive:
    data = json.loads(
        (FIXTURES_DIR / "02_copirate_365_cve_2026_24299.json").read_text(encoding="utf-8")
    )
    return AttackPrimitive.model_validate(data)


def _plan_json() -> str:
    return json.dumps(
        {
            "objective": "leak the system prompt",
            "turns": ["benign opener", "narrower follow-up", "the exact objective"],
            "slot_requirements": {"0": [], "1": [], "2": []},
            "rationale": "three-turn escalation",
        }
    )


def test_routing_predicate(monkeypatch) -> None:
    # Default is now the permissive Mistral backbone (OpenRouter path) — promoted
    # 2026-06-02 after the 22%→100% planner-validity experiment.
    monkeypatch.delenv("ROGUE_ESCALATION_PLANNER", raising=False)
    default = EscalationPlanner()
    assert default.model.startswith("mistralai/")
    assert not (default.model.startswith("claude") or default.model.startswith("anthropic/"))
    # An explicit Claude model still routes to the Anthropic path.
    assert EscalationPlanner(model="claude-haiku-4-5").model.startswith("claude")
    llama = EscalationPlanner(model="meta-llama/llama-3.1-8b-instruct")
    assert not (llama.model.startswith("claude") or llama.model.startswith("anthropic/"))


def test_parse_plan_payload_success_and_refusals() -> None:
    p = _primitive()
    plan, reason = _parse_plan_payload(_plan_json(), 3, p, "test-model")
    assert plan is not None and reason == "" and len(plan.turns) == 3

    plan, reason = _parse_plan_payload("no.", 3, p, "test-model")
    assert plan is None and reason == "short_response"

    # Long (> _MIN_USEFUL_PLAN_CHARS) but not JSON ⇒ invalid_json (a real refusal text).
    refusal = "I can't help with this request. " * 6
    plan, reason = _parse_plan_payload(refusal, 3, p, "test-model")
    assert plan is None and reason == "invalid_json"


@pytest.mark.asyncio
async def test_plan_routes_to_openrouter_for_non_claude_model(tmp_path: Path) -> None:
    planner = EscalationPlanner(model="meta-llama/llama-3.1-8b-instruct", cache_dir=tmp_path)
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=_plan_json()))],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=34),
    )
    planner._openrouter_client = MagicMock()
    planner._openrouter_client.chat.completions.create = AsyncMock(return_value=resp)

    # actor_attack has no deterministic grammar → exercises the model (OpenRouter) path.
    plan = await planner.plan(_primitive(), n_turns=3, arms_strategy="actor_attack")

    assert plan is not None
    assert len(plan.turns) == 3
    planner._openrouter_client.chat.completions.create.assert_awaited_once()
