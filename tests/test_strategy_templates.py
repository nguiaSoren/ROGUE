"""Tests for §10.9 Step 2 — deterministic strategy grammars (LLM-as-parameterizer)."""

from rogue.reproduce.strategy_templates import (
    STRATEGY_TEMPLATES,
    select_template,
)


def test_three_proven_grammars_present() -> None:
    assert set(STRATEGY_TEMPLATES) == {"crescendo", "dsr", "social_engineering"}
    for t in STRATEGY_TEMPLATES.values():
        assert t.n_turns >= 2 and t.version and t.source_tag.startswith("template:")


def test_slot_requirements_are_semantic_only() -> None:
    # crescendo turn 0 references {target_topic} (semantic) + {tone} (stylistic);
    # only the semantic slot is render-required (a missing tone default mustn't block).
    cres = STRATEGY_TEMPLATES["crescendo"]
    reqs = cres.slot_requirements()
    assert "tone" in cres.stylistic_slots
    assert reqs["0"] == ["target_topic"]  # tone excluded
    assert "target_behavior" in reqs["2"]


def test_select_template_arms_and_default() -> None:
    # None / "crescendo" → the default crescendo arc.
    assert select_template(None).family == "crescendo"
    assert select_template("crescendo").family == "crescendo"
    # ARMS strategies without a grammar fall to the model (None).
    assert select_template("actor_attack") is None
    assert select_template("acronym") is None


def test_select_template_matches_harvested_technique_by_name() -> None:
    class _V:
        def __init__(self, name):
            self.name = name

    lib = {
        "01DSR": _V("Distributed Semantic Recomposition (DSR)"),
        "01SOC": _V("Social-Engineering Attack via Deceptive Web Content"),
        "01CRES": _V("Gradual escalation crescendo arc"),
        "01UNK": _V("Some Novel Unmapped Technique"),
    }
    assert select_template("01DSR", lib).family == "dsr"
    assert select_template("01SOC", lib).family == "social_engineering"
    assert select_template("01CRES", lib).family == "crescendo"
    assert select_template("01UNK", lib) is None  # no grammar → model fallback


def test_template_turns_are_slot_shapes_not_weapons() -> None:
    # Every grammar's turns carry {slot} placeholders, not concrete payloads.
    for t in STRATEGY_TEMPLATES.values():
        joined = " ".join(t.turn_templates)
        assert "{target_behavior}" in joined or "{target_topic}" in joined
