"""One-shot migration: re-embed canonical primitives onto the canonicalized basis.

Why this exists. As of 2026-06-24 the harvest dedup path embeds
``canonicalize(payload_template)`` rather than the raw text (see
``rogue.obfuscation.canonicalize`` + ``dedupe.embeddings.Deduplicator``), so an
obfuscated payload (``1gn0r3 pr3v10us``) clusters with its plain twin instead of
re-entering the corpus once per skin. Rows persisted *before* that change carry
a **raw-text** embedding. For clean prose this is a no-op — ``canonicalize`` is
identity there, so the raw and canonical embeddings are identical — but a
canonical seed whose stored text is itself obfuscated sits on the old basis and
will not match new canonical-basis arrivals.

This script closes that asymmetry: it re-embeds **only** the canonical rows
whose text actually changes under ``canonicalize`` (the rare obfuscated seeds),
leaving every clean row untouched. It does not re-cluster — existing cluster
membership is preserved; it only refreshes the stored ``payload_embedding`` of
the affected canonical seeds so the whole canonical set shares one basis.

Cost: a handful of OpenAI ``text-embedding-3-small`` calls (only the obfuscated
seeds) — negligible. Idempotent: a second run finds nothing to do.

Usage::

    uv run python scripts/migrate/recanonicalize_embeddings.py            # dry-run (default)
    uv run python scripts/migrate/recanonicalize_embeddings.py --apply     # write changes

Reads ``DATABASE_URL`` and ``OPENAI_API_KEY`` from the environment (.env).
"""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Import after load_dotenv so DATABASE_URL/OPENAI_API_KEY are populated.
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from rogue.db.models import AttackPrimitive as AttackPrimitiveORM  # noqa: E402
from rogue.obfuscation import canonicalize  # noqa: E402

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


def _build_embed_fn(embedding_model: str):
    from openai import OpenAI

    client = OpenAI()

    def embed_fn(text: str) -> list[float]:
        resp = client.embeddings.create(model=embedding_model, input=text)
        return list(resp.data[0].embedding)

    return embed_fn


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    ap.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    ap.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="defaults to $DATABASE_URL",
    )
    args = ap.parse_args()

    if not args.database_url:
        print("error: DATABASE_URL not set (and --database-url not given)", file=sys.stderr)
        return 2

    engine = create_engine(args.database_url)
    embed_fn = None  # constructed lazily, only if there's work + --apply

    scanned = 0
    affected: list[str] = []
    try:
        with Session(engine) as session:
            # Stream canonical rows; only canonical seeds define the basis other
            # rows are compared against, so non-canonical rows need no fix.
            rows = session.execute(
                select(AttackPrimitiveORM).where(AttackPrimitiveORM.canonical.is_(True))
            ).scalars()

            for prim in rows:
                scanned += 1
                raw = prim.payload_template or ""
                canon = canonicalize(raw)
                if canon == raw:
                    continue  # clean text — raw embedding already on the canonical basis
                affected.append(prim.primitive_id)
                if args.apply:
                    if embed_fn is None:
                        embed_fn = _build_embed_fn(args.embedding_model)
                    prim.payload_embedding = embed_fn(canon)

            if args.apply and affected:
                session.commit()
    finally:
        engine.dispose()

    print(f"scanned canonical primitives: {scanned}")
    print(f"obfuscated seeds needing re-embed: {len(affected)}")
    if affected:
        preview = ", ".join(affected[:10])
        more = "" if len(affected) <= 10 else f" (+{len(affected) - 10} more)"
        print(f"  ids: {preview}{more}")
    if args.apply:
        print("APPLIED — re-embedded onto the canonicalized basis." if affected else "nothing to apply.")
    else:
        print("DRY-RUN — re-run with --apply to write." if affected else "nothing to do; corpus already consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
