"""Deduplicator — pgvector-backed clustering for AttackPrimitives.

Position in the dedup pipeline (ROGUE_PLAN.md §3.1 LAYER 3, §A.22, §9.5):

    ExtractionAgent.extract_from_raw_document(raw_doc)
            │
            ▼
    AttackPrimitive (primitive_id, payload_template, reproducibility_score, ...)
            │
            ▼
    Deduplicator.assign_cluster(primitive_orm)        ◄── this module
        │  1. embed_fn(primitive.payload_template) -> list[float] (1536-d)
        │  2. find nearest canonical via pgvector cosine `<=>`
        │  3. match -> cluster_id = matched, canonical = False
        │     no match -> cluster_id = self.primitive_id, canonical = True
        │  4. (optional) apply §3.5 quarantine gate
            ▼
    session.add(primitive_orm) — caller commits

Embedder is INJECTED, not constructed internally — so this module is
import-safe without OpenAI credentials and unit-testable with a mock
embedder. Production wiring (Day-1 evening): pass
``OpenAI().embeddings.create`` adapter via the ``embed_fn`` kwarg.

The pgvector query targets the ``attack_primitives`` table itself, filtered
to ``canonical = true`` rows — every primitive ROGUE has ever surfaced
that was elected the canonical representative of its cluster. The growing
index IS the dedup database; there is no external store. On Day-1 morning
the table is empty and every primitive becomes its own canonical seed; by
end-of-day the index has 30-60 entries and dedup begins to fire in earnest.

Cosine semantics: pgvector's ``<=>`` operator is cosine DISTANCE, not
similarity. similarity > THRESHOLD ↔ distance < (1 - THRESHOLD). Default
THRESHOLD = 0.92 per §9.5 spec.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from rogue.db.models import AttackPrimitive as AttackPrimitiveORM
from rogue.dedupe.quarantine import should_quarantine

__all__ = ["DEFAULT_COSINE_THRESHOLD", "Deduplicator"]


# Default cosine-similarity threshold above which two primitives are
# considered duplicates. Locked per §9.5; do not change without
# re-calibrating on a labelled sample (otherwise the cluster count drifts).
DEFAULT_COSINE_THRESHOLD: float = 0.92


EmbedFn = Callable[[str], list[float]]


class Deduplicator:
    """Embed-and-cluster engine for AttackPrimitives.

    Args:
        session: SQLAlchemy ``Session`` — the caller controls the transaction.
            We only ``session.add(...)`` and run ``session.execute(SELECT)``;
            never ``commit()``, never ``flush()``.
        embed_fn: callable that maps a ``payload_template`` string to a
            1536-d embedding vector. Inject ``OpenAI().embeddings.create(...)``
            wrapper for production; mock for tests. Injection (not
            constructor) keeps the module import-safe without credentials.
        threshold: cosine-similarity cutoff for cluster matching. Default
            0.92 per §9.5.
    """

    def __init__(
        self,
        session: Session,
        embed_fn: EmbedFn,
        threshold: float = DEFAULT_COSINE_THRESHOLD,
    ) -> None:
        self.session = session
        self.embed_fn = embed_fn
        self.threshold = threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assign_cluster(
        self,
        primitive: AttackPrimitiveORM,
        *,
        daily_bd_spend_usd: Optional[object] = None,
    ) -> None:
        """Embed the primitive's ``payload_template`` and assign
        ``cluster_id`` + ``canonical`` in place.

        Match -> primitive joins the existing cluster as a non-canonical row.
        No match -> primitive becomes its own cluster's canonical seed
        (``cluster_id = primitive_id``, ``canonical = True``).

        When ``daily_bd_spend_usd`` is provided (a ``Decimal``), the §3.5
        quarantine gate fires after assignment: low-reproducibility-score
        primitives over the daily budget threshold are forced to
        ``canonical = False`` regardless of whether they clustered.
        """
        embedding = self.embed_fn(primitive.payload_template)
        primitive.payload_embedding = embedding

        existing_cluster = self.find_cluster(embedding)
        if existing_cluster is not None:
            primitive.cluster_id = existing_cluster
            primitive.canonical = False
        else:
            # No nearby canonical — this primitive seeds its own cluster.
            primitive.cluster_id = primitive.primitive_id
            primitive.canonical = True

        # §3.5 quarantine gate (budget-conditional). Only force canonical=False;
        # never promote — clustering decisions above remain authoritative.
        if daily_bd_spend_usd is not None and should_quarantine(
            primitive_reproducibility_score=primitive.reproducibility_score,
            daily_bd_spend_usd=daily_bd_spend_usd,  # type: ignore[arg-type]
        ):
            primitive.canonical = False

    def find_cluster(self, embedding: list[float]) -> Optional[str]:
        """Return the ``cluster_id`` of the nearest canonical primitive
        within the cosine-similarity threshold, or None.

        Translates the threshold to pgvector's cosine-distance operator:
        ``payload_embedding <=> :emb < (1 - threshold)``. The ivfflat index
        declared on ``payload_embedding`` (db/models.py ~line 173) accelerates
        this lookup; the ordering by distance + LIMIT 1 returns the single
        nearest neighbour so cluster assignment is deterministic.
        """
        max_distance = 1.0 - self.threshold
        # SQLAlchemy's pgvector integration exposes ``.cosine_distance``
        # on the Vector column for the ``<=>`` operator (pgvector-python
        # registers it on the type). We sort ascending (nearest first) and
        # take the top hit if it's inside the band.
        distance_expr = AttackPrimitiveORM.payload_embedding.cosine_distance(
            embedding,
        )
        stmt = (
            select(AttackPrimitiveORM.cluster_id, distance_expr.label("distance"))
            .where(AttackPrimitiveORM.canonical.is_(True))
            .where(AttackPrimitiveORM.payload_embedding.is_not(None))
            .order_by(distance_expr)
            .limit(1)
        )
        row = self.session.execute(stmt).first()
        if row is None:
            return None
        cluster_id, distance = row
        if distance is None or float(distance) >= max_distance:
            return None
        return cluster_id
