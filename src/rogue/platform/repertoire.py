"""Load the live harvested repertoire (the `attack_primitives` corpus) as wire-type primitives.

A `pack` scan fires a small curated JSON pack (8–17 primitives). A `repertoire` scan fires the
platform's actual harvested arsenal — the corpus ROGUE continuously grows from the open web (hundreds
of primitives) — so customers benefit from the harvesting, not a frozen sample. This module is the
in-package, deployable corpus loader (the equivalent converter in `scripts/reproduce_once.py` can't be
imported by the worker — `scripts/` isn't on the package path).

Primitives are fully projected into Pydantic before the session closes, so callers can (and must) use a
SHORT session — never hold it across the scan's LLM calls (the Neon idle-in-transaction rule).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from sqlalchemy import select

from rogue.db.models import AttackPrimitive as AttackPrimitiveORM
from rogue.schemas import AttackFamily, AttackPrimitive, AttackVector, Severity

if TYPE_CHECKING:
    from .schemas import ScanSpec

_DEFAULT_DATABASE_URL = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"


def _orm_to_primitive(orm: AttackPrimitiveORM) -> AttackPrimitive:
    """Project an ORM corpus row into the Pydantic wire type the renderer + judge consume.

    Mirrors ``scripts/reproduce_once._orm_to_pydantic_primitive`` — enum coercion + JSON-column
    defaults + a placeholder ``sources`` entry (the reproduction layer never reads provenance)."""
    return AttackPrimitive.model_validate(
        {
            "primitive_id": orm.primitive_id,
            "cluster_id": orm.cluster_id,
            "canonical": orm.canonical,
            "family": AttackFamily(orm.family) if isinstance(orm.family, str) else orm.family,
            "secondary_families": [
                AttackFamily(f) if isinstance(f, str) else f for f in (orm.secondary_families or [])
            ],
            "vector": AttackVector(orm.vector) if isinstance(orm.vector, str) else orm.vector,
            "title": orm.title,
            "short_description": orm.short_description,
            "payload_template": orm.payload_template,
            "payload_slots": orm.payload_slots or {},
            "multi_turn_sequence": orm.multi_turn_sequence,
            "target_models_claimed": orm.target_models_claimed or [],
            "claimed_success_rate": orm.claimed_success_rate,
            "claimed_first_seen": orm.claimed_first_seen,
            "reproducibility_score": orm.reproducibility_score,
            "requires_multi_turn": orm.requires_multi_turn,
            "requires_system_prompt_access": orm.requires_system_prompt_access,
            "requires_tools": orm.requires_tools or [],
            "requires_multimodal": orm.requires_multimodal,
            "discovered_at": orm.discovered_at,
            "base_severity": (
                Severity(orm.base_severity) if isinstance(orm.base_severity, str) else orm.base_severity
            ),
            "severity_rationale": orm.severity_rationale,
            "notes": orm.notes,
            "sources": [
                {
                    "url": f"https://rogue.internal/replay/{orm.primitive_id}",
                    "source_type": "other",
                    "author": None,
                    "published_at": None,
                    "fetched_at": orm.discovered_at,
                    "archive_hash": "replay-placeholder",
                    "bright_data_product": "fixture",
                }
            ],
        }
    )


def load_repertoire(session, *, limit: int = 100, families: list[str] | None = None) -> list[AttackPrimitive]:
    """The top-``limit`` harvested corpus primitives, most-reproducible first. Fully materialized into
    Pydantic before returning, so the caller's session can close immediately."""
    stmt = select(AttackPrimitiveORM)
    if families:
        stmt = stmt.where(AttackPrimitiveORM.family.in_(families))
    stmt = stmt.order_by(
        AttackPrimitiveORM.reproducibility_score.desc().nullslast(),
        AttackPrimitiveORM.discovered_at.desc(),
    ).limit(limit)
    return [_orm_to_primitive(o) for o in session.execute(stmt).scalars().all()]


def default_repertoire_loader(spec: ScanSpec) -> list[AttackPrimitive]:
    """Production loader: a short-lived session against ``DATABASE_URL`` → the corpus, capped at
    ``spec.max_tests``. Builds + disposes its own engine (lazy, so importing this module needs no DB)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    url = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
    engine = create_engine(url, pool_pre_ping=True, pool_recycle=300, pool_timeout=10)
    try:
        with sessionmaker(bind=engine)() as s:
            return load_repertoire(s, limit=spec.max_tests)
    finally:
        engine.dispose()


__all__ = ["load_repertoire", "default_repertoire_loader", "_orm_to_primitive"]
