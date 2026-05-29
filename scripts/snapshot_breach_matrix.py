"""Snapshot the breach_matrix VIEW to disk + refresh the materialized view.

Two outputs per run:
  1. CSV at ``data/breach_matrix_snapshots/YYYY-MM-DD.csv`` — flat-file
     daily archive. Stable shape; diffable across days. Used for offline
     analysis + the submission packet's matrix archive.

  2. Refresh of ``breach_matrix_daily_snapshot`` MATERIALIZED VIEW —
     in-DB frozen baseline for the dashboard's day-over-day diff queries
     (`REFRESH MATERIALIZED VIEW CONCURRENTLY` so dashboard reads aren't
     blocked during the refresh).

By default snapshots TODAY's slice (rows where ``run_date = CURRENT_DATE``).
Pass ``--all-dates`` to dump every row in the view; pass ``--date YYYY-MM-DD``
to snapshot a specific day.

Spec: ROGUE_PLAN.md §10.3 (matrix view) + migration `0008_add_breach_matrix_materialized.py`.
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from datetime import date as date_cls, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import create_engine, text  # noqa: E402

logger = logging.getLogger("rogue.scripts.snapshot_breach_matrix")

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"
)
DEFAULT_SNAPSHOT_DIR = Path("data/breach_matrix_snapshots")

_CSV_COLUMNS = (
    "primitive_id",
    "deployment_config_id",
    "run_date",
    "n_trials",
    "n_errors",
    "n_judged",
    "full_breach_rate",
    "any_breach_rate",
    "avg_confidence",
)


def _snapshot_csv(
    *,
    database_url: str,
    output_dir: Path,
    target_date: date_cls | None,
) -> Path:
    """Dump ``breach_matrix`` view rows to a CSV. Returns the path written."""
    engine = create_engine(database_url)
    output_dir.mkdir(parents=True, exist_ok=True)
    fname_date = (target_date or datetime.now(timezone.utc).date()).isoformat()
    csv_path = output_dir / f"{fname_date}.csv"

    if target_date is None:
        # All-dates dump: filename uses today as the snapshot timestamp.
        query = "SELECT * FROM breach_matrix ORDER BY run_date, primitive_id, deployment_config_id"
        params = {}
        csv_path = output_dir / f"all-dates-as-of-{fname_date}.csv"
    else:
        query = (
            "SELECT * FROM breach_matrix "
            "WHERE run_date = :target_date "
            "ORDER BY primitive_id, deployment_config_id"
        )
        params = {"target_date": target_date}

    with engine.connect() as conn:
        result = conn.execute(text(query), params)
        rows = result.mappings().all()

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col) for col in _CSV_COLUMNS})
    engine.dispose()
    return csv_path


def _refresh_matview(database_url: str, concurrently: bool = True) -> None:
    """REFRESH the breach_matrix_daily_snapshot materialized view.

    Concurrently=True doesn't block dashboard reads but takes ~2× as long
    and requires the unique index added in migration 0008 (which is there).
    Set False for a faster refresh when no dashboard reads are in flight.
    """
    engine = create_engine(database_url)
    qualifier = "CONCURRENTLY " if concurrently else ""
    try:
        with engine.connect() as conn:
            # REFRESH MATERIALIZED VIEW must run outside a transaction in
            # some Postgres versions. Use the AUTOCOMMIT isolation level.
            conn = conn.execution_options(isolation_level="AUTOCOMMIT")
            conn.execute(
                text(
                    f"REFRESH MATERIALIZED VIEW {qualifier}breach_matrix_daily_snapshot;"
                ),
            )
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Snapshot breach_matrix view to CSV + refresh matview.",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_SNAPSHOT_DIR,
    )
    parser.add_argument(
        "--date",
        type=date_cls.fromisoformat,
        default=None,
        help="ISO date (YYYY-MM-DD). Defaults to today. Pass --all-dates to dump everything.",
    )
    parser.add_argument(
        "--all-dates",
        action="store_true",
        help="Dump every row in breach_matrix (all run_dates), not just one day.",
    )
    parser.add_argument(
        "--no-refresh-matview",
        action="store_true",
        help="Skip the REFRESH MATERIALIZED VIEW step (CSV-only run).",
    )
    parser.add_argument(
        "--no-concurrent-refresh",
        action="store_true",
        help=(
            "REFRESH without the CONCURRENTLY qualifier — faster but blocks "
            "dashboard reads during the refresh. Use when no dashboard "
            "consumers are in flight."
        ),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    target_date = None if args.all_dates else (
        args.date or datetime.now(timezone.utc).date()
    )

    csv_path = _snapshot_csv(
        database_url=args.database_url,
        output_dir=args.output_dir,
        target_date=target_date,
    )
    n_rows = sum(1 for _ in csv_path.open(encoding="utf-8")) - 1  # minus header
    logger.info(
        "wrote CSV snapshot: %s (%d rows%s)",
        csv_path, n_rows,
        f", target_date={target_date}" if target_date else " all dates",
    )

    if not args.no_refresh_matview:
        _refresh_matview(
            database_url=args.database_url,
            concurrently=not args.no_concurrent_refresh,
        )
        logger.info(
            "refreshed breach_matrix_daily_snapshot (concurrently=%s)",
            not args.no_concurrent_refresh,
        )

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
