"""End-to-end integration tests for the Technique Retrieval System (Team B).

Three test groups:
1. Package smoke — every public name in ``rogue.retrieval.__all__`` is importable.
2. Offline pipeline — deterministic embeddings only; no network, no paid calls.
   Proves the full chain composes: build_technique_profiles -> embed each ->
   build_target_fingerprint -> in-memory cosine retrieval -> RetrievalResult.
3. DB-gated end-to-end — seeds TechniqueEmbedding rows, runs TechniqueRetriever,
   asserts ordering.  Skips cleanly when Postgres is not reachable.
"""

from __future__ import annotations

import math
import os
import socket

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity for in-memory retrieval in the offline test."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue_test"
)


def _database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", DEFAULT_DATABASE_URL)


# ---------------------------------------------------------------------------
# 1. Package smoke
# ---------------------------------------------------------------------------


class TestPackageSmoke:
    """Every name listed in rogue.retrieval.__all__ must be importable."""

    def test_package_importable(self) -> None:
        import rogue.retrieval  # noqa: PLC0415

        assert rogue.retrieval is not None

    def test_all_names_present(self) -> None:
        import rogue.retrieval  # noqa: PLC0415

        expected = {
            "TechniqueProfile",
            "TargetFingerprint",
            "build_technique_embedding_text",
            "build_target_embedding_text",
            "default_embed_fn",
            "deterministic_embed_fn",
            "build_target_fingerprint",
            "build_technique_profiles",
            "TechniqueRetriever",
            "RetrievalResult",
            "evaluate_recall",
        }
        # evaluate_recall may be None if evaluation.py not yet landed (guarded import)
        missing = expected - set(rogue.retrieval.__all__)
        assert not missing, f"Missing from __all__: {missing}"

    def test_TechniqueProfile_importable(self) -> None:
        from rogue.retrieval import TechniqueProfile  # noqa: PLC0415

        assert TechniqueProfile is not None

    def test_TargetFingerprint_importable(self) -> None:
        from rogue.retrieval import TargetFingerprint  # noqa: PLC0415

        assert TargetFingerprint is not None

    def test_build_technique_embedding_text_importable(self) -> None:
        from rogue.retrieval import build_technique_embedding_text  # noqa: PLC0415

        assert callable(build_technique_embedding_text)

    def test_build_target_embedding_text_importable(self) -> None:
        from rogue.retrieval import build_target_embedding_text  # noqa: PLC0415

        assert callable(build_target_embedding_text)

    def test_default_embed_fn_importable(self) -> None:
        from rogue.retrieval import default_embed_fn  # noqa: PLC0415

        assert callable(default_embed_fn)

    def test_deterministic_embed_fn_importable(self) -> None:
        from rogue.retrieval import deterministic_embed_fn  # noqa: PLC0415

        assert callable(deterministic_embed_fn)

    def test_build_target_fingerprint_importable(self) -> None:
        from rogue.retrieval import build_target_fingerprint  # noqa: PLC0415

        assert callable(build_target_fingerprint)

    def test_build_technique_profiles_importable(self) -> None:
        from rogue.retrieval import build_technique_profiles  # noqa: PLC0415

        assert callable(build_technique_profiles)

    def test_TechniqueRetriever_importable(self) -> None:
        from rogue.retrieval import TechniqueRetriever  # noqa: PLC0415

        assert TechniqueRetriever is not None

    def test_RetrievalResult_importable(self) -> None:
        from rogue.retrieval import RetrievalResult  # noqa: PLC0415

        assert RetrievalResult is not None

    def test_evaluate_recall_in_all(self) -> None:
        import rogue.retrieval  # noqa: PLC0415

        assert "evaluate_recall" in rogue.retrieval.__all__


# ---------------------------------------------------------------------------
# 2. Offline pipeline (no network, no DB, deterministic only)
# ---------------------------------------------------------------------------


class TestOfflinePipeline:
    """Prove the full retrieval chain composes using deterministic_embed_fn."""

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------

    @pytest.fixture(scope="class")
    def embed_fn(self):
        from rogue.retrieval import deterministic_embed_fn  # noqa: PLC0415

        return deterministic_embed_fn(dim=1536)

    @pytest.fixture(scope="class")
    def profiles(self):
        from rogue.retrieval import build_technique_profiles  # noqa: PLC0415

        return build_technique_profiles(None)

    @pytest.fixture(scope="class")
    def profile_embeddings(self, profiles, embed_fn):
        """Embed every profile's text; returns list[(label, vector)]."""
        from rogue.retrieval import build_technique_embedding_text  # noqa: PLC0415

        return [
            (p.label, embed_fn(build_technique_embedding_text(p)))
            for p in profiles
        ]

    @pytest.fixture(scope="class")
    def target_fingerprint(self):
        from rogue.retrieval import build_target_fingerprint  # noqa: PLC0415

        return build_target_fingerprint("anthropic/claude-haiku-4-5")

    @pytest.fixture(scope="class")
    def target_embedding(self, target_fingerprint, embed_fn):
        from rogue.retrieval import build_target_embedding_text  # noqa: PLC0415

        text = build_target_embedding_text(target_fingerprint)
        return embed_fn(text)

    @pytest.fixture(scope="class")
    def retrieved(self, profile_embeddings, target_embedding):
        """In-memory top-K retrieval via pure-Python cosine similarity."""
        from rogue.retrieval import RetrievalResult  # noqa: PLC0415

        scored = [
            (label, _cosine_similarity(target_embedding, vec))
            for label, vec in profile_embeddings
        ]
        scored.sort(key=lambda t: t[1], reverse=True)

        results = [
            RetrievalResult(label=label, score=score, rank=rank)
            for rank, (label, score) in enumerate(scored, start=1)
        ]
        return results

    # ------------------------------------------------------------------
    # Assertions
    # ------------------------------------------------------------------

    def test_profiles_count_at_least_17_arms(self, profiles) -> None:
        """build_technique_profiles(None) must yield >= 17 profiles (ARMS minimum)."""
        assert len(profiles) >= 17, (
            f"Expected >= 17 ARMS profiles, got {len(profiles)}"
        )

    def test_profiles_arms_origin_count(self, profiles) -> None:
        arms_count = sum(1 for p in profiles if p.origin == "arms")
        assert arms_count >= 17, (
            f"Expected >= 17 ARMS-origin profiles, got {arms_count}"
        )

    def test_profiles_are_TechniqueProfile(self, profiles) -> None:
        from rogue.retrieval import TechniqueProfile  # noqa: PLC0415

        for p in profiles:
            assert isinstance(p, TechniqueProfile), (
                f"Expected TechniqueProfile, got {type(p)}: {p!r}"
            )

    def test_profiles_labels_nonempty(self, profiles) -> None:
        for p in profiles:
            assert p.label, f"Profile has empty label: {p!r}"

    def test_profile_embedding_text_nonempty(self, profiles, embed_fn) -> None:
        from rogue.retrieval import build_technique_embedding_text  # noqa: PLC0415

        for p in profiles:
            txt = build_technique_embedding_text(p)
            assert txt, f"Empty embedding text for profile {p.label!r}"

    def test_profile_embeddings_correct_dim(self, profile_embeddings) -> None:
        for label, vec in profile_embeddings:
            assert len(vec) == 1536, (
                f"Expected dim=1536 for {label!r}, got {len(vec)}"
            )

    def test_profile_embeddings_unit_normalised(self, profile_embeddings) -> None:
        for label, vec in profile_embeddings:
            norm_sq = sum(x * x for x in vec)
            assert abs(norm_sq - 1.0) < 1e-4, (
                f"Vector for {label!r} is not unit-normalised: |v|^2={norm_sq}"
            )

    def test_target_fingerprint_target_key(self, target_fingerprint) -> None:
        assert target_fingerprint.target_key == "anthropic/claude-haiku-4-5"

    def test_target_embedding_text_nonempty(self, target_fingerprint, embed_fn) -> None:
        from rogue.retrieval import build_target_embedding_text  # noqa: PLC0415

        txt = build_target_embedding_text(target_fingerprint)
        assert txt, "build_target_embedding_text returned empty string"

    def test_target_embedding_dim(self, target_embedding) -> None:
        assert len(target_embedding) == 1536

    def test_retrieved_are_RetrievalResult(self, retrieved) -> None:
        from rogue.retrieval import RetrievalResult  # noqa: PLC0415

        for r in retrieved:
            assert isinstance(r, RetrievalResult)

    def test_retrieved_count_equals_profiles(self, retrieved, profiles) -> None:
        """In-memory retrieval returns one result per profile (no DB cap)."""
        assert len(retrieved) == len(profiles)

    def test_retrieved_sorted_by_score_desc(self, retrieved) -> None:
        for i in range(len(retrieved) - 1):
            assert retrieved[i].score >= retrieved[i + 1].score, (
                f"Results not sorted by score desc at rank {i + 1}: "
                f"{retrieved[i].score} < {retrieved[i + 1].score}"
            )

    def test_retrieved_ranks_are_1based_sequential(self, retrieved) -> None:
        for i, r in enumerate(retrieved, start=1):
            assert r.rank == i, f"Expected rank={i}, got rank={r.rank}"

    def test_retrieved_min_k_satisfied(self, retrieved) -> None:
        """At least TechniqueRetriever.MIN_K results (or all profiles if fewer)."""
        from rogue.retrieval import TechniqueRetriever  # noqa: PLC0415

        expected_min = min(TechniqueRetriever.MIN_K, len(retrieved))
        assert len(retrieved) >= expected_min, (
            f"Expected >= {expected_min} results, got {len(retrieved)}"
        )

    def test_scores_in_valid_range(self, retrieved) -> None:
        """Cosine similarity must be in [-1, 1]; deterministic embeddings -> near [0, 1]."""
        for r in retrieved:
            assert -1.0 <= r.score <= 1.0, (
                f"Score out of [-1,1] range for {r.label!r}: {r.score}"
            )

    def test_determinism(self, profiles, embed_fn) -> None:
        """Same profile always produces the same embedding vector."""
        from rogue.retrieval import build_technique_embedding_text  # noqa: PLC0415

        p = profiles[0]
        txt = build_technique_embedding_text(p)
        v1 = embed_fn(txt)
        v2 = embed_fn(txt)
        assert v1 == v2, f"deterministic_embed_fn is not deterministic for {p.label!r}"

    def test_different_profiles_different_embeddings(self, profile_embeddings) -> None:
        """Two distinct profiles must not produce the same embedding vector."""
        if len(profile_embeddings) < 2:
            pytest.skip("Need at least 2 profiles to check uniqueness")
        v1 = profile_embeddings[0][1]
        v2 = profile_embeddings[1][1]
        assert v1 != v2, (
            "Two distinct profiles produced identical embedding vectors — "
            "collision in deterministic_embed_fn"
        )


# ---------------------------------------------------------------------------
# 3. DB-gated end-to-end (skips cleanly when Postgres is not reachable)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_engine():
    """Connected SQLAlchemy engine, or ``pytest.skip`` cleanly."""
    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError

    url = _database_url()
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            from sqlalchemy import text

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
def technique_embedding_table(live_engine):
    """Create (and teardown) the technique_embeddings table.

    State-neutral: only create/drop the table if it wasn't already present (e.g.
    via alembic head). Otherwise just clean up the test rows. This prevents the
    fixture from leaking a table into other test modules whose fixtures run
    ``alembic upgrade head`` (which would then hit DuplicateTable on 0026).
    """
    from sqlalchemy import inspect as _sa_inspect

    from rogue.db.models import TechniqueEmbedding

    created_here = not _sa_inspect(live_engine).has_table("technique_embeddings")
    if created_here:
        TechniqueEmbedding.__table__.create(bind=live_engine, checkfirst=True)
    try:
        yield
    finally:
        from sqlalchemy.orm import Session
        from sqlalchemy import delete

        if created_here:
            TechniqueEmbedding.__table__.drop(bind=live_engine, checkfirst=True)
        else:
            # Table pre-existed (alembic-managed): delete only our test rows.
            with Session(live_engine) as session:
                session.execute(
                    delete(TechniqueEmbedding).where(
                        TechniqueEmbedding.label.in_(
                            ["_test_crescendo", "_test_image_mml_wr"]
                        )
                    )
                )
                session.commit()


class TestDBGatedEndToEnd:
    """TechniqueRetriever.retrieve returns ordered RetrievalResult from live DB."""

    def test_retriever_retrieve_ordering(
        self, live_engine, technique_embedding_table
    ) -> None:
        from sqlalchemy.orm import Session

        from rogue.db.models import TechniqueEmbedding
        from rogue.retrieval import RetrievalResult, TechniqueRetriever, deterministic_embed_fn
        from rogue.retrieval import build_target_fingerprint, build_target_embedding_text

        embed = deterministic_embed_fn(dim=1536)

        # Build a target fingerprint and embed it
        fp = build_target_fingerprint("anthropic/claude-haiku-4-5")
        target_text = build_target_embedding_text(fp)
        target_vec = embed(target_text)

        # Build two technique embeddings — one that matches the target text (identical
        # vector = similarity 1.0), one that uses an unrelated label/text.
        similar_vec = list(target_vec)  # copy — will have similarity 1.0
        dissimilar_vec = embed("completely unrelated text about cooking recipes")

        with Session(live_engine) as session:
            session.add(
                TechniqueEmbedding(
                    label="_test_crescendo",
                    embedding=similar_vec,
                    profile={},
                    modalities=["multi_turn"],
                )
            )
            session.add(
                TechniqueEmbedding(
                    label="_test_image_mml_wr",
                    embedding=dissimilar_vec,
                    profile={},
                    modalities=["image"],
                )
            )
            session.commit()

        with Session(live_engine) as session:
            retriever = TechniqueRetriever(session, embed_fn=embed)
            results = retriever.retrieve(fp, k=50)

        # Contract assertions
        assert len(results) > 0, "retrieve() returned no results"
        assert all(isinstance(r, RetrievalResult) for r in results)

        # Sorted by score descending
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score, (
                f"Results not sorted by score desc at rank {i + 1}"
            )

        # Ranks are 1-based and sequential
        for i, r in enumerate(results, start=1):
            assert r.rank == i

        # The similar vector must rank before the dissimilar one
        labels = [r.label for r in results]
        assert "_test_crescendo" in labels
        assert "_test_image_mml_wr" in labels
        crescendo_rank = next(r.rank for r in results if r.label == "_test_crescendo")
        dissimilar_rank = next(r.rank for r in results if r.label == "_test_image_mml_wr")
        assert crescendo_rank < dissimilar_rank, (
            f"Expected similar vector to rank higher: "
            f"_test_crescendo rank={crescendo_rank}, "
            f"_test_image_mml_wr rank={dissimilar_rank}"
        )

    def test_retrieve_by_embedding_returns_results(
        self, live_engine, technique_embedding_table
    ) -> None:
        """retrieve_by_embedding works independently of build_target_fingerprint."""
        from sqlalchemy.orm import Session

        from rogue.retrieval import TechniqueRetriever, deterministic_embed_fn

        embed = deterministic_embed_fn(dim=1536)
        query_vec = embed("anthropic claude haiku target fingerprint")

        with Session(live_engine) as session:
            retriever = TechniqueRetriever(session, embed_fn=embed)
            results = retriever.retrieve_by_embedding(query_vec, k=50)

        assert isinstance(results, list)
        for r in results:
            assert hasattr(r, "label")
            assert hasattr(r, "score")
            assert hasattr(r, "rank")
