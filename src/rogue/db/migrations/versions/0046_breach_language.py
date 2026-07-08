"""multilingual breach language — breach_results.language

Revision ID: 0046
Revises: 0045
Create Date: 2026-07-09

Adds the Q20 translate-then-reproduce fire-language marker: the ISO code of the language a primitive
was fired in when ROGUE_MULTILINGUAL / --multilingual expanded it into a language panel. NULL for the
untranslated English baseline and every non-multilingual run — so pre-Q20 rows and flag-off runs are
byte-identical. Indexed for the English-vs-non-English breach-delta GROUP BY. String (not a PG enum),
matching the exfil_method / persona_used convention on this table. Downgrade: drop the column + index.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0046"
down_revision: Union[str, Sequence[str], None] = "0045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("breach_results", sa.Column("language", sa.String(length=8), nullable=True))
    op.create_index("ix_breach_results_language", "breach_results", ["language"])


def downgrade() -> None:
    op.drop_index("ix_breach_results_language", table_name="breach_results")
    op.drop_column("breach_results", "language")
