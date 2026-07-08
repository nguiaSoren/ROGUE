"""camouflaged-intent tag — attack_primitives.camouflage_score / camouflage_label

Revision ID: 0045
Revises: 0044
Create Date: 2026-07-09

Adds the Q20 camouflaged-intent signal (extract.camouflage, grounded in Zheng "Behind the Mask"
2509.05471): a benign-frame × dual-use CO-OCCURRENCE likelihood [0,1] + a discretized label
(camouflaged / overt / ambiguous), set at harvest-persist time on HARVESTED payloads under the
ROGUE_CAMOUFLAGE_TAG flag. A flag-for-review PRIOR — Zheng shows keyword detection can't reliably
catch camouflage (the strong signal is the LLM judge), so this is NEVER an auto-drop gate. NULL on
legacy rows, on ROGUE-synthesized primitives, and whenever the flag is off. The label is indexed for
the "show me camouflaged harvest" review query. Downgrade: drop both columns + the index.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: Union[str, Sequence[str], None] = "0044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("attack_primitives", sa.Column("camouflage_score", sa.Float(), nullable=True))
    op.add_column("attack_primitives", sa.Column("camouflage_label", sa.String(length=20), nullable=True))
    op.create_index(
        "ix_attack_primitives_camouflage_label", "attack_primitives", ["camouflage_label"]
    )


def downgrade() -> None:
    op.drop_index("ix_attack_primitives_camouflage_label", table_name="attack_primitives")
    op.drop_column("attack_primitives", "camouflage_label")
    op.drop_column("attack_primitives", "camouflage_score")
