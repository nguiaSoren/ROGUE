"""Newly-landed-corpus signal for the Slack harvest-cycle trigger (build-area 06 §3).

"Newly-landed" means attacks newly **harvested into the corpus** this cycle — primitives whose
``discovered_at >= since`` — NOT a breach-state diff. This is the area thesis: red-team using *this
week's harvested corpus*. (``ThreatBriefBuilder.build_diff`` computes a different thing — breached-
today-not-yesterday — and is deliberately NOT used here.)

The trigger consumes the returned ``{AttackFamily: [AttackPrimitive, ...]}`` grouping: it re-aims /
fires one agent per family that has newly-landed primitives, so the grouping IS the fan-out plan.

Projection reuses ``rogue.platform.repertoire._orm_to_primitive`` so a corpus row becomes the exact
same Pydantic wire type the renderer + judge consume — we never reimplement that projection. Like
``default_repertoire_loader``, this module touches no DB at import time: the engine is built lazily
inside the function only on the DB path, and disposed in a ``finally``.
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime
from typing import Iterable

from sqlalchemy import select

from rogue.db.models import AttackPrimitive as AttackPrimitiveORM
from rogue.platform.repertoire import _DEFAULT_DATABASE_URL, _orm_to_primitive
from rogue.schemas import AttackFamily, AttackPrimitive

__all__ = ["newly_landed_primitives"]


def _group(primitives: Iterable[AttackPrimitive]) -> dict[AttackFamily, list[AttackPrimitive]]:
    """Group already-filtered primitives by ``.family``, deterministically ordered within each
    family (most-recently-discovered first, then primitive_id). Families with no members are
    omitted — never emits an empty list."""
    grouped: dict[AttackFamily, list[AttackPrimitive]] = defaultdict(list)
    for p in primitives:
        grouped[p.family].append(p)
    for members in grouped.values():
        members.sort(key=lambda p: (p.discovered_at, p.primitive_id), reverse=True)
    return dict(grouped)


def newly_landed_primitives(
    since: datetime,
    *,
    primitives: Iterable[AttackPrimitive] | None = None,
    session=None,
    database_url: str | None = None,
) -> dict[AttackFamily, list[AttackPrimitive]]:
    """Corpus primitives harvested since ``since`` (``discovered_at >= since``), grouped by family.

    ``since`` is timezone-aware UTC by contract and is compared directly against ``discovered_at``.

    Source resolution, in priority order:
      1. ``primitives`` given — filter + group that in-memory iterable; NO DB touched (test/fake path).
      2. ``session`` given — query corpus rows with ``discovered_at >= since``, project each via
         ``_orm_to_primitive``, group. Fully materialized before returning (the session is not held).
      3. Neither — build a short-lived engine from ``database_url`` or ``DATABASE_URL`` (falling back
         to the same default literal ``repertoire.py`` uses), run path-2's query, dispose in a finally.
    """
    if primitives is not None:
        return _group(p for p in primitives if p.discovered_at >= since)

    stmt = select(AttackPrimitiveORM).where(AttackPrimitiveORM.discovered_at >= since)

    if session is not None:
        rows = session.execute(stmt).scalars().all()
        return _group(_orm_to_primitive(o) for o in rows)

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    url = database_url or os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
    engine = create_engine(url, pool_pre_ping=True, pool_recycle=300, pool_timeout=10)
    try:
        with sessionmaker(bind=engine)() as s:
            rows = s.execute(stmt).scalars().all()
            return _group(_orm_to_primitive(o) for o in rows)
    finally:
        engine.dispose()
