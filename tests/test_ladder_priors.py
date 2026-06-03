"""§10.10 Step 1 — greedy ladder reordering from breach telemetry.

Load-bearing guarantees:
  1. Laplace smoothing gives unseen strategies a 0.5 prior (cold-start survivability)
     — they sort ahead of proven-weak incumbents, not behind a wall of zeros.
  2. canonical = deterministic argmax (exploit); discovery = optimism that decays
     with trials (explore); fixed = identity. Ties preserve the hand-coded order.
  3. label_prefix keying maps bare tier elements (mml:wr) to full reward labels
     (image:mml:wr).
  4. strategy_breach_rates aggregates ladder_attempts over *valid* trials only.

Pure-logic tests need no DB; the aggregation test skips cleanly when Postgres is down.
"""

from __future__ import annotations

import math
import os
import socket
from datetime import datetime, timezone

import pytest

from rogue.reproduce.ladder_priors import (
    ALPHA,
    BETA,
    BreachStat,
    ladder_order_mode,
    order_by_prior,
    strategy_breach_rates,
)

DEFAULT_TEST_DB = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue_test"
NOW = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# BreachStat — smoothing + discovery score
# --------------------------------------------------------------------------- #


def test_unseen_strategy_prior_is_one_half():
    # ALPHA/(ALPHA+BETA) = 1/2 — the cold-start survivability guarantee.
    assert BreachStat("x", 0, 0).smoothed_rate == ALPHA / (ALPHA + BETA) == 0.5


def test_smoothing_pulls_extremes_toward_half():
    # 5/5 raw=1.0 → (5+1)/(5+2)=0.857 ; 0/5 raw=0.0 → 1/7=0.143
    assert BreachStat("a", 5, 5).smoothed_rate == pytest.approx(6 / 7)
    assert BreachStat("b", 0, 5).smoothed_rate == pytest.approx(1 / 7)


def test_unseen_outranks_proven_weak():
    # The whole point: a never-tried strategy (0.5) beats a 0/5 loser (0.143).
    assert BreachStat("new", 0, 0).smoothed_rate > BreachStat("weak", 0, 5).smoothed_rate


def test_discovery_bonus_decays_with_trials():
    s0, s100 = BreachStat("x", 0, 0), BreachStat("x", 50, 100)
    # bonus = C/sqrt(trials+1): larger for the under-tried strategy.
    b0 = s0.discovery_score(0.5) - s0.smoothed_rate
    b100 = s100.discovery_score(0.5) - s100.smoothed_rate
    assert b0 > b100
    assert b0 == pytest.approx(0.5 / math.sqrt(1))


# --------------------------------------------------------------------------- #
# ladder_order_mode — env resolution
# --------------------------------------------------------------------------- #


def test_mode_defaults_to_canonical(monkeypatch):
    monkeypatch.delenv("ROGUE_LADDER_ORDER", raising=False)
    assert ladder_order_mode() == "canonical"


def test_mode_respects_env_and_rejects_garbage(monkeypatch):
    monkeypatch.setenv("ROGUE_LADDER_ORDER", "discovery")
    assert ladder_order_mode() == "discovery"
    monkeypatch.setenv("ROGUE_LADDER_ORDER", "FIXED")
    assert ladder_order_mode() == "fixed"
    monkeypatch.setenv("ROGUE_LADDER_ORDER", "nonsense")
    assert ladder_order_mode() == "canonical"  # invalid → safe default


# --------------------------------------------------------------------------- #
# order_by_prior — the reorder
# --------------------------------------------------------------------------- #

_ELEMENTS = ("mml:wr", "typographic", "ocr:white_on_white")
# Reward labels are prefixed; typographic is a strong winner, ocr a proven loser,
# mml:wr unseen (absent from the dict).
_RATES = {
    "image:typographic": BreachStat("image:typographic", 8, 10),  # 0.75
    "image:ocr:white_on_white": BreachStat("image:ocr:white_on_white", 0, 10),  # 0.083
}


def test_fixed_mode_is_identity():
    assert order_by_prior(_ELEMENTS, _RATES, mode="fixed", label_prefix="image:") == _ELEMENTS


def test_canonical_sorts_strong_first_unseen_above_proven_weak():
    out = order_by_prior(_ELEMENTS, _RATES, mode="canonical", label_prefix="image:")
    # typographic (0.79 smoothed) > mml:wr unseen (0.5) > ocr proven-weak (0.083)
    assert out == ("typographic", "mml:wr", "ocr:white_on_white")


def test_canonical_is_deterministic_with_stable_tiebreak():
    # Two all-unseen elements (both 0.5) keep their original relative order.
    els = ("b", "a", "c")
    out = order_by_prior(els, {}, mode="canonical", label_prefix="x:")
    assert out == ("b", "a", "c")  # stable — no spurious reordering on ties


def test_discovery_front_loads_the_unseen():
    # In discovery, the unseen mml:wr (0.5 + full bonus) can outrank even the
    # strong-but-well-tried typographic — exploration over pure exploitation.
    out = order_by_prior(_ELEMENTS, _RATES, mode="discovery", label_prefix="image:")
    assert out[0] == "mml:wr"
    assert out.index("ocr:white_on_white") == len(out) - 1  # loser still last


# --------------------------------------------------------------------------- #
# strategy_breach_rates — DB aggregation (skips cleanly without Postgres)
# --------------------------------------------------------------------------- #


@pytest.fixture
def db_session():
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import sessionmaker

    from rogue.db.models import LadderAttempt

    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DB)
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect():
            pass
    except (OperationalError, ConnectionRefusedError, socket.gaierror, OSError) as exc:
        pytest.skip(f"Postgres not reachable at {url}: {exc} — run `docker compose up -d`")

    created_here = not inspect(engine).has_table("ladder_attempts")
    LadderAttempt.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    session = Session()

    def _clean() -> None:
        session.query(LadderAttempt).filter(
            LadderAttempt.run_id.like("test-prior-%")
        ).delete(synchronize_session=False)
        session.commit()

    _clean()
    yield session
    _clean()
    session.close()
    if created_here:
        LadderAttempt.__table__.drop(bind=engine, checkfirst=True)


def _attempt(session, *, label, outcome, breached, config_id=None):
    from rogue.db.models import LadderAttempt

    session.add(LadderAttempt(
        run_id="test-prior-1", parent_id="p", attempt_index=0, ladder_depth=1,
        entity_type="base", entity_id=label, technique_id=None,
        candidate_attempt_quota=0, config_id=config_id, outcome=outcome,
        breached=breached, stopped_run=False, created_at=NOW,
    ))


def test_strategy_breach_rates_counts_valid_trials_only(db_session):
    # image:mml:wr — 2 breach, 1 no_breach, 1 refused (orch failure, excluded).
    _attempt(db_session, label="image:mml:wr", outcome="breach", breached=True)
    _attempt(db_session, label="image:mml:wr", outcome="breach", breached=True)
    _attempt(db_session, label="image:mml:wr", outcome="no_breach", breached=False)
    _attempt(db_session, label="image:mml:wr", outcome="refused", breached=False)
    db_session.commit()

    rates = strategy_breach_rates(db_session)
    stat = rates["image:mml:wr"]
    assert stat.breaches == 2
    assert stat.trials == 3  # refused excluded from valid trials
    assert stat.smoothed_rate == pytest.approx((2 + ALPHA) / (3 + ALPHA + BETA))
