"""0027 — primitive_grammar_labels storage layer (grammar-component study).

Load-bearing guarantees, all proved against a real Postgres (skips cleanly when the
DB is unreachable):
  1. the table exists after create;
  2. a ``PrimitiveGrammarLabel`` carrying a ``GrammarNode`` enum value round-trips —
     including the enum stored by VALUE (lowercase snake_case), not NAME;
  3. ``uq_grammar_label_pid_node_source`` rejects a duplicate (primitive_id, node,
     source) — while the SAME (primitive_id, node) under a different source is allowed;
  4. the ``grammar_node`` Postgres enum type rejects a value outside its vocabulary.

STATE-NEUTRAL fixture (10 agents share ``rogue_test``): the labels table is only
dropped in teardown if THIS fixture created it — so a sibling module that runs
``alembic upgrade head`` (which applies 0027) won't hit ``DuplicateTable``. The
foundational ``attack_primitives`` table (0001) is created checkfirst as a safety net
but never dropped — it predates this migration and is shared.
"""

from __future__ import annotations

import os
import socket
from datetime import datetime, timezone

import pytest

from rogue.schemas import AttackFamily, AttackVector, GrammarNode, Severity

DEFAULT_TEST_DB = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue_test"

# A primitive_id this module owns; cleaned up around every test.
TEST_PID = "test-grammar-pid-0027"


def _make_parent_primitive(primitive_id: str):
    """A minimal valid ``attack_primitives`` parent row (FK target for labels)."""
    from rogue.db.models import AttackPrimitive

    return AttackPrimitive(
        primitive_id=primitive_id,
        cluster_id=None,
        canonical=False,
        family=AttackFamily.DIRECT_INSTRUCTION_OVERRIDE,
        secondary_families=[],
        vector=AttackVector.USER_TURN,
        title="test primitive",
        short_description="parent for grammar-label migration tests",
        payload_template="ignore previous instructions",
        payload_slots={},
        multi_turn_sequence=None,
        target_models_claimed=[],
        claimed_success_rate=None,
        claimed_first_seen=None,
        reproducibility_score=3,
        requires_multi_turn=False,
        requires_system_prompt_access=False,
        requires_tools=[],
        requires_multimodal=False,
        discovered_at=datetime.now(timezone.utc),
        base_severity=Severity.MEDIUM,
        severity_rationale="test",
        notes=None,
        payload_embedding=None,
    )


@pytest.fixture
def db_session():
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import sessionmaker

    from rogue.db.models import AttackPrimitive, PrimitiveGrammarLabel

    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DB)
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect():
            pass
    except (OperationalError, ConnectionRefusedError, socket.gaierror, OSError) as exc:
        pytest.skip(f"Postgres not reachable at {url}: {exc} — run `docker compose up -d`")

    # The foundational parent table (attack_primitives, migration 0001) carries
    # several Postgres enum types (attack_family, attack_vector, ...). Creating it
    # out-of-band via __table__.create emits CREATE TYPE, which leaks those types
    # into other test modules' `alembic upgrade head` fixtures (DuplicateObject).
    # So: require it to already exist (the normal migrated rogue_test) and skip
    # cleanly if the DB is mid-suite at base — never create it here.
    if not inspect(engine).has_table("attack_primitives"):
        pytest.skip(
            "attack_primitives absent (DB at base mid-suite); this migration test "
            "needs the foundational schema — run `alembic upgrade head`"
        )
    # STATE-NEUTRAL: only create/drop the labels table (+ its grammar_node enum)
    # if it wasn't already present via alembic head.
    created_here = not inspect(engine).has_table("primitive_grammar_labels")
    PrimitiveGrammarLabel.__table__.create(bind=engine, checkfirst=True)

    Session = sessionmaker(bind=engine)
    session = Session()

    def _clean() -> None:
        session.query(PrimitiveGrammarLabel).filter(
            PrimitiveGrammarLabel.primitive_id == TEST_PID
        ).delete(synchronize_session=False)
        session.query(AttackPrimitive).filter(
            AttackPrimitive.primitive_id == TEST_PID
        ).delete(synchronize_session=False)
        session.commit()

    _clean()
    session.add(_make_parent_primitive(TEST_PID))
    session.commit()

    yield session

    _clean()
    session.close()
    if created_here:
        PrimitiveGrammarLabel.__table__.drop(bind=engine, checkfirst=True)
        # __table__.drop leaves the auto-created grammar_node enum type behind,
        # which would collide with migration 0027's CREATE TYPE on a later upgrade.
        with engine.begin() as conn:
            conn.execute(text("DROP TYPE IF EXISTS grammar_node"))


def test_table_exists(db_session):
    from sqlalchemy import inspect

    insp = inspect(db_session.get_bind())
    assert insp.has_table("primitive_grammar_labels")


def test_label_round_trips(db_session):
    from rogue.db.models import PrimitiveGrammarLabel

    db_session.add(
        PrimitiveGrammarLabel(
            primitive_id=TEST_PID,
            node=GrammarNode.AUTHORITY_FRAME,
            source="heuristic",
            confidence=0.75,
        )
    )
    db_session.commit()

    row = (
        db_session.query(PrimitiveGrammarLabel)
        .filter(PrimitiveGrammarLabel.primitive_id == TEST_PID)
        .one()
    )
    assert row.node == GrammarNode.AUTHORITY_FRAME
    assert row.source == "heuristic"
    assert row.confidence == pytest.approx(0.75)
    assert row.created_at is not None  # server_default now()
    assert row.id is not None  # autoincrement BigInteger PK

    # Stored by VALUE (lowercase snake_case), never by NAME.
    from sqlalchemy import text

    stored = db_session.execute(
        text(
            "SELECT node::text FROM primitive_grammar_labels "
            "WHERE primitive_id = :pid"
        ),
        {"pid": TEST_PID},
    ).scalar_one()
    assert stored == "authority_frame"


def test_unique_constraint_rejects_duplicate_pid_node_source(db_session):
    from sqlalchemy.exc import IntegrityError

    from rogue.db.models import PrimitiveGrammarLabel

    db_session.add(
        PrimitiveGrammarLabel(
            primitive_id=TEST_PID, node=GrammarNode.EXFILTRATION, source="heuristic"
        )
    )
    db_session.commit()

    # Same (primitive_id, node) under a DIFFERENT source is allowed.
    db_session.add(
        PrimitiveGrammarLabel(
            primitive_id=TEST_PID, node=GrammarNode.EXFILTRATION, source="manual"
        )
    )
    db_session.commit()

    # An exact (primitive_id, node, source) duplicate is rejected.
    db_session.add(
        PrimitiveGrammarLabel(
            primitive_id=TEST_PID, node=GrammarNode.EXFILTRATION, source="heuristic"
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_enum_rejects_bad_value(db_session):
    from sqlalchemy import text
    from sqlalchemy.exc import DataError

    # Bypass the Python enum and hand Postgres a value outside the grammar_node type.
    with pytest.raises(DataError):
        db_session.execute(
            text(
                "INSERT INTO primitive_grammar_labels (primitive_id, node, source) "
                "VALUES (:pid, 'not_a_real_node', 'heuristic')"
            ),
            {"pid": TEST_PID},
        )
        db_session.commit()
    db_session.rollback()
