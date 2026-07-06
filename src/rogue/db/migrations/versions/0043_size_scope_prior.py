"""size-scope prior — ladder_attempts.target_size_class

Revision ID: 0043
Revises: 0042
Create Date: 2026-07-05

Adds the SIZE scope to the scheduler's contextual prior (§10.10): a config borrows strategy order
from configs of its size × context reach — the axes the many-shot / long-context papers tie to ASR.
Tagged at write time (strategy_lifecycle) alongside target_vendor/target_family; NULL on legacy rows
(they contribute to GLOBAL only, like the vendor/family cold case). Downgrade: drop the column.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0043"
down_revision: Union[str, Sequence[str], None] = "0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ladder_attempts", sa.Column("target_size_class", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("ladder_attempts", "target_size_class")
