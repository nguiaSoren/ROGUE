"""TechniqueProfile — a retrieval-optimised view of one attack technique.

Used by the Technique Retrieval System to match techniques to targets during
escalation planning. Unlike ``TechniqueSpec`` (the extraction-time wire type),
``TechniqueProfile`` is the *retrieval-time* representation: it carries telemetry
keys (``label``, ``technique_id``) that align with ``ladder_attempts.entity_id``
and ``ladder_rotation_membership.strategy_id``, plus historical target evidence.

The ``family`` field is a **free string** — it spans ARMS patterns, frozen
taxonomy families, renderer tiers, and harvested-method categories without being
bound to the ``AttackFamily`` enum. This is intentional: the retrieval system must
reason across all of those categories in a single field, and the frozen taxonomy
must not be modified (§13 non-goal: no taxonomy revisions after Day 0).

Spec: ROGUE_PLAN.md §10 (reproduction + escalation layer).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TechniqueProfile(BaseModel):
    """Retrieval-optimised view of one attack technique.

    ``label`` is the canonical key for telemetry lookups and retrieval indexing.
    It matches ``ladder_attempts.entity_id`` and
    ``ladder_rotation_membership.strategy_id`` exactly (e.g. ``"crescendo"``,
    ``"image:mml:wr"``).
    """

    # ----- Identity -----
    label: str = Field(
        ...,
        description=(
            "canonical retrieval + telemetry key; matches ladder_attempts.entity_id "
            "and ladder_rotation_membership.strategy_id, e.g. 'crescendo', 'image:mml:wr'"
        ),
    )
    technique_id: str = Field(
        "",
        description="strategy ULID when available; may equal label when no ULID is assigned",
    )
    name: str = Field(..., description="human-readable short name of the technique")

    # ----- Classification -----
    family: str = Field(
        ...,
        description=(
            "ARMS pattern / attack family / 'renderer_tier' / 'harvested_method' — "
            "free string, intentionally not bound to the frozen AttackFamily enum; "
            "spans all technique categories in a single field"
        ),
    )

    # ----- Description -----
    description: str = Field("", description="prose description of what the technique does")
    principle: str = Field(
        "",
        description="one-line design rationale (why the method works), paper-style",
    )
    steps: list[str] = Field(
        default_factory=list,
        description="ordered method steps describing how to carry out the technique",
    )

    # ----- Modality / scope -----
    modalities: list[str] = Field(
        default_factory=list,
        description='how the technique is realised, e.g. ["text"], ["image"], ["multi_turn"]',
    )

    # ----- Telemetry evidence -----
    historical_targets: list[str] = Field(
        default_factory=list,
        description=(
            "vendor/family strings this label has confirmed breaches against, "
            "e.g. ['anthropic/haiku']"
        ),
    )

    # ----- Provenance -----
    origin: str = Field(
        "arms",
        description='"arms" | "harvested" | "tier"',
    )
    tier: str = Field(
        "",
        description='"image" | "coj" | "structured" | "audio" | "planner" | ""',
    )
