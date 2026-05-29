"""breach_matrix baseline-only — exclude augmentation re-runs

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-28

Persona-wrapped (``persona_used IS NOT NULL``) and PAIR-refined
(``pair_attacker_total_cost_usd IS NOT NULL``) breach_results are *re-runs of
an attack that already has a baseline row*. Aggregating them into the same
(primitive × config × date) cell blended augmentation effects into the
single-shot baseline breach rate the matrix is meant to show — the same class
of bug as the persona-stats contamination fixed in `api/main.py` on
2026-05-28 (PAIR's ~100% iterations were being counted as a "persona").

Both the ``breach_matrix`` VIEW (migration 0002) and the
``breach_matrix_daily_snapshot`` MATERIALIZED VIEW (migration 0008) now filter
to baseline single-shot rows only. Augmentation effects live in the §10.7
stats endpoints / dashboard tiles, not the matrix.

Downgrade restores the unfiltered 0002/0008 definitions.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Baseline single-shot only: drop persona wraps + PAIR refinements (both are
# re-runs of an existing primitive that would otherwise blend into its cell).
_BASELINE_FILTER = (
    "WHERE persona_used IS NULL AND pair_attacker_total_cost_usd IS NULL"
)


def _select(with_filter: bool) -> str:
    where = _BASELINE_FILTER if with_filter else ""
    return f"""
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
{where}
GROUP BY primitive_id, deployment_config_id, DATE(ran_at)
"""


_INDEXES = (
    "CREATE UNIQUE INDEX ix_breach_matrix_daily_snapshot_pk "
    "ON breach_matrix_daily_snapshot "
    "(primitive_id, deployment_config_id, run_date);",
    "CREATE INDEX ix_breach_matrix_daily_snapshot_run_date "
    "ON breach_matrix_daily_snapshot (run_date);",
)


def _rebuild(*, with_filter: bool) -> None:
    # CREATE OR REPLACE keeps the column list identical (Postgres requires it),
    # so the view swap is in-place. The matview must be dropped + recreated
    # (no REPLACE for matviews); CREATE ... AS populates it WITH DATA.
    op.execute("CREATE OR REPLACE VIEW breach_matrix AS" + _select(with_filter) + ";")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS breach_matrix_daily_snapshot;")
    op.execute(
        "CREATE MATERIALIZED VIEW breach_matrix_daily_snapshot AS"
        + _select(with_filter)
        + ";"
    )
    for idx in _INDEXES:
        op.execute(idx)


def upgrade() -> None:
    _rebuild(with_filter=True)


def downgrade() -> None:
    _rebuild(with_filter=False)
