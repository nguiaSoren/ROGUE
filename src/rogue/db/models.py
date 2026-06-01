"""SQLAlchemy ORM models mirroring the Pydantic schemas in ``rogue.schemas``.

Pydantic schemas in ``src/rogue/schemas/`` define the WIRE format. These ORM
classes define the STORAGE format. They differ in three load-bearing ways:
  1. ORM rows carry a pgvector ``payload_embedding`` column (off-the-wire).
  2. Foreign keys are explicit (Pydantic uses string ids); relationships
     give read paths typed access to ``.sources`` / ``.breaches`` / etc.
  3. Enums are stored as native PostgreSQL enums via the same Python enum
     classes imported from ``rogue.schemas`` — never duplicated here, so the
     wire vocabulary and the storage vocabulary can never drift.

See ROGUE_PLAN.md §A.5 and §8.3 for the canonical spec.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, get_args

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from rogue.schemas import (
    AttackFamily,
    AttackVector,
    BrightDataProduct,
    JudgeVerdict,
    Modality,
    RetireReason,
    Severity,
    SourceType,
    StrategyStatus,
)


class Base(DeclarativeBase):
    """Declarative base for every ROGUE persistence model."""


# --------------------------------------------------------------------------- #
# Helpers — derive CHECK constraint vocabularies from the Pydantic Literals
# so the storage vocabulary can never drift from the wire vocabulary.
# --------------------------------------------------------------------------- #

_SOURCE_TYPE_VALUES: tuple[str, ...] = get_args(SourceType)
_BRIGHT_DATA_PRODUCT_VALUES: tuple[str, ...] = get_args(BrightDataProduct)


def _quoted_csv(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _enum_values(enum_cls: type) -> list[str]:
    """Return enum *values* (not names) for use with ``SAEnum(values_callable=)``.

    SQLAlchemy's default ``Enum(PythonEnum)`` column serializes by enum NAME
    (uppercase ``LANGUAGE_SWITCHING``), but the 0001 alembic migration creates
    the Postgres enum types from the Pydantic VALUES (lowercase
    ``language_switching``). Without this callable, every ORM insert into an
    enum column raises ``InvalidTextRepresentation: invalid input value for
    enum``. Surfaced 2026-05-24 by the §8.5 seed script; root-cause fix lives
    here so every future ORM writer is correct by construction.
    """
    return [m.value for m in enum_cls]


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #


class DeploymentConfig(Base):
    """ORM mirror of ``rogue.schemas.DeploymentConfig`` — the unit under test."""

    __tablename__ = "deployment_configs"

    config_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(100))
    target_model: Mapped[str] = mapped_column(String(100), index=True)
    system_prompt: Mapped[str] = mapped_column(Text)
    declared_tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    forbidden_topics: Mapped[list[str]] = mapped_column(JSON, default=list)

    breaches: Mapped[list["BreachResult"]] = relationship(
        back_populates="deployment_config",
    )


class AttackPrimitive(Base):
    """ORM mirror of ``rogue.schemas.AttackPrimitive`` — the load-bearing row."""

    __tablename__ = "attack_primitives"

    # ----- Identity -----
    primitive_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    cluster_id: Mapped[Optional[str]] = mapped_column(
        String(40), index=True, nullable=True
    )
    canonical: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # ----- Classification -----
    family: Mapped[AttackFamily] = mapped_column(
        SAEnum(AttackFamily, name="attack_family", values_callable=_enum_values),
        index=True,
    )
    secondary_families: Mapped[list[str]] = mapped_column(JSON, default=list)
    vector: Mapped[AttackVector] = mapped_column(
        SAEnum(AttackVector, name="attack_vector", values_callable=_enum_values),
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200))
    short_description: Mapped[str] = mapped_column(Text)

    # ----- The payload -----
    payload_template: Mapped[str] = mapped_column(Text)
    payload_slots: Mapped[dict] = mapped_column(JSON, default=dict)
    multi_turn_sequence: Mapped[Optional[list[str]]] = mapped_column(
        JSON, nullable=True
    )
    # §10.7 multi-turn escalation per-turn slot validation. Keys are turn
    # indices as strings ('0', '1', '2', ...), values are slot names required
    # in that turn's rendered output. NULL on every pre-§10.7 row.
    slot_requirements: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True
    )

    # ----- §10.7 augmentation chain -----
    # True iff this primitive was produced by an augmentation step
    # (escalation_planner, syntactic_mutation, ...) rather than harvested
    # from the open web. Default False keeps the existing harvested corpus
    # well-typed without a backfill.
    synthesized: Mapped[bool] = mapped_column(
        Boolean, default=False, index=True, server_default="false"
    )
    # When synthesized=True, points at the harvested parent. Cascade is NOT
    # set — synthesized rows survive parent deletion (the chain is for
    # provenance; nothing reads it transactionally).
    derived_from_primitive_id: Mapped[Optional[str]] = mapped_column(
        String(40),
        ForeignKey("attack_primitives.primitive_id"),
        nullable=True,
        index=True,
    )

    # ----- Source claims -----
    target_models_claimed: Mapped[list[str]] = mapped_column(JSON, default=list)
    claimed_success_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    claimed_first_seen: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ----- Quality / requirements -----
    reproducibility_score: Mapped[int] = mapped_column(Integer)
    requires_multi_turn: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_system_prompt_access: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    requires_multimodal: Mapped[bool] = mapped_column(Boolean, default=False)

    # ----- Timestamps + severity -----
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    base_severity: Mapped[Severity] = mapped_column(
        SAEnum(Severity, name="severity", values_callable=_enum_values),
        index=True,
    )
    severity_rationale: Mapped[str] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ----- pgvector: 1536-d to match text-embedding-3-small, cosine ops -----
    payload_embedding: Mapped[Optional[list[float]]] = mapped_column(
        Vector(1536), nullable=True
    )

    # ----- Relationships -----
    sources: Mapped[list["SourceProvenance"]] = relationship(
        back_populates="primitive", cascade="all, delete-orphan"
    )
    breaches: Mapped[list["BreachResult"]] = relationship(back_populates="primitive")
    # DB-stored image bytes (one-to-one), for the deployed drawer/cell view.
    image: Mapped[Optional["PrimitiveImage"]] = relationship(
        cascade="all, delete-orphan", uselist=False
    )

    # Composite / vector indices. Per-column scalar indices are declared with
    # ``index=True`` above; this block adds the pgvector ANN index and gives the
    # composite (family, vector) lookup the discovery view uses.
    __table_args__ = (
        Index(
            "ix_attack_primitives_payload_embedding",
            "payload_embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"payload_embedding": "vector_cosine_ops"},
        ),
        Index("ix_attack_primitives_family_vector", "family", "vector"),
    )


class SourceProvenance(Base):
    """ORM mirror of ``rogue.schemas.SourceProvenance`` — one fetched document."""

    __tablename__ = "source_provenances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    primitive_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("attack_primitives.primitive_id", ondelete="CASCADE"),
        index=True,
    )
    url: Mapped[str] = mapped_column(Text)
    # source_type / bright_data_product are Literals on the Pydantic side, not
    # Enums — we keep them as CHECK-constrained strings so adding a new literal
    # is a one-line schema edit instead of an Alembic enum migration.
    source_type: Mapped[str] = mapped_column(String(40), index=True)
    author: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    archive_hash: Mapped[str] = mapped_column(String(80))
    bright_data_product: Mapped[str] = mapped_column(String(40), index=True)

    primitive: Mapped["AttackPrimitive"] = relationship(back_populates="sources")

    __table_args__ = (
        CheckConstraint(
            f"source_type IN ({_quoted_csv(_SOURCE_TYPE_VALUES)})",
            name="ck_source_provenances_source_type",
        ),
        CheckConstraint(
            f"bright_data_product IN ({_quoted_csv(_BRIGHT_DATA_PRODUCT_VALUES)})",
            name="ck_source_provenances_bright_data_product",
        ),
    )


class BreachResult(Base):
    """ORM mirror of ``rogue.schemas.BreachResult`` — one (primitive × config × trial) verdict."""

    __tablename__ = "breach_results"

    breach_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    primitive_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("attack_primitives.primitive_id"),
        index=True,
    )
    deployment_config_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("deployment_configs.config_id"),
        index=True,
    )

    trial_index: Mapped[int] = mapped_column(Integer)
    temperature: Mapped[float] = mapped_column(Float)

    rendered_payload: Mapped[str] = mapped_column(Text)
    model_response: Mapped[str] = mapped_column(Text)

    verdict: Mapped[JudgeVerdict] = mapped_column(
        SAEnum(JudgeVerdict, name="judge_verdict", values_callable=_enum_values),
        index=True,
    )
    judge_rationale: Mapped[str] = mapped_column(Text)
    judge_confidence: Mapped[float] = mapped_column(Float)

    latency_ms: Mapped[int] = mapped_column(Integer)
    tokens_in: Mapped[int] = mapped_column(Integer)
    tokens_out: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[float] = mapped_column(Float)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    # §10.7 persona augmentation A/B: PAP persuasion technique name applied
    # by `reproduce.persona_wrap.PersonaWrapper`, or NULL for the unwrapped
    # baseline. Suffix `__refused` indicates the wrap LLM declined and we
    # fell back to the original payload (preserved as a separate value so
    # the dashboard surfaces refusal rate distinctly).
    persona_used: Mapped[Optional[str]] = mapped_column(
        String(60), nullable=True, index=False
    )

    # §10.7 full PAIR build: iteration index at which this cell FIRST
    # breached (verdict ∈ {partial_breach, full_breach}). NULL when no PAIR
    # refinement was run for this cell (baseline corpus) OR when PAIR ran
    # but never broke through. Drives the dashboard "stubbornness" tile
    # (avg iters to breach per config).
    pair_iters_to_breach: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
    )
    # Sum of attacker_cost_usd across all RefinementSteps for this cell.
    # NULL when no PAIR refinement was run.
    pair_attacker_total_cost_usd: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
    )

    primitive: Mapped["AttackPrimitive"] = relationship(back_populates="breaches")
    deployment_config: Mapped["DeploymentConfig"] = relationship(
        back_populates="breaches"
    )


class PairRefinementStep(Base):
    """ORM mirror of one §10.7 PAIR iteration. Linked to BreachResult via
    ``breach_id`` FK — cascade delete so removing a cell removes its chain.

    The dashboard's chain-replay query (``ORDER BY iter_index ASC WHERE
    breach_id = ?``) is index-served by ``ix_pair_refinement_steps_breach_id_iter_index``.
    """

    __tablename__ = "pair_refinement_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    breach_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("breach_results.breach_id", ondelete="CASCADE"),
        index=False,  # composite index below covers this
    )
    iter_index: Mapped[int] = mapped_column(Integer)
    # refinement_type kept as String(40) (not enum) so the taxonomy can be
    # extended without a migration. Current vocabulary:
    # roleplaying / logical_appeal / authority_endorsement / obfuscation /
    # multi_turn_escalation / syntactic_mutation
    refinement_type: Mapped[str] = mapped_column(String(40))
    attacker_model: Mapped[str] = mapped_column(String(80))
    proposed_prompt: Mapped[str] = mapped_column(Text)
    improvement: Mapped[str] = mapped_column(Text)
    target_response: Mapped[str] = mapped_column(Text)
    verdict: Mapped[str] = mapped_column(String(40))
    score: Mapped[int] = mapped_column(Integer)
    attacker_cost_usd: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "ix_pair_refinement_steps_breach_id_iter_index",
            "breach_id", "iter_index",
        ),
        CheckConstraint(
            "iter_index >= 0",
            name="ck_pair_refinement_steps_iter_index_nonneg",
        ),
        CheckConstraint(
            "score >= 1 AND score <= 10",
            name="ck_pair_refinement_steps_score_range",
        ),
    )


class BrightDataCostLog(Base):
    """Per-call cost ledger for Bright Data API usage.

    Task spec (§8.3 cost-tracking) requires ``(id, product, units, cost_usd,
    ran_at, notes)``; we follow that surface here. The §A.5 snippet listed a
    slightly different shape (``url``, ``success``, ``latency_ms``,
    ``estimated_cost_usd``) — the task instructions take precedence.
    """

    __tablename__ = "bright_data_cost_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product: Mapped[str] = mapped_column(String(40), index=True)
    units: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[float] = mapped_column(Float)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            f"product IN ({_quoted_csv(_BRIGHT_DATA_PRODUCT_VALUES)})",
            name="ck_bright_data_cost_log_product",
        ),
    )


class BanditState(Base):
    """Single-row store of the DiscoveryAgent ε-greedy bandit state — the same
    dict persisted to ``data/discovery_bandit.json``, mirrored into the DB so the
    ``/api/bandit/stats`` widget is live from the database (updates on each harvest,
    no redeploy). ``id`` is pinned to 1; the harvest upserts that row."""

    __tablename__ = "bandit_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class FetchCache(Base):
    """Persistent cross-run URL skip-cache (§11.7). One row per URL ROGUE has
    ever fetched — including zero-yield ones — so a daily harvest skips
    re-crawling / re-extracting unchanged content.

    ``version_token`` is a source-supplied freshness signal (git blob SHA,
    arxiv updated-date, reddit ``created:num_comments``, HTTP ETag) compared
    BEFORE the Bright Data fetch (Tier B). ``content_hash`` mirrors
    ``RawDocument.archive_hash`` and is compared BEFORE LLM extraction (Tier A,
    universal). ``n_primitives_yielded`` records yield so a future bandit
    reward can down-weight low-novelty sources."""

    __tablename__ = "fetch_cache"

    url: Mapped[str] = mapped_column(Text, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(40), index=True)
    version_token: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    last_fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    last_status: Mapped[str] = mapped_column(String(20), default="ok")
    n_primitives_yielded: Mapped[int] = mapped_column(Integer, default=0)


class PrimitiveImage(Base):
    """The real image bytes for one multimodal/carrier primitive, stored IN the
    DB so they travel to Neon with the data sync and render on the DEPLOYED site.

    The image files live on local disk under ``data/media_cache/`` (§11.8
    per-attack ``{id}/carrier.*`` carriers + Feature-A ``ingested/`` payloads),
    but that disk is local-only — the deployed Render API can't read it. This
    one-row-per-primitive table holds the bytes + media type so the image route
    serves them anywhere. Populated by ``rogue.db.image_cache.cache_images_to_db``
    from the on-disk cache; synced to Neon by ``rogue.db.neon_sync``.
    """

    __tablename__ = "primitive_images"

    primitive_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("attack_primitives.primitive_id", ondelete="CASCADE"),
        primary_key=True,
    )
    media_type: Mapped[str] = mapped_column(String(40))  # e.g. "image/png"
    image_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    # Where the bytes came from — "carrier" (§11.8) or "ingested" (Feature A).
    source: Mapped[str] = mapped_column(String(20), default="carrier")
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class AttackStrategy(Base):
    """ORM twin of ``rogue.schemas.TechniqueSpec`` — one reusable attack *technique*.

    Parallel to ``attack_primitives`` (which stores payload *instances*); this table
    stores harvested *methods* and is the single source the planner reads strategies
    from (§10.9 risk-note 3), interchangeable with the hand-written
    ``reproduce/arms_strategies.py`` entries via the shared ``directive`` field.

    Lifecycle in ``status``: ``candidate`` (harvested, untrusted) → ``active``
    (graduated: actually breached in a reproduction run, Phase 4 gate) /
    ``needs_implementation`` (renderer technique whose code a human/sandbox must write).
    See ROGUE_PLAN.md §10.9.
    """

    __tablename__ = "attack_strategies"

    # ----- Identity -----
    technique_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))

    # ----- Classification -----
    modality: Mapped[Modality] = mapped_column(
        SAEnum(Modality, name="attack_strategy_modality", values_callable=_enum_values),
        index=True,
    )

    # ----- The method -----
    principle: Mapped[str] = mapped_column(Text)
    steps: Mapped[list[str]] = mapped_column(JSON, default=list)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    example: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ----- Realization -----
    # The operational prompt fragment the EscalationPlanner injects. NULL until a
    # text/multi_turn technique is auto-integrated (Phase 3a) or a renderer is built.
    directive: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ----- Provenance -----
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ----- Lifecycle -----
    status: Mapped[StrategyStatus] = mapped_column(
        SAEnum(
            StrategyStatus, name="attack_strategy_status", values_callable=_enum_values
        ),
        index=True,
        default=StrategyStatus.CANDIDATE,
    )
    claimed_first_seen: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Storage-only: when the row was harvested. Powers freshness ordering and the
    # candidate-prune TTL (Phase 4); no Pydantic twin, like discovered_at's role.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        default=lambda: datetime.now(timezone.utc),
    )

    # ----- §10.9 Phase 4 lifecycle (storage-only runtime state) -----
    # Trial/breach counters drive graduation (winner-only), the least-tried
    # selection order, and the retirement rules. breach_rate is derived
    # (n_breaches / n_times_tried), never stored.
    n_times_tried: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    n_breaches: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Weak signal: tried in a ladder that breached on ANOTHER strategy (not the
    # causal winner). Used for ranking, NOT graduation — see §10.9 attribution.
    supporting_breach_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    # Graduation audit — set once, on the first winning breach.
    first_breach_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    first_breach_config_id: Mapped[Optional[str]] = mapped_column(
        String(40), nullable=True
    )
    # Recency — power the least-tried selection tiebreak + resurrection latency.
    last_tried_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_breached_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Retirement (soft, reversible). resurrection_latency = last_breached_at -
    # retired_at is derived, not stored.
    retired_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retire_reason: Mapped[Optional[RetireReason]] = mapped_column(
        SAEnum(RetireReason, name="strategy_retire_reason", values_callable=_enum_values),
        nullable=True,
    )
    resurrected: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    # Future-proofs the Phase 4b sweep scheduler (daily active / weekly retired
    # sample / on-new-model retry). NULL until a sweep policy stamps it.
    next_eligible_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


__all__ = [
    "Base",
    "DeploymentConfig",
    "AttackPrimitive",
    "AttackStrategy",
    "SourceProvenance",
    "BreachResult",
    "PairRefinementStep",
    "BrightDataCostLog",
    "BanditState",
    "FetchCache",
    "PrimitiveImage",
]
