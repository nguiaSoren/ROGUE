"""attack_strategies lifecycle — graduation / retirement / resurrection (§10.9 Phase 4)

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-02

Adds the technique lifecycle to ``attack_strategies``:
  - extends the ``attack_strategy_status`` enum with ``retired`` + ``archived``
    (``candidate → active → retired → archived``; ``needs_implementation`` stays);
  - a new ``strategy_retire_reason`` enum
    (``never_breached_n_runs | expired_ttl | manual | budget``);
  - trial/breach counters + audit + recency + retirement + a ``next_eligible_at``
    column that future-proofs the Phase 4b sweep scheduler.

``ALTER TYPE ... ADD VALUE`` cannot run inside a transaction, so the enum widening
uses Alembic's ``autocommit_block`` (same pattern as 0004). The new values are not
*used* in this migration, so the "can't use a new enum value in the same txn"
restriction doesn't apply.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: Union[str, Sequence[str], None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_STATUS_VALUES = ("retired", "archived")
_RETIRE_REASON_VALUES = (
    "never_breached_n_runs",
    "expired_ttl",
    "manual",
    "budget",
)


def upgrade() -> None:
    # 1. Widen the status enum (autocommit — PG transaction restriction).
    with op.get_context().autocommit_block():
        for value in _NEW_STATUS_VALUES:
            op.execute(
                f"ALTER TYPE attack_strategy_status ADD VALUE IF NOT EXISTS '{value}'"
            )

    # 2. Create the retire-reason enum type.
    retire_reason = sa.Enum(*_RETIRE_REASON_VALUES, name="strategy_retire_reason")
    retire_reason.create(op.get_bind(), checkfirst=True)

    # 3. Add the lifecycle columns.
    op.add_column(
        "attack_strategies",
        sa.Column("n_times_tried", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "attack_strategies",
        sa.Column("n_breaches", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "attack_strategies",
        sa.Column(
            "supporting_breach_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "attack_strategies",
        sa.Column("first_breach_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "attack_strategies",
        sa.Column("first_breach_config_id", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "attack_strategies",
        sa.Column("last_tried_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "attack_strategies",
        sa.Column("last_breached_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "attack_strategies",
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "attack_strategies",
        sa.Column(
            "retire_reason",
            sa.Enum(*_RETIRE_REASON_VALUES, name="strategy_retire_reason", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "attack_strategies",
        sa.Column(
            "resurrected",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "attack_strategies",
        sa.Column("next_eligible_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_attack_strategies_next_eligible_at",
        "attack_strategies",
        ["next_eligible_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_attack_strategies_next_eligible_at", table_name="attack_strategies"
    )
    for col in (
        "next_eligible_at",
        "resurrected",
        "retire_reason",
        "retired_at",
        "last_breached_at",
        "last_tried_at",
        "first_breach_config_id",
        "first_breach_at",
        "supporting_breach_count",
        "n_breaches",
        "n_times_tried",
    ):
        op.drop_column("attack_strategies", col)

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS strategy_retire_reason")
        # NOTE: the two new attack_strategy_status values (retired/archived)
        # are NOT removed — PostgreSQL can't drop a single enum value cleanly,
        # and enum widening is backwards-compatible (same rationale as 0004).
