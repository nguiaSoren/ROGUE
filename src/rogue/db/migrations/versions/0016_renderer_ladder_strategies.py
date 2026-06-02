"""add ladder_strategies to renderer_capabilities (§10.9 Phase 3b-v1 ladder wiring)

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-02

A renderer's ladder identifier is the ``image_strategy`` / audio-style string the
``instantiator.render`` dispatch understands (e.g. 'typographic', 'mml:wr',
'vpi:lowcontrast'). ``ladder_strategies`` records the string(s) a renderer
contributes, so an *active* harvested renderer can be merged into the reproduce
ladder's renderer tier (the 3b-v1 loop closure). Additive; default empty.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: Union[str, Sequence[str], None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "renderer_capabilities",
        sa.Column("ladder_strategies", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("renderer_capabilities", "ladder_strategies")
