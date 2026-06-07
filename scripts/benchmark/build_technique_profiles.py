"""Build technique profiles and print them as JSON or a summary count.

Usage::

    # Summary count by origin/tier (default):
    uv run python scripts/benchmark/build_technique_profiles.py

    # Full JSON output:
    uv run python scripts/benchmark/build_technique_profiles.py --json

    # With a live database (adds harvested + telemetry coverage):
    uv run python scripts/benchmark/build_technique_profiles.py --database-url postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue

No DB writes — this script only builds and displays profiles.  Embedding and
storage is handled by a separate step (Engineer 3's script).
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build TechniqueProfile objects and display summary or JSON."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print all profiles as a JSON array (default: print summary counts).",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help=(
            "SQLAlchemy database URL.  When omitted, only ARMS + tier profiles are "
            "built (no DB connection attempted).  Falls back to DATABASE_URL env var."
        ),
    )
    return parser.parse_args()


def _get_session(database_url: str | None):
    """Return a SQLAlchemy Session for the given URL, or None."""
    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        return None

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    try:
        engine = create_engine(url, connect_args={"connect_timeout": 5})
        Session = sessionmaker(bind=engine)
        session = Session()
        # Probe connectivity
        from sqlalchemy import text
        session.execute(text("SELECT 1"))
        return session
    except Exception as exc:
        print(f"[warn] Could not connect to database: {exc}", file=sys.stderr)
        return None


def main() -> None:
    args = _parse_args()

    session = _get_session(args.database_url)

    from rogue.retrieval.technique_profile_builder import build_technique_profiles

    profiles = build_technique_profiles(session)

    if session is not None:
        try:
            session.close()
        except Exception:
            pass

    if args.json:
        print(json.dumps([p.model_dump() for p in profiles], indent=2))
        return

    # Summary mode — counts by origin, then by tier for "tier" origin
    from collections import Counter

    by_origin: Counter[str] = Counter(p.origin for p in profiles)
    by_tier: Counter[str] = Counter(
        p.tier for p in profiles if p.origin == "tier"
    )

    print(f"Total profiles: {len(profiles)}")
    print()
    print("By origin:")
    for origin, count in sorted(by_origin.items()):
        print(f"  {origin:12s}  {count}")

    if by_tier:
        print()
        print("Tier breakdown (origin=tier):")
        for tier, count in sorted(by_tier.items()):
            tier_name = tier if tier else "(no tier)"
            print(f"  {tier_name:12s}  {count}")

    print()
    print("Sample labels:")
    for p in profiles[:10]:
        print(f"  [{p.origin:10s}] {p.label!r:40s}  family={p.family!r}")


if __name__ == "__main__":
    main()
