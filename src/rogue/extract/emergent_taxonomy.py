"""Emergent-taxonomy layer — the automatic half of taxonomy extension.

The extraction agent proposes a free-text ``emergent_label`` for any technique that doesn't cleanly
fit the frozen (family, vector) enums (``taxonomy_fit`` weak/novel). This module CLUSTERS those
labels (deterministic, no LLM) and DRAFTS promotion proposals when a cluster is large enough — so
recurring novelty surfaces automatically. The one thing that is NOT automatic is the promotion
itself: adding an enum value ripples into weights/judge/comparability + needs a migration, so a human
approves it. Automatic capture + cluster + propose; gated commit.

Storage-agnostic: ``cluster_emergent`` accepts ORM rows, Pydantic ``AttackPrimitive``s, or dicts —
anything exposing ``primitive_id`` / ``emergent_label`` / ``family`` / ``vector``.
"""

from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

_STOP = {"the", "a", "an", "via", "through", "of", "to", "in", "on", "by", "attack",
         "injection", "based", "using", "with", "and", "for"}


def _normalize(label: str) -> str:
    """Canonical key: lowercase, split on non-alphanumerics, drop stopwords, sort tokens."""
    toks = [t for t in re.split(r"[^a-z0-9]+", label.lower().strip()) if t and t not in _STOP]
    return " ".join(sorted(toks))


def _snake(label: str) -> str:
    return "_".join(t for t in re.split(r"[^a-z0-9]+", label.lower()) if t)[:40]


def _row(item: Any) -> tuple[str | None, str | None, str | None, str | None]:
    def get(name: str):
        return item.get(name) if isinstance(item, dict) else getattr(item, name, None)

    fam, vec = get("family"), get("vector")
    return get("primitive_id"), get("emergent_label"), getattr(fam, "value", fam), getattr(vec, "value", vec)


@dataclass
class EmergentCluster:
    label: str                    # most common raw label (representative)
    key: str                      # normalized key
    variants: list[str]
    primitive_ids: list[str]
    families: dict[str, int]      # assigned families among members (context)
    vectors: dict[str, int]

    @property
    def count(self) -> int:
        return len(self.primitive_ids)


@dataclass
class PromotionProposal:
    proposed_value: str           # snake_case candidate enum value
    representative_label: str
    count: int
    primitive_ids: list[str]
    dominant_family: str
    dominant_vector: str
    rationale: str
    migration_hint: str


def cluster_emergent(items: Iterable[Any], *, similarity: float = 0.82) -> list[EmergentCluster]:
    """Group primitives by fuzzy-matched emergent_label. Items without a label are ignored."""
    clusters: list[dict] = []
    for item in items:
        pid, label, fam, vec = _row(item)
        if not label or not pid:
            continue
        key = _normalize(label)
        match = None
        for c in clusters:
            if key == c["key"] or difflib.SequenceMatcher(None, key, c["key"]).ratio() >= similarity:
                match = c
                break
        if match is None:
            match = {"key": key, "labels": [], "pids": [], "fams": Counter(), "vecs": Counter()}
            clusters.append(match)
        match["labels"].append(label)
        match["pids"].append(pid)
        match["fams"][fam or "?"] += 1
        match["vecs"][vec or "?"] += 1

    out = [
        EmergentCluster(
            label=Counter(c["labels"]).most_common(1)[0][0], key=c["key"],
            variants=sorted(set(c["labels"])), primitive_ids=c["pids"],
            families=dict(c["fams"]), vectors=dict(c["vecs"]),
        )
        for c in clusters
    ]
    out.sort(key=lambda c: c.count, reverse=True)
    return out


def promotion_candidates(
    items: Iterable[Any], *, min_cluster_size: int = 5, similarity: float = 0.82
) -> list[PromotionProposal]:
    """Emergent clusters at/above ``min_cluster_size`` → drafted (human-approved) promotion proposals."""
    proposals: list[PromotionProposal] = []
    for c in cluster_emergent(items, similarity=similarity):
        if c.count < min_cluster_size:
            continue
        fam = max(c.families, key=c.families.get) if c.families else "?"
        vec = max(c.vectors, key=c.vectors.get) if c.vectors else "?"
        value = _snake(c.label)
        proposals.append(
            PromotionProposal(
                proposed_value=value, representative_label=c.label, count=c.count,
                primitive_ids=list(c.primitive_ids), dominant_family=fam, dominant_vector=vec,
                rationale=(
                    f"{c.count} primitives were classified as ({fam}, {vec}) but share the emergent "
                    f"pattern '{c.label}' (variants: {', '.join(c.variants[:4])}). Candidate for a "
                    f"dedicated family/vector."
                ),
                migration_hint=(
                    f"To promote (HUMAN-approved, never automatic): add the enum value "
                    f"'{value}' in schemas/attack_primitive.py, a FAMILY_WEIGHTS/VECTOR_WEIGHTS entry, "
                    f"a judge rule, and an alembic migration widening the CHECK vocabulary; then "
                    f"reclassify these {c.count} primitives off their emergent_label."
                ),
            )
        )
    return proposals


def promotion_candidates_from_db(database_url: str, *, min_cluster_size: int = 5) -> list[PromotionProposal]:
    """Query primitives that carry an emergent_label and draft promotion candidates. Best-effort."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from rogue.db.models import AttackPrimitive as AttackPrimitiveORM

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            rows = session.execute(
                select(
                    AttackPrimitiveORM.primitive_id, AttackPrimitiveORM.emergent_label,
                    AttackPrimitiveORM.family, AttackPrimitiveORM.vector,
                ).where(AttackPrimitiveORM.emergent_label.is_not(None))
            ).all()
        items = [
            {"primitive_id": r[0], "emergent_label": r[1], "family": r[2], "vector": r[3]}
            for r in rows
        ]
        return promotion_candidates(items, min_cluster_size=min_cluster_size)
    finally:
        engine.dispose()


__all__ = [
    "EmergentCluster", "PromotionProposal", "cluster_emergent",
    "promotion_candidates", "promotion_candidates_from_db",
]
