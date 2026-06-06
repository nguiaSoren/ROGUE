"""newsletter_subscribers table — marketing-site newsletter sign-ups

Revision ID: 0029
Revises: 0028
Create Date: 2026-06-06

Stores newsletter subscribers submitted from the marketing site via
``POST /api/newsletter``. Standalone append-only table — no FK into the
threat-DB graph. ``email`` is unique so a re-subscribe is idempotent. Purely
additive (§13-safe). Storage twin of ``rogue.api.newsletter.NewsletterBody`` /
``rogue.db.models.NewsletterSubscriber``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "newsletter_subscribers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("source", sa.String(length=60), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_newsletter_subscribers_email",
        "newsletter_subscribers",
        ["email"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_newsletter_subscribers_email", table_name="newsletter_subscribers"
    )
    op.drop_table("newsletter_subscribers")
