"""§10.10 Growth Scheduler — the deterministic growth-vs-canonical policy.

The policy (`_decide`) is pure and the load-bearing piece; `candidate_pool_stats`
gets a DB test that skips cleanly without Postgres.
"""

from __future__ import annotations

import os
import socket
from datetime import datetime, timedelta, timezone

import pytest

from rogue.reproduce.growth_scheduler import (
    _decide,
    candidate_pool_stats,
)

NOW = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
DEFAULT_TEST_DB = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue_test"


# --------------------------------------------------------------------------- #
# _decide — the deterministic rule
# --------------------------------------------------------------------------- #


def test_pool_at_or_above_threshold_triggers_growth():
    d = _decide(5, 30.0, min_pool=5, min_age_days=0.0, growth_K=5)
    assert d.mode == "growth"
    assert (d.K, d.quota, d.order) == (5, 5, "starvation")
    assert d.is_growth


def test_below_threshold_stays_canonical():
    d = _decide(4, 30.0, min_pool=5, min_age_days=0.0, growth_K=5)
    assert d.mode == "canonical"
    assert (d.K, d.quota, d.order) == (3, 0, "canonical")
    assert "too little inventory" in d.reason


def test_growth_quota_always_equals_K():
    # The footgun guard at the policy level: quota can never drift from K.
    for K in (3, 5, 8):
        d = _decide(20, 30.0, min_pool=5, min_age_days=0.0, growth_K=K)
        assert d.quota == d.K == K


def test_age_gate_blocks_a_fresh_pool():
    # Big pool but too fresh → canonical (the "let candidates age" variant).
    d = _decide(12, 3.0, min_pool=5, min_age_days=7.0, growth_K=5)
    assert d.mode == "canonical"
    assert "fresh" in d.reason


def test_age_gate_passes_once_aged():
    d = _decide(12, 8.0, min_pool=5, min_age_days=7.0, growth_K=5)
    assert d.mode == "growth"


def test_age_off_by_default_means_pool_only():
    # min_age_days=0 → age never blocks; pure pool-size rule.
    d = _decide(5, 0.0, min_pool=5, min_age_days=0.0, growth_K=5)
    assert d.mode == "growth"


# --------------------------------------------------------------------------- #
# candidate_pool_stats — DB aggregation (skips cleanly without Postgres)
# --------------------------------------------------------------------------- #


@pytest.fixture
def db_session():
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import sessionmaker

    from rogue.db.models import AttackStrategy

    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DB)
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect():
            pass
    except (OperationalError, ConnectionRefusedError, socket.gaierror, OSError) as exc:
        pytest.skip(f"Postgres not reachable at {url}: {exc} — run `docker compose up -d`")

    created_here = not inspect(engine).has_table("attack_strategies")
    AttackStrategy.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    session = Session()

    def _clean() -> None:
        session.query(AttackStrategy).filter(
            AttackStrategy.technique_id.like("test-gs-%")
        ).delete(synchronize_session=False)
        session.commit()

    _clean()
    yield session
    _clean()
    session.close()
    if created_here:
        AttackStrategy.__table__.drop(bind=engine, checkfirst=True)


def test_candidate_pool_stats_counts_candidates_and_avg_age(db_session):
    from rogue.db.models import AttackStrategy
    from rogue.schemas import Modality, StrategyStatus

    def _cand(tid, status, age_days):
        r = AttackStrategy(
            technique_id=tid, name="n", modality=Modality.TEXT,
            principle="p", directive="d", status=status,
        )
        r.created_at = NOW - timedelta(days=age_days)
        return r

    db_session.add_all([
        _cand("test-gs-1", StrategyStatus.CANDIDATE, 5),
        _cand("test-gs-2", StrategyStatus.CANDIDATE, 9),
        _cand("test-gs-3", StrategyStatus.ACTIVE, 2),  # excluded (not candidate)
    ])
    db_session.commit()

    n, avg_age = candidate_pool_stats(db_session, now=NOW)
    assert n == 2  # the active one is excluded
    assert avg_age == pytest.approx(7.0, abs=0.1)  # (5 + 9) / 2
