"""add primitive_images table — DB-stored image bytes for the deployed dashboard

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-30

The real images for multimodal/carrier primitives live on local disk under
``data/media_cache/`` (§11.8 ``{id}/carrier.*`` + Feature-A ``ingested/``), but
that disk is local-only — the deployed Render API can't read it, so images never
rendered on the live site. This one-row-per-primitive table holds the bytes +
media type IN the DB so they travel to Neon with the data sync and the image
route can serve them anywhere. Additive — creates one empty table; no existing
rows touched. Populated by ``rogue.db.image_cache.cache_images_to_db``.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "primitive_images",
        sa.Column(
            "primitive_id",
            sa.String(length=40),
            sa.ForeignKey("attack_primitives.primitive_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("media_type", sa.String(length=40), nullable=False),
        sa.Column("image_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="carrier"),
        sa.Column(
            "cached_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("primitive_images")
