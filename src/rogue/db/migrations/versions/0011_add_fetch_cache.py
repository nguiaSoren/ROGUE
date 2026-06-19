"""add fetch_cache table — persistent cross-run URL skip-cache (§11.7)

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-29

Records every URL ROGUE has fetched (including zero-yield ones) so a daily harvest
skips re-crawling / re-extracting unchanged content. ``version_token`` is a
source-supplied freshness signal (git blob SHA, arxiv updated-date, reddit
``created:num_comments``, HTTP ETag); ``content_hash`` mirrors
``RawDocument.archive_hash`` for the universal pre-extraction skip. Additive —
creates one empty table; no existing rows touched. See ROGUE_PLAN.md §11.7.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fetch_cache",
        sa.Column("url", sa.Text(), primary_key=True),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("version_token", sa.String(length=200), nullable=True),
        sa.Column("content_hash", sa.String(length=80), nullable=True),
        sa.Column(
            "last_fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_status",
            sa.String(length=20),
            nullable=False,
            server_default="ok",
        ),
        sa.Column(
            "n_primitives_yielded",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index(
        "ix_fetch_cache_source_type", "fetch_cache", ["source_type"]
    )


def downgrade() -> None:
    op.drop_index("ix_fetch_cache_source_type", table_name="fetch_cache")
    op.drop_table("fetch_cache")
