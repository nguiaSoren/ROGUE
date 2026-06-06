"""Technique Retrieval — migration 0026 schema tests.

Covers the three foundational retrieval tables (``technique_embeddings``,
``target_embeddings``, ``retrieval_metrics``):

  - all three tables are created by ``Base.metadata.create_all``
  - a ``TechniqueEmbedding`` row with a 1536-d embedding round-trips
  - a pgvector ``cosine_distance`` query against the embedding compiles + runs

Network-gated: these need a live Postgres (pgvector). They skip cleanly when the
DB is unreachable — no hard failures from missing infra (mirrors test_smoke.py).
"""

from __future__ import annotations

import os
import socket

import pytest

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue_test"
)


def _database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", DEFAULT_DATABASE_URL)


@pytest.fixture(scope="module")
def live_engine():
    """Connected SQLAlchemy engine, or ``pytest.skip`` cleanly.

    Always TRIES to connect (never gates on env vars). The skip message carries
    the real reason so a developer who forgot ``docker compose up`` sees it.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError

    url = _database_url()
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            from sqlalchemy import text

            # pgvector must be installed for the Vector columns to bind.
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
    except (OperationalError, ConnectionRefusedError, socket.gaierror, OSError) as exc:
        pytest.skip(
            f"Postgres not reachable at {url}: {exc.__class__.__name__}: {exc} "
            "— run `docker compose up -d`"
        )
    yield engine
    engine.dispose()


@pytest.fixture
def retrieval_tables(live_engine):
    """Create the three retrieval tables on the live DB, drop them after.

    Uses ``Base.metadata.create_all`` scoped to just the retrieval ORM tables so
    the test is independent of whether the full migration chain has been applied
    to ``rogue_test``.
    """
    from sqlalchemy import inspect as _sa_inspect

    from rogue.db.models import RetrievalMetric, TargetEmbedding, TechniqueEmbedding

    tables = [
        TechniqueEmbedding.__table__,
        TargetEmbedding.__table__,
        RetrievalMetric.__table__,
    ]
    # State-neutral: only create/drop tables this fixture actually introduces, so
    # it never leaves rogue_test inconsistent with alembic's recorded head for
    # subsequent test modules.
    insp = _sa_inspect(live_engine)
    created_here = [t for t in tables if not insp.has_table(t.name)]
    for tbl in created_here:
        tbl.create(bind=live_engine, checkfirst=True)
    try:
        yield
    finally:
        for tbl in reversed(created_here):
            tbl.drop(bind=live_engine, checkfirst=True)


def test_retrieval_tables_exist(live_engine, retrieval_tables) -> None:
    """All three retrieval tables exist after create_all."""
    from sqlalchemy import inspect as sa_inspect

    names = set(sa_inspect(live_engine).get_table_names())
    assert {
        "technique_embeddings",
        "target_embeddings",
        "retrieval_metrics",
    } <= names


def test_technique_embedding_roundtrips_1536d(live_engine, retrieval_tables) -> None:
    """A TechniqueEmbedding with a 1536-d embedding writes + reads back intact."""
    from sqlalchemy.orm import Session

    from rogue.db.models import TechniqueEmbedding

    emb = [0.001 * i for i in range(1536)]
    row = TechniqueEmbedding(
        label="roleplay_dan_v2",
        technique_id="01HSTRATEGYULID00000000000",
        embedding=emb,
        profile={"family": "roleplay", "note": "test"},
        modalities=["text"],
        version="te3-small-v1",
    )
    with Session(live_engine) as session:
        session.add(row)
        session.commit()

    with Session(live_engine) as session:
        fetched = session.get(TechniqueEmbedding, "roleplay_dan_v2")
        assert fetched is not None
        assert len(fetched.embedding) == 1536
        assert fetched.embedding[1] == pytest.approx(0.001)
        assert fetched.profile == {"family": "roleplay", "note": "test"}
        assert fetched.modalities == ["text"]
        assert fetched.version == "te3-small-v1"


def test_cosine_distance_query_compiles(live_engine, retrieval_tables) -> None:
    """A pgvector cosine_distance query against the embedding compiles + runs."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from rogue.db.models import TechniqueEmbedding

    with Session(live_engine) as session:
        session.add(
            TechniqueEmbedding(
                label="probe_a",
                embedding=[0.0] * 1536,
                profile={},
                modalities=[],
            )
        )
        session.commit()

        query_vec = [0.5] * 1536
        stmt = (
            select(
                TechniqueEmbedding.label,
                TechniqueEmbedding.embedding.cosine_distance(query_vec).label("dist"),
            )
            .order_by("dist")
            .limit(5)
        )
        rows = session.execute(stmt).all()
    assert any(label == "probe_a" for label, _ in rows)
