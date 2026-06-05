"""adaptive technique prioritization — vendor/family + winner segmentation columns

Phase 2 of Adaptive Technique Prioritization. Adds denormalized vendor/family and
a causal-winner flag to ``ladder_attempts`` so escalation telemetry can be sliced
by model maker and by which attempt actually broke the ladder, and adds a
``ladder_order`` policy tag to ``benchmark_runs`` so the external-ASR timeline can
be segmented by ladder-ordering policy.

Notes:
  * ``ladder_attempts`` already stores ladder depth as ``ladder_depth`` (tier 1..5),
    so no new depth column is added — the existing one is reused.
  * vendor = model maker (anthropic/openai/google/...), DISTINCT from the routing
    provider/backend (openrouter/anthropic/groq) in target_panel._PROVIDER_ROUTES.

All columns are additive and NULLABLE, so the migration is safe on the populated
prod ``ladder_attempts`` / ``benchmark_runs`` tables (no backfill required).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0025"
down_revision: Union[str, Sequence[str], None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ladder_attempts",
        sa.Column("target_vendor", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "ladder_attempts",
        sa.Column("target_family", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "ladder_attempts",
        sa.Column(
            "is_winner",
            sa.Boolean(),
            nullable=True,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "benchmark_runs",
        sa.Column("ladder_order", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("benchmark_runs", "ladder_order")
    op.drop_column("ladder_attempts", "is_winner")
    op.drop_column("ladder_attempts", "target_family")
    op.drop_column("ladder_attempts", "target_vendor")
