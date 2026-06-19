"""slack_registered_agents table — per-org self-registered Slack agent targets

Revision ID: 0033
Revises: 0032
Create Date: 2026-06-09

A customer's own consented Slack agent endpoint, stored separately from `integrations` (different
cardinality/lifecycle). Carries enough to reconstruct the target's `DeploymentConfig`; the
`system_prompt_ref` holds either the inline prompt or a `secref_…` handle into `secrets`. Additive.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "slack_registered_agents",
        sa.Column("agent_id", sa.String(48), primary_key=True),
        sa.Column("org_id", sa.String(40), nullable=False),
        sa.Column("agent_name", sa.String(80), nullable=False),
        sa.Column("workspace", sa.String(120), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("system_prompt_ref", sa.Text(), nullable=False),
        sa.Column("declared_tools", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("forbidden_topics", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("sandbox_channel_id", sa.String(64), nullable=False),
        sa.Column("security_channel_id", sa.String(64), nullable=False),
        sa.Column("rule_pack_ref", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "agent_name", name="uq_slack_agent_org_name"),
    )
    op.create_index(
        "ix_slack_registered_agents_org_id", "slack_registered_agents", ["org_id"]
    )


def downgrade() -> None:
    op.drop_table("slack_registered_agents")
