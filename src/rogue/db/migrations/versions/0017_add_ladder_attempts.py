"""add ladder_attempts — orchestration-trace telemetry (§10.9 → §10.10 substrate)

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-02

Instrument the ESCALATION LADDER itself (not just candidates): one row per ladder
attempt, tagged with the scheduler policy (``candidate_attempt_quota``). This is the
substrate the future adaptive scheduler (§10.10 break-bandit) learns over — and it
lets us segment A/B telemetry by orchestration policy (quota=0 vs N vs probe),
measure renderer dominance by depth, starvation frequency, and "did a candidate
breach after the renderers failed?". Most jailbreak systems log successes; this logs
orchestrator decision dynamics.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: Union[str, Sequence[str], None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ladder_attempts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=40), nullable=False, index=True),
        sa.Column("parent_id", sa.String(length=40), nullable=False, index=True),
        sa.Column("attempt_index", sa.Integer(), nullable=False),
        sa.Column("ladder_depth", sa.Integer(), nullable=False),  # tier 1..5
        # 'renderer' | 'coj' | 'base' (ARMS) | 'candidate' | 'meta'
        sa.Column("entity_type", sa.String(length=20), nullable=False, index=True),
        sa.Column("entity_id", sa.String(length=60), nullable=False),
        # Soft reference to attack_strategies.technique_id (NO hard FK — this is an
        # append-only analytics log; a constraint would couple log retention to the
        # strategy table's lifecycle).
        sa.Column("technique_id", sa.String(length=40), nullable=True, index=True),
        # The scheduler policy in effect (the §10.9 control variable).
        sa.Column(
            "candidate_attempt_quota", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("config_id", sa.String(length=40), nullable=True),
        # breach | no_breach | refused | render_error | budget_stopped
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("breached", sa.Boolean(), nullable=False, server_default="false"),
        # True iff this attempt early-stopped the ladder (vs natural exhaustion) —
        # the load-bearing field for starvation analysis.
        sa.Column(
            "stopped_run", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("ladder_attempts")
