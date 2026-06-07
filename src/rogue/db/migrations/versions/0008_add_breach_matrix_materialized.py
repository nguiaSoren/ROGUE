"""add breach_matrix_daily_snapshot materialized view

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-27

Three persistence mechanisms for the per-cell breach matrix now coexist:

  1. ``breach_matrix`` (VIEW, defined in migration 0002) — always-live.
     Recomputed on every read. The dashboard's `/api/breaches/matrix`
     endpoint queries this; today's data is reflected immediately when a
     new BreachResult lands.

  2. ``breach_matrix_daily_snapshot`` (MATERIALIZED VIEW, added here) —
     frozen-on-refresh. Same SELECT as ``breach_matrix`` but the results
     are physically stored. ``REFRESH MATERIALIZED VIEW
     breach_matrix_daily_snapshot;`` recomputes; otherwise the data is
     whatever was captured at last refresh. Useful for: (a) day-over-day
     diff queries that want a stable yesterday-baseline; (b) cheap
     dashboard queries that don't need today's most-recent rows;
     (c) reproducible analysis that needs a frozen reference point.

  3. CSV snapshot at ``data/breach_matrix_snapshots/YYYY-MM-DD.csv`` —
     written by ``scripts/ops/snapshot_breach_matrix.py``. Plain-text artifact
     for offline analysis / git-diffable archive / sharing in the
     submission packet.

The materialized view's SELECT is intentionally IDENTICAL to the
``breach_matrix`` VIEW (same columns, same aggregation, same NULL guards)
so a query that works against the live view works against the snapshot
unchanged. The difference is purely freshness/cost.

**Refresh strategy**: ROGUE doesn't auto-refresh on INSERT (Postgres
materialized views aren't transactional). The script that fires sweeps
(``scripts/reproduce/reproduce_once.py``, etc.) doesn't refresh either — that would
slow each sweep by ~100ms for marginal value. Instead, the daily snapshot
script + a cron-style invocation refresh on a deliberate cadence.
``REFRESH MATERIALIZED VIEW CONCURRENTLY breach_matrix_daily_snapshot;``
is also legal (requires a unique index, added below) so a refresh during
business hours doesn't block dashboard reads.

**Downgrade**: clean drop. The materialized view holds a copy of data
that survives in ``breach_results`` anyway, so the downgrade loses nothing
unrecoverable.
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Same SELECT as `breach_matrix` VIEW (migration 0002). When that view's
# definition changes, this needs to change in lockstep. Acceptable
# duplication for the two-snapshot pattern; the alternative (one being a
# wrapper over the other) breaks `REFRESH MATERIALIZED VIEW CONCURRENTLY`
# because it requires the matview to be expressible in a single SELECT.
_MATVIEW_SQL = """
CREATE MATERIALIZED VIEW breach_matrix_daily_snapshot AS
SELECT
    primitive_id,
    deployment_config_id,
    DATE(ran_at) AS run_date,
    COUNT(*) AS n_trials,
    COUNT(*) FILTER (WHERE verdict = 'error') AS n_errors,
    COUNT(*) FILTER (WHERE verdict != 'error') AS n_judged,
    (
        COUNT(*) FILTER (WHERE verdict = 'full_breach')::float
        / NULLIF(COUNT(*) FILTER (WHERE verdict != 'error'), 0)
    ) AS full_breach_rate,
    (
        COUNT(*) FILTER (WHERE verdict IN ('full_breach', 'partial_breach'))::float
        / NULLIF(COUNT(*) FILTER (WHERE verdict != 'error'), 0)
    ) AS any_breach_rate,
    AVG(judge_confidence) FILTER (WHERE verdict != 'error') AS avg_confidence
FROM breach_results
GROUP BY primitive_id, deployment_config_id, DATE(ran_at);
"""


def upgrade() -> None:
    op.execute(_MATVIEW_SQL)
    # Unique index on the grouping key enables `REFRESH MATERIALIZED VIEW
    # CONCURRENTLY` — refreshes that don't block reader queries.
    op.execute(
        "CREATE UNIQUE INDEX ix_breach_matrix_daily_snapshot_pk "
        "ON breach_matrix_daily_snapshot "
        "(primitive_id, deployment_config_id, run_date);"
    )
    # Auxiliary index on run_date alone speeds the dashboard's "today vs
    # yesterday" diff query (WHERE run_date = :target_date).
    op.execute(
        "CREATE INDEX ix_breach_matrix_daily_snapshot_run_date "
        "ON breach_matrix_daily_snapshot (run_date);"
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS breach_matrix_daily_snapshot;")
