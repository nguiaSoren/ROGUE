"""add synthesized + slot_requirements + derived_from to attack_primitives

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-27

§10.7 augmentation roadmap — schema changes for the multi-turn escalation
planner (and the syntactic-mutation augmentation that ships after it). Three
new columns on ``attack_primitives``:

  * ``synthesized`` (NOT NULL bool, default False): True iff this row was
    produced by an augmentation step (escalation_planner, syntactic_mutation)
    rather than harvested from the open web. Keeps the HuggingFace dataset
    splittable into ``rogue-attacks-{harvested,derived}-*.jsonl`` per the
    §10.7 "HuggingFace dataset split" checklist item.

  * ``derived_from_primitive_id`` (nullable FK → attack_primitives): when
    ``synthesized=True``, points at the harvested parent. No CASCADE — the
    chain is for provenance, not transactional integrity, and we want
    synthesized rows to outlive their parents if a future cleanup deletes
    the original.

  * ``slot_requirements`` (nullable JSON): per-turn slot validation for
    multi-turn primitives. Keys are turn indices as strings ('0', '1', '2'),
    values are lists of slot names that must be populated in that turn.
    Enforced at render time by
    :func:`rogue.reproduce.instantiator.render_multi_turn`.

The ``synthesized`` index speeds up the dashboard query
``WHERE synthesized=true`` (the §10.7 escalation-vulnerability tile);
``derived_from_primitive_id`` is indexed to support the parent-→children
lookup the dashboard needs to render the chain.

**Downgrade**: clean drop. ``synthesized`` was server-default False so any
ORM-side INSERT that omitted the column still wrote False; downgrading to
0005 loses the column but no harvested row depended on it.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "attack_primitives",
        sa.Column(
            "synthesized",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_attack_primitives_synthesized",
        "attack_primitives",
        ["synthesized"],
    )

    op.add_column(
        "attack_primitives",
        sa.Column(
            "derived_from_primitive_id",
            sa.String(length=40),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_attack_primitives_derived_from",
        "attack_primitives",
        "attack_primitives",
        ["derived_from_primitive_id"],
        ["primitive_id"],
    )
    op.create_index(
        "ix_attack_primitives_derived_from_primitive_id",
        "attack_primitives",
        ["derived_from_primitive_id"],
    )

    op.add_column(
        "attack_primitives",
        sa.Column(
            "slot_requirements",
            sa.JSON(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("attack_primitives", "slot_requirements")
    op.drop_index(
        "ix_attack_primitives_derived_from_primitive_id",
        table_name="attack_primitives",
    )
    op.drop_constraint(
        "fk_attack_primitives_derived_from",
        "attack_primitives",
        type_="foreignkey",
    )
    op.drop_column("attack_primitives", "derived_from_primitive_id")
    op.drop_index(
        "ix_attack_primitives_synthesized",
        table_name="attack_primitives",
    )
    op.drop_column("attack_primitives", "synthesized")
