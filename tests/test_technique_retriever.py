"""Tests for TechniqueRetriever (Engineer 5 — Vector Retrieval).

Three layers, none of which require the parallel sibling files (embed.py /
embedding_text.py) to have landed:

1. MIN_K enforcement — a fake session records the LIMIT the retriever asked for;
   we assert it floors to >= MIN_K even when the caller passes a smaller k.
2. Ranking math — a fake session returns known (label, distance) rows in arbitrary
   order; we assert the retriever orders by similarity, ranks 1-based, and produces
   scores = 1 - distance in [0, 1]. (The SQL ``order_by`` is exercised honestly in
   the DB-gated test below; here we verify the pure score/rank mapping the retriever
   applies to whatever the DB returns.)
3. DB-gated end-to-end — insert real TechniqueEmbedding rows with deterministic
   vectors and assert pgvector cosine returns them ordered with labels present.
   Skips cleanly when Postgres is unreachable.
"""

from __future__ import annotations

import math
import socket

import pytest

from rogue.retrieval.retriever import RetrievalResult, TechniqueRetriever

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue_test"
)


def _database_url() -> str:
    import os

    return os.environ.get("TEST_DATABASE_URL", DEFAULT_DATABASE_URL)


# --------------------------------------------------------------------------- #
# Fakes — let us unit-test the retriever's logic without a live DB or siblings.
# --------------------------------------------------------------------------- #


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    """Records the SELECT statement and returns canned rows.

    We inspect the compiled statement's ``_limit`` so the MIN_K test can read the
    actual LIMIT the retriever requested, independent of any DB.
    """

    def __init__(self, rows):
        self._rows = rows
        self.last_limit: int | None = None

    def execute(self, stmt):
        # SQLAlchemy Select exposes the limit via the public ``_limit`` attr.
        self.last_limit = stmt._limit
        return _FakeResult(self._rows)


def _identity_embed(_text: str) -> list[float]:
    # Embed function is never exercised in the fake-session unit tests (we call
    # retrieve_by_embedding directly), but __init__ requires one to avoid the
    # lazy default import of the sibling embed module.
    return [0.0] * 1536


# --------------------------------------------------------------------------- #
# 1. MIN_K enforcement
# --------------------------------------------------------------------------- #


def test_min_k_floor_is_enforced():
    """A caller asking for k=5 must still request at least MIN_K (25) rows."""
    session = _FakeSession(rows=[])
    retriever = TechniqueRetriever(session, embed_fn=_identity_embed)

    retriever.retrieve_by_embedding([0.1] * 1536, k=5)

    assert retriever.MIN_K == 25
    assert session.last_limit == 25, "k below MIN_K must be floored to MIN_K"


def test_k_above_min_k_is_respected():
    """A caller asking for more than MIN_K gets exactly what they asked for."""
    session = _FakeSession(rows=[])
    retriever = TechniqueRetriever(session, embed_fn=_identity_embed)

    retriever.retrieve_by_embedding([0.1] * 1536, k=100)

    assert session.last_limit == 100


# --------------------------------------------------------------------------- #
# 2. Ranking math — score = 1 - distance, 1-based rank, ordering preserved
# --------------------------------------------------------------------------- #


def test_ranking_scores_and_ranks():
    """Rows arrive ordered-by-distance from the DB; verify the score/rank mapping.

    Distances 0.0, 0.25, 0.9 -> similarities 1.0, 0.75, 0.1; ranks 1, 2, 3.
    """
    rows = [("nearest", 0.0), ("mid", 0.25), ("far", 0.9)]
    session = _FakeSession(rows=rows)
    retriever = TechniqueRetriever(session, embed_fn=_identity_embed)

    results = retriever.retrieve_by_embedding([0.1] * 1536, k=25)

    assert [r.label for r in results] == ["nearest", "mid", "far"]
    assert [r.rank for r in results] == [1, 2, 3]
    assert results[0].score == pytest.approx(1.0)
    assert results[1].score == pytest.approx(0.75)
    assert results[2].score == pytest.approx(0.1)

    # Scores are a descending sequence within [0, 1].
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= s <= 1.0 for s in scores)
    assert results[0].rank == 1  # nearest is rank 1


def test_returns_fewer_than_k_when_table_smaller():
    """Robust to fewer than k eligible rows — return what exists."""
    rows = [("only", 0.1)]
    session = _FakeSession(rows=rows)
    retriever = TechniqueRetriever(session, embed_fn=_identity_embed)

    results = retriever.retrieve_by_embedding([0.1] * 1536, k=50)

    assert len(results) == 1
    assert results[0] == RetrievalResult(label="only", score=pytest.approx(0.9), rank=1)


# --------------------------------------------------------------------------- #
# 3. DB-gated end-to-end — real pgvector cosine ordering.
# --------------------------------------------------------------------------- #


def _orthonormal_like(seed: int, dim: int = 1536) -> list[float]:
    """A deterministic unit vector with a seed-controlled dominant axis.

    Falls back here only if the sibling ``deterministic_embed_fn`` isn't importable;
    the DB-gated test prefers the real sibling embedder when present.
    """
    vec = [0.0] * dim
    vec[seed % dim] = 1.0
    # add a tiny shared component so vectors aren't perfectly orthogonal
    norm = 0.0
    for i in range(0, dim, 97):
        vec[i] += 0.01
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec]


@pytest.fixture()
def live_session():
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session

    from rogue.db.models import TechniqueEmbedding

    url = _database_url()
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.commit()
    except (OperationalError, ConnectionRefusedError, socket.gaierror, OSError) as exc:
        pytest.skip(
            f"Postgres not reachable at {url}: {exc.__class__.__name__}: {exc} "
            "— run `docker compose up -d`"
        )

    # Self-contained: create just the technique_embeddings table for this test so
    # we don't depend on a migration owned by a parallel engineer. State-neutral:
    # only create/drop if it wasn't already present (e.g. via alembic head), so we
    # never leak a table into — or remove one out from under — other test modules.
    from sqlalchemy import inspect as _sa_inspect

    created_here = not _sa_inspect(engine).has_table("technique_embeddings")
    if created_here:
        TechniqueEmbedding.__table__.create(bind=engine, checkfirst=True)
    session = Session(engine)
    try:
        session.query(TechniqueEmbedding).delete()
        session.commit()
        yield session
    finally:
        session.rollback()
        session.query(TechniqueEmbedding).delete()
        session.commit()
        session.close()
        if created_here:
            TechniqueEmbedding.__table__.drop(bind=engine, checkfirst=True)
        engine.dispose()


def _embed_fn():
    """Prefer the sibling deterministic embedder; fall back to a local one."""
    try:
        from rogue.retrieval.embed import deterministic_embed_fn

        return deterministic_embed_fn()
    except Exception:  # sibling not landed yet — use a local deterministic fn
        return lambda text: _orthonormal_like(abs(hash(text)))


def test_db_end_to_end_ordering(live_session):
    from rogue.db.models import TechniqueEmbedding

    embed = _embed_fn()
    labels = ["crescendo", "image:mml:wr", "roleplay:dan"]
    for label in labels:
        live_session.add(
            TechniqueEmbedding(
                label=label,
                embedding=embed(label),
                profile={"label": label},
                modalities=["text"],
            )
        )
    # one null-embedding row that must be skipped by the retriever
    live_session.add(
        TechniqueEmbedding(label="no-embedding", embedding=None, profile={}, modalities=[])
    )
    live_session.commit()

    retriever = TechniqueRetriever(live_session, embed_fn=embed)
    # Query with the exact vector of "crescendo" -> it must come back rank 1.
    results = retriever.retrieve_by_embedding(embed("crescendo"), k=50)

    got_labels = [r.label for r in results]
    assert "no-embedding" not in got_labels, "null-embedding rows must be skipped"
    assert set(got_labels) == set(labels)
    assert results[0].label == "crescendo", "exact-match vector should rank 1"
    assert results[0].score == pytest.approx(1.0, abs=1e-3)

    # Ranks are 1-based and contiguous; scores are descending in [0, 1].
    assert [r.rank for r in results] == [1, 2, 3]
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
    assert all(-1e-6 <= s <= 1.0 + 1e-6 for s in scores)


def test_db_min_k_floor_with_few_rows(live_session):
    """MIN_K floor doesn't break when the table holds fewer than MIN_K rows."""
    from rogue.db.models import TechniqueEmbedding

    embed = _embed_fn()
    live_session.add(
        TechniqueEmbedding(
            label="solo", embedding=embed("solo"), profile={}, modalities=["text"]
        )
    )
    live_session.commit()

    retriever = TechniqueRetriever(live_session, embed_fn=embed)
    results = retriever.retrieve_by_embedding(embed("solo"), k=1)  # below MIN_K

    assert len(results) == 1  # only one eligible row exists
    assert results[0].label == "solo"
    assert results[0].rank == 1
