"""reconcile CHECK-constraint vocabularies with the ORM + add missing platform indexes

Revision ID: 0030
Revises: 0029
Create Date: 2026-06-08

Closes three storage/ORM drifts surfaced by the v2 schema audit:

1. ``bright_data_cost_log.product`` CHECK was hand-listed in migration 0003 as
   ``(web_scraper_api, serp_api, web_unlocker, scraping_browser, mcp)`` — which
   never matched the canonical ``BrightDataProduct`` Literal
   ``(web_scraper_api, serp, web_unlocker, scraping_browser, mcp_server, fixture)``
   that the ORM's CHECK derives from via ``typing.get_args``. The harvest client
   was even writing ``product="serp_api"`` (now fixed to ``"serp"``). We migrate
   the existing ``serp_api``/``mcp`` rows to the canonical tokens, then rebuild
   the CHECK from the canonical vocabulary so storage == wire.

2. ``source_provenances`` declared ``ck_source_provenances_source_type`` and
   ``ck_source_provenances_bright_data_product`` in the ORM, but 0001 created the
   columns as plain ``String(40)`` and no migration ever added the CHECKs — so
   the live DB had zero value-validation there. We add them (verified clean
   against live data: every existing value is in-vocabulary).

3. ``scan_jobs.org_id`` and ``scan_runs.project_id`` are declared ``index=True``
   in the platform ORM but migration 0022 never created the indexes — leaving the
   worker queue / per-tenant listing on seq-scans. We add them.

Non-destructive. The data migration (serp_api→serp) runs BEFORE the CHECK
rebuild so no existing row violates the new constraint.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0030"
down_revision: Union[str, Sequence[str], None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Inlined per the 0001/0003 migration convention (keeps this file importable
# without application code). These MUST stay in sync with
# rogue.schemas.source_provenance.{BrightDataProduct, SourceType}.
PRODUCT_VALUES_NEW = (
    "web_scraper_api",
    "serp",
    "web_unlocker",
    "scraping_browser",
    "mcp_server",
    "fixture",
)
PRODUCT_VALUES_OLD = (
    "web_scraper_api",
    "serp_api",
    "web_unlocker",
    "scraping_browser",
    "mcp",
)
SOURCE_TYPE_VALUES = (
    "reddit",
    "x",
    "arxiv",
    "github",
    "huggingface",
    "blog",
    "mitre",
    "owasp",
    "vendor_safety_blog",
    "discord_archive",
    "community_archive",
    "other",
)


def _quoted_csv(values: Sequence[str]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # 1) Migrate legacy cost-log product tokens to the canonical vocabulary
    #    BEFORE rebuilding the CHECK, so no existing row violates it.
    op.execute("UPDATE bright_data_cost_log SET product = 'serp' WHERE product = 'serp_api'")
    op.execute("UPDATE bright_data_cost_log SET product = 'mcp_server' WHERE product = 'mcp'")

    op.drop_constraint(
        "ck_bright_data_cost_log_product", "bright_data_cost_log", type_="check"
    )
    op.create_check_constraint(
        "ck_bright_data_cost_log_product",
        "bright_data_cost_log",
        f"product IN ({_quoted_csv(PRODUCT_VALUES_NEW)})",
    )

    # 2) Add the source_provenances CHECKs the ORM has always declared.
    op.create_check_constraint(
        "ck_source_provenances_source_type",
        "source_provenances",
        f"source_type IN ({_quoted_csv(SOURCE_TYPE_VALUES)})",
    )
    op.create_check_constraint(
        "ck_source_provenances_bright_data_product",
        "source_provenances",
        f"bright_data_product IN ({_quoted_csv(PRODUCT_VALUES_NEW)})",
    )

    # 3) Add the platform indexes the ORM declares (index=True) but 0022 omitted.
    op.create_index("ix_scan_jobs_org_id", "scan_jobs", ["org_id"])
    op.create_index("ix_scan_runs_project_id", "scan_runs", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_scan_runs_project_id", table_name="scan_runs")
    op.drop_index("ix_scan_jobs_org_id", table_name="scan_jobs")

    op.drop_constraint(
        "ck_source_provenances_bright_data_product", "source_provenances", type_="check"
    )
    op.drop_constraint(
        "ck_source_provenances_source_type", "source_provenances", type_="check"
    )

    # Revert cost-log tokens, then restore the old (0003) CHECK vocabulary.
    op.execute("UPDATE bright_data_cost_log SET product = 'serp_api' WHERE product = 'serp'")
    op.execute("UPDATE bright_data_cost_log SET product = 'mcp' WHERE product = 'mcp_server'")
    op.drop_constraint(
        "ck_bright_data_cost_log_product", "bright_data_cost_log", type_="check"
    )
    op.create_check_constraint(
        "ck_bright_data_cost_log_product",
        "bright_data_cost_log",
        f"product IN ({_quoted_csv(PRODUCT_VALUES_OLD)})",
    )
