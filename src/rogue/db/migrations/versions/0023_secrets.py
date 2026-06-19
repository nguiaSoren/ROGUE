"""secrets table — encrypted tenant credentials (the api_key_ref indirection)

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-05

Stores Fernet ciphertext for customer target keys so the hosted path never persists a raw key in
`scan_jobs`/`scan_runs` — those carry only a `secref_…` handle. Additive.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "secrets",
        sa.Column("secret_id", sa.String(48), primary_key=True),
        sa.Column("org_id", sa.String(40), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_secrets_org_id", "secrets", ["org_id"])


def downgrade() -> None:
    op.drop_table("secrets")
