"""split attack-strategy trials into total attempts vs valid trials (§10.9 correctness)

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-02

Live telemetry (the candidate-quota A/B) showed most candidate "trials" were not
semantic evaluations at all — they were orchestration failures (planner refused to
author the plan, or a slot render error). The old `n_times_tried` counted those,
so retirement measured ORCHESTRATION failure, not ATTACK failure — a correctness
bug that would poison retirement, breach-rate estimation, and future bandit rewards.

Fix: separate the two. Rename `n_times_tried` → `n_attempts_total` (every attempt,
drives selection ordering) and add `n_valid_trials` (breach/no_breach only — drives
retirement). Conservative backfill: `n_valid_trials = n_breaches` (the only trials we
KNOW were valid; historical totals mixed blocked attempts and can't be reconstructed).
`validity_rate = n_valid_trials / n_attempts_total` becomes a first-class signal —
a powerful-but-planner-refused technique reads differently from a weak one.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: Union[str, Sequence[str], None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "attack_strategies", "n_times_tried", new_column_name="n_attempts_total"
    )
    op.add_column(
        "attack_strategies",
        sa.Column("n_valid_trials", sa.Integer(), nullable=False, server_default="0"),
    )
    # Conservative backfill: only breaches are known-valid trials.
    op.execute("UPDATE attack_strategies SET n_valid_trials = n_breaches")


def downgrade() -> None:
    op.drop_column("attack_strategies", "n_valid_trials")
    op.alter_column(
        "attack_strategies", "n_attempts_total", new_column_name="n_times_tried"
    )
