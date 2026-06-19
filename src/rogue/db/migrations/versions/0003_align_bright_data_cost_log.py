"""align bright_data_cost_log with ORM

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-27

Resolves the §STATUS-tracked schema drift between
``rogue.db.models.BrightDataCostLog`` and the 0001 initial-schema migration:

  - ORM declares    : (id, product, units, cost_usd, ran_at, notes) + CHECK on product
  - 0001 created    : (id, ran_at, product, url, success, estimated_cost_usd, latency_ms)

The ORM follows the §8.3 task spec ("(id, product, units, cost_usd, ran_at,
notes)"); the 0001 migration was generated from the slightly-different §A.5
snippet and never reconciled. Effect: every ``BrightDataCostLog(cost_usd=...,
units=..., ...)`` INSERT in ``BrightDataClient._log_cost`` raised
``ProgrammingError: column "cost_usd" does not exist`` and rolled back
silently; the table has been empty since first harvest.

This migration is non-destructive (ALTER, not DROP+CREATE) but assumes the
table is empty — which it is, per the above. The ``units`` column is added
with a temporary ``server_default='0'`` so the NOT NULL constraint is
satisfiable on any straggler row, then the default is dropped so subsequent
INSERTs must supply ``units`` explicitly (matching the ORM contract).

Adds the CHECK constraint on ``product`` to mirror the ORM's
``ck_bright_data_cost_log_product`` constraint — both 0001 and the ORM agree
on the column type (String(40)), but only the ORM declared the CHECK.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Mirror rogue.schemas.source_provenance.BrightDataProduct. Kept inline per
# the 0001-migration convention so this file stays importable without
# application code.
BRIGHT_DATA_PRODUCT_VALUES = (
    "web_scraper_api",
    "serp_api",
    "web_unlocker",
    "scraping_browser",
    "mcp",
)


def _quoted_csv(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    """Upgrade schema — morph bright_data_cost_log to the ORM contract."""
    # Add `units` (NOT NULL) with a transient server_default to cover any
    # legacy rows; drop the default so the application is forced to provide
    # units on every INSERT (matches the ORM's `Mapped[int]` declaration).
    op.add_column(
        "bright_data_cost_log",
        sa.Column("units", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("bright_data_cost_log", "units", server_default=None)

    # Add `notes` (nullable Text) — ORM declares `Optional[str]`.
    op.add_column(
        "bright_data_cost_log",
        sa.Column("notes", sa.Text(), nullable=True),
    )

    # Rename estimated_cost_usd → cost_usd.
    op.alter_column(
        "bright_data_cost_log",
        "estimated_cost_usd",
        new_column_name="cost_usd",
    )

    # Drop legacy columns no longer in the ORM contract.
    op.drop_column("bright_data_cost_log", "url")
    op.drop_column("bright_data_cost_log", "success")
    op.drop_column("bright_data_cost_log", "latency_ms")

    # Add the CHECK constraint that the ORM has declared since Day 0.
    op.create_check_constraint(
        "ck_bright_data_cost_log_product",
        "bright_data_cost_log",
        f"product IN ({_quoted_csv(BRIGHT_DATA_PRODUCT_VALUES)})",
    )


def downgrade() -> None:
    """Downgrade schema — restore the 0001-shape column set."""
    op.drop_constraint(
        "ck_bright_data_cost_log_product",
        "bright_data_cost_log",
        type_="check",
    )

    # Re-add legacy columns with transient server_defaults so NOT NULL holds
    # on any rows written under the 0003-shape, then drop the defaults to
    # match the 0001 declaration.
    op.add_column(
        "bright_data_cost_log",
        sa.Column("url", sa.Text(), nullable=False, server_default=""),
    )
    op.alter_column("bright_data_cost_log", "url", server_default=None)

    op.add_column(
        "bright_data_cost_log",
        sa.Column(
            "success",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.alter_column("bright_data_cost_log", "success", server_default=None)

    op.add_column(
        "bright_data_cost_log",
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("bright_data_cost_log", "latency_ms", server_default=None)

    # Rename cost_usd → estimated_cost_usd.
    op.alter_column(
        "bright_data_cost_log",
        "cost_usd",
        new_column_name="estimated_cost_usd",
    )

    op.drop_column("bright_data_cost_log", "notes")
    op.drop_column("bright_data_cost_log", "units")
