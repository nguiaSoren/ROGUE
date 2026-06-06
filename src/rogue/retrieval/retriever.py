"""TechniqueRetriever — pgvector cosine top-K over the technique repertoire.

Position in the Technique Retrieval System (Team B):

    target -> TechniqueRetriever (top-K) -> contextual scheduler (rank) -> ladder

This module owns the *candidate-generation* step: given a ``TargetFingerprint``
(or a precomputed embedding), return the K technique labels whose stored
embeddings are most cosine-similar to the target. The contextual scheduler
remains the ranker; retrieval only narrows the field to a relevant candidate set.

The query shape mirrors the proven dedup lookup (``src/rogue/dedupe/embeddings.py``):
pgvector ``cosine_distance`` on the indexed ``embedding`` column, filtered to rows
with a non-null embedding, ordered ascending by distance, limited to K. pgvector's
``<=>`` is cosine *distance* (= 1 - cosine similarity), so the returned
``RetrievalResult.score`` is ``1 - distance`` to give a similarity in ``[0, 1]``.

Embedding is INJECTED (``embed_fn``) so the module imports without network/credentials;
the default is the offline ``deterministic_embed_fn`` (no API spend). Both ``embed_fn``
and the ``build_target_embedding_text`` sibling are imported lazily so this module's
import never hard-fails while parallel siblings are still landing their files.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from sqlalchemy import select

from rogue.db.models import TechniqueEmbedding

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from rogue.schemas import TargetFingerprint

# 1536-d embedding vector -> the wire/storage dimension (frozen contract).
EmbedFn = Callable[[str], list[float]]


@dataclass
class RetrievalResult:
    """One retrieved technique.

    ``score`` is cosine similarity in ``[0, 1]`` (``1 - cosine_distance``).
    ``rank`` is 1-based (rank 1 == nearest / highest similarity).
    """

    label: str
    score: float
    rank: int


class TechniqueRetriever:
    """Vector retrieval of techniques (ladder strategy ``label``s) for a target.

    The retriever embeds the target's behavioural fingerprint and returns the
    top-K most cosine-similar technique embeddings from ``technique_embeddings``.
    """

    #: Hard floor on the number of candidates retrieved. Early in a target's life
    #: the contextual scheduler has little/no telemetry to rank with, so a too-tight
    #: top-K can permanently strand a technique that would in fact breach the target
    #: (a retrieval mistake the scheduler can never recover from, because a technique
    #: that is never *surfaced* is never *tried*). We therefore always return at least
    #: MIN_K candidates regardless of the caller's ``k`` — over-retrieval is cheap
    #: (the scheduler re-ranks) while under-retrieval is irreversible.
    MIN_K: int = 25

    def __init__(self, session: "Session", *, embed_fn: Optional[EmbedFn] = None) -> None:
        if embed_fn is None:
            # Lazy import: keep module import offline-safe and decoupled from the
            # parallel sibling (E3) that owns retrieval/embed.py.
            from rogue.retrieval.embed import deterministic_embed_fn

            embed_fn = deterministic_embed_fn()
        self.session = session
        self._embed: EmbedFn = embed_fn

    def retrieve(self, target: "TargetFingerprint", k: int = 50) -> list[RetrievalResult]:
        """Embed ``target`` and return the top-K most similar techniques."""
        # Lazy import: retrieval/embedding_text.py is owned by a parallel sibling.
        from rogue.retrieval.embedding_text import build_target_embedding_text

        text = build_target_embedding_text(target)
        vec = self._embed(text)
        return self.retrieve_by_embedding(vec, k)

    def retrieve_by_embedding(
        self, embedding: list[float], k: int = 50
    ) -> list[RetrievalResult]:
        """Top-K technique labels by cosine similarity to ``embedding``.

        Enforces the ``MIN_K`` floor, skips rows with a null embedding, orders by
        ascending cosine distance (nearest first), and limits to K. Returns fewer
        than K results when the table holds fewer eligible rows. ``score`` is
        ``1 - distance``; ``rank`` is 1-based.
        """
        k = max(k, self.MIN_K)

        distance_expr = TechniqueEmbedding.embedding.cosine_distance(embedding)
        stmt = (
            select(TechniqueEmbedding.label, distance_expr.label("distance"))
            .where(TechniqueEmbedding.embedding.is_not(None))
            .order_by(distance_expr)
            .limit(k)
        )
        rows = self.session.execute(stmt).all()

        results: list[RetrievalResult] = []
        for rank, (label, distance) in enumerate(rows, start=1):
            score = 1.0 - float(distance)
            results.append(RetrievalResult(label=label, score=score, rank=rank))
        return results
