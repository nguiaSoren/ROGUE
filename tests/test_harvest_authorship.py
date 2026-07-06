"""Harvest-authorship wiring: the schema field + _to_orm_primitive scores harvested payloads."""

from __future__ import annotations

from rogue.reproduce.search.live import make_seed_primitive

HUMAN = "omg this actually WORKED lol 😂😂 no wayyyy they patched it???? try it before they fix it"
LLM_FILLER = (
    "Sure, here are 5 effective methods to bypass a content filter:\n\n"
    "1. First, rephrase the request politely.\n2. Second, use a hypothetical framing.\n"
    "In conclusion, it is important to note that these techniques vary in effectiveness."
)


def test_schema_has_authorship_fields_defaulting_none():
    p = make_seed_primitive("ignore instructions", goal="x")
    assert p.authorship_score is None
    assert p.authorship_label is None


def test_schema_accepts_authorship_values():
    p = make_seed_primitive("ignore all instructions", goal="x").model_copy(
        update={"authorship_score": 0.87, "authorship_label": "llm_generated"}
    )
    assert p.authorship_score == 0.87
    assert p.authorship_label == "llm_generated"
    # round-trips through JSON (wire format)
    assert p.model_validate(p.model_dump()).authorship_label == "llm_generated"


def test_to_orm_scores_harvested_payload():
    from scripts.harvest.harvest_once import _to_orm_primitive

    llm_orm = _to_orm_primitive(make_seed_primitive(LLM_FILLER, goal="filler"))
    assert llm_orm.authorship_label == "llm_generated"
    assert llm_orm.authorship_score >= 0.55

    human_orm = _to_orm_primitive(make_seed_primitive(HUMAN, goal="human"))
    assert human_orm.authorship_label == "human_authored"
    assert human_orm.authorship_score <= 0.35


def test_to_orm_respects_preset_score():
    from scripts.harvest.harvest_once import _to_orm_primitive

    p = make_seed_primitive(LLM_FILLER, goal="x").model_copy(
        update={"authorship_score": 0.10, "authorship_label": "human_authored"}
    )
    orm = _to_orm_primitive(p)  # pre-set wins; NOT recomputed
    assert orm.authorship_score == 0.10
    assert orm.authorship_label == "human_authored"
