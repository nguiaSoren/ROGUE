"""integrations table — per-org stored Slack/Jira config (secret via the secrets table)

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-05

Lets MCP/workflow tools reference an org's integration by name instead of taking raw creds as
arguments. Non-secret config inline; the credential is a `secret_ref` into `secrets` (Fernet). Additive.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integrations",
        sa.Column("integration_id", sa.String(48), primary_key=True),
        sa.Column("org_id", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("secret_ref", sa.String(48), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "name", name="uq_integration_org_name"),
    )
    op.create_index("ix_integrations_org_id", "integrations", ["org_id"])


def downgrade() -> None:
    op.drop_table("integrations")
