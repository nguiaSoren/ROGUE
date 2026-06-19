"""Tests for §10.9 Phase 4 — strategy lifecycle (graduation / retirement / resurrection).

The transition functions mutate an ORM row in place with no I/O, so most of this is
pure (an in-memory AttackStrategy with its lifecycle fields initialized). The
least-tried selection query gets a live-DB test that skips cleanly when Postgres
is down.
"""

import os
import socket
from datetime import datetime, timedelta, timezone

import pytest

from rogue.reproduce.strategy_lifecycle import (
    apply_ladder_outcome,
    apply_retirement,
    build_ladder_rotation,
    build_rotation_plan,
    evaluate_retirement,
    format_rotation_plan,
    graduate,
    ladder_config_from_env,
    log_ladder_attempts,
    record_trial,
    select_candidates,
)
from rogue.reproduce.strategy_lifecycle import _classify_ladder_entity
from rogue.schemas import Modality, RetireReason, StrategyStatus

DEFAULT_TEST_DB = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue_test"
)
BASE = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def _row(**over):
    """In-memory AttackStrategy with lifecycle fields initialized (no DB flush)."""
    from rogue.db.models import AttackStrategy

    r = AttackStrategy(
        technique_id="t",
        name="n",
        modality=Modality.TEXT,
        principle="p",
        directive="d",
        status=StrategyStatus.CANDIDATE,
    )
    # Column defaults only apply on INSERT flush; set them for in-memory use.
    r.n_attempts_total = 0
    r.n_valid_trials = 0
    r.n_breaches = 0
    r.supporting_breach_count = 0
    r.resurrected = False
    r.created_at = BASE
    r.first_breach_at = None
    r.first_breach_config_id = None
    r.last_tried_at = None
    r.last_breached_at = None
    r.retired_at = None
    r.retire_reason = None
    r.next_eligible_at = None
    for k, v in over.items():
        setattr(r, k, v)
    return r


# --------------------------------------------------------------------------- #
# Graduation (winner-only)
# --------------------------------------------------------------------------- #


def test_winning_trial_graduates_candidate_to_active() -> None:
    r = _row()
    record_trial(r, won=True, valid=True, ladder_breached=True, config_id="cfg1", now=BASE)
    assert r.status is StrategyStatus.ACTIVE
    assert r.n_attempts_total == 1 and r.n_valid_trials == 1 and r.n_breaches == 1
    assert r.last_tried_at == BASE and r.last_breached_at == BASE
    assert r.first_breach_at == BASE and r.first_breach_config_id == "cfg1"
    assert r.supporting_breach_count == 0


def test_non_winner_in_breaching_ladder_is_supporting_only() -> None:
    r = _row()
    record_trial(r, won=False, valid=True, ladder_breached=True, now=BASE)
    assert r.status is StrategyStatus.CANDIDATE  # NOT graduated
    assert r.n_attempts_total == 1 and r.n_valid_trials == 1 and r.n_breaches == 0
    assert r.supporting_breach_count == 1


def test_non_winner_in_failed_ladder_just_counts_the_trial() -> None:
    r = _row()
    record_trial(r, won=False, valid=True, ladder_breached=False, now=BASE)
    assert r.status is StrategyStatus.CANDIDATE
    assert r.n_attempts_total == 1 and r.supporting_breach_count == 0


def test_blocked_attempt_counts_total_but_not_valid() -> None:
    # refused / render_error: reached the candidate but was NOT a semantic test.
    r = _row()
    record_trial(r, won=False, valid=False, ladder_breached=False, now=BASE)
    assert r.n_attempts_total == 1 and r.n_valid_trials == 0  # blocked, not tested
    assert r.supporting_breach_count == 0
    record_trial(r, won=False, valid=False, ladder_breached=True, now=BASE)
    assert r.supporting_breach_count == 0  # blocked attempts don't earn "supporting"


def test_first_breach_audit_is_set_once() -> None:
    r = _row()
    record_trial(r, won=True, valid=True, ladder_breached=True, config_id="cfg1", now=BASE)
    later = BASE + timedelta(days=1)
    record_trial(r, won=True, valid=True, ladder_breached=True, config_id="cfg2", now=later)
    assert r.n_breaches == 2
    assert r.first_breach_at == BASE and r.first_breach_config_id == "cfg1"  # unchanged
    assert r.last_breached_at == later  # tracks the latest


# --------------------------------------------------------------------------- #
# Retirement (Rule A evidence, Rule B staleness) — soft
# --------------------------------------------------------------------------- #


def test_rule_a_retires_after_valid_trials_with_time_diversity() -> None:
    r = _row(n_valid_trials=5, last_tried_at=BASE + timedelta(days=8))
    retire, reason = evaluate_retirement(r, now=BASE + timedelta(days=8))
    assert retire is True and reason is RetireReason.NEVER_BREACHED_N_RUNS


def test_rule_a_does_not_retire_on_blocked_attempts() -> None:
    # 20 attempts but ZERO valid trials (all planner-refused/render_error) — the
    # candidate was never actually tested, so it MUST NOT retire (the correctness fix).
    r = _row(
        n_attempts_total=20, n_valid_trials=0, last_tried_at=BASE + timedelta(days=8)
    )
    retire, reason = evaluate_retirement(r, now=BASE + timedelta(days=8))
    assert retire is False and reason is None


def test_rule_a_does_not_retire_on_fast_retries() -> None:
    # 5 valid trials but all within an hour — weak evidence, must NOT retire.
    r = _row(n_valid_trials=5, last_tried_at=BASE + timedelta(hours=1))
    retire, reason = evaluate_retirement(r, now=BASE + timedelta(hours=1))
    assert retire is False and reason is None


def test_rule_b_retires_stale_never_breached() -> None:
    r = _row(created_at=BASE - timedelta(days=40), n_valid_trials=0)
    retire, reason = evaluate_retirement(r, now=BASE)
    assert retire is True and reason is RetireReason.EXPIRED_TTL


def test_breached_candidate_never_retires() -> None:
    r = _row(n_valid_trials=9, n_breaches=1, last_tried_at=BASE + timedelta(days=30))
    assert evaluate_retirement(r, now=BASE + timedelta(days=30)) == (False, None)


def test_apply_retirement_sets_soft_fields() -> None:
    r = _row(n_valid_trials=5, last_tried_at=BASE + timedelta(days=8))
    assert apply_retirement(r, now=BASE + timedelta(days=8)) is True
    assert r.status is StrategyStatus.RETIRED
    assert r.retired_at == BASE + timedelta(days=8)
    assert r.retire_reason is RetireReason.NEVER_BREACHED_N_RUNS


# --------------------------------------------------------------------------- #
# Resurrection
# --------------------------------------------------------------------------- #


def test_retired_strategy_resurrects_on_breach() -> None:
    retired_at = BASE
    r = _row(
        status=StrategyStatus.RETIRED,
        retired_at=retired_at,
        retire_reason=RetireReason.NEVER_BREACHED_N_RUNS,
        n_attempts_total=5,
    )
    breach_at = BASE + timedelta(days=50)
    graduate(r, config_id="newmodel-cfg", now=breach_at)
    assert r.status is StrategyStatus.ACTIVE
    assert r.resurrected is True
    assert r.last_breached_at == breach_at
    # retired_at preserved so latency = last_breached_at - retired_at is derivable.
    assert r.retired_at == retired_at
    assert (r.last_breached_at - r.retired_at) == timedelta(days=50)


# --------------------------------------------------------------------------- #
# select_candidates — least-tried-first + dedup (live DB; skips when down)
# --------------------------------------------------------------------------- #


@pytest.fixture
def db_session():
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import sessionmaker

    from rogue.db.models import AttackStrategy as ORM
    from rogue.db.models import LadderAttempt

    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DB)
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect():
            pass
    except (OperationalError, ConnectionRefusedError, socket.gaierror, OSError) as exc:
        pytest.skip(f"Postgres not reachable at {url}: {exc} — run `docker compose up -d`")

    created_here = not inspect(engine).has_table("attack_strategies")
    ORM.__table__.create(bind=engine, checkfirst=True)
    LadderAttempt.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    session = Session()

    def _clean() -> None:
        session.query(LadderAttempt).filter(
            LadderAttempt.run_id.like("test-%")
        ).delete(synchronize_session=False)
        session.query(ORM).filter(ORM.technique_id.like("test-%")).delete(
            synchronize_session=False
        )
        session.commit()

    _clean()
    yield session
    _clean()
    session.close()
    if created_here:
        LadderAttempt.__table__.drop(bind=engine, checkfirst=True)
        ORM.__table__.drop(bind=engine, checkfirst=True)
        if engine.dialect.name == "postgresql":
            with engine.begin() as conn:
                conn.execute(text("DROP TYPE IF EXISTS strategy_retire_reason"))
                conn.execute(text("DROP TYPE IF EXISTS attack_strategy_status"))
                conn.execute(text("DROP TYPE IF EXISTS attack_strategy_modality"))
    engine.dispose()


def _add(session, tid, **over):
    from rogue.db.models import AttackStrategy as ORM

    row = ORM(
        technique_id=tid,
        name=over.pop("name", tid),
        modality=over.pop("modality", Modality.TEXT),
        principle="p",
        directive=over.pop("directive", f"directive for {tid}"),
        status=over.pop("status", StrategyStatus.CANDIDATE),
        **over,
    )
    session.add(row)
    return row


# --------------------------------------------------------------------------- #
# Orchestration-trace logging (ladder_attempts)
# --------------------------------------------------------------------------- #


def test_classify_ladder_entity() -> None:
    cands = frozenset({"01TECH"})
    assert _classify_ladder_entity("image:mml:wr", cands) == ("renderer", 1)
    assert _classify_ladder_entity("coj:reorder", cands) == ("coj", 2)
    assert _classify_ladder_entity("structured:csv", cands) == ("structured", 3)
    assert _classify_ladder_entity("audio:noisy", cands) == ("renderer", 4)
    assert _classify_ladder_entity("crescendo", cands) == ("base", 5)
    assert _classify_ladder_entity("01TECH", cands) == ("candidate", 5)
    assert _classify_ladder_entity("budget", cands) == ("meta", 5)


def test_log_ladder_attempts_writes_orchestration_trace(db_session) -> None:
    from rogue.db.models import LadderAttempt

    _add(db_session, "test-tech-trace", status=StrategyStatus.CANDIDATE)
    db_session.commit()

    # An image breach (quota=0 → early-stop), a base no_breach, a candidate no_breach.
    log_ladder_attempts(
        db_session,
        run_id="test-run-1",
        parent_id="parentX",
        attempts=[
            ("image:mml:wr", "breach"),
            ("crescendo", "no_breach"),
            ("test-tech-trace", "no_breach"),
        ],
        winning_strategy="image:mml:wr",
        breached_on="openai/gpt-5.4-nano",
        candidate_ids=frozenset({"test-tech-trace"}),
        quota=0,
        now=BASE,
    )
    db_session.commit()

    rows = (
        db_session.query(LadderAttempt)
        .filter(LadderAttempt.run_id == "test-run-1")
        .order_by(LadderAttempt.attempt_index)
        .all()
    )
    assert len(rows) == 3
    img, base, cand = rows
    assert (img.entity_type, img.ladder_depth, img.breached) == ("renderer", 1, True)
    assert img.stopped_run is True  # quota=0 winner early-stopped the ladder
    assert img.config_id == "openai/gpt-5.4-nano"
    assert (base.entity_type, base.breached, base.stopped_run) == ("base", False, False)
    assert cand.entity_type == "candidate" and cand.technique_id == "test-tech-trace"
    assert cand.candidate_attempt_quota == 0


def test_log_ladder_attempts_quota_mode_no_early_stop(db_session) -> None:
    from rogue.db.models import LadderAttempt

    # quota>0: even the winning breach did NOT early-stop (suppression on).
    log_ladder_attempts(
        db_session,
        run_id="test-run-2",
        parent_id="parentY",
        attempts=[("image:mml:wr", "breach")],
        winning_strategy="image:mml:wr",
        breached_on="m",
        candidate_ids=frozenset(),
        quota=1,
        now=BASE,
    )
    db_session.commit()
    row = db_session.query(LadderAttempt).filter(
        LadderAttempt.run_id == "test-run-2"
    ).one()
    assert row.breached is True and row.stopped_run is False  # quota suppressed early-stop
    assert row.candidate_attempt_quota == 1


class _Cfg:
    """Minimal stand-in for a config: log_ladder_attempts only reads .target_model."""

    def __init__(self, target_model: str) -> None:
        self.target_model = target_model


def test_log_ladder_attempts_tags_vendor_family_for_single_config(db_session) -> None:
    """§10.10 telemetry: a single-config ladder tags every attempt with the target's
    vendor/family, and the winning attempt's row carries is_winner=True."""
    from rogue.db.models import LadderAttempt

    claude_cfg = _Cfg("anthropic/claude-haiku-4-5")
    log_ladder_attempts(
        db_session,
        run_id="test-run-vf",
        parent_id="parentVF",
        attempts=[
            ("image:mml:wr", "no_breach"),
            ("crescendo", "breach"),
        ],
        winning_strategy="crescendo",
        breached_on="anthropic/claude-haiku-4-5",
        candidate_ids=frozenset(),
        quota=0,
        now=BASE,
        configs=[claude_cfg],
    )
    db_session.commit()

    rows = (
        db_session.query(LadderAttempt)
        .filter(LadderAttempt.run_id == "test-run-vf")
        .order_by(LadderAttempt.attempt_index)
        .all()
    )
    assert len(rows) == 2
    img, winner = rows
    # Every attempt tagged with the (single) target's vendor/family.
    for r in rows:
        assert r.target_vendor == "anthropic"
        assert r.target_family == "claude"
    # is_winner is the explicit causal-winner flag — only the breaching winner row.
    assert img.is_winner is False
    assert winner.is_winner is True
    assert winner.entity_id == "crescendo"


def test_log_ladder_attempts_leaves_vendor_family_null_for_multi_config(db_session) -> None:
    """A multi-model panel is ambiguous (the short-circuiting ladder doesn't record
    which model each attempt was scored against), so vendor/family stay NULL — counted
    globally only by the priors aggregator."""
    from rogue.db.models import LadderAttempt

    log_ladder_attempts(
        db_session,
        run_id="test-run-vf-multi",
        parent_id="parentVFM",
        attempts=[("crescendo", "breach")],
        winning_strategy="crescendo",
        breached_on="anthropic/claude-haiku-4-5",
        candidate_ids=frozenset(),
        quota=0,
        now=BASE,
        configs=[
            _Cfg("anthropic/claude-haiku-4-5"),
            _Cfg("openai/gpt-5.4-nano"),
        ],
    )
    db_session.commit()
    row = db_session.query(LadderAttempt).filter(
        LadderAttempt.run_id == "test-run-vf-multi"
    ).one()
    assert row.target_vendor is None and row.target_family is None
    assert row.is_winner is True  # winner flag is independent of vendor/family tagging


def test_log_ladder_attempts_no_configs_leaves_vendor_family_null(db_session) -> None:
    """Back-compat: omitting ``configs`` (legacy callers) leaves vendor/family NULL."""
    from rogue.db.models import LadderAttempt

    log_ladder_attempts(
        db_session,
        run_id="test-run-vf-none",
        parent_id="parentVFN",
        attempts=[("image:mml:wr", "breach")],
        winning_strategy="image:mml:wr",
        breached_on="m",
        candidate_ids=frozenset(),
        quota=0,
        now=BASE,
    )
    db_session.commit()
    row = db_session.query(LadderAttempt).filter(
        LadderAttempt.run_id == "test-run-vf-none"
    ).one()
    assert row.target_vendor is None and row.target_family is None
    assert row.is_winner is True


def test_select_candidates_least_tried_first(db_session) -> None:
    _add(db_session, "test-a", n_attempts_total=3)
    _add(db_session, "test-b", n_attempts_total=0)
    _add(db_session, "test-c", n_attempts_total=1)
    db_session.commit()

    picked = select_candidates(db_session, k=2)
    assert [r.technique_id for r in picked] == ["test-b", "test-c"]  # 0 then 1


def test_select_candidates_dedups_identical_directive(db_session) -> None:
    _add(db_session, "test-dup1", directive="same directive text")
    _add(db_session, "test-dup2", directive="same directive text")
    db_session.commit()
    picked = select_candidates(db_session, k=5)
    ids = [r.technique_id for r in picked]
    assert ("test-dup1" in ids) ^ ("test-dup2" in ids)  # exactly one


def test_select_candidates_excludes_non_candidate_and_image(db_session) -> None:
    _add(db_session, "test-active", status=StrategyStatus.ACTIVE)
    _add(
        db_session,
        "test-img",
        modality=Modality.IMAGE,
        status=StrategyStatus.NEEDS_IMPLEMENTATION,
    )
    _add(db_session, "test-ok")
    db_session.commit()
    ids = [r.technique_id for r in select_candidates(db_session, k=5)]
    assert ids == ["test-ok"]


# --------------------------------------------------------------------------- #
# 4-wire: env config, rotation builder, outcome applier
# --------------------------------------------------------------------------- #


def test_ladder_config_defaults(monkeypatch) -> None:
    monkeypatch.delenv("CAND_LADDER_SCOPE", raising=False)
    monkeypatch.delenv("CAND_LADDER_CAP", raising=False)
    assert ladder_config_from_env() == ("run", 3)


def test_ladder_config_env_override(monkeypatch) -> None:
    monkeypatch.setenv("CAND_LADDER_SCOPE", "parent")
    monkeypatch.setenv("CAND_LADDER_CAP", "2")
    assert ladder_config_from_env() == ("parent", 2)


def test_build_rotation_includes_active_always_and_capped_candidates(db_session) -> None:
    _add(db_session, "test-active1", status=StrategyStatus.ACTIVE)
    _add(db_session, "test-cand1", n_attempts_total=0)
    _add(db_session, "test-cand2", n_attempts_total=1)
    _add(db_session, "test-cand3", n_attempts_total=2)
    db_session.commit()

    base = ("crescendo", "actor_attack", "acronym")
    rotation, harvested = build_ladder_rotation(db_session, base, cap=2)
    # base preserved, active always in, only 2 (least-tried) candidates.
    assert rotation[:3] == base
    assert "test-active1" in rotation
    assert "test-cand1" in rotation and "test-cand2" in rotation
    assert "test-cand3" not in rotation  # capped out
    assert harvested == {"test-active1", "test-cand1", "test-cand2"}


def test_build_rotation_plan_counts_and_cost(db_session) -> None:
    _add(db_session, "test-active1", status=StrategyStatus.ACTIVE)
    _add(db_session, "test-cand1", n_attempts_total=0)
    _add(db_session, "test-cand2", n_attempts_total=1)
    db_session.commit()

    base = ("crescendo", "actor_attack", "acronym")
    plan = build_rotation_plan(
        db_session,
        base_ladder=base,
        cap=5,
        n_parents_est=10,
        n_configs=5,
        n_trials=2,
        target_cost_usd=0.01,
        judge_cost_usd=0.002,
    )
    assert plan.base_ids == base
    assert set(plan.active_ids) == {"test-active1"}
    assert set(plan.candidate_ids) == {"test-cand1", "test-cand2"}
    assert plan.n_new_strategies == 3  # 1 active + 2 candidates
    # upper bound: 3 new × 10 parents × 5 configs × 2 trials = 300 target calls
    assert plan.est_target_calls == 300 and plan.est_judge_calls == 300
    assert plan.est_usd == round(300 * 0.01 + 300 * 0.002, 2)
    # format is printable + mentions the cost
    text = format_rotation_plan(plan)
    assert "rotation summary" in text and "est usd" in text


def test_apply_ladder_outcome_graduates_winner_and_counts_rest(db_session) -> None:
    _add(db_session, "test-w", n_attempts_total=0)  # will win
    _add(db_session, "test-l", n_attempts_total=0)  # tried-but-lost (before winner)
    db_session.commit()

    # Ladder tried 'test-l' (no_breach) then 'test-w' (breach).
    apply_ladder_outcome(
        db_session,
        attempts=[("test-l", "no_breach"), ("test-w", "breach")],
        winning_strategy="test-w",
        harvested_ids={"test-w", "test-l"},
        config_id="cfg-X",
        now=BASE,
    )
    db_session.expire_all()
    from rogue.db.models import AttackStrategy as ORM

    winner = db_session.get(ORM, "test-w")
    loser = db_session.get(ORM, "test-l")
    assert winner.status is StrategyStatus.ACTIVE
    assert winner.n_breaches == 1 and winner.first_breach_config_id == "cfg-X"
    assert loser.status is StrategyStatus.CANDIDATE
    assert loser.n_attempts_total == 1 and loser.n_valid_trials == 1  # no_breach = valid
    assert loser.supporting_breach_count == 1  # in a ladder that breached elsewhere


def test_apply_ladder_outcome_blocked_attempt_not_a_valid_trial(db_session) -> None:
    _add(db_session, "test-blocked")
    db_session.commit()
    # The candidate was reached but planner-refused / render-errored — NOT a test.
    apply_ladder_outcome(
        db_session,
        attempts=[("test-blocked", "refused"), ("image:mml:wr", "breach")],
        winning_strategy="image:mml:wr",
        harvested_ids={"test-blocked"},
        config_id="cfg-Y",
        now=BASE,
    )
    db_session.expire_all()
    from rogue.db.models import AttackStrategy as ORM

    row = db_session.get(ORM, "test-blocked")
    assert row.n_attempts_total == 1  # the orchestration reached it...
    assert row.n_valid_trials == 0  # ...but it was never validly tested → no retirement credit
