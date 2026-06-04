"""platform tables: organizations, users, memberships, projects, api_keys, scan_runs, scan_jobs, reports

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-04

Adds the multi-tenancy + scan-orchestration tables for the platform layer (docs/platform/). Mirrors
`src/rogue/platform/models.py`. Additive only — existing research tables are untouched.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

_TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("org_id", sa.String(40), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", _TS, nullable=False),
    )
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(40), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("created_at", _TS, nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_table(
        "memberships",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.String(40), sa.ForeignKey("organizations.org_id"), nullable=False),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.UniqueConstraint("org_id", "user_id", name="uq_membership_org_user"),
    )
    op.create_index("ix_memberships_org_id", "memberships", ["org_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_table(
        "projects",
        sa.Column("project_id", sa.String(40), primary_key=True),
        sa.Column("org_id", sa.String(40), sa.ForeignKey("organizations.org_id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("created_at", _TS, nullable=False),
        sa.UniqueConstraint("org_id", "slug", name="uq_project_org_slug"),
    )
    op.create_index("ix_projects_org_id", "projects", ["org_id"])
    op.create_table(
        "api_keys",
        sa.Column("key_id", sa.String(40), primary_key=True),
        sa.Column("org_id", sa.String(40), sa.ForeignKey("organizations.org_id"), nullable=False),
        sa.Column("project_id", sa.String(40), sa.ForeignKey("projects.project_id"), nullable=True),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("prefix", sa.String(24), nullable=False),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("scopes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", _TS, nullable=False),
        sa.Column("last_used_at", _TS, nullable=True),
        sa.Column("revoked_at", _TS, nullable=True),
    )
    op.create_index("ix_api_keys_org_id", "api_keys", ["org_id"])
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"])
    op.create_table(
        "scan_runs",
        sa.Column("scan_id", sa.String(48), primary_key=True),
        sa.Column("org_id", sa.String(40), sa.ForeignKey("organizations.org_id"), nullable=False),
        sa.Column("project_id", sa.String(40), sa.ForeignKey("projects.project_id"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("progress", sa.Integer, nullable=False, server_default="0"),
        sa.Column("n_tests", sa.Integer, nullable=False, server_default="0"),
        sa.Column("n_completed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("n_breaches", sa.Integer, nullable=False, server_default="0"),
        sa.Column("top_attack", sa.String(100), nullable=True),
        sa.Column("score", sa.Float, nullable=True),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("report_id", sa.String(48), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("target", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("pack", sa.String(40), nullable=False, server_default="default"),
        sa.Column("spec", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("idempotency_key", sa.String(80), nullable=True),
        sa.Column("created_at", _TS, nullable=False),
        sa.Column("started_at", _TS, nullable=True),
        sa.Column("completed_at", _TS, nullable=True),
    )
    op.create_index("ix_scan_runs_org_id", "scan_runs", ["org_id"])
    op.create_index("ix_scan_runs_status", "scan_runs", ["status"])
    op.create_index("ix_scan_runs_idempotency_key", "scan_runs", ["idempotency_key"])
    op.create_index("ix_scan_runs_created_at", "scan_runs", ["created_at"])
    op.create_table(
        "scan_jobs",
        sa.Column("job_id", sa.String(48), primary_key=True),
        sa.Column("scan_id", sa.String(48), sa.ForeignKey("scan_runs.scan_id"), nullable=False),
        sa.Column("org_id", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"),
        sa.Column("locked_by", sa.String(80), nullable=True),
        sa.Column("locked_at", _TS, nullable=True),
        sa.Column("lease_expires_at", _TS, nullable=True),
        sa.Column("available_at", _TS, nullable=False),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", _TS, nullable=False),
    )
    op.create_index("ix_scan_jobs_scan_id", "scan_jobs", ["scan_id"])
    op.create_index("ix_scan_jobs_status", "scan_jobs", ["status"])
    op.create_index("ix_scan_jobs_available_at", "scan_jobs", ["available_at"])
    op.create_index("ix_scan_jobs_lease_expires_at", "scan_jobs", ["lease_expires_at"])
    op.create_table(
        "reports",
        sa.Column("report_id", sa.String(48), primary_key=True),
        sa.Column("scan_id", sa.String(48), sa.ForeignKey("scan_runs.scan_id"), nullable=False),
        sa.Column("format", sa.String(16), nullable=False, server_default="json"),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", _TS, nullable=False),
    )
    op.create_index("ix_reports_scan_id", "reports", ["scan_id"])


def downgrade() -> None:
    for t in ("reports", "scan_jobs", "scan_runs", "api_keys", "projects", "memberships", "users", "organizations"):
        op.drop_table(t)
