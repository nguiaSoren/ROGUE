"""mitigations — persisted measured-remediation outcomes (Surface 1b, build-05 §8)

Revision ID: 0032
Revises: 0031
Create Date: 2026-06-09

NET-NEW additive table for the ROGUE v2 measured-remediation layer (build-05 §8,
Surface 1b). One row per remediation outcome: storage twin of
``rogue.schemas.remediation.RemediationResult`` (flattening its
``MitigationCandidate`` identity/artifact + the re-test rates into a single record).

The ``mitigation_type`` Postgres enum is created from the Pydantic
``MitigationType`` VALUE strings (lowercase ``system_prompt_patch`` etc.), so the
storage vocabulary can never drift from the wire vocabulary. Values are inlined as
a string list (mirroring 0001 / 0013) so the migration stays self-contained and
applies without importing application code; ``downgrade()`` drops the table then
the enum type (Postgres-only, dialect-guarded — matching the initial migration).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


# ---------- Enum value list (mirror src/rogue/schemas/remediation.py:MitigationType) ----------
MITIGATION_TYPE_VALUES = [
    "system_prompt_patch",
    "finetune_preference_data",
    "tool_permission_scope",
    "retrieval_context_fix",
    "architecture_recommendation",
    "guardrail_rule",
    "human_gate_route",
]


def upgrade() -> None:
    op.create_table(
        "mitigations",
        sa.Column("mitigation_id", sa.String(length=40), primary_key=True),
        sa.Column("breach_ref", sa.String(length=40), nullable=False),
        sa.Column(
            "mitigation_type",
            sa.Enum(*MITIGATION_TYPE_VALUES, name="mitigation_type"),
            nullable=False,
        ),
        sa.Column("artifact", sa.Text(), nullable=False),
        sa.Column("generated_by", sa.String(length=120), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("verified_by", sa.String(length=40), nullable=False),
        sa.Column("pre_breach_rate", sa.Float(), nullable=True),
        sa.Column("post_breach_rate", sa.Float(), nullable=True),
        sa.Column("over_block_rate", sa.Float(), nullable=True),
        sa.Column("ci_low", sa.Float(), nullable=True),
        sa.Column("ci_high", sa.Float(), nullable=True),
        sa.Column("rejected_candidates", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_mitigations_breach_ref", "mitigations", ["breach_ref"])
    op.create_index("ix_mitigations_mitigation_type", "mitigations", ["mitigation_type"])
    op.create_index("ix_mitigations_accepted", "mitigations", ["accepted"])
    op.create_index("ix_mitigations_created_at", "mitigations", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_mitigations_created_at", table_name="mitigations")
    op.drop_index("ix_mitigations_accepted", table_name="mitigations")
    op.drop_index("ix_mitigations_mitigation_type", table_name="mitigations")
    op.drop_index("ix_mitigations_breach_ref", table_name="mitigations")
    op.drop_table("mitigations")

    # Drop the enum type last (Postgres-specific; dialect-guarded — ROGUE is
    # Postgres-only at runtime, SQLite test backends never created the type).
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS mitigation_type")
