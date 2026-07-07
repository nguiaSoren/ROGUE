"""Pre-fire feature row = Q11's structural block ⊕ the embedding-affinity block.

We reuse ``survival.features.build_features`` verbatim for the structural half — same family/vector
one-hots, requirement flags, provenance scores, and target descriptor — so the two predictors share one
audited featuriser and Q7 is *exactly* Q11's features plus the content axis. That makes the ablation in
``train.py`` a clean apples-to-apples comparison: drop the trailing ``AFFINITY_DIM`` columns and you
have Q11's vector.

The layout is versioned independently of survival's: ``PREFIRE_FEATURE_DIM`` tracks
``survival.FEATURE_DIM`` (so a survival-layout bump flows through automatically) plus the affinity dims,
and the artifact refuses to load under a mismatched dim.
"""

from __future__ import annotations

from rogue.reproduce.config_features import ConfigFeatures, derive_config_features
from rogue.reproduce.prefire.embedding_affinity import AFFINITY_DIM, EmbeddingAffinity
from rogue.reproduce.survival.features import FEATURE_DIM as STRUCT_DIM
from rogue.reproduce.survival.features import build_features as build_structural_features
from rogue.schemas import AttackPrimitive, DeploymentConfig

# Bump when either block's layout changes — load() cross-checks this and the dim.
PREFIRE_SCHEMA_VERSION = 1

PREFIRE_FEATURE_DIM = STRUCT_DIM + AFFINITY_DIM


def sibling_key(config: DeploymentConfig, *, config_features: ConfigFeatures | None = None) -> str:
    """The config's sibling class (size × context reach) — the axis the affinity centroids are keyed on."""
    cf = config_features or derive_config_features(
        config.target_model, base_url=getattr(config, "base_url", None)
    )
    return cf.sibling_key


def build_prefire_features(
    primitive: AttackPrimitive,
    config: DeploymentConfig,
    embedding: list[float] | None,
    affinity: EmbeddingAffinity | None,
    *,
    config_features: ConfigFeatures | None = None,
) -> list[float]:
    """Full pre-fire row. ``config`` is duck-typed (Pydantic at scan time, ORM at train time), exactly
    as in survival. ``affinity`` may be ``None`` (no model / uninformative) → the affinity block is
    zeros and the row degrades to the structural signal."""
    cf = config_features or derive_config_features(
        config.target_model, base_url=getattr(config, "base_url", None)
    )
    struct = build_structural_features(primitive, config, config_features=cf)
    if affinity is not None:
        aff = affinity.features(embedding, cf.sibling_key)
    else:
        aff = [0.0, 0.0, 1.0 if embedding is not None else 0.0]
    return struct + aff


__all__ = [
    "PREFIRE_SCHEMA_VERSION",
    "PREFIRE_FEATURE_DIM",
    "STRUCT_DIM",
    "AFFINITY_DIM",
    "sibling_key",
    "build_prefire_features",
]
