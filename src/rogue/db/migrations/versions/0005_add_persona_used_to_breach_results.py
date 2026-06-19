"""add persona_used to breach_results

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-27

§10.7 Persona augmentation A/B persistence. Adds a nullable ``persona_used``
column to ``breach_results`` carrying the PAP persuasion technique name
applied by :class:`rogue.reproduce.persona_wrap.PersonaWrapper`. ``NULL``
means the row is an unwrapped baseline (the existing 4100-result sweep is
the A side; persona-wrapped rows are the B side).

The ``__refused`` suffix on the value (e.g. ``"Logical Appeal__refused"``)
indicates the wrap LLM refused the paraphrase and we fell back to the
original payload — preserved as a distinct value so the dashboard can
surface refusal rate as a separate signal from "persona was applied and
landed on a non-breach verdict".

60-char limit matches the longest PAP technique name (~22 chars) plus the
``__refused`` suffix plus generous headroom for future v2 technique families.

**Downgrade**: clean DROP COLUMN — no value-preservation concern because
persona_used is purely auxiliary (the baseline rate query SELECT WHERE
persona_used IS NULL still works without the column once existing rows
are NULL).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "breach_results",
        sa.Column("persona_used", sa.String(length=60), nullable=True),
    )
    # Partial index — most rows in the 4100-result baseline sweep will have
    # persona_used=NULL, so a regular index would mostly contain duplicate
    # NULL entries. The dashboard queries always filter on persona_used IS
    # NOT NULL (the wrapped subset) or persona_used IS NULL (baseline), so
    # a partial index on the wrapped subset is what speeds them up.
    op.create_index(
        "ix_breach_results_persona_used",
        "breach_results",
        ["persona_used"],
        postgresql_where=sa.text("persona_used IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_breach_results_persona_used", table_name="breach_results",
    )
    op.drop_column("breach_results", "persona_used")
