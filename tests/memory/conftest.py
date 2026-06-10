"""Shared offline fixtures for the Surface-3 (agent-memory skill pool) tests.

Everything here is offline by construction: a deterministic token-hash embedder
(no model/creds), in-memory stores, and a SQLite engine for the few tests that
want a real ORM round-trip. Postgres-backed paths are NOT exercised here; the
DB-backed tests use SQLite (which exercises the same ORM/SQLAlchemy seam) and the
0037 migration round-trip is verified separately by the runner, not pytest.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable

import pytest

from rogue.db.models import Skill, SkillSourceKind, SkillStatus

_EMBED_DIM = 1536


def _hash_embed(text: str) -> list[float]:
    """A deterministic, content-sensitive 1536-d unit-ish vector for offline dedup.

    Token bag-of-words hashed into buckets — so identical text yields an identical
    vector (cosine distance 0 → a near-duplicate) and unrelated text yields a
    near-orthogonal vector. No model, no creds, fully reproducible.
    """
    vec = [0.0] * _EMBED_DIM
    tokens = text.lower().split()
    if not tokens:
        # Non-zero so it is never the degenerate zero-vector (which pool.py treats
        # as maximally distant); a stable constant direction for empty strings.
        vec[0] = 1.0
        return vec
    for tok in tokens:
        h = int(hashlib.sha256(tok.encode()).hexdigest(), 16)
        bucket = h % _EMBED_DIM
        sign = 1.0 if (h >> 8) & 1 else -1.0
        vec[bucket] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm:
        vec = [v / norm for v in vec]
    return vec


@pytest.fixture
def embed_fn() -> Callable[[str], list[float]]:
    """The injected deterministic offline embedder used across the pool tests."""
    return _hash_embed


def make_skill(
    *,
    skill_id: str,
    org_id: str = "org-a",
    cohort_id: str = "team-a",
    trust_domain: str = "domain-a",
    skill_md: str = "do the thing",
    status: SkillStatus = SkillStatus.CANDIDATE,
    embedding: list[float] | None = None,
    applicability_condition: dict | None = None,
    source_kind: SkillSourceKind = SkillSourceKind.CORRECTION,
) -> Skill:
    """Construct a ``Skill`` ORM object (unpersisted) for offline gate tests."""
    return Skill(
        skill_id=skill_id,
        org_id=org_id,
        cohort_id=cohort_id,
        trust_domain=trust_domain,
        skill_md=skill_md,
        embedding=embedding,
        status=status,
        applicability_condition=applicability_condition or {},
        source_kind=source_kind,
    )


@pytest.fixture
def skill_factory() -> Callable[..., Skill]:
    return make_skill


_SENTINEL = re.compile(r"^\[(repair|regression|neutral)\]")


def stub_net_effect_judge(
    *, task, expected_outcome, output_without_skill, output_with_skill
) -> str:
    """Read the FakeRolloutRunner sentinel off the WITH-side output → verdict string.

    The promotion/reverification gates' ``_verdict_of`` projects this bare string to a
    ``NetEffectVerdict`` — so the whole gate runs with no LLM and no creds.
    """
    m = _SENTINEL.match(output_with_skill or "")
    return m.group(1) if m else "neutral"


@pytest.fixture
def net_effect_stub() -> Callable[..., str]:
    return stub_net_effect_judge


@pytest.fixture
def sqlite_session_factory():
    """A SQLite-backed ``sessionmaker`` registering only the Surface-3 + org tables.

    Mirrors ``tests/attestation/test_service.py``: create just the tables the unit
    under test touches on an in-memory SQLite engine, so the pgvector ``Vector``
    column (and any other Postgres-only column on unrelated tables) never loads.
    Returns ``None``-skip semantics are not needed — SQLite is always available.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from rogue.db.models import (
        Base,
        SkillEdge,
        SkillVerification,
    )
    from rogue.platform.models import Organization

    engine = create_engine("sqlite://")
    # The Vector(1536) column on `skills` is Postgres-only; SQLite cannot create it.
    # The DB-backed tests here that use this factory only touch skill_verifications /
    # skill_edges (+ organizations for the FK), so create exactly those.
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__,
            SkillVerification.__table__,
            SkillEdge.__table__,
        ],
    )
    return sessionmaker(bind=engine, expire_on_commit=False)
