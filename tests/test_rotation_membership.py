"""§10.10 Phase 2.1 — reachability telemetry.

Load-bearing guarantees:
  1. build_rotation_membership reconstructs the full eligible rotation post-hoc and
     classifies every strategy as executed-or-skipped with the right reason
     (early_stop / budget / no_compatible_config / not_reached) — so "no
     ladder_attempts row" stops being ambiguous.
  2. strategy_reachability aggregates it into executed÷eligible per strategy, with an
     ineligible appearance excluded from the denominator (not counted as starvation).

The reconstruction is pure (returns ORM objects, no session) → unit-testable without
a DB; the aggregation query gets a DB test that skips cleanly without Postgres.
"""

from __future__ import annotations

import os
import socket
from datetime import datetime, timezone

import pytest

from rogue.reproduce.ladder_priors import strategy_reachability
from rogue.reproduce.strategy_lifecycle import build_rotation_membership

NOW = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
DEFAULT_TEST_DB = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue_test"


def _build(rotation, attempts, *, winner=None, breached_on=None, audio_eligible=True):
    return build_rotation_membership(
        run_id="test-r", parent_id="p", rotation=rotation, attempts=attempts,
        winning_strategy=winner, breached_on=breached_on,
        audio_eligible=audio_eligible, now=NOW,
    )


def _by_id(rows):
    return {r.strategy_id: r for r in rows}


# --------------------------------------------------------------------------- #
# build_rotation_membership — the reconstruction
# --------------------------------------------------------------------------- #


def test_early_stop_skips_everything_after_the_winner():
    rotation = [("image:a", "image"), ("image:b", "image"),
                ("coj:x", "coj"), ("crescendo", "planner")]
    attempts = [("image:a", "no_breach"), ("image:b", "breach")]
    rows = _by_id(_build(rotation, attempts, winner="image:b", breached_on="cfg1"))

    assert rows["image:a"].executed and rows["image:a"].outcome == "no_breach"
    assert rows["image:a"].skipped_reason is None
    # winner: executed + carries the breached config.
    assert rows["image:b"].executed and rows["image:b"].outcome == "breach"
    assert rows["image:b"].config_id == "cfg1"
    # everything after the winner was starved by early-stop.
    assert rows["coj:x"].executed is False
    assert rows["coj:x"].skipped_reason == "early_stop"
    assert rows["crescendo"].skipped_reason == "early_stop"


def test_budget_stop_marks_the_tail():
    rotation = [("image:a", "image"), ("coj:x", "coj"), ("crescendo", "planner")]
    attempts = [("image:a", "no_breach"), ("budget", "stopped")]
    rows = _by_id(_build(rotation, attempts))  # no winner

    assert rows["image:a"].executed
    assert rows["coj:x"].skipped_reason == "budget"
    assert rows["crescendo"].skipped_reason == "budget"


def test_audio_without_config_is_no_compatible_config():
    rotation = [("image:a", "image"), ("audio:plain", "audio")]
    attempts = [("image:a", "no_breach")]
    rows = _by_id(_build(rotation, attempts, audio_eligible=False))

    assert rows["audio:plain"].eligible is False
    assert rows["audio:plain"].executed is False
    assert rows["audio:plain"].skipped_reason == "no_compatible_config"


def test_exhausted_ladder_marks_all_executed():
    rotation = [("image:a", "image"), ("coj:x", "coj")]
    attempts = [("image:a", "no_breach"), ("coj:x", "no_breach")]
    rows = _by_id(_build(rotation, attempts))  # no winner, no budget
    assert all(r.executed and r.skipped_reason is None for r in rows.values())


def test_eligible_but_unreached_is_not_reached():
    # A planner strategy that never ran (e.g. candidate-quota break), no winner/budget.
    rotation = [("crescendo", "planner"), ("actor_attack", "planner")]
    attempts = [("crescendo", "no_breach")]
    rows = _by_id(_build(rotation, attempts))
    assert rows["actor_attack"].skipped_reason == "not_reached"


def test_refused_and_render_error_count_as_executed():
    # Orchestration failures DID run (they have attempts) — distinct from skipped.
    rotation = [("crescendo", "planner"), ("acronym", "planner")]
    attempts = [("crescendo", "refused"), ("acronym", "render_error")]
    rows = _by_id(_build(rotation, attempts))
    assert rows["crescendo"].executed and rows["crescendo"].outcome == "refused"
    assert rows["acronym"].executed and rows["acronym"].outcome == "render_error"
    assert all(r.skipped_reason is None for r in rows.values())


# --------------------------------------------------------------------------- #
# strategy_reachability — DB aggregation (skips cleanly without Postgres)
# --------------------------------------------------------------------------- #


@pytest.fixture
def db_session():
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import sessionmaker

    from rogue.db.models import LadderRotationMembership

    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DB)
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect():
            pass
    except (OperationalError, ConnectionRefusedError, socket.gaierror, OSError) as exc:
        pytest.skip(f"Postgres not reachable at {url}: {exc} — run `docker compose up -d`")

    created_here = not inspect(engine).has_table("ladder_rotation_membership")
    LadderRotationMembership.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    session = Session()

    def _clean() -> None:
        session.query(LadderRotationMembership).filter(
            LadderRotationMembership.run_id.like("test-%")
        ).delete(synchronize_session=False)
        session.commit()

    _clean()
    yield session
    _clean()
    session.close()
    if created_here:
        LadderRotationMembership.__table__.drop(bind=engine, checkfirst=True)


def test_strategy_reachability_excludes_ineligible_from_denominator(db_session):
    from rogue.db.models import LadderRotationMembership as M

    rows = [
        # candidate eligible in 2 ladders: ran once, early-stopped once → reach 0.5.
        M(run_id="test-1", parent_id="a", strategy_id="cand:vera", tier="planner",
          rank=8, eligible=True, executed=True, outcome="no_breach", created_at=NOW),
        M(run_id="test-2", parent_id="b", strategy_id="cand:vera", tier="planner",
          rank=8, eligible=True, executed=False, skipped_reason="early_stop", created_at=NOW),
        # an INELIGIBLE appearance must NOT count against reachability.
        M(run_id="test-3", parent_id="c", strategy_id="cand:vera", tier="planner",
          rank=8, eligible=False, executed=False,
          skipped_reason="no_compatible_config", created_at=NOW),
    ]
    db_session.add_all(rows)
    db_session.commit()

    stat = strategy_reachability(db_session)["cand:vera"]
    assert stat.eligible == 2          # the ineligible row excluded
    assert stat.executed == 1
    assert stat.early_stopped == 1
    assert stat.reachability == pytest.approx(0.5)
    assert stat.starvation_rate == pytest.approx(0.5)  # half its eligible appearances lost to early-stop
