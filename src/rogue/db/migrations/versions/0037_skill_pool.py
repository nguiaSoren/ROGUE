"""skill pool — skills, skill_edges, skill_verifications (Surface 3 agent memory)

Revision ID: 0037
Revises: 0036
Create Date: 2026-06-11

The Surface 3 (agent memory / accumulated-knowledge assurance) skill-pool plumbing
(build-area 08, Section A; ADR-0009 Postgres-only — the risk graph is Postgres
adjacency + recursive CTE, NOT a graph DB). Three tables:

  - ``skills``           — the org/cohort-scoped assured substrate; pgvector
                           ``embedding`` (1536-d, ivfflat cosine ANN — mirrors
                           ``attack_primitives.payload_embedding``) for dedup/retrieval.
  - ``skill_edges``      — adjacency for the combination-risk graph; PK
                           ``(skill_a, skill_b, edge_type)`` with an index on BOTH
                           endpoints for recursive-CTE neighborhood traversal (ADR-0009).
  - ``skill_verifications`` — the SQL-queryable audit spine the attestation reads
                           (verified-promotion / re-verification / leakage / combination
                           outcomes with bootstrap CIs).

Enum value lists are inlined as string lists (mirroring 0013/0015) so the migration
stays self-contained; the ORM in ``db/models.py`` derives from the same vocabulary.
Downgrade drops all three in reverse FK order and the four enum types.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


# ---------- Enum value lists (mirror db/models.py SkillPool enums) ----------
_SKILL_STATUS_VALUES = ("candidate", "active", "quarantined", "retired")
_SOURCE_KIND_VALUES = ("correction", "trajectory", "distilled")
_EDGE_TYPE_VALUES = ("co_invocation", "composition", "semantic")
_VERIFICATION_KIND_VALUES = ("promotion", "reverification", "leakage", "combination")
_VERDICT_VALUES = ("pass", "fail")


def upgrade() -> None:
    # ----- skills -----
    op.create_table(
        "skills",
        sa.Column("skill_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "org_id",
            sa.String(length=40),
            sa.ForeignKey("organizations.org_id"),
            nullable=False,
        ),
        sa.Column("cohort_id", sa.String(length=64), nullable=False),
        sa.Column("trust_domain", sa.String(length=64), nullable=False),
        sa.Column("skill_md", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column(
            "status",
            sa.Enum(*_SKILL_STATUS_VALUES, name="skill_status"),
            nullable=False,
            server_default="candidate",
        ),
        sa.Column("applicability_condition", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "source_kind",
            sa.Enum(*_SOURCE_KIND_VALUES, name="skill_source_kind"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_skills_org_cohort_status", "skills", ["org_id", "cohort_id", "status"]
    )
    op.execute(
        "CREATE INDEX ix_skills_embedding "
        "ON skills USING ivfflat "
        "(embedding vector_cosine_ops) WITH (lists = 100)"
    )

    # ----- skill_edges -----
    op.create_table(
        "skill_edges",
        sa.Column(
            "skill_a",
            sa.String(length=64),
            sa.ForeignKey("skills.skill_id"),
            primary_key=True,
        ),
        sa.Column(
            "skill_b",
            sa.String(length=64),
            sa.ForeignKey("skills.skill_id"),
            primary_key=True,
        ),
        sa.Column(
            "edge_type",
            sa.Enum(*_EDGE_TYPE_VALUES, name="skill_edge_type"),
            primary_key=True,
        ),
        sa.Column("risk_score", sa.Numeric(), nullable=True),
        sa.Column("evidence_breach_id", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Index BOTH endpoints for recursive-CTE neighborhood traversal (ADR-0009).
    op.create_index("ix_skill_edges_skill_a", "skill_edges", ["skill_a"])
    op.create_index("ix_skill_edges_skill_b", "skill_edges", ["skill_b"])

    # ----- skill_verifications -----
    op.create_table(
        "skill_verifications",
        sa.Column("verification_id", sa.String(length=48), primary_key=True),
        sa.Column(
            "skill_id",
            sa.String(length=64),
            sa.ForeignKey("skills.skill_id"),
            nullable=False,
        ),
        sa.Column("cohort_id", sa.String(length=64), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(*_VERIFICATION_KIND_VALUES, name="skill_verification_kind"),
            nullable=False,
        ),
        sa.Column("net_effect", sa.Numeric(), nullable=True),
        sa.Column("repairs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("regressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ci_low", sa.Numeric(), nullable=True),
        sa.Column("ci_high", sa.Numeric(), nullable=True),
        sa.Column("leakage_rate", sa.Numeric(), nullable=True),
        sa.Column("held_out_n", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("judge_calibration_ref", sa.String(length=120), nullable=True),
        sa.Column("scan_run_id", sa.String(length=40), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "verdict",
            sa.Enum(*_VERDICT_VALUES, name="skill_verification_verdict"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_skill_verifications_skill_id", "skill_verifications", ["skill_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_skill_verifications_skill_id", table_name="skill_verifications")
    op.drop_table("skill_verifications")
    op.drop_index("ix_skill_edges_skill_b", table_name="skill_edges")
    op.drop_index("ix_skill_edges_skill_a", table_name="skill_edges")
    op.drop_table("skill_edges")
    op.drop_index("ix_skills_embedding", table_name="skills")
    op.drop_index("ix_skills_org_cohort_status", table_name="skills")
    op.drop_table("skills")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS skill_verification_verdict")
        op.execute("DROP TYPE IF EXISTS skill_verification_kind")
        op.execute("DROP TYPE IF EXISTS skill_edge_type")
        op.execute("DROP TYPE IF EXISTS skill_source_kind")
        op.execute("DROP TYPE IF EXISTS skill_status")
