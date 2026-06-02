"""add renderer_capabilities table — governed renderer lifecycle (§10.9 Phase 3b)

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-02

The executable counterpart to ``attack_strategies``: stores each modality renderer's
safety manifest + lifecycle state, so an image/audio technique that parked as
``needs_implementation`` can be linked to a renderer that is governed through
``harvested → spec_validated → synthesized → sandbox_verified → deterministic →
human_approved → active`` (+ a terminal ``rejected``). Two new enums:
``renderer_status`` and ``renderer_origin`` (human | synthesized).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: Union[str, Sequence[str], None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STATUS_VALUES = (
    "harvested",
    "spec_validated",
    "synthesized",
    "sandbox_verified",
    "deterministic",
    "human_approved",
    "active",
    "rejected",
)
_ORIGIN_VALUES = ("human", "synthesized")


def upgrade() -> None:
    # Enum types are auto-created by create_table from the column definitions
    # (the proven 0013 pattern); no explicit .create() needed.
    op.create_table(
        "renderer_capabilities",
        sa.Column("renderer_id", sa.String(length=60), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "technique_id",
            sa.String(length=40),
            sa.ForeignKey("attack_strategies.technique_id"),
            nullable=True,
            index=True,
        ),
        sa.Column("modality", sa.String(length=10), nullable=False),
        sa.Column(
            "origin",
            sa.Enum(*_ORIGIN_VALUES, name="renderer_origin"),
            nullable=False,
            index=True,
        ),
        sa.Column("entrypoint", sa.Text(), nullable=False),
        sa.Column("artifact_types", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "network_allowed", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "deterministic", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("sandbox_policy", sa.String(length=40), nullable=True),
        sa.Column("provenance_hash", sa.String(length=64), nullable=True),
        sa.Column("resource_limits", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "status",
            sa.Enum(*_STATUS_VALUES, name="renderer_status"),
            nullable=False,
            server_default="harvested",
            index=True,
        ),
        sa.Column("approved_by", sa.String(length=100), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("renderer_capabilities")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS renderer_status")
        op.execute("DROP TYPE IF EXISTS renderer_origin")
