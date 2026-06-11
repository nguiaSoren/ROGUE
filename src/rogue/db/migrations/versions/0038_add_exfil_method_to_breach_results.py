"""add exfil_method to breach_results

Revision ID: 0038
Revises: 0037
Create Date: 2026-06-12

Output-side exfiltration-method taxonomy persistence. Adds a nullable
``exfil_method`` column to ``breach_results`` carrying the concrete egress
channel (``rogue.schemas.ExfiltrationMethod`` value) that the judge layer
deterministically classifies from ``model_response`` — markdown-image beacon,
hyperlink exfil, inline data URI, base64 blob, PII egress,
secret/credential egress, or tool-argument smuggling.

``NULL`` means no concrete egress artifact was present: either a non-breach
verdict, or a breach with no output-side channel (e.g. a pure
capability-transfer / policy-roleplay answer). The label sharpens findings
without changing the verdict axis — it is an extra label ON a breach.

Stored as ``String(40)`` (not a Postgres enum) so the label vocabulary can
extend without a migration, matching the ``persona_used`` / ``refinement_type``
convention already on this table.

**Downgrade**: clean DROP COLUMN — ``exfil_method`` is purely auxiliary, so
every existing query works unchanged once the column is gone.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0038"
down_revision: Union[str, Sequence[str], None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "breach_results",
        sa.Column("exfil_method", sa.String(length=40), nullable=True),
    )
    # Partial index on the labeled subset only — the vast majority of rows have
    # exfil_method=NULL (non-egress breaches + non-breach verdicts), so a
    # full index would be mostly duplicate NULLs. Channel-aggregation queries
    # filter on exfil_method IS NOT NULL, which this partial index serves.
    op.create_index(
        "ix_breach_results_exfil_method",
        "breach_results",
        ["exfil_method"],
        postgresql_where=sa.text("exfil_method IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_breach_results_exfil_method", table_name="breach_results",
    )
    op.drop_column("breach_results", "exfil_method")
