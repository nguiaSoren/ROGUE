"""customer-real tools (Level 1 tool_specs) + taxonomy misfit flag

Revision ID: 0040
Revises: 0039
Create Date: 2026-07-05

Extension of the agent execution harness (docs/v2/agent_harness/) so a scan can exercise a
customer's REAL tool surface, plus a taxonomy-fit flag on extracted primitives:

1. ``deployment_configs.tool_specs`` — nullable JSON list of AgentToolSpec dicts. Level 1
   (bring-your-own tool schema): the model is tested against the customer's exact production
   tool surface; returns stay ROGUE-simulated. NULL = today's behaviour (synthesize specs from
   ``declared_tools`` names). (Level 2 ``live_tool_target`` is deliberately NOT persisted — it
   carries auth-header secrets; it is an ephemeral scan-time field like ``base_url``.)

2. ``attack_primitives.taxonomy_fit`` (clear|weak|novel, default 'clear') + ``taxonomy_fit_note``
   — a misfit signal set by the extraction agent when a technique doesn't cleanly map to the
   frozen (family, vector) enums, surfacing HUMAN-approved taxonomy-extension candidates. The
   extractor NEVER auto-adds an enum value. 'clear' server-default keeps existing rows valid.

**Downgrade**: drop the three columns — purely additive, every existing query works unchanged.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0040"
down_revision: Union[str, Sequence[str], None] = "0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "deployment_configs",
        sa.Column("tool_specs", sa.JSON(), nullable=True),
    )
    op.add_column(
        "attack_primitives",
        sa.Column(
            "taxonomy_fit",
            sa.String(length=10),
            nullable=False,
            server_default="clear",
        ),
    )
    op.add_column(
        "attack_primitives",
        sa.Column("taxonomy_fit_note", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("attack_primitives", "taxonomy_fit_note")
    op.drop_column("attack_primitives", "taxonomy_fit")
    op.drop_column("deployment_configs", "tool_specs")
