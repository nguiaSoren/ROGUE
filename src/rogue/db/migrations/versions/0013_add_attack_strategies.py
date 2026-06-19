"""add attack_strategies table — the self-growing technique library (§10.9)

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-01

Creates ``attack_strategies`` — the storage twin of ``rogue.schemas.TechniqueSpec``.
Parallel to ``attack_primitives`` (payload *instances*); this table holds harvested
*techniques* (reusable methods) and is the single source the planner reads strategies
from (§10.9 risk-note 3), interchangeable with the hand-written
``reproduce/arms_strategies.py`` entries via the shared ``directive`` column.

Two new Postgres enums:
  - ``attack_strategy_modality`` {text, image, audio, multi_turn}
  - ``attack_strategy_status``   {candidate, active, needs_implementation}

Enum values are inlined as string lists (mirroring 0001) so the migration stays
self-contained and applies without importing application code.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------- Enum value lists (mirror src/rogue/schemas/technique_spec.py) ----------

MODALITY_VALUES = ("text", "image", "audio", "multi_turn")

STRATEGY_STATUS_VALUES = ("candidate", "active", "needs_implementation")


def upgrade() -> None:
    op.create_table(
        "attack_strategies",
        sa.Column("technique_id", sa.String(length=40), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "modality",
            sa.Enum(*MODALITY_VALUES, name="attack_strategy_modality"),
            nullable=False,
            index=True,
        ),
        sa.Column("principle", sa.Text(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("params", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("example", sa.Text(), nullable=True),
        sa.Column("directive", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(*STRATEGY_STATUS_VALUES, name="attack_strategy_status"),
            nullable=False,
            server_default="candidate",
            index=True,
        ),
        sa.Column("claimed_first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("attack_strategies")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for enum_name in ("attack_strategy_status", "attack_strategy_modality"):
            op.execute(f"DROP TYPE IF EXISTS {enum_name}")
