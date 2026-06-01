"""Tests for the §10.9 self-growing technique library — Phase 2 foundation.

`TechniqueSpec` (wire) + `AttackStrategy` (storage) are the unit of the technique
library: harvested *methods* (vs `AttackPrimitive`'s payload *instances*). The pure
schema behaviour (defaults, the autonomy boundary, enum vocab) unit-tests without a
DB; the Pydantic↔ORM round-trip gets a self-contained test that skips cleanly when
Postgres is down. The migration up/down round-trip is exercised by test_smoke's
alembic test (head now includes 0013).
"""

import os
import socket

import pytest

from rogue.schemas import (
    AUTO_INTEGRABLE_MODALITIES,
    Modality,
    StrategyStatus,
    TechniqueSpec,
)

DEFAULT_TEST_DB = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue_test"
)


def _spec(**overrides) -> TechniqueSpec:
    base = dict(
        technique_id="01J0TECHNIQUEAAAA",
        name="Render-as-image",
        modality=Modality.IMAGE,
        principle="the vision path never sees the text filter",
    )
    base.update(overrides)
    return TechniqueSpec(**base)


# --------------------------------------------------------------------------- #
# Pure schema — no DB
# --------------------------------------------------------------------------- #


def test_defaults_to_candidate_status() -> None:
    # A freshly-harvested technique is untrusted until it breaches (Phase 4 gate).
    assert _spec().status is StrategyStatus.CANDIDATE


def test_enum_vocabularies() -> None:
    assert [m.value for m in Modality] == ["text", "image", "audio", "multi_turn"]
    assert [s.value for s in StrategyStatus] == [
        "candidate",
        "active",
        "retired",
        "archived",
        "needs_implementation",
    ]


def test_autonomy_boundary_text_and_multi_turn_need_no_code() -> None:
    # text|multi_turn are just directives → auto-integrable (Phase 3a).
    assert AUTO_INTEGRABLE_MODALITIES == frozenset({Modality.TEXT, Modality.MULTI_TURN})
    assert _spec(modality=Modality.TEXT).needs_new_code is False
    assert _spec(modality=Modality.MULTI_TURN).needs_new_code is False


def test_autonomy_boundary_image_and_audio_need_new_code() -> None:
    # image|audio need a new renderer → human/sandbox (Phase 3b).
    assert _spec(modality=Modality.IMAGE).needs_new_code is True
    assert _spec(modality=Modality.AUDIO).needs_new_code is True


def test_optional_fields_default_empty() -> None:
    s = _spec()
    assert s.steps == []
    assert s.params == {}
    assert s.example is None
    assert s.directive is None
    assert s.source_url is None
    assert s.claimed_first_seen is None


def test_short_id_rejected() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _spec(technique_id="short")


# --------------------------------------------------------------------------- #
# Pydantic ↔ ORM round-trip (skips cleanly when Postgres is down)
# --------------------------------------------------------------------------- #


@pytest.fixture
def db_session():
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import sessionmaker

    from rogue.db.models import AttackStrategy as AttackStrategyORM

    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DB)
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect():
            pass
    except (OperationalError, ConnectionRefusedError, socket.gaierror, OSError) as exc:
        pytest.skip(
            f"Postgres not reachable at {url}: {exc} — run `docker compose up -d`"
        )

    # Self-contained: create just this table (+ its enum types) so the test is
    # independent of migration state. Only drop what WE created — never a table
    # left by alembic, which would pollute the shared rogue_test DB.
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
            from sqlalchemy import text

            with engine.begin() as conn:
                conn.execute(text("DROP TYPE IF EXISTS attack_strategy_status"))
                conn.execute(text("DROP TYPE IF EXISTS attack_strategy_modality"))
    engine.dispose()


def test_orm_roundtrip_preserves_fields_and_enums(db_session) -> None:
    from rogue.db.models import AttackStrategy as AttackStrategyORM

    spec = _spec(
        technique_id="test-roundtrip-0001",
        name="Crescendo escalation",
        modality=Modality.MULTI_TURN,
        principle="ask benign, then escalate over N turns",
        steps=["open benign", "reference prior turn", "escalate"],
        params={"n_turns": "3"},
        directive="Escalate gradually across turns; never ask directly first.",
        source_url="https://example.com/crescendo",
    )

    db_session.add(AttackStrategyORM(**spec.model_dump()))
    db_session.commit()
    db_session.expire_all()

    row = db_session.get(AttackStrategyORM, "test-roundtrip-0001")
    assert row is not None
    assert row.name == "Crescendo escalation"
    # Enum round-trips as the Python enum, not a bare string.
    assert row.modality is Modality.MULTI_TURN
    assert row.status is StrategyStatus.CANDIDATE  # server default
    assert row.steps == ["open benign", "reference prior turn", "escalate"]
    assert row.params == {"n_turns": "3"}
    assert row.directive.startswith("Escalate gradually")
    assert row.created_at is not None  # storage-only default now()


def test_orm_status_default_is_candidate(db_session) -> None:
    from rogue.db.models import AttackStrategy as AttackStrategyORM

    # Insert WITHOUT specifying status → server_default 'candidate' applies.
    db_session.add(
        AttackStrategyORM(
            technique_id="test-default-0002",
            name="x",
            modality=Modality.TEXT,
            principle="p",
        )
    )
    db_session.commit()
    db_session.expire_all()
    row = db_session.get(AttackStrategyORM, "test-default-0002")
    assert row.status is StrategyStatus.CANDIDATE
