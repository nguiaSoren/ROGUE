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
from datetime import datetime, timedelta, timezone

import pytest

from rogue.reproduce.ladder_priors import (
    ALPHA,
    BETA,
    FRESHNESS_TAU_DAYS,
    FRESHNESS_WEIGHT,
    BreachStat,
    ContextStat,
    StrategyValue,
    ladder_order_mode,
    order_by_prior,
    order_by_value,
    strategy_breach_rates,
    strategy_values,
    winning_model_distribution,
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


def test_viability_is_a_valid_mode(monkeypatch):
    monkeypatch.setenv("ROGUE_LADDER_ORDER", "viability")
    assert ladder_order_mode() == "viability"


# --------------------------------------------------------------------------- #
# §10.10 Phase 2 — StrategyValue + the expected-value (viability) score
# --------------------------------------------------------------------------- #


def test_validity_rate_separates_viable_from_blocked():
    # Same breaches, but one strategy is mostly refused/render-errored.
    viable = StrategyValue("a", breaches=4, valid_trials=8, attempts_total=10)
    blocked = StrategyValue("b", breaches=4, valid_trials=4, attempts_total=20)
    assert viable.validity_rate == pytest.approx((8 + ALPHA) / (10 + ALPHA + BETA))
    assert blocked.validity_rate < viable.validity_rate  # 16 orch-failures drag it down


def test_freshness_bonus_rises_with_staleness():
    fresh = StrategyValue("x", 1, 1, 1, last_tried_at=NOW)
    stale = StrategyValue("x", 1, 1, 1, last_tried_at=NOW - timedelta(days=FRESHNESS_TAU_DAYS * 2))
    unseen = StrategyValue("x", 0, 0, 0, last_tried_at=None)
    assert fresh.freshness_bonus(NOW) == pytest.approx(1.0)
    assert stale.freshness_bonus(NOW) == pytest.approx(1.0 + FRESHNESS_WEIGHT)  # capped
    assert unseen.freshness_bonus(NOW) == pytest.approx(1.0 + FRESHNESS_WEIGHT)  # max boost


def test_exploration_bonus_decays_with_evidence():
    assert StrategyValue("x", 0, 0, 0).exploration_bonus > StrategyValue("x", 50, 100, 100).exploration_bonus


def test_value_score_demotes_high_breach_low_validity():
    # THE viability insight: a strategy that breaks hard but almost never runs
    # (planner refuses it) scores BELOW a moderate strategy that reliably runs.
    breaks_but_blocked = StrategyValue("a", breaches=9, valid_trials=10, attempts_total=100)  # 0.83 breach, 0.10 validity
    reliable = StrategyValue("b", breaches=4, valid_trials=10, attempts_total=11)  # 0.42 breach, 0.85 validity
    assert reliable.value_score(NOW) > breaks_but_blocked.value_score(NOW)


def test_context_stat_breach_rate_is_laplace_smoothed():
    # (target_model × family) contextual prior — same Laplace family as the others.
    # The `contextual_breach_rates` join is validated against live breach_results.
    c = ContextStat("mistralai/mistral-small-2603", "training_data_extraction", 70, 75)
    assert c.breach_rate == pytest.approx((70 + ALPHA) / (75 + ALPHA + BETA))
    unseen = ContextStat("anthropic/claude-opus-4-8", "dan_persona", 0, 0)
    assert unseen.breach_rate == 0.5  # cold-start prior, consistent with the rest


def test_order_by_value_demotes_proven_unviable_keeps_unseen_eager():
    values = {
        # high breach, terrible validity — should sink despite breaching.
        "image:mml:wr": StrategyValue("image:mml:wr", 9, 10, 100, last_tried_at=NOW),
        # moderate breach, high validity, fresh — should win.
        "image:typographic": StrategyValue("image:typographic", 4, 10, 11, last_tried_at=NOW),
    }
    # ocr is unseen (absent) → fair 0.5/0.5 prior + full bonuses → tried eagerly.
    out = order_by_value(
        ("mml:wr", "typographic", "ocr:white_on_white"),
        values, now=NOW, label_prefix="image:",
    )
    assert out.index("typographic") < out.index("mml:wr")  # viable beats blocked
    assert out.index("ocr:white_on_white") < out.index("mml:wr")  # unseen beats blocked


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


def test_winning_model_distribution_reads_winner_rows(db_session):
    from rogue.db.models import LadderAttempt

    # config_id on winner (breached) rows holds the winning TARGET_MODEL (misnomer).
    def _win(model):
        return LadderAttempt(
            run_id="test-prior-win", parent_id="p", attempt_index=0, ladder_depth=1,
            entity_type="base", entity_id="crescendo", candidate_attempt_quota=0,
            config_id=model, outcome="breach", breached=True, stopped_run=True,
            created_at=NOW,
        )

    db_session.add_all([
        _win("mistralai/mistral-small-2603"),
        _win("mistralai/mistral-small-2603"),
        _win("openai/gpt-5.4-nano"),
        # a non-winner row (config_id NULL) must NOT be counted.
        LadderAttempt(
            run_id="test-prior-win", parent_id="p", attempt_index=1, ladder_depth=1,
            entity_type="base", entity_id="acronym", candidate_attempt_quota=0,
            config_id=None, outcome="no_breach", breached=False, stopped_run=False,
            created_at=NOW,
        ),
    ])
    db_session.commit()

    dist = winning_model_distribution(db_session, run_id="test-prior-win")
    assert dist == {"mistralai/mistral-small-2603": 2, "openai/gpt-5.4-nano": 1}


def test_strategy_values_surfaces_attempts_and_freshness(db_session):
    # 1 breach, 1 no_breach (valid) + 2 refused (orch failures, counted in attempts).
    _attempt(db_session, label="coj:delete_then_insert", outcome="breach", breached=True)
    _attempt(db_session, label="coj:delete_then_insert", outcome="no_breach", breached=False)
    _attempt(db_session, label="coj:delete_then_insert", outcome="refused", breached=False)
    _attempt(db_session, label="coj:delete_then_insert", outcome="render_error", breached=False)
    db_session.commit()

    vals = strategy_values(db_session)
    sv = vals["coj:delete_then_insert"]
    assert sv.breaches == 1
    assert sv.valid_trials == 2          # breach + no_breach
    assert sv.attempts_total == 4        # incl. the 2 orchestration failures
    assert sv.last_tried_at is not None  # max(created_at) surfaced for freshness
    # validity_rate reflects the orchestration drag (2 valid of 4 attempts, smoothed).
    assert sv.validity_rate == pytest.approx((2 + ALPHA) / (4 + ALPHA + BETA))
