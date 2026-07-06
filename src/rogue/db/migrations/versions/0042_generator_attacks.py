"""generator/sweep attacks — attack_primitives.generator

Revision ID: 0042
Revises: 0041
Create Date: 2026-07-05

Opt-in procedural-attack spec (PayloadGenerator dict): when set, the payload is BUILT at reproduce
time (many-shot, shot-repetition, token-budget scaling) instead of using the static payload_template,
and can be SWEPT over a dimension to trace an ASR curve (rogue.reproduce.generators + generator_sweep).
Lets ROGUE represent attacks that are procedures, not strings (e.g. Many-Shot Jailbreaking). NULL =
today's static-template behaviour.

**Downgrade**: drop the column — purely additive.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0042"
down_revision: Union[str, Sequence[str], None] = "0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("attack_primitives", sa.Column("generator", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("attack_primitives", "generator")
