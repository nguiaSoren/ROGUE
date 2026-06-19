"""add benchmark_runs — durable external-benchmark history (AdvBench/JBB over time)

ROGUE's internal metrics measure how the system behaves; none measure whether the
repertoire improved against a fixed external reference. The benchmark layer
(``benchmark/``) runs the frozen AdvBench/JBB goal sets against a target and
records one row per run here, so the ``date -> ASR/coverage`` timeline — the
figure that proves the orchestration work mattered — lives on Neon and survives
any single machine (a local file would not). Append-only telemetry; this is run
*results*, NOT benchmark goals (those stay frozen in git, never ingested as
primitives — the eval/generation wall holds).

New table only — no change to existing tables.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: Union[str, Sequence[str], None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "benchmark_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_label", sa.String(length=80), nullable=False),
        sa.Column(
            "run_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("dataset", sa.String(length=40), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("target_model", sa.String(length=80), nullable=False),
        sa.Column("n_goals", sa.Integer(), nullable=False),
        sa.Column("n_breached", sa.Integer(), nullable=False),
        sa.Column("asr", sa.Float(), nullable=False),
        sa.Column("repertoire_size", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("git_sha", sa.String(length=40), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_benchmark_runs_run_label", "benchmark_runs", ["run_label"])
    op.create_index("ix_benchmark_runs_run_at", "benchmark_runs", ["run_at"])
    op.create_index("ix_benchmark_runs_dataset", "benchmark_runs", ["dataset"])


def downgrade() -> None:
    op.drop_index("ix_benchmark_runs_dataset", table_name="benchmark_runs")
    op.drop_index("ix_benchmark_runs_run_at", table_name="benchmark_runs")
    op.drop_index("ix_benchmark_runs_run_label", table_name="benchmark_runs")
    op.drop_table("benchmark_runs")
