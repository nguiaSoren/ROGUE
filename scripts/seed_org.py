"""Platform-admin CLI: onboard a company (org + optional user + first API key).

Creates an `organizations` row, optionally a `users` row, and issues one `api_keys`
row — storing ONLY the sha256 hash of the key (never the raw value). The raw key is
shown to the operator exactly once at issue time.

Run from the repo root against the target deployment's `DATABASE_URL`::

    # Onboard "Acme" with a default-scoped key, print the raw key once:
    uv run python scripts/seed_org.py --name "Acme"

    # Attach an owner user + custom scopes:
    uv run python scripts/seed_org.py --name "Acme" --email ops@acme.com \
        --scopes scan:read,scan:write,admin

    # Org already exists — reuse it and issue a fresh key:
    uv run python scripts/seed_org.py --name "Acme" --force

This connects to a real database ONLY when a human runs `main()` against
`DATABASE_URL`. Importing the module (or calling `seed_org` with a test session)
opens no connection.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Defensive `src/` insert so the script runs even without the editable install on path.
_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import os  # noqa: E402

from rogue.platform import tenancy  # noqa: E402
from rogue.platform.memory import _new_id  # noqa: E402
from rogue.platform.models import ApiKey, Organization, User  # noqa: E402

DEFAULT_DATABASE_URL = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"
DEFAULT_SCOPES = ["scan:read", "scan:write"]
API_BASE_URL = "https://rogue-api-mr5w.onrender.com"


def seed_org(
    session,
    *,
    name: str,
    email: str | None = None,
    scopes: list[str] | None = None,
    force: bool = False,
) -> tuple[str, str]:
    """Find-or-create an org and issue a fresh API key for it.

    Find-or-create the org by `name`: if one already exists and `force` is False, reuse it
    (never duplicate). With `force=True` the existing org is reused but a fresh key is still
    issued. Optionally create a `users` row (find-or-create by `email`). The raw key is minted
    via `tenancy.generate_api_key("live")`, and ONLY its sha256 hash + display prefix are stored.

    Returns `(org_id, raw_key)`. The `raw_key` is the caller's only chance to see the secret —
    it is never persisted.
    """
    from sqlalchemy import select

    now = datetime.now(timezone.utc)

    org = session.execute(
        select(Organization).where(Organization.name == name)
    ).scalar_one_or_none()
    if org is None:
        org = Organization(org_id=_new_id("org"), name=name, created_at=now)
        session.add(org)
    elif not force:
        # Reuse the existing org; still issue a fresh key below.
        pass

    if email is not None:
        user = session.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()
        if user is None:
            session.add(
                User(
                    user_id=_new_id("user"),
                    email=email,
                    name=None,
                    created_at=now,
                )
            )

    raw_key, key_hash, prefix = tenancy.generate_api_key("live")
    session.add(
        ApiKey(
            key_id=_new_id("key"),
            org_id=org.org_id,
            project_id=None,
            key_hash=key_hash,
            prefix=prefix,
            name=name,
            scopes=scopes or list(DEFAULT_SCOPES),
            created_at=now,
        )
    )
    session.commit()
    return org.org_id, raw_key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Onboard a company: create an org (+ optional user) and issue its first API key."
    )
    parser.add_argument("--name", required=True, help="Organization name (find-or-create by name).")
    parser.add_argument("--email", default=None, help="Optional owner/contact email (find-or-create a users row).")
    parser.add_argument(
        "--scopes",
        default=None,
        help="Comma-separated scopes for the key (default: scan:read,scan:write).",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        help="SQLAlchemy URL for the target deployment (default: $DATABASE_URL).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Org already exists: reuse it and issue a fresh key (never duplicates the org).",
    )
    args = parser.parse_args(argv)

    scopes = [s.strip() for s in args.scopes.split(",") if s.strip()] if args.scopes else None

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(args.database_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        org_id, raw_key = seed_org(
            session,
            name=args.name,
            email=args.email,
            scopes=scopes,
            force=args.force,
        )
    finally:
        session.close()
        engine.dispose()

    print()
    print("=" * 72)
    print(f"  org_id:   {org_id}")
    print(f"  API key:  {raw_key}")
    print("=" * 72)
    print("  ⚠️  save this now — it is shown only once and only its hash is stored")
    print(f"  API base: {API_BASE_URL}")
    print(f"  usage:    Authorization: Bearer {raw_key[:16]}…")
    print("=" * 72)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
