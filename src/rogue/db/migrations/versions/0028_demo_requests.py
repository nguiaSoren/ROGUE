"""demo_requests table — marketing-site lead capture

Revision ID: 0028
Revises: 0027
Create Date: 2026-06-06

Stores demo-request leads submitted from the marketing site via
``POST /api/demo-request``. Standalone append-only table — no FK into the
threat-DB graph. Purely additive (§13-safe). Storage twin of
``rogue.api.demo.DemoRequestBody`` / ``rogue.db.models.DemoRequest``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "demo_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("company", sa.String(length=200), nullable=True),
        sa.Column("deployment_type", sa.String(length=60), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=60), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_demo_requests_email", "demo_requests", ["email"])
    op.create_index("ix_demo_requests_created_at", "demo_requests", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_demo_requests_created_at", table_name="demo_requests")
    op.drop_index("ix_demo_requests_email", table_name="demo_requests")
    op.drop_table("demo_requests")
