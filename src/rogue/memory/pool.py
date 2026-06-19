"""``SkillPool`` — the assured shared-skill substrate (Surface 3, Section B).

**Framing (spec §1): the pool is plumbing; the assurance is the product.** The
API here is ingest / retrieve / load-fixture only — the carriers the
verified-promotion gate, the leakage red-team, and the lazy-gate retrieval-
pressure counter run over. There is deliberately **no** "inject the best skill"
/ "make this task faster" entry point.

Two seams keep this offline-testable and import-safe (no DB / no creds at
import), mirroring ``rogue.oversight.decider``'s store split and
``rogue.dedupe.embeddings.Deduplicator``'s injected embedder:

- ``SkillStore`` (Protocol) with ``InMemorySkillStore`` (offline/test) and
  ``PostgresSkillStore`` (durable, over the 0037 ``skills`` table).
- ``embed_fn`` is injected (a ``str -> list[float]`` 1536-d embedder), exactly
  as ``Deduplicator`` takes it.

**Dedup REUSES the ``Deduplicator``/``embeddings.py`` cosine ``<=>`` semantics**
(``DEFAULT_COSINE_THRESHOLD``, distance = ``1 - similarity``): on ingest a
candidate is embedded and compared against the *active* skills in the **same
cohort/trust_domain**; a near-duplicate clusters onto the existing active skill
(no second active row is inserted) rather than creating a duplicate. The
Postgres store uses the pgvector ``<=>`` operator via
``Skill.embedding.cosine_distance`` — the same operator ``Deduplicator`` uses on
``attack_primitives``; the in-memory store computes the identical cosine
distance in Python so the two paths agree.

All scoping (which skills are visible to ingest-dedup / retrieve) is enforced
centrally through ``rogue.memory.cohorts`` — a request scoped to trust_domain X
can never see a domain-Y skill.
"""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol

from rogue.dedupe.embeddings import DEFAULT_COSINE_THRESHOLD
from rogue.db.models import Skill, SkillSourceKind, SkillStatus
from rogue.memory.cohorts import CohortScope, resolve_scope, scope_query

__all__ = [
    "SkillStore",
    "InMemorySkillStore",
    "PostgresSkillStore",
    "SkillPool",
    "DEFAULT_FIXTURE_PATH",
]

EmbedFn = Callable[[str], list[float]]

# The harvested 55-skill demo/test fixture the pool ingests as candidates.
DEFAULT_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "memory"
    / "skill_pool.json"
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_skill_id() -> str:
    return f"skill-{uuid.uuid4().hex[:16]}"


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """Cosine DISTANCE between two vectors — matches pgvector's ``<=>``.

    distance = 1 - cosine_similarity, so ``distance < (1 - threshold)`` is the
    same near-duplicate test ``Deduplicator.find_cluster`` runs in SQL. A zero
    vector has no defined direction; treat it as maximally distant (never a
    duplicate) so degenerate embeddings can't silently collapse skills.
    """
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 1.0
    return 1.0 - (dot / (na * nb))


# --------------------------------------------------------------------------------------------------
# Store seam
# --------------------------------------------------------------------------------------------------


class SkillStore(Protocol):
    """Persistence seam the ``SkillPool`` records through.

    Two impls: ``InMemorySkillStore`` (offline/test) and ``PostgresSkillStore``
    (durable, over the ``skills`` table). Keeping this a Protocol is what makes
    the pool unit-testable with no DB. Both impls enforce cohort/trust-domain
    scoping via ``rogue.memory.cohorts`` — the store never serves an out-of-scope
    skill.
    """

    def find_active_duplicate(
        self, embedding: list[float], scope: CohortScope, threshold: float
    ) -> Optional[Skill]:
        """Return the nearest ACTIVE skill in-scope within ``threshold``, else None."""
        ...

    def add(self, skill: Skill) -> Skill:
        """Persist a new skill (status as set on the object). Returns it."""
        ...

    def top_k_active(
        self, embedding: list[float], scope: CohortScope, k: int
    ) -> list[Skill]:
        """Return up to ``k`` ACTIVE in-scope skills nearest ``embedding`` (cosine)."""
        ...


class InMemorySkillStore:
    """Offline skill store — a single-process substrate for tests/demo.

    Holds ``Skill`` rows in a list and runs the *same* cosine-distance test the
    Postgres store delegates to pgvector ``<=>``. Scoping is enforced in Python
    (only in-scope rows are ever considered), so the isolation invariant holds
    identically offline and on Postgres.
    """

    def __init__(self) -> None:
        self.skills: list[Skill] = []

    def _in_scope_active(self, scope: CohortScope) -> list[Skill]:
        return [
            s
            for s in self.skills
            if s.status == SkillStatus.ACTIVE
            and s.embedding is not None
            and scope.contains(
                org_id=s.org_id,
                cohort_id=s.cohort_id,
                trust_domain=s.trust_domain,
            )
        ]

    def find_active_duplicate(
        self, embedding: list[float], scope: CohortScope, threshold: float
    ) -> Optional[Skill]:
        max_distance = 1.0 - threshold
        best: Optional[Skill] = None
        best_dist = max_distance
        for s in self._in_scope_active(scope):
            dist = _cosine_distance(embedding, list(s.embedding))
            if dist < best_dist:
                best, best_dist = s, dist
        return best

    def add(self, skill: Skill) -> Skill:
        self.skills.append(skill)
        return skill

    def top_k_active(
        self, embedding: list[float], scope: CohortScope, k: int
    ) -> list[Skill]:
        scored = [
            (_cosine_distance(embedding, list(s.embedding)), s)
            for s in self._in_scope_active(scope)
        ]
        scored.sort(key=lambda t: t[0])
        return [s for _, s in scored[: max(0, k)]]


class PostgresSkillStore:
    """Durable skill store over the 0037 ``skills`` table.

    REUSES the pgvector ``<=>`` cosine operator via
    ``Skill.embedding.cosine_distance`` — the exact operator
    ``Deduplicator.find_cluster`` uses on ``attack_primitives`` — and routes
    every read through ``cohorts.scope_query`` so trust-boundary isolation is
    enforced in the WHERE clause, not a post-filter. ORM/SQLAlchemy are imported
    lazily inside methods so importing this module needs no DB/driver (mirrors
    ``tenancy.py`` / ``decider.PostgresSessionStore``).

    ``session_factory`` is a SQLAlchemy ``sessionmaker`` (or any zero-arg callable
    returning a ``Session`` usable as a context manager).
    """

    def __init__(self, session_factory: Callable[[], object]) -> None:
        self._session_factory = session_factory

    def find_active_duplicate(
        self, embedding: list[float], scope: CohortScope, threshold: float
    ) -> Optional[Skill]:
        from sqlalchemy import select

        max_distance = 1.0 - threshold
        distance_expr = Skill.embedding.cosine_distance(embedding)
        stmt = (
            select(Skill, distance_expr.label("distance"))
            .where(Skill.status == SkillStatus.ACTIVE)
            .where(Skill.embedding.is_not(None))
        )
        stmt = scope_query(stmt, scope).order_by(distance_expr).limit(1)
        with self._session_factory() as session:
            row = session.execute(stmt).first()
        if row is None:
            return None
        skill, distance = row
        if distance is None or float(distance) >= max_distance:
            return None
        return skill

    def add(self, skill: Skill) -> Skill:
        with self._session_factory() as session:
            session.add(skill)
            session.commit()
            session.refresh(skill)
            session.expunge(skill)
        return skill

    def top_k_active(
        self, embedding: list[float], scope: CohortScope, k: int
    ) -> list[Skill]:
        from sqlalchemy import select

        distance_expr = Skill.embedding.cosine_distance(embedding)
        stmt = (
            select(Skill)
            .where(Skill.status == SkillStatus.ACTIVE)
            .where(Skill.embedding.is_not(None))
        )
        stmt = scope_query(stmt, scope).order_by(distance_expr).limit(max(0, k))
        with self._session_factory() as session:
            rows = list(session.execute(stmt).scalars().all())
            for r in rows:
                session.expunge(r)
        return rows


# --------------------------------------------------------------------------------------------------
# SkillPool service
# --------------------------------------------------------------------------------------------------


class SkillPool:
    """The assured shared-skill substrate (Surface 3, Section B).

    Args:
        store: the injected ``SkillStore`` (in-memory for tests, Postgres for
            durable runs). The pool never opens a session itself.
        embed_fn: ``str -> list[float]`` 1536-d embedder, injected exactly as
            ``Deduplicator`` takes it (keeps the module import-safe without creds).
        threshold: cosine-similarity cutoff for the dedup-cluster test; defaults
            to ``DEFAULT_COSINE_THRESHOLD`` (REUSE — same constant ``Deduplicator``
            uses on ``attack_primitives``).
    """

    def __init__(
        self,
        store: SkillStore,
        embed_fn: EmbedFn,
        threshold: float = DEFAULT_COSINE_THRESHOLD,
    ) -> None:
        self.store = store
        self.embed_fn = embed_fn
        self.threshold = threshold

    # ------------------------------------------------------------------
    # ingest
    # ------------------------------------------------------------------

    def ingest_candidate(
        self,
        skill_md: str,
        *,
        org_id: str,
        cohort_id: str,
        trust_domain: str,
        source_kind: SkillSourceKind | str,
        applicability_condition: Optional[dict] = None,
    ) -> Skill:
        """Ingest a candidate skill (``status=candidate``), embedding + dedup.

        Embeds ``skill_md`` via the injected ``embed_fn`` and checks it against
        the **active** skills in the SAME cohort/trust_domain (scoped — never
        cross-domain). If a near-duplicate active skill exists (cosine distance
        below the threshold band), the candidate **clusters** onto it: that
        existing active skill is returned and NO second active row is inserted.
        Otherwise a new ``candidate`` row is persisted and returned.

        Note this is *not* a promotion path — a fresh ingest is always a
        ``candidate``; the verified-promotion gate (another engineer's module)
        is the only thing that flips a skill to ``active``.
        """
        scope = resolve_scope(
            org_id=org_id, cohort_id=cohort_id, trust_domain=trust_domain
        )
        embedding = self.embed_fn(skill_md)

        # Dedup against ACTIVE in-scope skills — REUSE the Deduplicator cosine
        # `<=>` semantics. A near-duplicate clusters onto the existing active
        # skill instead of inserting a second active row.
        duplicate = self.store.find_active_duplicate(
            embedding, scope, self.threshold
        )
        if duplicate is not None:
            return duplicate

        skill = Skill(
            skill_id=_new_skill_id(),
            org_id=scope.org_id,
            cohort_id=scope.cohort_id,
            trust_domain=scope.trust_domain,
            skill_md=skill_md,
            embedding=embedding,
            status=SkillStatus.CANDIDATE,
            applicability_condition=applicability_condition or {},
            source_kind=SkillSourceKind(source_kind)
            if not isinstance(source_kind, SkillSourceKind)
            else source_kind,
            created_at=_now(),
        )
        return self.store.add(skill)

    # ------------------------------------------------------------------
    # retrieve (carrier only — see module docstring / spec §1)
    # ------------------------------------------------------------------

    def retrieve(
        self,
        cohort_id: str,
        query: str,
        k: int,
        *,
        org_id: str,
        trust_domain: str,
    ) -> list[Skill]:
        """Return up to ``k`` ACTIVE skills in ``cohort_id`` nearest ``query``.

        The carrier for the verification rollouts and the lazy-gate retrieval-
        pressure counter — NOT a "make task faster" pitch (spec §1). Scoped to
        the requested ``org_id`` / ``cohort_id`` / ``trust_domain``: a domain-Y
        skill is never returned to a domain-X request (Section G isolation,
        enforced centrally via ``cohorts.scope_query`` / the in-memory store's
        scope check).
        """
        scope = resolve_scope(
            org_id=org_id, cohort_id=cohort_id, trust_domain=trust_domain
        )
        embedding = self.embed_fn(query)
        return self.store.top_k_active(embedding, scope, k)

    # ------------------------------------------------------------------
    # fixture loader (demo/tests)
    # ------------------------------------------------------------------

    def load_fixture(
        self,
        path: Optional[str | Path] = None,
        *,
        org_id: str,
        cohort_id: str,
        trust_domain: str,
    ) -> list[Skill]:
        """Ingest the 55-skill fixture as candidates into one cohort/trust_domain.

        Each fixture record's ``skill_md``, ``source_kind`` and
        ``applicability_condition`` flow straight through ``ingest_candidate``
        (so the same embed + dedup-cluster path runs). Returns the ingested /
        clustered skills in fixture order.
        """
        fixture_path = Path(path) if path is not None else DEFAULT_FIXTURE_PATH
        records = json.loads(Path(fixture_path).read_text())
        out: list[Skill] = []
        for rec in records:
            out.append(
                self.ingest_candidate(
                    rec["skill_md"],
                    org_id=org_id,
                    cohort_id=cohort_id,
                    trust_domain=trust_domain,
                    source_kind=rec["source_kind"],
                    applicability_condition=rec.get("applicability_condition"),
                )
            )
        return out
