"""emergent-taxonomy layer — attack_primitives.emergent_label

Revision ID: 0041
Revises: 0040
Create Date: 2026-07-05

The automatic-capture half of the taxonomy-extension pipeline (glossary "Customer-real tools"):
a free-text label the extractor proposes for a novel technique's mechanism/channel. UNLIKE the
frozen family/vector enums this column is unconstrained, so novelty is captured with NO migration
per new label. Recurring labels are auto-clustered (rogue.extract.emergent_taxonomy) into promotion
candidates; the actual enum extension stays human-approved. Indexed for the cluster query.

**Downgrade**: drop the column + its index — purely additive.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0041"
down_revision: Union[str, Sequence[str], None] = "0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "attack_primitives",
        sa.Column("emergent_label", sa.String(length=60), nullable=True),
    )
    op.create_index(
        "ix_attack_primitives_emergent_label", "attack_primitives", ["emergent_label"]
    )


def downgrade() -> None:
    op.drop_index("ix_attack_primitives_emergent_label", table_name="attack_primitives")
    op.drop_column("attack_primitives", "emergent_label")
