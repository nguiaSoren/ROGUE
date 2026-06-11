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

import enum
from datetime import datetime, timezone
from typing import Optional, get_args

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from rogue.schemas import (
    AttackFamily,
    AttackVector,
    BrightDataProduct,
    GrammarNode,
    JudgeVerdict,
    Modality,
    RendererOrigin,
    RendererStatus,
    RetireReason,
    Severity,
    SourceType,
    StrategyStatus,
)
from rogue.schemas.remediation import MitigationType


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

    # Output-side exfiltration channel (`rogue.schemas.ExfiltrationMethod`),
    # deterministically classified from `model_response` by the judge layer.
    # NULL for non-egress breaches and non-breach verdicts. Stored as a String
    # (not a PG enum) so the label vocabulary can extend without a migration,
    # matching the `persona_used` / `refinement_type` convention on this table.
    exfil_method: Mapped[Optional[str]] = mapped_column(
        String(40), nullable=True, index=True
    )

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
    # Provenance (migration 0020): the harvest run that discovered this technique,
    # so discovery-rate / per-run-yield / time-to-graduation become measurable.
    # Nullable — pre-0020 rows stay NULL (run unknown).
    harvest_run_id: Mapped[Optional[str]] = mapped_column(
        String(40), nullable=True, index=True
    )
    # Storage-only: when the row was harvested. Powers freshness ordering and the
    # candidate-prune TTL (Phase 4); no Pydantic twin, like discovered_at's role.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        default=lambda: datetime.now(timezone.utc),
    )

    # ----- §10.9 Phase 4 lifecycle (storage-only runtime state) -----
    # Trial/breach counters. `n_attempts_total` = EVERY ladder attempt (drives the
    # least-tried selection order). `n_valid_trials` = attempts that were a real
    # semantic test (breach/no_breach only — NOT planner-refused or render_error);
    # this is what RETIREMENT measures (attack failure, not orchestration failure).
    # validity_rate = n_valid_trials / n_attempts_total is a first-class signal.
    n_attempts_total: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    n_valid_trials: Mapped[int] = mapped_column(
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


class RendererCapability(Base):
    """ORM twin of ``rogue.schemas.RendererManifest`` — a governed renderer capability.

    The executable counterpart to ``attack_strategies``: that table stores *what*
    multimodal method to use; this stores *the renderer that operationalizes it*,
    with its safety manifest + lifecycle state. A row reaches ``status='active'``
    (and thus the reproduce ladder's renderer tiers) only after the §10.9 Phase 3b
    lifecycle — and a ``synthesized`` renderer can never skip sandbox/determinism/
    approval to get there (enforced in ``reproduce/renderer_registry.py``).
    """

    __tablename__ = "renderer_capabilities"

    renderer_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    # The harvested technique this implements; NULL for pre-§10.9 static renderers.
    technique_id: Mapped[Optional[str]] = mapped_column(
        String(40),
        ForeignKey("attack_strategies.technique_id"),
        nullable=True,
        index=True,
    )
    modality: Mapped[str] = mapped_column(String(10))  # "image" | "audio"
    origin: Mapped[RendererOrigin] = mapped_column(
        SAEnum(RendererOrigin, name="renderer_origin", values_callable=_enum_values),
        index=True,
    )

    # ----- Capability contract (manifest) -----
    entrypoint: Mapped[str] = mapped_column(Text)
    artifact_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Ladder identifier(s) (image_strategy / audio-style strings) this renderer
    # contributes to the reproduce ladder tier when active (§10.9 Phase 3b-v1).
    ladder_strategies: Mapped[list[str]] = mapped_column(JSON, default=list)
    network_allowed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    deterministic: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    sandbox_policy: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    provenance_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    resource_limits: Mapped[dict] = mapped_column(JSON, default=dict)

    # ----- Lifecycle -----
    status: Mapped[RendererStatus] = mapped_column(
        SAEnum(RendererStatus, name="renderer_status", values_callable=_enum_values),
        index=True,
        default=RendererStatus.HARVESTED,
    )
    approved_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        default=lambda: datetime.now(timezone.utc),
    )


class LadderAttempt(Base):
    """Orchestration-trace telemetry — one row per escalation-ladder attempt (§10.9).

    Instruments the *ladder as a learning object*: every tier attempt (renderer /
    coj / base ARMS / harvested candidate) is logged with the scheduler policy
    (``candidate_attempt_quota``) in effect, so A/B telemetry can be segmented by
    policy and the future §10.10 break-bandit can learn renderer dominance, depth
    curves, starvation frequency, and exploration economics. Append-only; not synced
    to the dashboard (analytics-only).
    """

    __tablename__ = "ladder_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    parent_id: Mapped[str] = mapped_column(String(40), index=True)
    attempt_index: Mapped[int] = mapped_column(Integer)
    ladder_depth: Mapped[int] = mapped_column(Integer)  # tier 1..5
    entity_type: Mapped[str] = mapped_column(String(20), index=True)
    entity_id: Mapped[str] = mapped_column(String(60))
    # Soft reference to attack_strategies.technique_id (no hard FK — append-only log).
    technique_id: Mapped[Optional[str]] = mapped_column(
        String(40), nullable=True, index=True
    )
    candidate_attempt_quota: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    # MISNOMER (legacy): on winner rows this holds the winning **target_model**
    # string (e.g. "anthropic/claude-haiku-4-5"), NOT a deployment-config id —
    # ``_strategy_breaches`` returns ``config.target_model`` as ``breached_on``.
    # Kept as-is to avoid a rename migration; ``winning_model_distribution`` reads it.
    config_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    outcome: Mapped[str] = mapped_column(String(20))
    breached: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    stopped_run: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    # ----- Adaptive Technique Prioritization (vendor/family segmentation) -----
    # Denormalized vendor/family of the attempt's target model, so ladder telemetry
    # can be sliced by who-built-the-model without re-parsing config_id. NOTE: vendor
    # is the model *maker* (anthropic/openai/google/...), distinct from the routing
    # provider/backend in target_panel._PROVIDER_ROUTES (openrouter/anthropic/groq) —
    # several vendors (mistralai/google/meta-llama) all route through one backend.
    # Derived via adapters.model_specs.extract_vendor / extract_model_family.
    target_vendor: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    target_family: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    # The causal winner of this ladder (the attempt whose strategy actually broke
    # the target), distinct from ``breached`` which is true on any attempt that
    # breached — see §10.9 attribution (ranking, NOT graduation). NULL on legacy rows.
    is_winner: Mapped[Optional[bool]] = mapped_column(
        Boolean, default=False, server_default="false", nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        default=lambda: datetime.now(timezone.utc),
    )


class LadderRotationMembership(Base):
    """§10.10 Phase 2.1 — REACHABILITY telemetry: one row per (ladder × eligible
    strategy), whether or not it ran.

    ``ladder_attempts`` only logs strategies that *executed*, so a missing row is
    ambiguous — it could mean the strategy was never eligible, was starved by
    early-stop, lost the reorder, or the ladder hit budget. This table records the
    FULL eligible rotation for each ladder (one ladder = one (run_id, parent_id)
    sweep), with each strategy's ``rank``, whether it was ``eligible`` (its tier
    runnable given the configs), whether it ``executed``, and — if not — the
    ``skipped_reason`` (early_stop / budget / no_compatible_config / not_reached).

    This is what makes **reachability** measurable (executed ÷ eligible), and with
    it: starvation frequency, opportunity cost, reorder efficiency, and "high-value
    but never reached". Append-only analytics log; reconstructed post-hoc from the
    ``LadderResult`` so the ladder execution path stays untouched.
    """

    __tablename__ = "ladder_rotation_membership"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    parent_id: Mapped[str] = mapped_column(String(40), index=True)
    strategy_id: Mapped[str] = mapped_column(String(60), index=True)
    tier: Mapped[str] = mapped_column(String(20))  # image|coj|structured|audio|planner
    rank: Mapped[int] = mapped_column(Integer)  # position in the eligible rotation
    eligible: Mapped[bool] = mapped_column(Boolean, server_default="true")
    executed: Mapped[bool] = mapped_column(Boolean, server_default="false")
    outcome: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # NULL iff executed; else early_stop|budget|no_compatible_config|not_reached
    skipped_reason: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    config_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        default=lambda: datetime.now(timezone.utc),
    )


class BenchmarkRun(Base):
    """One run of the external benchmark (AdvBench/JBB) against a target, stored
    durably on Neon so the coverage-over-time series survives any single machine.

    The external yardstick ROGUE otherwise lacks: internal metrics (harvested,
    graduated, reachability, cost/breach, K) measure how the system *behaves*;
    this measures whether the *repertoire* improved against a fixed reference.
    Append-only — each row is one point on the ``date -> ASR/coverage`` timeline.

    ``mode`` is ``'repertoire'`` (the graduated repertoire applied to each goal —
    the standing regression metric) or ``'attacker'`` (IterativeAttacker peak ASR,
    a milestone-only number). ``repertoire_size`` snapshots how many graduated
    techniques were available at run time, so a rising ASR can be tied to a
    growing repertoire rather than noise. ``detail`` holds the per-family /
    per-goal breakdown so a figure can be redrawn without a re-run.
    """

    __tablename__ = "benchmark_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_label: Mapped[str] = mapped_column(String(80), index=True)
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, default=lambda: datetime.now(timezone.utc)
    )
    dataset: Mapped[str] = mapped_column(String(40), index=True)  # advbench_100|jbb_100|...
    mode: Mapped[str] = mapped_column(String(20))  # repertoire|attacker
    target_model: Mapped[str] = mapped_column(String(80))
    n_goals: Mapped[int] = mapped_column(Integer)
    n_breached: Mapped[int] = mapped_column(Integer)
    asr: Mapped[float] = mapped_column(Float)  # n_breached / n_goals
    repertoire_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Which escalation-ladder ordering policy this benchmark run used (e.g. the
    # static default vs an adaptive-priority reorder), so the ASR timeline can be
    # segmented by ladder policy. NULL on runs taken before the policy was recorded.
    ladder_order: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    duration_s: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    git_sha: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class TechniqueEmbedding(Base):
    """Technique Retrieval — one row per ladder strategy ``label`` (the retrieval key).

    Stores the embedding of a technique (ladder strategy) and its serialized
    ``TechniqueProfile`` so the retriever can vector-search the repertoire for the
    techniques most relevant to a given target. The ``label`` (ladder strategy label)
    is the primary key — the stable retrieval key; ``technique_id`` is the strategy
    ULID when one is available. Append-on-rebuild; the embedding column carries an
    ivfflat cosine ANN index.
    """

    __tablename__ = "technique_embeddings"

    label: Mapped[str] = mapped_column(String(80), primary_key=True)
    technique_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    embedding: Mapped[Optional[list[float]]] = mapped_column(
        Vector(1536), nullable=True
    )
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    modalities: Mapped[list[str]] = mapped_column(JSON, default=list)
    version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index(
            "ix_technique_embeddings_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class TargetEmbedding(Base):
    """Technique Retrieval — one row per target (the ``target_model`` string).

    Stores the embedding of a target's behavioural fingerprint and its serialized
    ``TargetFingerprint`` so the retriever can match a target to the techniques most
    likely to break it. ``target_key`` (the ``target_model`` string) is the primary
    key. The embedding column carries an ivfflat cosine ANN index.
    """

    __tablename__ = "target_embeddings"

    target_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    embedding: Mapped[Optional[list[float]]] = mapped_column(
        Vector(1536), nullable=True
    )
    fingerprint: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index(
            "ix_target_embeddings_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class RetrievalMetric(Base):
    """Technique Retrieval — shadow-mode telemetry, one row per (run × winner).

    Append-only log of how the retriever WOULD have ranked the technique that
    actually won, so retrieval quality can be measured offline before the retriever
    drives execution. ``retrieved_rank`` is the rank the retriever gave the eventual
    winner (NULL if the winner was not in the retrieved top-K); ``winner_rank`` is the
    rank the winner actually executed at; ``retrieval_hit`` is True iff the winner was
    within the retrieved top-K. No hard FKs — analytics-only.
    """

    __tablename__ = "retrieval_metrics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    parent_id: Mapped[str] = mapped_column(String(40), index=True)
    target_key: Mapped[str] = mapped_column(String(100))
    label: Mapped[str] = mapped_column(String(80))
    retrieved_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    winner_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    retrieval_hit: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    k: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        default=lambda: datetime.now(timezone.utc),
    )


class PrimitiveGrammarLabel(Base):
    """Grammar-component study — one row per (primitive × grammar node × source).

    Append-only labeling store sitting BELOW the frozen ``AttackFamily`` taxonomy:
    decomposes each ``AttackPrimitive`` into the reusable structural ``GrammarNode``s
    it exhibits (see ``rogue.schemas.GrammarNode``). One primitive carries multiple
    rows (one per assigned node); the same (primitive, node) pair may appear once per
    ``source`` (``heuristic`` | ``manual`` | ``llm``), so a human/LLM label can coexist
    with — and be compared against — the heuristic one. The ORM twin of
    ``rogue.schemas.GrammarLabel``. The ``grammar_node`` enum is the SAME Postgres enum
    type the migration creates, serialized by VALUE via ``_enum_values`` (never by
    NAME), so the storage vocabulary can never drift from the wire vocabulary.
    """

    __tablename__ = "primitive_grammar_labels"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    primitive_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("attack_primitives.primitive_id"),
        index=True,
    )
    node: Mapped[GrammarNode] = mapped_column(
        SAEnum(GrammarNode, name="grammar_node", values_callable=_enum_values),
        index=True,
    )
    # heuristic | manual | llm — how this label was produced.
    source: Mapped[str] = mapped_column(String(20), default="heuristic")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint(
            "primitive_id",
            "node",
            "source",
            name="uq_grammar_label_pid_node_source",
        ),
    )


class DemoRequest(Base):
    """A demo-request lead captured from the marketing site (``/api/demo-request``).

    Append-only lead-capture store — no FK into the threat-DB graph, deliberately
    standalone. Purely additive (§13-safe). The wire body lives in
    ``rogue.api.demo.DemoRequestBody``; this is its storage twin.
    """

    __tablename__ = "demo_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    company: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    deployment_type: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )


class NewsletterSubscriber(Base):
    """A newsletter subscriber captured from the marketing site (``/api/newsletter``).

    Append-only subscription store — no FK into the threat-DB graph, deliberately
    standalone. Purely additive (§13-safe). ``email`` is unique so a re-subscribe
    is idempotent (the router returns the existing row's id). The wire body lives
    in ``rogue.api.newsletter.NewsletterBody``; this is its storage twin.
    """

    __tablename__ = "newsletter_subscribers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    source: Mapped[Optional[str]] = mapped_column(String(60), nullable=True, default="site")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )


class Mitigation(Base):
    """Storage twin of ``rogue.schemas.remediation.RemediationResult`` — one
    persisted measured-remediation outcome (Surface 1b, build-05 §8).

    The Pydantic side splits a remediation into a :class:`~rogue.schemas.remediation.MitigationCandidate`
    (the generated artifact) + its re-test evidence (:class:`~rogue.schemas.remediation.RemediationResult`
    fields + an :class:`~rogue.schemas.remediation.OverBlockCheck`). This single row
    flattens the candidate's identity/artifact + the result's rates into one record.
    Per the CLAUDE.md alias convention, a caller that needs BOTH the ORM and the
    Pydantic class imports this as ``from rogue.db.models import Mitigation as MitigationORM``
    (the Pydantic side stays ``RemediationResult`` / ``MitigationCandidate``).

    ``breach_ref`` is a SOFT reference to the area-04 ``RuleVerdict`` / ``BreachResult``
    being remediated (no hard FK — a remediation may outlive the breach row, and the
    ref can point at a rule_id rather than a breach_id). ``rejected_candidates`` stores
    small dicts/refs (candidate_id + type + reason), NOT full artifact blobs.
    ``verified_by`` mirrors the Pydantic ``Literal['rescan', 'by_construction_out_of_band']``
    — kept as a CHECK-free ``String(40)`` so adding a verification mode is a one-line edit.
    The rate columns are nullable because ``by_construction_out_of_band`` results have no
    measured breach-rate delta (the fix lives outside the prompt/scope, §6.note).
    """

    __tablename__ = "mitigations"

    # ----- Identity -----
    mitigation_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    breach_ref: Mapped[str] = mapped_column(String(40), index=True)

    # ----- The candidate (artifact + provenance) -----
    mitigation_type: Mapped[MitigationType] = mapped_column(
        SAEnum(MitigationType, name="mitigation_type", values_callable=_enum_values),
        index=True,
    )
    artifact: Mapped[str] = mapped_column(Text)
    generated_by: Mapped[str] = mapped_column(String(120))

    # ----- Re-test evidence -----
    accepted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # 'rescan' | 'by_construction_out_of_band' (Pydantic Literal mirror).
    verified_by: Mapped[str] = mapped_column(String(40), default="rescan")
    # Rates are NULL for by_construction_out_of_band (no measured delta).
    pre_breach_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    post_breach_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    over_block_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ci_low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ci_high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Small dicts/refs for the candidates that were tried and rejected — NOT
    # full artifact blobs. Store {candidate_id, mitigation_type, reason} shapes.
    rejected_candidates: Mapped[list] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )


# --------------------------------------------------------------------------- #
# Surface 3 — skill pool (build-area 08, Section A; migration 0037; ADR-0009)
#
# Storage-only lifecycle enums (no Pydantic wire twin — like BanditState, the
# skill pool is runtime memory-pool state, not a harvested wire object). Defined
# here and stored as native PostgreSQL enums via the same VALUE-serializing
# convention (``values_callable=_enum_values``) so storage can't drift from code.
# --------------------------------------------------------------------------- #


class SkillStatus(str, enum.Enum):
    """Lifecycle of a shared skill — admitted to ``active`` only by the
    verified-promotion gate (net-effect CI-lower-bound > 0); demoted to
    ``quarantined`` on a net-negative re-check; ``retired`` is terminal."""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    QUARANTINED = "quarantined"
    RETIRED = "retired"


class SkillSourceKind(str, enum.Enum):
    """Where a candidate skill came from (SoK ingest source)."""

    CORRECTION = "correction"
    TRAJECTORY = "trajectory"
    DISTILLED = "distilled"


class SkillEdgeType(str, enum.Enum):
    """Combination-risk graph edge kind (ADR-0009 adjacency)."""

    CO_INVOCATION = "co_invocation"
    COMPOSITION = "composition"
    SEMANTIC = "semantic"


class SkillVerificationKind(str, enum.Enum):
    """Which verification produced a ``skill_verifications`` audit row."""

    PROMOTION = "promotion"
    REVERIFICATION = "reverification"
    LEAKAGE = "leakage"
    COMBINATION = "combination"


class SkillVerificationVerdict(str, enum.Enum):
    """Pass/fail outcome of a verification."""

    PASS = "pass"
    FAIL = "fail"


class Skill(Base):
    """One shared skill in the assured pool (Surface 3, ADR-0009).

    Org/cohort/trust-domain-scoped Markdown skill carrying a 1536-d pgvector
    ``embedding`` (for dedup/retrieval — mirrors ``AttackPrimitive.payload_embedding``,
    same ivfflat cosine ANN index). ``applicability_condition`` is the SoK ``C``
    precondition (the cheap applicability pre-filter reads it). A skill reaches
    ``status='active'`` ONLY via the verified-promotion gate; popularity is
    explicitly NOT a field here (>90% of high-popularity skills failed audit —
    popularity is never a safety signal).
    """

    __tablename__ = "skills"

    skill_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.org_id"), nullable=False
    )
    cohort_id: Mapped[str] = mapped_column(String(64))
    trust_domain: Mapped[str] = mapped_column(String(64))
    skill_md: Mapped[str] = mapped_column(Text)

    # 1536-d to match text-embedding-3-small, cosine ops — mirrors attack_primitives.
    embedding: Mapped[Optional[list[float]]] = mapped_column(Vector(1536), nullable=True)

    status: Mapped[SkillStatus] = mapped_column(
        SAEnum(SkillStatus, name="skill_status", values_callable=_enum_values),
        default=SkillStatus.CANDIDATE,
        server_default="candidate",
    )
    applicability_condition: Mapped[dict] = mapped_column(JSON, default=dict)
    source_kind: Mapped[SkillSourceKind] = mapped_column(
        SAEnum(SkillSourceKind, name="skill_source_kind", values_callable=_enum_values),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    promoted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "ix_skills_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_skills_org_cohort_status", "org_id", "cohort_id", "status"),
    )


class SkillEdge(Base):
    """One edge of the combination-risk graph (ADR-0009: Postgres adjacency +
    recursive CTE, NOT a graph DB).

    Two benign skills can compose into malicious behavior; this table is the
    adjacency the ``WITH RECURSIVE`` neighborhood / connected-component queries
    traverse. ``risk_score`` + ``evidence_breach_id`` are written when a
    co-invoked set is judged to *produce* harmful behavior (composition breach).
    PK is the triple ``(skill_a, skill_b, edge_type)``; BOTH endpoints are
    indexed so neighborhood traversal can start from either node.
    """

    __tablename__ = "skill_edges"

    skill_a: Mapped[str] = mapped_column(
        String(64), ForeignKey("skills.skill_id"), primary_key=True
    )
    skill_b: Mapped[str] = mapped_column(
        String(64), ForeignKey("skills.skill_id"), primary_key=True
    )
    edge_type: Mapped[SkillEdgeType] = mapped_column(
        SAEnum(SkillEdgeType, name="skill_edge_type", values_callable=_enum_values),
        primary_key=True,
    )
    risk_score: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    evidence_breach_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_skill_edges_skill_a", "skill_a"),
        Index("ix_skill_edges_skill_b", "skill_b"),
    )


class SkillVerification(Base):
    """One verification outcome row — the SQL-queryable audit spine the
    attestation reads (ADR-0009).

    Records each verified-promotion / re-verification / leakage / combination
    decision with its measured ``net_effect = repairs - regressions`` on the
    held-out set + bootstrap ``ci_low``/``ci_high``, the ``leakage_rate`` (for
    ``kind='leakage'``), and provenance to the calibrated judge
    (``judge_calibration_ref``) + the scan run (``scan_run_id``). ``verdict``
    is the pass/fail the gate emitted.
    """

    __tablename__ = "skill_verifications"

    verification_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    skill_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("skills.skill_id"), index=True
    )
    cohort_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[SkillVerificationKind] = mapped_column(
        SAEnum(
            SkillVerificationKind,
            name="skill_verification_kind",
            values_callable=_enum_values,
        ),
    )
    net_effect: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    repairs: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    regressions: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ci_low: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    ci_high: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    leakage_rate: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    held_out_n: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    judge_calibration_ref: Mapped[Optional[str]] = mapped_column(
        String(120), nullable=True
    )
    scan_run_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    verdict: Mapped[SkillVerificationVerdict] = mapped_column(
        SAEnum(
            SkillVerificationVerdict,
            name="skill_verification_verdict",
            values_callable=_enum_values,
        ),
    )


__all__ = [
    "Base",
    "DeploymentConfig",
    "AttackPrimitive",
    "AttackStrategy",
    "RendererCapability",
    "LadderAttempt",
    "LadderRotationMembership",
    "SourceProvenance",
    "BreachResult",
    "PairRefinementStep",
    "BrightDataCostLog",
    "BanditState",
    "FetchCache",
    "PrimitiveImage",
    "BenchmarkRun",
    "TechniqueEmbedding",
    "TargetEmbedding",
    "RetrievalMetric",
    "PrimitiveGrammarLabel",
    "DemoRequest",
    "NewsletterSubscriber",
    "Mitigation",
    "Skill",
    "SkillEdge",
    "SkillVerification",
]
