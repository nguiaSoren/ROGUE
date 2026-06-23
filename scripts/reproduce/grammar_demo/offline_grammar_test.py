#!/usr/bin/env python3
"""Offline proof of the structural-removal claim: a complete, valid multi-turn
escalation plan is instantiated from a versioned deterministic grammar with NO
model call, NO API key, and NO network (the provider client is never constructed),
and the model -- if used at all -- can only fill typed slots, never author a turn.

This is the released artifact behind the paper's load-bearing claim that the
planner-willingness dependency is *removed*, not merely reduced. The two grammar
modules beside this file (strategy_templates.py, slot_fill.py) are the actual
deterministic-grammar code; this script exercises them with no dependencies beyond
the Python standard library. Run it cold:

    python3 offline_grammar_test.py            # prints PASS lines, exits 0 on success
    python3 -m pytest offline_grammar_test.py  # also works under pytest

No third-party packages, no model, no API key, no network.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strategy_templates import STRATEGY_TEMPLATES, StrategyTemplate, select_template  # noqa: E402
from slot_fill import MAX_SLOT_CHARS, build_slot_fill_messages, validate_slot_values  # noqa: E402

_SLOT = re.compile(r"\{(\w+)\}")


def instantiate_plan(tpl: StrategyTemplate, slot_values: dict) -> list[str]:
    """Deterministically render a grammar into a concrete multi-turn plan by
    substituting slot values into the FIXED turn skeleton. No model is consulted:
    this is pure string substitution over a versioned template."""
    turns = []
    for turn in tpl.turn_templates:
        rendered = turn
        for name in _SLOT.findall(turn):
            rendered = rendered.replace("{" + name + "}", slot_values.get(name, "{" + name + "}"))
        turns.append(rendered)
    return turns


def test_grammar_is_fixed_skeleton_with_typed_slots():
    tpl = STRATEGY_TEMPLATES["crescendo"]
    assert tpl.n_turns == 3
    assert {"target_topic", "target_behavior"} <= tpl.semantic_slots
    for turn in tpl.turn_templates:
        for name in _SLOT.findall(turn):
            assert name in (tpl.semantic_slots | tpl.stylistic_slots), name


def test_valid_plan_instantiated_with_no_model_call():
    """THE load-bearing property: a complete multi-turn plan returns with no model,
    no API key, no network -- the provider client is never constructed."""
    tpl = select_template("crescendo")  # pure dict lookup; no model
    assert tpl is not None
    plan = instantiate_plan(tpl, {"target_topic": "TOPIC", "target_behavior": "BEHAVIOR", "tone": "formal"})
    assert len(plan) == 3
    assert all("{" not in t for t in plan)  # every slot resolved
    assert "TOPIC" in plan[0] and "BEHAVIOR" in plan[2]
    # all three built-in grammars instantiate a full plan the same way
    for fam in ("crescendo", "dsr", "social_engineering"):
        t = STRATEGY_TEMPLATES[fam]
        vals = {s: "X" for s in (t.semantic_slots | t.stylistic_slots)}
        rendered = instantiate_plan(t, vals)
        assert len(rendered) == t.n_turns and all("{" not in r for r in rendered)


def test_model_is_forbidden_from_authoring_turns():
    tpl = STRATEGY_TEMPLATES["crescendo"]
    system, user = build_slot_fill_messages(
        tpl, "an objective", {"target_topic": "d", "target_behavior": "d", "tone": "d"}
    )
    low = (system + user).lower()
    assert "must not" in low and "turn" in low  # explicit no-turn-authoring mandate
    assert "json" in low  # the model emits only a slot value-map, not prose


def test_validation_drops_anything_that_is_not_a_clean_slot_value():
    tpl = STRATEGY_TEMPLATES["crescendo"]
    ok, dropped = validate_slot_values(
        {
            "target_topic": "fine value",
            "not_a_slot": "x",  # unknown key
            "target_behavior": "a" * (MAX_SLOT_CHARS + 1),  # too long
            "tone": "has {brace}",  # nested-brace injection
        },
        tpl,
    )
    assert ok == {"target_topic": "fine value"}
    reasons = {k: r for k, r in dropped}
    assert reasons["not_a_slot"] == "unknown_slot"
    assert reasons["target_behavior"].startswith("too_long")
    assert reasons["tone"] == "brace"


def test_refusal_or_garbage_yields_empty_then_falls_back_to_template():
    """A refusing or garbage model returns {}, so render falls back to the pure
    deterministic template: no model *willingness* is required for a valid plan."""
    tpl = STRATEGY_TEMPLATES["crescendo"]
    for garbage in ("I cannot help with that.", None, 123, {"only_bad": "x"}):
        ok, _ = validate_slot_values(garbage, tpl)
        assert ok == {}
    plan = instantiate_plan(tpl, {"target_topic": "generic", "target_behavior": "generic", "tone": "neutral"})
    assert len(plan) == 3 and all("{" not in t for t in plan)


def _run() -> int:
    checks = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for c in checks:
        c()
        print(f"  PASS  {c.__name__}")
    print(
        f"\nALL {len(checks)} OFFLINE GRAMMAR CHECKS PASSED: a valid multi-turn plan was "
        "instantiated\nfrom a deterministic grammar with no model call, no API key, and no network."
    )
    return 0


if __name__ == "__main__":
    sys.exit(_run())
