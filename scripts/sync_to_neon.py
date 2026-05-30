"""Push the local pipeline's results to the live Neon DB — data-only, no spend.

The dashboard reads Neon; the `$`-billed scripts write the local docker DB. This
copies the display-critical tables (configs, primitives, provenance, breach
results, PAIR steps, bandit state) local → Neon with idempotent upserts and
**zero LLM/BD calls** — so a local re-grade / reproduce surfaces on the live
site. It runs AUTOMATICALLY at the end of `harvest_once` / `reproduce_once` /
`rejudge_batch` / `second_grader_pass` when ``NEON_DATABASE_URL`` is set; this
script is the manual/standalone entry point for the same operation.

Usage::

    # .env (or shell): point at the Neon connection string
    export NEON_DATABASE_URL='postgresql+psycopg://USER:PASS@HOST/neondb?sslmode=require'

    uv run python scripts/sync_to_neon.py             # local → Neon
    uv run python scripts/sync_to_neon.py --dry-run   # show counts, commit nothing
    uv run python scripts/sync_to_neon.py --source <url> --dest <url>
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from rogue.db.neon_sync import looks_like_placeholder, sync  # noqa: E402

DEFAULT_LOCAL_URL = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Data-only local → Neon sync (no LLM/BD spend).")
    parser.add_argument(
        "--source",
        default=os.environ.get("DATABASE_URL", DEFAULT_LOCAL_URL),
        help="Source DB (default: DATABASE_URL or local docker).",
    )
    parser.add_argument(
        "--dest",
        default=os.environ.get("NEON_DATABASE_URL"),
        help="Destination DB (default: NEON_DATABASE_URL).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Roll back instead of commit.")
    parser.add_argument(
        "--no-refresh-snapshot",
        action="store_true",
        help="Skip the materialized-snapshot refresh on the destination.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")

    if not args.dest:
        print(
            "error: no destination — set NEON_DATABASE_URL or pass --dest <url>",
            file=sys.stderr,
        )
        return 2

    if looks_like_placeholder(args.dest):
        print(
            "error: NEON_DATABASE_URL is still the placeholder "
            "(postgresql+psycopg://USER:PASS@HOST/neondb?sslmode=require).\n"
            "       Put your REAL Neon connection string there — find it in the Neon\n"
            "       dashboard (Connection Details → connection string) or the Render\n"
            "       service's DATABASE_URL env var. It must NOT contain USER, PASS, or HOST.",
            file=sys.stderr,
        )
        return 2

    from sqlalchemy.exc import OperationalError

    try:
        result = sync(
            args.source,
            args.dest,
            dry_run=args.dry_run,
            refresh_snapshot=not args.no_refresh_snapshot,
        )
    except OperationalError as exc:
        # Clean one-liner instead of a 100-line SQLAlchemy/psycopg traceback.
        host = args.dest.rsplit("@", 1)[-1].split("/", 1)[0]
        print(
            f"error: could not connect to the destination DB (host '{host}'): "
            f"{exc.orig.__class__.__name__ if exc.orig else type(exc).__name__}.\n"
            "       Check the NEON_DATABASE_URL host/credentials and that the DB is reachable.",
            file=sys.stderr,
        )
        return 1
    if not result.get("synced"):
        print(f"skipped: {result.get('reason')}")
        return 0
    total = sum(result["counts"].values())
    mode = "DRY-RUN (no commit)" if args.dry_run else "committed"
    print(f"{mode}: {total} rows synced — {result['counts']}")
    return 0


if __name__ == "__main__":  # pragma: no cover — exercised via the unit-tested sync()
    sys.exit(main())
