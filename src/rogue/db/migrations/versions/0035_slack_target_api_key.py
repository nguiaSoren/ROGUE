"""slack_registered_agents.target_api_key_ref column

Revision ID: 0035
Revises: 0034
Create Date: 2026-06-10

Additive: a SecretStore handle to the target endpoint's bearer key, mirroring the
`system_prompt_ref` secret pattern. Nullable — open / self-gatewayed (keyless) endpoints have
none. Without it a keyed agent endpoint gets no Authorization header and the live policy scan 401s.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "slack_registered_agents", sa.Column("target_api_key_ref", sa.String(48), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("slack_registered_agents", "target_api_key_ref")
