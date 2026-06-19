"""snapshot_captures table + slack_registered_agents.client_policy column

Revision ID: 0034
Revises: 0033
Create Date: 2026-06-10

Two additive changes for build-area 06 §4 (Slack sandbox scan):

1. `snapshot_captures` — content-addressed, byte-faithful capture store. Rows hold raw captured
   bytes keyed by content address (`snapshot_ref` = `"sha256:" + hexdigest`), deduped per-tenant via
   `uq_snapshot_org_ref`; the sandbox-scan post links to a `snapshot_ref` instead of inlining transcripts.
2. `slack_registered_agents.client_policy` — cached serialized `ClientPolicy`
   (from `governance.decompose_policy`) so the per-rule policy scan doesn't re-decompose each cycle.
   Nullable (None until first derived).

Additive.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "snapshot_captures",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("org_id", sa.String(40), nullable=False),
        sa.Column("snapshot_ref", sa.String(80), nullable=False),
        sa.Column("content_type", sa.String(40), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "snapshot_ref", name="uq_snapshot_org_ref"),
    )
    op.create_index(
        "ix_snapshot_captures_org_ref", "snapshot_captures", ["org_id", "snapshot_ref"]
    )
    op.add_column(
        "slack_registered_agents", sa.Column("client_policy", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("slack_registered_agents", "client_policy")
    op.drop_table("snapshot_captures")
