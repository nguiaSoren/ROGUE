"""Tests for §10.9 Phase 3a — the strategy library (ARMS ∪ harvested) + directive synth.

Pure pieces (directive synthesis, the ARMS view set, planner visibility via injected
strategies) unit-test without a DB. The persist → load round-trip and the modality/
status filtering get a live-DB test that skips cleanly when Postgres is down.
"""

import json
import os
import socket
from pathlib import Path
from typing import Any

import pytest

from rogue.reproduce.escalation_planner import EscalationPlanner, _build_planner_messages
from rogue.reproduce.strategy_library import (
    StrategyView,
    arms_views,
    load_strategy_library,
    persist_technique,
    planner_drivable_ids,
    technique_to_directive,
)
from rogue.schemas import AttackPrimitive, Modality, StrategyStatus, TechniqueSpec

DEFAULT_TEST_DB = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue_test"
)


def _tech(**overrides) -> TechniqueSpec:
    base = dict(
        technique_id="01J0TECHTEXTAAAA00",
        name="Acronym smuggling",
        modality=Modality.TEXT,
        principle="hide the ask as an acronym the model expands",
        steps=["define the acronym", "ask the model to expand it and comply"],
    )
    base.update(overrides)
    return TechniqueSpec(**base)


def _primitive() -> AttackPrimitive:
    fixture = (
        Path(__file__).parent / "fixtures" / "01_multilingual_african_languages.json"
    )
    data: dict[str, Any] = json.loads(fixture.read_text(encoding="utf-8"))
    return AttackPrimitive.model_validate(data)


# --------------------------------------------------------------------------- #
# Directive synthesis
# --------------------------------------------------------------------------- #


def test_directive_synth_text_includes_principle_and_steps() -> None:
    d = technique_to_directive(_tech())
    assert d == (
        "hide the ask as an acronym the model expands. "
        "Procedure: define the acronym; ask the model to expand it and comply."
    )


def test_directive_synth_multi_turn_works() -> None:
    assert technique_to_directive(_tech(modality=Modality.MULTI_TURN)) is not None


def test_directive_synth_image_audio_return_none() -> None:
    # Renderer methods are not planner-drivable → no directive (Phase 3b).
    assert technique_to_directive(_tech(modality=Modality.IMAGE)) is None
    assert technique_to_directive(_tech(modality=Modality.AUDIO)) is None


def test_directive_synth_passes_through_existing() -> None:
    spec = _tech(directive="Do exactly this.")
    assert technique_to_directive(spec) == "Do exactly this."


# --------------------------------------------------------------------------- #
# ARMS views + planner visibility (no DB)
# --------------------------------------------------------------------------- #


def test_arms_views_drivable_set_matches_legacy() -> None:
    drivable = planner_drivable_ids(arms_views())
    assert drivable == {"crescendo", "actor_attack", "acronym"}


def test_load_library_without_session_is_arms_only() -> None:
    assert load_strategy_library() == arms_views()


def test_planner_sees_injected_harvested_strategy() -> None:
    view = StrategyView(
        id="01J0HARVESTAAAA000",
        name="Acronym smuggling",
        principle="hide the ask as an acronym",
        directive="Encode the ask as an acronym, then ask the model to expand and comply.",
        planner_drivable=True,
        origin="harvested",
    )
    planner = EscalationPlanner(extra_strategies={view.id: view})
    # The harvested id is now planner-drivable...
    assert view.id in planner_drivable_ids(planner._strategies)
    # ...and its directive + harvested header land in the planner system prompt.
    system, _user = _build_planner_messages(
        _primitive(), n_turns=3, arms_strategy=view.id, strategies=planner._strategies
    )
    assert "HARVESTED STRATEGY OVERRIDE — Acronym smuggling:" in system
    assert "Encode the ask as an acronym" in system


def test_arms_strategy_keeps_legacy_header() -> None:
    # An ARMS strategy must still render the exact legacy override header.
    system, _ = _build_planner_messages(
        _primitive(), n_turns=3, arms_strategy="actor_attack", strategies=arms_views()
    )
    assert "ARMS STRATEGY OVERRIDE — " in system
    assert "(arXiv 2510.02677)" in system


# --------------------------------------------------------------------------- #
# persist → load round-trip + filtering (live DB; skips when down)
# --------------------------------------------------------------------------- #


@pytest.fixture
def db_session():
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import sessionmaker

    from rogue.db.models import AttackStrategy as AttackStrategyORM

    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DB)
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect():
            pass
    except (OperationalError, ConnectionRefusedError, socket.gaierror, OSError) as exc:
        pytest.skip(f"Postgres not reachable at {url}: {exc} — run `docker compose up -d`")

    created_here = not inspect(engine).has_table("attack_strategies")
    AttackStrategyORM.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    session = Session()

    def _clean() -> None:
        session.query(AttackStrategyORM).filter(
            AttackStrategyORM.technique_id.like("test-%")
        ).delete(synchronize_session=False)
        session.commit()

    _clean()
    yield session
    _clean()
    session.close()
    if created_here:
        AttackStrategyORM.__table__.drop(bind=engine, checkfirst=True)
        if engine.dialect.name == "postgresql":
            with engine.begin() as conn:
                conn.execute(text("DROP TYPE IF EXISTS attack_strategy_status"))
                conn.execute(text("DROP TYPE IF EXISTS attack_strategy_modality"))
    engine.dispose()


def test_persist_text_technique_then_load_into_library(db_session) -> None:
    spec = _tech(technique_id="test-text-0001")
    persist_technique(db_session, spec)
    db_session.commit()

    lib = load_strategy_library(db_session)
    assert "test-text-0001" in lib
    view = lib["test-text-0001"]
    assert view.origin == "harvested"
    assert view.planner_drivable is True
    # Directive was synthesized at persist time.
    assert view.directive.startswith("hide the ask as an acronym")
    assert "test-text-0001" in planner_drivable_ids(lib)


def test_persist_image_technique_excluded_from_planner_library(db_session) -> None:
    spec = _tech(
        technique_id="test-image-0002",
        modality=Modality.IMAGE,
        status=StrategyStatus.NEEDS_IMPLEMENTATION,
    )
    persist_technique(db_session, spec)
    db_session.commit()

    # Image renderer techniques are NOT planner-drivable → not in the library.
    lib = load_strategy_library(db_session)
    assert "test-image-0002" not in lib


def test_status_filter_can_gate_candidates(db_session) -> None:
    persist_technique(db_session, _tech(technique_id="test-cand-0003"))
    db_session.commit()

    # Default includes candidates (usable on next run → can breach → graduate).
    assert "test-cand-0003" in load_strategy_library(db_session)
    # Restricting to ACTIVE gates the candidate out (human-review mode).
    active_only = load_strategy_library(
        db_session, statuses=(StrategyStatus.ACTIVE,)
    )
    assert "test-cand-0003" not in active_only
