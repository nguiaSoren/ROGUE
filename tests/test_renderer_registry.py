"""Tests for §10.9 Phase 3b — renderer capability registry + governed lifecycle.

The transition logic is pure (in-memory ORM rows, no I/O) — most importantly it
proves the safety invariant: a ``synthesized`` renderer can NEVER reach ``active``
without sandbox + determinism + human approval. The registry queries (register,
seed, active set, backlog) get live-DB tests that skip cleanly when Postgres is down.
"""

import os
import socket
from datetime import datetime, timezone

import pytest

from rogue.reproduce.renderer_registry import (
    STATIC_RENDERERS,
    InvalidTransition,
    activate,
    activate_with_cascade,
    active_dynamic_strategies,
    active_renderers,
    approve,
    backlog,
    can_transition,
    effective_order,
    register_renderer,
    reject,
    seed_static_renderers,
    transition,
)
from rogue.schemas import (
    Modality,
    RendererManifest,
    RendererOrigin,
    RendererStatus,
    StrategyStatus,
    TechniqueSpec,
)

DEFAULT_TEST_DB = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue_test"
)
NOW = datetime(2026, 6, 2, tzinfo=timezone.utc)
S = RendererStatus
ORG = RendererOrigin


def _row(**over):
    from rogue.db.models import RendererCapability

    r = RendererCapability(
        renderer_id=over.pop("renderer_id", "r1"),
        name="r",
        modality=over.pop("modality", "image"),
        origin=over.pop("origin", ORG.SYNTHESIZED),
        entrypoint="mod:fn",
        status=over.pop("status", S.HARVESTED),
    )
    r.approved_by = None
    r.approved_at = None
    for k, v in over.items():
        setattr(r, k, v)
    return r


# --------------------------------------------------------------------------- #
# The safety invariant (pure)
# --------------------------------------------------------------------------- #


def test_synthesized_cannot_skip_to_active() -> None:
    # THE invariant: a generated renderer can never collapse synthesized→active.
    assert can_transition(ORG.SYNTHESIZED, S.SYNTHESIZED, S.ACTIVE) is False
    r = _row(origin=ORG.SYNTHESIZED, status=S.SYNTHESIZED)
    with pytest.raises(InvalidTransition):
        activate(r)


def test_synthesized_full_chain_is_legal_step_by_step() -> None:
    r = _row(origin=ORG.SYNTHESIZED, status=S.HARVESTED)
    for nxt in (
        S.SPEC_VALIDATED,
        S.SYNTHESIZED,
        S.SANDBOX_VERIFIED,
        S.DETERMINISTIC,
    ):
        transition(r, nxt)
    approve(r, "soren", now=NOW)
    assert r.status is S.HUMAN_APPROVED and r.approved_by == "soren"
    activate(r)
    assert r.status is S.ACTIVE


def test_human_path_skips_synthesis_states() -> None:
    order = [s.value for s in effective_order(ORG.HUMAN)]
    assert "synthesized" not in order and "sandbox_verified" not in order
    r = _row(origin=ORG.HUMAN, status=S.HARVESTED)
    transition(r, S.SPEC_VALIDATED)
    transition(r, S.DETERMINISTIC)  # human may skip the synthesis-only states
    approve(r, "soren", now=NOW)
    activate(r)
    assert r.status is S.ACTIVE
    # ...but a human renderer cannot enter a synthesis-only state.
    r2 = _row(origin=ORG.HUMAN, status=S.SPEC_VALIDATED)
    with pytest.raises(InvalidTransition):
        transition(r2, S.SYNTHESIZED)


def test_no_skipping_forward() -> None:
    r = _row(origin=ORG.SYNTHESIZED, status=S.SPEC_VALIDATED)
    with pytest.raises(InvalidTransition):
        transition(r, S.DETERMINISTIC)  # skips synthesized + sandbox_verified


def test_approve_requires_approver() -> None:
    r = _row(origin=ORG.HUMAN, status=S.DETERMINISTIC)
    with pytest.raises(InvalidTransition):
        transition(r, S.HUMAN_APPROVED)  # no approved_by


def test_reject_allowed_from_any_review_gate_but_not_active() -> None:
    r = _row(origin=ORG.SYNTHESIZED, status=S.SANDBOX_VERIFIED)
    reject(r)
    assert r.status is S.REJECTED
    active = _row(origin=ORG.HUMAN, status=S.ACTIVE)
    assert can_transition(ORG.HUMAN, S.ACTIVE, S.REJECTED) is False
    with pytest.raises(InvalidTransition):
        reject(active)


# --------------------------------------------------------------------------- #
# Registry queries (live DB)
# --------------------------------------------------------------------------- #


@pytest.fixture
def db_session():
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import sessionmaker

    from rogue.db.models import AttackStrategy, RendererCapability

    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DB)
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect():
            pass
    except (OperationalError, ConnectionRefusedError, socket.gaierror, OSError) as exc:
        pytest.skip(f"Postgres not reachable at {url}: {exc} — run `docker compose up -d`")

    made_strat = not inspect(engine).has_table("attack_strategies")
    made_rend = not inspect(engine).has_table("renderer_capabilities")
    AttackStrategy.__table__.create(bind=engine, checkfirst=True)
    RendererCapability.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    session = Session()

    def _clean() -> None:
        # renderer_capabilities is exclusive to this test (incl. the seeded static
        # renderers, whose ids are NOT test-prefixed) → clear it fully.
        session.query(RendererCapability).delete(synchronize_session=False)
        session.query(AttackStrategy).filter(
            AttackStrategy.technique_id.like("test-%")
        ).delete(synchronize_session=False)
        session.commit()

    _clean()
    yield session
    _clean()
    session.close()
    if made_rend:
        RendererCapability.__table__.drop(bind=engine, checkfirst=True)
        if engine.dialect.name == "postgresql":
            with engine.begin() as conn:
                conn.execute(text("DROP TYPE IF EXISTS renderer_status"))
                conn.execute(text("DROP TYPE IF EXISTS renderer_origin"))
    if made_strat:
        AttackStrategy.__table__.drop(bind=engine, checkfirst=True)
        # Drop the enum types too — Table.drop leaves them, orphaning the types
        # and breaking the next alembic `upgrade head` (CREATE TYPE → DuplicateObject).
        if engine.dialect.name == "postgresql":
            with engine.begin() as conn:
                conn.execute(text("DROP TYPE IF EXISTS attack_strategy_status"))
                conn.execute(text("DROP TYPE IF EXISTS attack_strategy_modality"))
    engine.dispose()


def _manifest(rid, **over) -> RendererManifest:
    base = dict(
        renderer_id=rid,
        name=rid,
        modality="image",
        origin=ORG.HUMAN,
        entrypoint="mod:fn",
        deterministic=True,
        status=S.ACTIVE,
    )
    base.update(over)
    return RendererManifest(**base)


def test_register_and_active_query(db_session) -> None:
    register_renderer(db_session, _manifest("test-img1", modality="image"))
    register_renderer(db_session, _manifest("test-aud1", modality="audio"))
    register_renderer(
        db_session, _manifest("test-harv1", status=S.HARVESTED)
    )  # not active
    db_session.commit()

    ids = [r.renderer_id for r in active_renderers(db_session)]
    assert "test-img1" in ids and "test-aud1" in ids
    assert "test-harv1" not in ids  # only active renderers
    img_ids = [r.renderer_id for r in active_renderers(db_session, modality="image")]
    assert img_ids == ["test-img1"]


def test_backlog_lists_unimplemented_image_audio_techniques(db_session) -> None:
    from rogue.reproduce.strategy_library import persist_technique

    # An image technique parked as needs_implementation, no renderer yet.
    persist_technique(
        db_session,
        TechniqueSpec(
            technique_id="test-tech-img",
            name="t",
            modality=Modality.IMAGE,
            principle="p",
            status=StrategyStatus.NEEDS_IMPLEMENTATION,
        ),
    )
    db_session.commit()
    assert "test-tech-img" in [t.technique_id for t in backlog(db_session)]

    # Once an ACTIVE renderer implements it, it leaves the backlog.
    register_renderer(
        db_session,
        _manifest("test-rend-img", technique_id="test-tech-img", status=S.ACTIVE),
    )
    db_session.commit()
    assert "test-tech-img" not in [t.technique_id for t in backlog(db_session)]


def test_activate_with_cascade_flips_linked_technique(db_session) -> None:
    """Activating a renderer for a parked technique closes the 3b-v1 loop: the
    technique leaves needs_implementation and becomes operational (active)."""
    from rogue.reproduce.strategy_library import persist_technique

    persist_technique(
        db_session,
        TechniqueSpec(
            technique_id="test-tech-cascade",
            name="t",
            modality=Modality.IMAGE,
            principle="p",
            status=StrategyStatus.NEEDS_IMPLEMENTATION,
        ),
    )
    row = register_renderer(
        db_session,
        _manifest(
            "test-rend-cascade",
            technique_id="test-tech-cascade",
            status=S.HUMAN_APPROVED,
            ladder_strategies=["foo:bar"],
        ),
    )
    db_session.commit()

    activate_with_cascade(db_session, row, now=NOW)
    db_session.commit()
    db_session.expire_all()

    from rogue.db.models import AttackStrategy as Strat
    from rogue.db.models import RendererCapability as Rend

    assert db_session.get(Rend, "test-rend-cascade").status is S.ACTIVE
    assert db_session.get(Strat, "test-tech-cascade").status is StrategyStatus.ACTIVE


def test_active_dynamic_strategies_only_returns_harvested(db_session) -> None:
    """The dynamic tier merge yields strategies from ACTIVE *harvested* renderers
    (technique_id set) only — static renderers (already in the default tier) and
    non-active renderers are excluded."""
    from rogue.reproduce.strategy_library import persist_technique

    for tid in ("test-some-tech", "test-tech-t2"):  # satisfy the renderer FK
        persist_technique(
            db_session,
            TechniqueSpec(
                technique_id=tid,
                name="t",
                modality=Modality.IMAGE,
                principle="p",
                status=StrategyStatus.NEEDS_IMPLEMENTATION,
            ),
        )
    register_renderer(
        db_session,
        _manifest(
            "test-dyn",
            modality="image",
            technique_id="test-some-tech",
            ladder_strategies=["smuggle:v1"],
            status=S.ACTIVE,
        ),
    )
    register_renderer(  # static-style (no technique_id) → excluded
        db_session,
        _manifest(
            "test-static", modality="image", ladder_strategies=["typographic"]
        ),
    )
    register_renderer(  # harvested but not active → excluded
        db_session,
        _manifest(
            "test-pending",
            modality="image",
            technique_id="test-tech-t2",
            ladder_strategies=["other:v1"],
            status=S.HUMAN_APPROVED,
        ),
    )
    db_session.commit()
    assert active_dynamic_strategies(db_session, "image") == ("smuggle:v1",)
    assert active_dynamic_strategies(db_session, "audio") == ()


def test_seed_static_renderers_is_idempotent(db_session) -> None:
    n1 = seed_static_renderers(db_session)
    db_session.commit()
    assert n1 == len(STATIC_RENDERERS)
    n2 = seed_static_renderers(db_session)  # second call inserts nothing
    db_session.commit()
    assert n2 == 0
    # all seeded renderers are active + human-origin
    seeded = active_renderers(db_session)
    assert {m.renderer_id for m in STATIC_RENDERERS}.issubset(
        {r.renderer_id for r in seeded}
    )
