"""Seed the local Postgres with the three demo-seed fixtures.

Purpose: populate the local ``rogue-postgres`` instance with enough data
that the Day 0 / Day 1 dashboard work and the Day 1 reproduction layer
can run end-to-end *without* needing a live Bright Data harvest. The
script reads the three golden ``AttackPrimitive`` JSON fixtures under
``tests/fixtures/``, projects each through its Pydantic schema, and
persists the resulting ORM rows alongside the 5 demo ``DeploymentConfig``
records returned by ``rogue.schemas.demo_deployment_configs``.

ORM-aliasing convention (canonical Day-1+ pattern — CLAUDE.md flags
this): ``rogue.schemas`` and ``rogue.db.models`` both define classes
named ``AttackPrimitive`` / ``DeploymentConfig`` / ``SourceProvenance``
(wire format vs. storage format). The first module that needs BOTH
sides must alias the ORM imports with an ``ORM`` suffix so the wire
shapes keep their bare names. This file is that first module.

Idempotency: re-runnable any number of times. Before inserting, the
script ``DELETE``s from ``breach_results``, ``source_provenances``,
``attack_primitives``, and ``deployment_configs`` (children before
parents to satisfy the FK constraints). This is safe because the
script seeds *demo* data only — it never touches rows produced by a
live Bright Data harvest. The ``BreachResult`` table is empty on
Day 0 but the DELETE is included for forward compatibility with the
Day 1 reproduction layer.

Sync SQLAlchemy: §A.14 sketches an async variant, but for a one-shot
seed script the sync API is dramatically simpler (no asyncio
boilerplate, no async context manager juggling) and matches the
existing ``alembic/env.py`` pattern. See the engine-construction
comment below.

Invocation:
    uv run python scripts/seed_demo_data.py

Environment:
    DATABASE_URL  (defaults to the .env.example value pointing at the
                   local ``rogue-postgres`` Docker container)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# Load .env so a customized DATABASE_URL takes effect without requiring the
# operator to `source .env` first. Without this, a missing env var falls
# through to the hardcoded default below (which matches docker-compose) —
# silent-wrong-DB footgun if you ever point at a non-default host.
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import create_engine, delete, func, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from rogue.db.models import (  # noqa: E402
    AttackPrimitive as AttackPrimitiveORM,
    BreachResult as BreachResultORM,
    DeploymentConfig as DeploymentConfigORM,
    SourceProvenance as SourceProvenanceORM,
)
from rogue.schemas import (  # noqa: E402
    AttackPrimitive,
    DeploymentConfig,
    demo_deployment_configs,
)
from rogue.schemas.source_provenance import SourceProvenance  # noqa: E402

# Enum wire/storage alignment is handled in `rogue.db.models` via
# `SAEnum(..., values_callable=_enum_values)` on every enum column
# (added 2026-05-24 after the §8.5 seed surfaced the latent mismatch
# between SQLAlchemy's name-serialization default and the migration's
# value-based enum types). No process-local patch needed here.

# IMPLEMENT Day 1 §10.1: once ``rogue.config.settings`` (§A.3) lands,
# replace this with ``from rogue.config import settings;
# DATABASE_URL = settings.DATABASE_URL``. Same marker convention as
# ``extract/extraction_agent.py`` and ``reproduce/target_panel.py``.
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue",
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"


# --------------------------------------------------------------------------- #
# Pydantic → ORM projection helpers
# --------------------------------------------------------------------------- #


def _to_orm_deployment(cfg: DeploymentConfig) -> DeploymentConfigORM:
    """Project a Pydantic ``DeploymentConfig`` into its ORM mirror.

    The two shapes match 1:1 for this model, so a straight
    ``**model_dump()`` splat is correct.
    """
    return DeploymentConfigORM(**cfg.model_dump())


def _to_orm_source(s: SourceProvenance) -> SourceProvenanceORM:
    """Project a Pydantic ``SourceProvenance`` into its ORM mirror.

    The only non-trivial conversion is ``url``: Pydantic uses ``HttpUrl``
    (a validated URL object), while the ORM column is ``Text``. We coerce
    via ``str(...)``. ``source_type`` and ``bright_data_product`` are
    ``Literal[...]``s on the wire side and CHECK-constrained strings on
    the storage side — they round-trip as-is.
    """
    return SourceProvenanceORM(
        url=str(s.url),
        source_type=s.source_type,
        author=s.author,
        published_at=s.published_at,
        fetched_at=s.fetched_at,
        archive_hash=s.archive_hash,
        bright_data_product=s.bright_data_product,
    )


def _to_orm_primitive(p: AttackPrimitive) -> AttackPrimitiveORM:
    """Project a Pydantic ``AttackPrimitive`` into its ORM mirror.

    Handles the 24 schema fields:
      - ``family``, ``vector``, ``base_severity``: enum fields. The
        Postgres enum types created by the 0001 migration use the
        Pydantic *values* (lowercase, e.g. ``language_switching``), but
        SQLAlchemy's default ``Enum(PythonEnum)`` column serializes by
        *name* (uppercase ``LANGUAGE_SWITCHING``). Pass ``.value``
        explicitly so the storage layer sees what its CHECK / enum types
        expect. (A fuller fix would be ``SAEnum(..., values_callable=
        lambda e: [m.value for m in e])`` on the column definitions in
        ``db/models.py``, but per task spec we do not touch that file.)
      - ``secondary_families``: ``list[AttackFamily]`` on the wire,
        stored as a JSON list of plain strings — unpack via ``.value``.
      - ``sources``: build the ORM children and pass via the ``sources=``
        kwarg; the relationship's ``cascade="all, delete-orphan"`` setup
        on the parent handles the FK wiring at flush time.
      - ``payload_embedding``: deliberately NOT set — it's nullable, and
        harvest-time embeddings land in Day 1 §9.5.
    """
    return AttackPrimitiveORM(
        # Identity
        primitive_id=p.primitive_id,
        cluster_id=p.cluster_id,
        canonical=p.canonical,
        # Classification (.value to match Postgres-side enum members)
        family=p.family.value,
        secondary_families=[f.value for f in p.secondary_families],
        vector=p.vector.value,
        title=p.title,
        short_description=p.short_description,
        # Payload
        payload_template=p.payload_template,
        payload_slots=p.payload_slots,
        multi_turn_sequence=p.multi_turn_sequence,
        # Source claims
        target_models_claimed=p.target_models_claimed,
        claimed_success_rate=p.claimed_success_rate,
        claimed_first_seen=p.claimed_first_seen,
        # Quality / requirements
        reproducibility_score=p.reproducibility_score,
        requires_multi_turn=p.requires_multi_turn,
        requires_system_prompt_access=p.requires_system_prompt_access,
        requires_tools=p.requires_tools,
        requires_multimodal=p.requires_multimodal,
        # Timestamps + severity (.value to match Postgres-side enum members)
        discovered_at=p.discovered_at,
        base_severity=p.base_severity.value,
        severity_rationale=p.severity_rationale,
        notes=p.notes,
        # Relationships (cascade-insert via the parent)
        sources=[_to_orm_source(s) for s in p.sources],
    )


# --------------------------------------------------------------------------- #
# Main flow
# --------------------------------------------------------------------------- #


def main() -> None:
    # Sync engine + session — see the module docstring for why we deviate
    # from §A.14's async sketch.
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    with SessionLocal() as session:
        # 1. Idempotent reset. Order is load-bearing: children before parents
        #    so the FK constraints (breach_results → attack_primitives,
        #    breach_results → deployment_configs, source_provenances →
        #    attack_primitives) are never violated mid-flush.
        session.execute(delete(BreachResultORM))
        session.execute(delete(SourceProvenanceORM))
        session.execute(delete(AttackPrimitiveORM))
        session.execute(delete(DeploymentConfigORM))
        session.commit()

        # 2. Seed the 5 demo DeploymentConfigs.
        for cfg in demo_deployment_configs():
            session.add(_to_orm_deployment(cfg))

        # 3. Seed the 3 golden AttackPrimitives. Each carries 1+
        #    SourceProvenance children that cascade-insert via the parent.
        fixture_paths = sorted(FIXTURES_DIR.glob("0*.json"))
        for fp in fixture_paths:
            data = json.loads(fp.read_text(encoding="utf-8"))
            primitive = AttackPrimitive.model_validate(data)
            session.add(_to_orm_primitive(primitive))
            print(
                f"  loaded {primitive.primitive_id}: {primitive.title}"
                f"  ({len(primitive.sources)} source(s))"
            )

        session.commit()

        # 4. Summary counts.
        for name, model in [
            ("deployment_configs", DeploymentConfigORM),
            ("attack_primitives", AttackPrimitiveORM),
            ("source_provenances", SourceProvenanceORM),
        ]:
            n = session.execute(select(func.count()).select_from(model)).scalar_one()
            print(f"  {name}: {n}")

    engine.dispose()


if __name__ == "__main__":
    main()
