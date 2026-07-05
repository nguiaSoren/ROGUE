"""agent execution harness — forbidden_tools + agent_transcripts + trace_findings

Revision ID: 0039
Revises: 0038
Create Date: 2026-07-05

Phase 0 of the agent execution harness (docs/v2/agent_harness/DESIGN.md). Lands the
data model dark — nothing writes these tables until the Phase-3/4 harness+judge:

1. ``deployment_configs.forbidden_tools`` — JSON list of tool names the model must
   not invoke (signal (a) of the harness). NOT NULL with a ``'[]'`` server default
   so existing rows are valid. (The platform-side twin lives on
   ``slack_registered_agents``; it is intentionally NOT touched here — v1 scopes
   ``forbidden_tools`` to the core ``deployment_configs`` table. There is no
   ``platform_deployment_configs`` table — review H9.)

2. ``agent_transcripts`` — the replayable trace of one agent run, 1:1 with
   ``breach_results`` via a UNIQUE ``breach_id`` FK (CASCADE). Full trace in a JSON
   ``trace`` blob; ``n_turns`` / ``fired_signals`` / ``seed`` promoted for querying.

3. ``trace_findings`` — one row per per-signal breach finding, CASCADE off the
   transcript. ``headline_eligible`` (indexed) is the mechanical filter the
   deterministic headline ASR respects (Q3 reversed — DESIGN §10): emulated /
   quarantine / fingerprint-less-(c) findings are excluded from the headline.

``signal`` / ``verdict`` / ``severity`` / ``fired_signals`` stay ``String``/JSON (not
PG enums) so the additive ``AgentBreachSignal`` vocabulary extends without a
migration, matching the ``exfil_method`` / ``persona_used`` convention.

**Downgrade**: drop both tables then the column — purely additive, so every
existing query works unchanged once they are gone.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0039"
down_revision: Union[str, Sequence[str], None] = "0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "deployment_configs",
        sa.Column(
            "forbidden_tools",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )

    op.create_table(
        "agent_transcripts",
        sa.Column("transcript_id", sa.String(length=40), primary_key=True),
        sa.Column(
            "breach_id",
            sa.String(length=40),
            sa.ForeignKey("breach_results.breach_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("primitive_id", sa.String(length=40), nullable=False),
        sa.Column("config_id", sa.String(length=40), nullable=False),
        sa.Column("trial_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("seed", sa.BigInteger(), nullable=True),
        sa.Column("n_turns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "stop_reason", sa.String(length=40), nullable=False, server_default="final_text"
        ),
        sa.Column("fired_signals", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("trace", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_agent_transcripts_breach_id", "agent_transcripts", ["breach_id"], unique=True
    )
    op.create_index("ix_agent_transcripts_primitive_id", "agent_transcripts", ["primitive_id"])
    op.create_index("ix_agent_transcripts_config_id", "agent_transcripts", ["config_id"])

    op.create_table(
        "trace_findings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "transcript_id",
            sa.String(length=40),
            sa.ForeignKey("agent_transcripts.transcript_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("signal", sa.String(length=48), nullable=False),
        sa.Column("verdict", sa.String(length=20), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column(
            "headline_eligible", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "emulated_involved", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("source_return_call_id", sa.String(length=40), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index("ix_trace_findings_transcript_id", "trace_findings", ["transcript_id"])
    op.create_index(
        "ix_trace_findings_headline_eligible", "trace_findings", ["headline_eligible"]
    )


def downgrade() -> None:
    op.drop_index("ix_trace_findings_headline_eligible", table_name="trace_findings")
    op.drop_index("ix_trace_findings_transcript_id", table_name="trace_findings")
    op.drop_table("trace_findings")

    op.drop_index("ix_agent_transcripts_config_id", table_name="agent_transcripts")
    op.drop_index("ix_agent_transcripts_primitive_id", table_name="agent_transcripts")
    op.drop_index("ix_agent_transcripts_breach_id", table_name="agent_transcripts")
    op.drop_table("agent_transcripts")

    op.drop_column("deployment_configs", "forbidden_tools")
