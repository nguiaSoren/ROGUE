"""harvest authorship provenance — attack_primitives.authorship_score / authorship_label

Revision ID: 0044
Revises: 0043
Create Date: 2026-07-07

Adds the XDAC-inspired harvest-authorship signal (dedupe.llm_authored): an LLM-authored likelihood
[0,1] + a discretized label, set at harvest-persist time on HARVESTED payloads. A flag-for-review
PRIOR (HC3-calibrated AUC ~0.84 forum, precision ~0.74) to surface likely-synthetic open-web filler
(SEO listicles, karma-farm boilerplate) — NOT an auto-drop gate. NULL on legacy rows and on
ROGUE-synthesized/generator primitives (known-synthetic by construction). The label is indexed for the
"show me likely-synthetic harvest" review query. Downgrade: drop both columns + the index.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0044"
down_revision: Union[str, Sequence[str], None] = "0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("attack_primitives", sa.Column("authorship_score", sa.Float(), nullable=True))
    op.add_column("attack_primitives", sa.Column("authorship_label", sa.String(length=20), nullable=True))
    op.create_index(
        "ix_attack_primitives_authorship_label", "attack_primitives", ["authorship_label"]
    )


def downgrade() -> None:
    op.drop_index("ix_attack_primitives_authorship_label", table_name="attack_primitives")
    op.drop_column("attack_primitives", "authorship_label")
    op.drop_column("attack_primitives", "authorship_score")
