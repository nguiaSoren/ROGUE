"""add harvest_run_id to attack_strategies — technique provenance for campaign metrics

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-04

`claimed_first_seen` already exists on attack_strategies (the source/first-seen
date) but was never populated — extraction now fills it via
`harvest.source_date.derive_source_date` (arXiv submission day, plugin post date,
else NULL — never the harvest time). This adds the missing provenance link:
`harvest_run_id` ties each technique to the harvest run that discovered it, so
campaign questions become answerable — discovery rate before/after a query-pool
change, per-run yield, time-from-discovery-to-graduation/implementation. Nullable
+ indexed; existing rows stay NULL until backfilled. Metadata-only ADD COLUMN
(fast, no table rewrite).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: Union[str, Sequence[str], None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "attack_strategies",
        sa.Column("harvest_run_id", sa.String(length=40), nullable=True),
    )
    op.create_index(
        "ix_attack_strategies_harvest_run_id", "attack_strategies", ["harvest_run_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_attack_strategies_harvest_run_id", table_name="attack_strategies")
    op.drop_column("attack_strategies", "harvest_run_id")
