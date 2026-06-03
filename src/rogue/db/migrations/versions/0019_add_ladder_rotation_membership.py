"""add ladder_rotation_membership — reachability telemetry (§10.10 Phase 2.1)

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-03

``ladder_attempts`` logs only strategies that EXECUTED, so a missing row is
ambiguous (never eligible / starved by early-stop / lost the reorder / budget-cut).
This table records the FULL eligible rotation per ladder — every strategy's rank,
eligibility, whether it executed, and the skip reason if not — so REACHABILITY
(executed ÷ eligible), starvation frequency, opportunity cost, and reorder
efficiency become measurable. Append-only analytics log, reconstructed post-hoc
from the LadderResult (the ladder execution path is untouched).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: Union[str, Sequence[str], None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ladder_rotation_membership",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=40), nullable=False, index=True),
        sa.Column("parent_id", sa.String(length=40), nullable=False, index=True),
        sa.Column("strategy_id", sa.String(length=60), nullable=False, index=True),
        # image | coj | structured | audio | planner
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),  # position in the rotation
        # Was this strategy's tier runnable given the configs (e.g. audio needs an
        # audio-capable config)? An *eligible* strategy that didn't run was starved.
        sa.Column("eligible", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("executed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("outcome", sa.String(length=20), nullable=True),  # if executed
        # NULL iff executed; else early_stop | budget | no_compatible_config | not_reached
        sa.Column("skipped_reason", sa.String(length=30), nullable=True),
        sa.Column("config_id", sa.String(length=40), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("ladder_rotation_membership")
