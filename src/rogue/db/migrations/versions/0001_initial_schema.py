"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-24

Creates the 5 ROGUE tables (deployment_configs, attack_primitives,
source_provenances, breach_results, bright_data_cost_log) plus the pgvector
extension and the ivfflat cosine index over attack_primitives.payload_embedding.

Enums are encoded as in-migration sa.Enum string lists rather than the Python
Enum classes from rogue.schemas — this keeps the migration self-contained and
portable, so it can be applied without importing application code.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------- Enum value lists (mirror src/rogue/schemas/*.py) ----------

ATTACK_FAMILY_VALUES = (
    "direct_instruction_override",
    "role_hijack",
    "dan_persona",
    "policy_roleplay",
    "refusal_suppression",
    "multi_turn_gradient",
    "chain_of_thought_hijack",
    "system_prompt_leak",
    "training_data_extraction",
    "indirect_prompt_injection",
    "tool_use_hijack",
    "obfuscation_encoding",
    "language_switching",
    "multimodal_injection",
)

ATTACK_VECTOR_VALUES = (
    "system_prompt",
    "user_turn",
    "user_multi_turn",
    "tool_output",
    "rag_document",
    "multimodal_image",
    "multimodal_audio",
)

SEVERITY_VALUES = ("low", "medium", "high", "critical")

JUDGE_VERDICT_VALUES = (
    "refused",
    "evaded",
    "partial_breach",
    "full_breach",
    "error",
)


def upgrade() -> None:
    """Upgrade schema."""
    # pgvector extension must exist before any Vector column references it.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ---------- deployment_configs ----------
    op.create_table(
        "deployment_configs",
        sa.Column("config_id", sa.String(length=40), primary_key=True, nullable=False),
        sa.Column("customer_id", sa.String(length=40), nullable=False, index=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("target_model", sa.String(length=100), nullable=False, index=True),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("declared_tools", sa.JSON(), nullable=False),
        sa.Column("forbidden_topics", sa.JSON(), nullable=False),
    )

    # ---------- attack_primitives ----------
    op.create_table(
        "attack_primitives",
        sa.Column("primitive_id", sa.String(length=40), primary_key=True, nullable=False),
        sa.Column("cluster_id", sa.String(length=40), nullable=True, index=True),
        sa.Column("canonical", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "family",
            sa.Enum(*ATTACK_FAMILY_VALUES, name="attack_family"),
            nullable=False,
            index=True,
        ),
        sa.Column("secondary_families", sa.JSON(), nullable=False),
        sa.Column(
            "vector",
            sa.Enum(*ATTACK_VECTOR_VALUES, name="attack_vector"),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("short_description", sa.Text(), nullable=False),
        sa.Column("payload_template", sa.Text(), nullable=False),
        sa.Column("payload_slots", sa.JSON(), nullable=False),
        sa.Column("multi_turn_sequence", sa.JSON(), nullable=True),
        sa.Column("target_models_claimed", sa.JSON(), nullable=False),
        sa.Column("claimed_success_rate", sa.Float(), nullable=True),
        sa.Column("claimed_first_seen", sa.DateTime(), nullable=True),
        sa.Column("reproducibility_score", sa.Integer(), nullable=False),
        sa.Column(
            "requires_multi_turn", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "requires_system_prompt_access",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("requires_tools", sa.JSON(), nullable=False),
        sa.Column(
            "requires_multimodal", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("discovered_at", sa.DateTime(), nullable=False, index=True),
        sa.Column(
            "base_severity",
            sa.Enum(*SEVERITY_VALUES, name="severity"),
            nullable=False,
            index=True,
        ),
        sa.Column("severity_rationale", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        # pgvector embedding column — 1536d matches text-embedding-3-small.
        sa.Column("payload_embedding", Vector(1536), nullable=True),
    )

    # Standard B-tree indices on attack_primitives (those declared inline via
    # `index=True` are created by create_table; we add the explicit ones the
    # plan calls out separately for clarity / future tuning).
    op.create_index(
        "ix_attack_primitives_canonical",
        "attack_primitives",
        ["canonical"],
    )

    # pgvector ivfflat cosine index for ANN search over payload_embedding.
    op.execute(
        "CREATE INDEX ix_attack_primitives_payload_embedding "
        "ON attack_primitives USING ivfflat (payload_embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )

    # ---------- source_provenances ----------
    op.create_table(
        "source_provenances",
        sa.Column(
            "id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False
        ),
        sa.Column(
            "primitive_id",
            sa.String(length=40),
            sa.ForeignKey("attack_primitives.primitive_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False, index=True),
        sa.Column("author", sa.String(length=200), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("archive_hash", sa.String(length=80), nullable=False),
        sa.Column(
            "bright_data_product", sa.String(length=40), nullable=False, index=True
        ),
    )

    # ---------- breach_results ----------
    op.create_table(
        "breach_results",
        sa.Column("breach_id", sa.String(length=40), primary_key=True, nullable=False),
        sa.Column(
            "primitive_id",
            sa.String(length=40),
            sa.ForeignKey("attack_primitives.primitive_id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "deployment_config_id",
            sa.String(length=40),
            sa.ForeignKey("deployment_configs.config_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("trial_index", sa.Integer(), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("rendered_payload", sa.Text(), nullable=False),
        sa.Column("model_response", sa.Text(), nullable=False),
        sa.Column(
            "verdict",
            sa.Enum(*JUDGE_VERDICT_VALUES, name="judge_verdict"),
            nullable=False,
            index=True,
        ),
        sa.Column("judge_rationale", sa.Text(), nullable=False),
        sa.Column("judge_confidence", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("ran_at", sa.DateTime(), nullable=False, index=True),
    )

    # ---------- bright_data_cost_log ----------
    op.create_table(
        "bright_data_cost_log",
        sa.Column(
            "id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False
        ),
        sa.Column("ran_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("product", sa.String(length=40), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema — drop everything in reverse creation order."""
    op.drop_table("bright_data_cost_log")
    op.drop_table("breach_results")
    op.drop_table("source_provenances")

    # Drop the pgvector ivfflat index before the table.
    op.execute("DROP INDEX IF EXISTS ix_attack_primitives_payload_embedding")
    op.drop_index("ix_attack_primitives_canonical", table_name="attack_primitives")
    op.drop_table("attack_primitives")

    op.drop_table("deployment_configs")

    # Drop enum types last (Postgres-specific; safe no-ops on other backends
    # would require checking dialect, but ROGUE is Postgres-only).
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for enum_name in ("judge_verdict", "severity", "attack_vector", "attack_family"):
            op.execute(f"DROP TYPE IF EXISTS {enum_name}")

    # We deliberately do NOT drop the `vector` extension on downgrade — other
    # objects in the database may depend on it.
