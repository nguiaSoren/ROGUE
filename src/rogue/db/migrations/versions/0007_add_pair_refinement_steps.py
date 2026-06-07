"""add pair_refinement_steps + refinement-history columns

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-27

§10.7 full PAIR build — per-iteration history persistence with
``RefinementStep`` chain. Adds:

  1. ``pair_refinement_steps`` table: one row per (cell × iteration) capturing
     the attacker's proposal, the target's response, the judge's verdict +
     score, and the per-call attacker cost. Linked to BreachResult via
     ``breach_id`` FK so the dashboard can replay the conversation chain
     for any breached cell.

  2. ``breach_results.pair_iters_to_breach`` (nullable Integer): the
     iteration index at which the cell first breached, or NULL if it never
     breached. Drives the dashboard "stubbornness" metric (avg iters to
     breach per config).

  3. ``breach_results.pair_attacker_total_cost_usd`` (nullable Float): sum
     of attacker_cost_usd across all RefinementSteps for this cell. NULL
     for non-PAIR breaches (the existing baseline corpus). Lets the
     dashboard show per-config $-cost of cracking it.

The ``pair_refinement_steps`` table has a composite index on
``(breach_id, iter_index)`` so the dashboard's chain-replay query
(``ORDER BY iter_index ASC WHERE breach_id = ?``) is index-served.

**Downgrade**: drops both columns + the table cleanly. ``pair_iters_to_breach``
and ``pair_attacker_total_cost_usd`` are nullable and not referenced by any
view yet, so existing rows survive the downgrade unchanged.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pair_refinement_steps",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "breach_id",
            sa.String(length=40),
            sa.ForeignKey("breach_results.breach_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("iter_index", sa.Integer(), nullable=False),
        # The refinement_type strategy picked by the attacker LLM (§10.7).
        # Free-form String so we can extend the taxonomy without a migration.
        # Current values: roleplaying / logical_appeal / authority_endorsement
        # / obfuscation / multi_turn_escalation / syntactic_mutation.
        sa.Column("refinement_type", sa.String(length=40), nullable=False),
        sa.Column("attacker_model", sa.String(length=80), nullable=False),
        sa.Column("proposed_prompt", sa.Text(), nullable=False),
        sa.Column("improvement", sa.Text(), nullable=False),
        sa.Column("target_response", sa.Text(), nullable=False),
        # Verdict on this iteration's target response. We don't enum-constrain
        # at the SQL layer (judge_verdict enum is on breach_results); the
        # values match `rogue.schemas.JudgeVerdict`.
        sa.Column("verdict", sa.String(length=40), nullable=False),
        # 1-10 score (PAIR's training-data convention). See VERDICT_SCORE_MAP
        # in scripts/reproduce/pair_attacker_ab.py for the canonical mapping.
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("attacker_cost_usd", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_pair_refinement_steps_breach_id_iter_index",
        "pair_refinement_steps",
        ["breach_id", "iter_index"],
    )
    # CHECK constraint so iter_index is never negative — surfaces orchestrator
    # bugs immediately rather than silently corrupting the chain.
    op.create_check_constraint(
        "ck_pair_refinement_steps_iter_index_nonneg",
        "pair_refinement_steps",
        "iter_index >= 0",
    )
    op.create_check_constraint(
        "ck_pair_refinement_steps_score_range",
        "pair_refinement_steps",
        "score >= 1 AND score <= 10",
    )

    op.add_column(
        "breach_results",
        sa.Column("pair_iters_to_breach", sa.Integer(), nullable=True),
    )
    op.add_column(
        "breach_results",
        sa.Column("pair_attacker_total_cost_usd", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("breach_results", "pair_attacker_total_cost_usd")
    op.drop_column("breach_results", "pair_iters_to_breach")
    op.drop_constraint(
        "ck_pair_refinement_steps_score_range",
        "pair_refinement_steps",
        type_="check",
    )
    op.drop_constraint(
        "ck_pair_refinement_steps_iter_index_nonneg",
        "pair_refinement_steps",
        type_="check",
    )
    op.drop_index(
        "ix_pair_refinement_steps_breach_id_iter_index",
        table_name="pair_refinement_steps",
    )
    op.drop_table("pair_refinement_steps")
