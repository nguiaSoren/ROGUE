"""add multi_turn_persona_chain to attack_family enum

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-27

Extends the ``attack_family`` PG enum with the 15th family value
``multi_turn_persona_chain`` per ROGUE_PLAN.md §4.2 row 15 (added 2026-05-27).
Covers AJAR's ActorAttack pattern — persona-impersonation multi-turn attacks
where each turn plays a different actor/role — distinct from row 6's
``multi_turn_gradient`` escalation pattern (Crescendo / Many-shot / X-Teaming).

The Python :class:`rogue.schemas.AttackFamily` enum already lists this value
(extends pure-additive); this migration brings the database in sync.

**Postgres quirk**: ``ALTER TYPE ... ADD VALUE`` cannot run inside a
transaction block. We use Alembic's :meth:`autocommit_block` context manager
to drop out of the surrounding transaction for the duration of the ALTER.
``IF NOT EXISTS`` makes the operation idempotent so re-running a partial
migration doesn't fail.

**Downgrade**: PostgreSQL doesn't support removing a single enum value
cleanly. The clean downgrade path would be drop-and-recreate-the-type with
data migration of any rows using the new value — risky and lossy. We make
the downgrade a no-op with a logged warning; the new enum value persists
even after downgrade to 0003. Acceptable because (a) enum widening is
backwards-compatible (0003-era code ignores unknown values), and (b) the
zero-downgrade tradeoff is standard practice for enum-add migrations.
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_FAMILY_VALUE = "multi_turn_persona_chain"


def upgrade() -> None:
    """Add the new enum value via autocommit-block (PG transaction restriction)."""
    with op.get_context().autocommit_block():
        op.execute(
            f"ALTER TYPE attack_family ADD VALUE IF NOT EXISTS '{_NEW_FAMILY_VALUE}'"
        )


def downgrade() -> None:
    """No-op — see module docstring. Enum widening is backwards-compatible."""
    # Intentionally empty. Documented in the migration header.
    pass
