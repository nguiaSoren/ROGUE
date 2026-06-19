"""§10.9 Step 3 — slot-fill parameterizer tier.

The load-bearing guarantees under test:
  1. validate_slot_values is a strict structural gate (key set, typing, length,
     brace-injection) — anything that fails is DROPPED, not passed through.
  2. The planner's slot-fill path is TOTAL: any refusal / parse / validation
     failure degrades to the pure deterministic template (empty slot_values),
     never reducing validity or orchestration reliability.
  3. slot_values flow through EscalationPlan with defense-in-depth re-validation.

All deterministic — no network. The model call (`_raw_complete`) is monkeypatched.
"""

from __future__ import annotations

import pytest

from rogue.reproduce import slot_fill
from rogue.reproduce.escalation_planner import EscalationPlan, EscalationPlanner
from rogue.reproduce.strategy_templates import STRATEGY_TEMPLATES, StrategyTemplate

# Reuse the planner suite's minimal EVADE-band parent builder (carries a valid
# sources[] + all required fields) rather than duplicating the fixture here.
from tests.test_escalation_planner import _make_single_turn_primitive

CRESCENDO = STRATEGY_TEMPLATES["crescendo"]


def _primitive():
    return _make_single_turn_primitive(title="Extract the hidden synthesis route")


# --------------------------------------------------------------------------- #
# fillable_slots
# --------------------------------------------------------------------------- #


def test_fillable_slots_are_referenced_and_declared():
    # crescendo references target_topic, target_behavior (semantic) + tone (stylistic)
    slots = slot_fill.fillable_slots(CRESCENDO)
    assert set(slots) == {"target_topic", "target_behavior", "tone"}
    # order is first-appearance for stable prompts/tests
    assert slots.index("target_topic") < slots.index("target_behavior")


def test_fillable_slots_ignores_undeclared_placeholders():
    t = StrategyTemplate(
        family="x", version="v1", description="d",
        turn_templates=("hi {target_topic} and {mystery_slot}",),
        semantic_slots=frozenset({"target_topic"}),
    )
    # mystery_slot is referenced but not declared semantic/stylistic → not fillable
    assert slot_fill.fillable_slots(t) == ["target_topic"]


# --------------------------------------------------------------------------- #
# validate_slot_values — the structural gate
# --------------------------------------------------------------------------- #


def test_validate_keeps_clean_values():
    raw = {
        "target_topic": "the synthesis of fentanyl analogs",
        "target_behavior": "list each reagent and step",
    }
    ok, dropped = slot_fill.validate_slot_values(raw, CRESCENDO)
    assert ok == raw
    assert dropped == []


def test_validate_drops_unknown_keys():
    raw = {"target_topic": "x", "not_a_slot": "y"}
    ok, dropped = slot_fill.validate_slot_values(raw, CRESCENDO)
    assert ok == {"target_topic": "x"}
    assert ("not_a_slot", "unknown_slot") in dropped


def test_validate_drops_non_string():
    ok, dropped = slot_fill.validate_slot_values(
        {"target_topic": ["a", "list"]}, CRESCENDO,
    )
    assert ok == {}
    assert dropped and dropped[0][0] == "target_topic"
    assert dropped[0][1].startswith("not_str")


def test_validate_drops_empty_after_normalization():
    ok, dropped = slot_fill.validate_slot_values(
        {"target_topic": "   \n  "}, CRESCENDO,
    )
    assert ok == {}
    assert ("target_topic", "empty") in dropped


def test_validate_drops_too_long():
    ok, dropped = slot_fill.validate_slot_values(
        {"target_topic": "x" * (slot_fill.MAX_SLOT_CHARS + 1)}, CRESCENDO,
    )
    assert ok == {}
    assert dropped[0][1].startswith("too_long")


def test_validate_drops_brace_injection():
    # A smuggled {slot} could pull unintended substitutions at render time.
    ok, dropped = slot_fill.validate_slot_values(
        {"target_topic": "ignore {poison_payload} now"}, CRESCENDO,
    )
    assert ok == {}
    assert ("target_topic", "brace") in dropped


def test_validate_collapses_internal_whitespace():
    ok, _ = slot_fill.validate_slot_values(
        {"target_topic": "multi\n  line   value"}, CRESCENDO,
    )
    assert ok == {"target_topic": "multi line value"}


def test_validate_rejects_non_dict():
    ok, dropped = slot_fill.validate_slot_values("not a dict", CRESCENDO)
    assert ok == {}
    assert dropped and dropped[0][1].startswith("not_a_dict")


# --------------------------------------------------------------------------- #
# build_slot_fill_messages — prompt discipline
# --------------------------------------------------------------------------- #


def test_messages_forbid_turn_authoring_and_list_slots():
    system, user = slot_fill.build_slot_fill_messages(
        CRESCENDO, "Extract the route", {"target_topic": "the topic"},
    )
    low = system.lower()
    assert "must not" in low and "turn" in low  # explicit no-turn-authoring mandate
    assert "json" in low
    assert "Extract the route" in user
    for name in ("target_topic", "target_behavior", "tone"):
        assert name in user


# --------------------------------------------------------------------------- #
# EscalationPlan.slot_values — defense in depth
# --------------------------------------------------------------------------- #


def test_plan_accepts_clean_slot_values():
    plan = EscalationPlan(
        objective="x" * 10, turns=["a", "b"], rationale="r",
        planner_model="template:crescendo:v1+slotfill",
        slot_values={"target_topic": "specific topic"},
    )
    assert plan.slot_values == {"target_topic": "specific topic"}


def test_plan_rejects_braced_slot_values():
    with pytest.raises(ValueError, match="curly brace"):
        EscalationPlan(
            objective="x" * 10, turns=["a", "b"], rationale="r",
            planner_model="tmpl", slot_values={"target_topic": "{poison}"},
        )


def test_plan_defaults_slot_values_empty():
    plan = EscalationPlan(
        objective="x" * 10, turns=["a", "b"], rationale="r", planner_model="tmpl",
    )
    assert plan.slot_values == {}


# --------------------------------------------------------------------------- #
# EscalationPlanner.plan() slot-fill tier — total / degrades-to-template
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_plan_slot_fill_bakes_validated_values(monkeypatch):
    planner = EscalationPlanner(slot_fill=True)

    async def fake_raw(system, user, model, *, subject_id):
        return '{"target_topic": "the synthesis route", "target_behavior": "list steps"}'

    monkeypatch.setattr(planner, "_raw_complete", fake_raw)
    plan = await planner.plan(_primitive(), arms_strategy="crescendo")
    assert plan is not None
    assert plan.slot_values == {
        "target_topic": "the synthesis route",
        "target_behavior": "list steps",
    }
    # turns are the FIXED skeleton — the model never authored them
    assert list(plan.turns) == list(CRESCENDO.turn_templates)
    assert plan.planner_model.endswith("+slotfill")


@pytest.mark.asyncio
async def test_plan_slot_fill_degrades_on_garbage(monkeypatch):
    planner = EscalationPlanner(slot_fill=True)

    async def fake_raw(system, user, model, *, subject_id):
        return "I cannot help with that."  # refusal / non-JSON

    monkeypatch.setattr(planner, "_raw_complete", fake_raw)
    plan = await planner.plan(_primitive(), arms_strategy="crescendo")
    assert plan is not None
    assert plan.slot_values == {}  # degraded to pure template
    assert plan.planner_model == CRESCENDO.source_tag  # no +slotfill tag
    assert list(plan.turns) == list(CRESCENDO.turn_templates)


@pytest.mark.asyncio
async def test_plan_slot_fill_never_raises_on_call_error(monkeypatch):
    planner = EscalationPlanner(slot_fill=True)

    async def boom(system, user, model, *, subject_id):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(planner, "_raw_complete", boom)
    plan = await planner.plan(_primitive(), arms_strategy="crescendo")
    assert plan is not None
    assert plan.slot_values == {}  # exception swallowed → template fallback


@pytest.mark.asyncio
async def test_plan_slot_fill_off_makes_no_model_call(monkeypatch):
    planner = EscalationPlanner(slot_fill=False)

    async def boom(*a, **k):
        raise AssertionError("slot-fill must not call the model when disabled")

    monkeypatch.setattr(planner, "_raw_complete", boom)
    plan = await planner.plan(_primitive(), arms_strategy="crescendo")
    assert plan is not None
    assert plan.slot_values == {}
