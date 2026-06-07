"""Embed all known techniques and upsert TechniqueEmbedding rows.

Usage
-----
    uv run python scripts/benchmark/embed_techniques.py [options]

Options
-------
--database-url URL      Postgres connection string.
                        Defaults to DATABASE_URL env var or the local dev URL.
--deterministic         Use the offline deterministic embed function (DEFAULT).
                        Safe: no API calls, no cost.
--live                  Use the real OpenAI embedding API (costs money).
                        Overrides --deterministic.
--version-tag TAG       Version string stored in TechniqueEmbedding.version.
                        Default: "te3-small-v1".
                        Must be ≤ 20 chars (DB column constraint).

Safety
------
Defaults to --deterministic so this script NEVER makes a paid OpenAI call
unless --live is explicitly passed.
"""

from __future__ import annotations

import argparse
import os
import sys

# ---------------------------------------------------------------------------
# Script guard — must not auto-execute on import.
# ---------------------------------------------------------------------------
if __name__ != "__main__":
    raise ImportError(
        "embed_techniques.py is a CLI script and must not be imported as a module."
    )

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser(
    description="Embed technique profiles and upsert into technique_embeddings table.",
    formatter_class=argparse.RawDescriptionHelpFormatter,
)
parser.add_argument(
    "--database-url",
    default=None,
    help=(
        "Postgres connection string. "
        "Defaults to DATABASE_URL env var or postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue."
    ),
)
parser.add_argument(
    "--deterministic",
    action="store_true",
    default=False,
    help="Use offline deterministic embeddings (no cost). This is the DEFAULT behaviour.",
)
parser.add_argument(
    "--live",
    action="store_true",
    default=False,
    help="Use real OpenAI embeddings (costs money). Overrides --deterministic.",
)
parser.add_argument(
    "--version-tag",
    default="te3-small-v1",
    help='Version tag stored in TechniqueEmbedding.version (max 20 chars). Default: "te3-small-v1".',
)
args = parser.parse_args()

if len(args.version_tag) > 20:
    print(
        f"ERROR: --version-tag '{args.version_tag}' exceeds the 20-character column limit.",
        file=sys.stderr,
    )
    sys.exit(1)

# Resolve embed mode: --live overrides everything; otherwise deterministic.
use_live = args.live
if use_live:
    print("Mode: LIVE (real OpenAI embeddings — this will cost money)")
else:
    print("Mode: deterministic (offline, no cost)")

# ---------------------------------------------------------------------------
# DB URL
# ---------------------------------------------------------------------------
_FALLBACK_DB_URL = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"
database_url: str = (
    args.database_url
    or os.environ.get("DATABASE_URL", _FALLBACK_DB_URL)
)

# ---------------------------------------------------------------------------
# Imports (deferred so argparse --help doesn't require the full stack)
# ---------------------------------------------------------------------------
from datetime import datetime, timezone  # noqa: E402

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from rogue.db.models import TechniqueEmbedding  # noqa: E402
from rogue.retrieval.embed import default_embed_fn, deterministic_embed_fn  # noqa: E402
from rogue.retrieval.embedding_text import build_technique_embedding_text  # noqa: E402

# Sibling builder — built in parallel; guard the import clearly.
try:
    from rogue.retrieval.technique_profile_builder import build_technique_profiles  # noqa: E402
except ImportError as exc:
    print(
        f"ERROR: could not import build_technique_profiles from "
        f"rogue.retrieval.technique_profile_builder: {exc}\n"
        f"Make sure Engineer 6 (E6) has built retrieval/technique_profile_builder.py "
        f"and it is on PYTHONPATH.",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Select embed function
# ---------------------------------------------------------------------------
if use_live:
    model_name = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
    embed = default_embed_fn(model=model_name)
    model_label = model_name
else:
    embed = deterministic_embed_fn(dim=1536)
    model_label = "deterministic-sha256"

# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------
engine = create_engine(database_url, pool_pre_ping=True)

with Session(engine) as session:
    # Build technique profiles (reads from DB / ladder registry).
    profiles = build_technique_profiles(session=session)
    print(f"Profiles loaded: {len(profiles)}")

    upserted = 0
    for profile in profiles:
        text = build_technique_embedding_text(profile)
        vector = embed(text)

        row = session.get(TechniqueEmbedding, profile.label)
        if row is None:
            row = TechniqueEmbedding(label=profile.label)
            session.add(row)

        row.technique_id = profile.technique_id or profile.label
        row.embedding = vector
        row.profile = profile.model_dump()
        row.modalities = profile.modalities
        row.version = args.version_tag
        row.created_at = datetime.now(timezone.utc)

        upserted += 1

    session.commit()

print(
    f"\nDone. Upserted {upserted} technique embedding(s). "
    f"Model: {model_label}. Version tag: {args.version_tag}."
)
