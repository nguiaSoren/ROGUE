"""Platform ORM tables (multi-tenancy + scan orchestration). Registered on the shared `Base`.

New tables only — the existing research tables in `rogue.db.models` are untouched. Created by
migration `0022_platform_tables`. Importing this module registers the tables on `Base.metadata`;
it opens no connection. Per the design docs (`docs/platform/tenancy/`), the `customer_id="acme"`
single-tenant seam is superseded by `org_id` here.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from rogue.attestation.chain import ENTRY_TYPES
from rogue.db.models import Base

# The CHECK-constraint vocabulary for `attestation_entries.entry_type` is derived
# from the one source of truth in `attestation.chain` (no duplication, per the
# CLAUDE.md schema convention) — both the ORM CHECK and migration 0031 read it.
_ENTRY_TYPE_CHECK = "entry_type IN (" + ", ".join(f"'{t}'" for t in ENTRY_TYPES) + ")"


class Organization(Base):
    __tablename__ = "organizations"
    org_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class User(Base):
    __tablename__ = "users"
    user_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_membership_org_user"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.org_id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # owner|admin|member|viewer


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("org_id", "slug", name="uq_project_org_slug"),)
    project_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.org_id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApiKey(Base):
    __tablename__ = "api_keys"
    key_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.org_id"), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.project_id"), nullable=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # sha256 hex
    prefix: Mapped[str] = mapped_column(String(24))  # rk_live_xxxx (display only)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ScanRun(Base):
    """Durable scan record (the persisted `ScanRecord`). Modeled on `BenchmarkRun`."""

    __tablename__ = "scan_runs"
    scan_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.org_id"), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.project_id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    n_tests: Mapped[int] = mapped_column(Integer, default=0)
    n_completed: Mapped[int] = mapped_column(Integer, default=0)
    n_breaches: Mapped[int] = mapped_column(Integer, default=0)
    top_attack: Mapped[str | None] = mapped_column(String(100), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    report_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    target: Mapped[dict] = mapped_column(JSON, default=dict)  # redacted snapshot, no raw secret
    pack: Mapped[str] = mapped_column(String(40), default="default")
    spec: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ScanJob(Base):
    """Durable dispatch record (the queue's source of truth). Postgres SKIP-LOCKED lease."""

    __tablename__ = "scan_jobs"
    job_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.scan_id"), index=True)
    org_id: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)  # queued|leased|running|done|failed|canceled
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    locked_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Report(Base):
    __tablename__ = "reports"
    report_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.scan_id"), index=True)
    format: Mapped[str] = mapped_column(String(16), default="json")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Secret(Base):
    """Encrypted tenant secret (a customer's raw target credential). The queue/record reference it by
    `secret_id` (`secref_…`); only Fernet ciphertext is stored here — never plaintext."""

    __tablename__ = "secrets"
    secret_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(40), index=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Integration(Base):
    """A per-org stored integration (Slack / Jira). Holds non-secret `config` inline + a `secret_ref`
    handle into the `secrets` table for the credential (webhook URL / API token). MCP tools reference it
    by `name` so an agent never handles the raw secret."""

    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_integration_org_name"),)
    integration_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # slack | jira
    name: Mapped[str] = mapped_column(String(80))
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # non-secret (e.g. jira base_url/project/email)
    secret_ref: Mapped[str | None] = mapped_column(String(48), nullable=True)  # secref_ → secrets table
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SlackRegisteredAgent(Base):
    """A per-org self-registered Slack agent target — the customer's own consented agent endpoint.

    Stored as a lightweight row separate from `integrations` (different cardinality/lifecycle:
    one org runs many short-lived agents; we do NOT overload that table). Carries enough to
    faithfully reconstruct the target's `DeploymentConfig` (model + system prompt + declared
    tools + forbidden topics).

    `system_prompt_ref` holds EITHER the inline system prompt OR a `secref_…` handle into the
    `secrets` table: by convention (no extra column), a value starting with `"secref_"` is a
    SecretStore handle to resolve; otherwise it is the literal prompt. The sandbox binding
    (`sandbox_channel_id`) is mandatory / fail-closed — kept non-nullable here, enforced in app code.
    """

    __tablename__ = "slack_registered_agents"
    __table_args__ = (UniqueConstraint("org_id", "agent_name", name="uq_slack_agent_org_name"),)
    agent_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(40), index=True)
    agent_name: Mapped[str] = mapped_column(String(80))
    workspace: Mapped[str] = mapped_column(String(120))
    base_url: Mapped[str] = mapped_column(String(500))
    model: Mapped[str] = mapped_column(String(100))
    system_prompt_ref: Mapped[str] = mapped_column(Text)  # inline prompt OR secref_ → secrets table
    declared_tools: Mapped[list] = mapped_column(JSON, default=list)
    forbidden_topics: Mapped[list] = mapped_column(JSON, default=list)
    sandbox_channel_id: Mapped[str] = mapped_column(String(64))  # NOT NULL — sandbox binding mandatory
    security_channel_id: Mapped[str] = mapped_column(String(64))
    rule_pack_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    target_api_key_ref: Mapped[str | None] = mapped_column(String(48), nullable=True)  # SecretStore handle to the target endpoint's bearer key — None for open/keyless endpoints
    client_policy: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # cached serialized ClientPolicy (governance.decompose_policy) — None until first derived
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SnapshotCapture(Base):
    """Content-addressed capture store — byte-faithful evidence for reproducibility (ADR-0012-adjacent).

    Each row holds the raw captured bytes of an artifact (a transcript, a target response, a JSON
    payload) keyed by its content address `snapshot_ref` (`"sha256:" + hexdigest`). Dedup is
    per-tenant: the same content within an org maps to the same `snapshot_ref`, so a re-capture is
    an idempotent write (the `uq_snapshot_org_ref` constraint collapses duplicates). The sandbox-scan
    post (§4) links to a `snapshot_ref` instead of inlining transcripts, keeping the post-row small
    while the heavy bytes live here once per (org, content).
    """

    __tablename__ = "snapshot_captures"
    __table_args__ = (
        UniqueConstraint("org_id", "snapshot_ref", name="uq_snapshot_org_ref"),
        Index("ix_snapshot_captures_org_ref", "org_id", "snapshot_ref"),
    )
    id: Mapped[str] = mapped_column(String(48), primary_key=True)  # surrogate, _new_id("snap")
    org_id: Mapped[str] = mapped_column(String(40), index=True)
    snapshot_ref: Mapped[str] = mapped_column(String(80))  # content address: "sha256:" + hexdigest
    content_type: Mapped[str] = mapped_column(String(40))  # transcript | response | json
    content: Mapped[bytes] = mapped_column(LargeBinary)  # byte-faithful captured bytes
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AttestationEntry(Base):
    """One line in an org's append-only, hash-chained attestation record (v2 §2.5 / ADR-0012).

    The tamper-evident, reproducible, queryable record every surface emits. ONE chain per
    `org_id` (per-tenant system-of-record, ADR-0006): `seq` is a per-org monotonic integer
    (genesis is seq 0), and `entry_hash = sha256(prev_hash || canonical_json(payload))` links
    each entry to the prior one's `entry_hash` (genesis links to `GENESIS_PREV` = 64 zeros).

    Append-only is *enforced*, not just intended: migration 0031 installs a Postgres
    BEFORE UPDATE OR DELETE trigger that RAISEs. A correction is a NEW entry, never an edit.
    Captures are pointers (`reproducibility_ref` → scan_id/breach_id/report_id), not blobs.
    `corpus_as_of` is NOT NULL — the "as of date D" framing is structural, not cosmetic.
    `ground_truth_ref` (ADR-0011) is the independent label this verdict is scored against; it
    is nullable because harm Phase-0 entries have no per-rule independent label yet.
    """

    __tablename__ = "attestation_entries"
    __table_args__ = (
        UniqueConstraint("org_id", "seq", name="uq_attestation_org_seq"),
        UniqueConstraint("org_id", "entry_hash", name="uq_attestation_org_entry_hash"),
        CheckConstraint(_ENTRY_TYPE_CHECK, name="ck_attestation_entry_type"),
        Index("ix_attestation_org_seq", "org_id", "seq"),
        Index("ix_attestation_org_entry_type", "org_id", "entry_type"),
        Index("ix_attestation_org_reproducibility_ref", "org_id", "reproducibility_ref"),
    )

    entry_id: Mapped[str] = mapped_column(String(48), primary_key=True)  # att_…
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.org_id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)  # per-org monotonic; genesis is 0
    entry_type: Mapped[str] = mapped_column(String(20))  # genesis|scan|decision|mitigation|promotion
    prev_hash: Mapped[str] = mapped_column(String(64))  # prior entry_hash (GENESIS_PREV at genesis)
    entry_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # structured decision-rationale (redacted)
    reproducibility_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ground_truth_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)  # ADR-0011
    corpus_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # NOT NULL — the "as of date D"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GatedCase(Base):
    """One entry in the answer-key corpus — the shared, designed-label key (Surface 2, §2/§5).

    Global (NOT org-scoped): the designed labels are the fixed key every reviewer's decisions are
    scored against, so the corpus is the same across tenants. `designed_label` is the intended
    verdict (APPROVE|DENY); `label_provenance` records how that label was set; `source_refs` points
    at the originating exemplars (incl. negative exemplars, kept per §5). Decisions live in
    `gated_decisions`, captured per (org) review session in `review_sessions`.
    """

    __tablename__ = "gated_cases"
    case_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_class: Mapped[str] = mapped_column(String(40))
    facts: Mapped[dict] = mapped_column(JSON, default=dict)
    designed_label: Mapped[str] = mapped_column(String(10))  # APPROVE|DENY
    designed_rationale: Mapped[str] = mapped_column(Text)
    label_provenance: Mapped[str] = mapped_column(String(40))
    source_refs: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReviewSession(Base):
    """A reviewer's working session over one gated case (org-scoped, ADR-0006 tenancy).

    Links a tenant reviewer (`reviewer_user_id`) to a global `gated_cases` row for the duration of a
    review. `status` walks assigned → decided (or expires). The captured decision lands in
    `gated_decisions`, referencing this session.
    """

    __tablename__ = "review_sessions"
    __table_args__ = (Index("ix_review_sessions_org_id", "org_id"),)
    session_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(40), index=True)
    reviewer_user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"))
    case_id: Mapped[str] = mapped_column(ForeignKey("gated_cases.case_id"))
    status: Mapped[str] = mapped_column(String(20))  # assigned|decided|expired
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GatedDecision(Base):
    """A reviewer's captured decision on a gated case (org-scoped, ADR-0006 tenancy).

    The human-gate decision row scored against the case's `designed_label`. The capture is a pointer
    (`snapshot_ref` → `snapshot_captures`, NOT an inline blob — unified §3). The `(org_id, case_id)`
    index serves the "every action over threshold where the gate approved" query path.
    """

    __tablename__ = "gated_decisions"
    __table_args__ = (Index("ix_gated_decisions_org_case", "org_id", "case_id"),)
    decision_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(40), index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("review_sessions.session_id"))
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    reviewer_user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"))
    decision: Mapped[str] = mapped_column(String(10))  # APPROVE|DENY
    deliberation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_latency_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    snapshot_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)  # capture pointer
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


__all__ = [
    "Organization", "User", "Membership", "Project", "ApiKey",
    "ScanRun", "ScanJob", "Report", "Secret", "Integration",
    "SlackRegisteredAgent", "AttestationEntry",
    "GatedCase", "ReviewSession", "GatedDecision",
]
