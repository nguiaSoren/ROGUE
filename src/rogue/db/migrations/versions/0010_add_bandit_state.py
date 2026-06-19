"""add bandit_state table — DB-backed bandit for a live /api/bandit/stats

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-29

Mirrors the DiscoveryAgent bandit state (the dict in `data/discovery_bandit.json`)
into a single-row table so the dashboard's bandit widget reads it live from the DB
instead of a file baked into the deploy. The harvest upserts row id=1 after each run.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bandit_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("state", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("bandit_state")
