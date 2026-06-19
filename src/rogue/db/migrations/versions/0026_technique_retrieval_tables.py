"""technique retrieval tables — technique/target embeddings + shadow metrics

Foundational slice of the Technique Retrieval System. Three tables:

  * ``technique_embeddings`` — one row per ladder strategy ``label`` (retrieval key);
    a 1536-d embedding of the technique plus its serialized ``TechniqueProfile``.
  * ``target_embeddings`` — one row per ``target_model`` string; a 1536-d embedding
    of the target's behavioural ``TargetFingerprint``.
  * ``retrieval_metrics`` — append-only shadow-mode telemetry: how the retriever
    WOULD have ranked the technique that actually won, so retrieval quality can be
    measured offline before the retriever ever drives execution.

The two embedding tables carry an ivfflat cosine ANN index (lists=100), matching the
``attack_primitives.payload_embedding`` index shape (migration 0001). No hard FKs —
``retrieval_metrics`` is analytics-only and append-only, like ``ladder_attempts``.
All embedding columns are 1536-d (text-embedding-3-small) and nullable.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "0026"
down_revision: Union[str, Sequence[str], None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "technique_embeddings",
        sa.Column("label", sa.String(length=80), primary_key=True),
        sa.Column("technique_id", sa.String(length=40), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("profile", sa.JSON(), nullable=True),
        sa.Column("modalities", sa.JSON(), nullable=True),
        sa.Column("version", sa.String(length=20), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            index=True,
        ),
    )
    op.execute(
        "CREATE INDEX ix_technique_embeddings_embedding "
        "ON technique_embeddings USING ivfflat "
        "(embedding vector_cosine_ops) WITH (lists = 100)"
    )

    op.create_table(
        "target_embeddings",
        sa.Column("target_key", sa.String(length=100), primary_key=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("fingerprint", sa.JSON(), nullable=True),
        sa.Column("version", sa.String(length=20), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            index=True,
        ),
    )
    op.execute(
        "CREATE INDEX ix_target_embeddings_embedding "
        "ON target_embeddings USING ivfflat "
        "(embedding vector_cosine_ops) WITH (lists = 100)"
    )

    op.create_table(
        "retrieval_metrics",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=40), nullable=False, index=True),
        sa.Column("parent_id", sa.String(length=40), nullable=False, index=True),
        sa.Column("target_key", sa.String(length=100), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("retrieved_rank", sa.Integer(), nullable=True),
        sa.Column("winner_rank", sa.Integer(), nullable=True),
        sa.Column(
            "retrieval_hit", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("k", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("retrieval_metrics")
    op.drop_table("target_embeddings")
    op.drop_table("technique_embeddings")
