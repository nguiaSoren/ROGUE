"""distill-from-failure — strategy_avoid_rules (negative cross-run memory)

Revision ID: 0047
Revises: 0046
Create Date: 2026-07-19

Adds the loser-side twin of the attack_strategies winner lifecycle (audit 5, rec #1). Where a win
graduates a technique, a target *refusal* is distilled into an avoid-rule here — the heuristic reason
the target gave for refusing ($0, no LLM call; reproduce/refusal_distill.extract_refusal_reason). The
top-k relevant rules are injected into the escalation-planner / iterative-attacker prompts as an AVOID
block, so every daily-run refusal becomes compounding signal instead of being discarded.

Keyed by (technique_id, target-context, reason_category) — target context (vendor/family/size_class)
mirrors ladder_attempts and is only set for a single-config panel; a multi-model sweep stores the rule
globally (all three NULL). Recurring refusals bump hit_count rather than duplicating (unique key). Rows
are written ONLY under the ROGUE_DISTILL_FAILURE Arm flag, so a flag-off run touches this table zero
times — pre-flag and flag-off behavior is byte-identical. No hard FK (soft ref to
attack_strategies.technique_id, like ladder_attempts). Downgrade: drop the table (+ its indexes).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0047"
down_revision: Union[str, Sequence[str], None] = "0046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "strategy_avoid_rules",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("technique_id", sa.String(length=40), nullable=False),
        sa.Column("target_vendor", sa.String(length=40), nullable=True),
        sa.Column("target_family", sa.String(length=40), nullable=True),
        sa.Column("target_size_class", sa.String(length=20), nullable=True),
        sa.Column("reason_category", sa.String(length=40), nullable=False),
        sa.Column("reason_text", sa.Text(), nullable=False),
        sa.Column("hit_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "technique_id",
            "target_vendor",
            "target_family",
            "target_size_class",
            "reason_category",
            name="uq_strategy_avoid_rule_key",
        ),
    )
    op.create_index(
        "ix_strategy_avoid_rules_technique_id",
        "strategy_avoid_rules",
        ["technique_id"],
    )
    op.create_index(
        "ix_strategy_avoid_rules_reason_category",
        "strategy_avoid_rules",
        ["reason_category"],
    )
    op.create_index(
        "ix_strategy_avoid_rules_last_seen_at",
        "strategy_avoid_rules",
        ["last_seen_at"],
    )
    op.create_index(
        "ix_strategy_avoid_rules_lookup",
        "strategy_avoid_rules",
        ["technique_id", "target_vendor", "target_family"],
    )


def downgrade() -> None:
    op.drop_index("ix_strategy_avoid_rules_lookup", table_name="strategy_avoid_rules")
    op.drop_index("ix_strategy_avoid_rules_last_seen_at", table_name="strategy_avoid_rules")
    op.drop_index(
        "ix_strategy_avoid_rules_reason_category", table_name="strategy_avoid_rules"
    )
    op.drop_index(
        "ix_strategy_avoid_rules_technique_id", table_name="strategy_avoid_rules"
    )
    op.drop_table("strategy_avoid_rules")
