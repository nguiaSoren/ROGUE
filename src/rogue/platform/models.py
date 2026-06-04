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
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from rogue.db.models import Base


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


__all__ = [
    "Organization", "User", "Membership", "Project", "ApiKey",
    "ScanRun", "ScanJob", "Report", "Secret", "Integration",
]
