"""add primitive_grammar_labels — grammar-component study labeling store

Revision ID: 0027
Revises: 0026
Create Date: 2026-06-06

Creates ``primitive_grammar_labels`` — the storage twin of
``rogue.schemas.GrammarLabel``. One append-only row per (primitive × grammar node ×
source) decomposes each ``AttackPrimitive`` into the reusable structural ``GrammarNode``
components it exhibits, sitting BELOW the frozen ``AttackFamily`` taxonomy
(purely additive, §13-safe — does not touch ``AttackFamily`` / ``AttackVector``).

One new Postgres enum:
  - ``grammar_node`` — the ~23 lowercase snake_case ``GrammarNode`` values.

The enum is created from ``GrammarNode``'s VALUES (not NAMEs), matching the ORM's
``sa.Enum(GrammarNode, name="grammar_node", values_callable=...)`` so wire and storage
vocabularies can never drift. A ``UniqueConstraint(primitive_id, node, source)`` keeps a
single label per source per (primitive, node) — a heuristic, manual, and llm label of
the same node can coexist. Downgrade drops the table AND the enum type.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from rogue.schemas import GrammarNode

# revision identifiers, used by Alembic.
revision: str = "0027"
down_revision: Union[str, Sequence[str], None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Enum VALUES (not NAMEs) — mirrors the ORM's values_callable so the Postgres enum
# type vocabulary matches what the ORM serializes on insert.
GRAMMAR_NODE_VALUES = tuple(member.value for member in GrammarNode)


def upgrade() -> None:
    op.create_table(
        "primitive_grammar_labels",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "primitive_id",
            sa.String(length=40),
            sa.ForeignKey("attack_primitives.primitive_id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "node",
            sa.Enum(*GRAMMAR_NODE_VALUES, name="grammar_node"),
            nullable=False,
            index=True,
        ),
        # heuristic | manual | llm
        sa.Column(
            "source", sa.String(length=20), nullable=False, server_default="heuristic"
        ),
        sa.Column(
            "confidence", sa.Float(), nullable=False, server_default="1.0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            index=True,
        ),
        sa.UniqueConstraint(
            "primitive_id",
            "node",
            "source",
            name="uq_grammar_label_pid_node_source",
        ),
    )


def downgrade() -> None:
    op.drop_table("primitive_grammar_labels")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS grammar_node")
