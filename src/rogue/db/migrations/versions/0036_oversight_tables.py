"""oversight tables — gated_cases, review_sessions, gated_decisions (Surface 2 human gate)

Revision ID: 0036
Revises: 0035
Create Date: 2026-06-10

The Surface 2 oversight schema (build-area 07, Phase B). `gated_cases` is the global answer-key
corpus (the shared designed-label key — NOT org-scoped). `review_sessions` and `gated_decisions`
are org-scoped (ADR-0006 tenancy): a reviewer's working session over a case, and the captured
decision scored against the case's designed label. Captures are pointers (`snapshot_ref` →
`snapshot_captures`), not inline blobs (unified §3). Additive.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gated_cases",
        sa.Column("case_id", sa.String(64), primary_key=True),
        sa.Column("case_class", sa.String(40), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("designed_label", sa.String(10), nullable=False),
        sa.Column("designed_rationale", sa.Text(), nullable=False),
        sa.Column("label_provenance", sa.String(40), nullable=False),
        sa.Column("source_refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "review_sessions",
        sa.Column("session_id", sa.String(48), primary_key=True),
        sa.Column("org_id", sa.String(40), nullable=False),
        sa.Column(
            "reviewer_user_id",
            sa.String(40),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            sa.String(64),
            sa.ForeignKey("gated_cases.case_id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),  # assigned|decided|expired
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_review_sessions_org_id", "review_sessions", ["org_id"])

    op.create_table(
        "gated_decisions",
        sa.Column("decision_id", sa.String(48), primary_key=True),
        sa.Column("org_id", sa.String(40), nullable=False),
        sa.Column(
            "session_id",
            sa.String(48),
            sa.ForeignKey("review_sessions.session_id"),
            nullable=False,
        ),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column(
            "reviewer_user_id",
            sa.String(40),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(10), nullable=False),  # APPROVE|DENY
        sa.Column("deliberation_notes", sa.Text(), nullable=True),
        sa.Column("decision_latency_s", sa.Float(), nullable=True),
        sa.Column("snapshot_ref", sa.String(80), nullable=True),  # capture pointer, NOT inline blob
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_gated_decisions_org_id", "gated_decisions", ["org_id"])
    op.create_index("ix_gated_decisions_case_id", "gated_decisions", ["case_id"])
    op.create_index("ix_gated_decisions_org_case", "gated_decisions", ["org_id", "case_id"])


def downgrade() -> None:
    op.drop_index("ix_gated_decisions_org_case", table_name="gated_decisions")
    op.drop_index("ix_gated_decisions_case_id", table_name="gated_decisions")
    op.drop_index("ix_gated_decisions_org_id", table_name="gated_decisions")
    op.drop_table("gated_decisions")
    op.drop_index("ix_review_sessions_org_id", table_name="review_sessions")
    op.drop_table("review_sessions")
    op.drop_table("gated_cases")
