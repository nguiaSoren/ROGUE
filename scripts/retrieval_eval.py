#!/usr/bin/env python
"""Offline retrieval Recall@K evaluation — replay historical ladder wins.

Measures whether the Technique Retriever's top-K contains the technique that
eventually won, by replaying ``ladder_attempts`` winner rows. The headline KPI is
**Recall@50 >= 80%** (deployment gate + publishable result).

DEFAULTS TO DETERMINISTIC (offline, no spend). Only ``--live`` calls the real
OpenAI embedding API and costs money.

Usage
-----
    uv run python scripts/retrieval_eval.py                       # deterministic (default)
    uv run python scripts/retrieval_eval.py --ks 10 25 50 100
    uv run python scripts/retrieval_eval.py --live                # spends money (OpenAI)
    uv run python scripts/retrieval_eval.py --database-url postgresql+psycopg://...

Writes a JSON report to ``data/retrieval_eval/recall_<runtag>.json`` and prints
the recall table plus the uncovered-winner count.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

# Project root on sys.path so `rogue.*` imports when run as a bare script.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_OUT_DIR = _ROOT / "data" / "retrieval_eval"


def _db_url(explicit: str | None) -> str:
    from dotenv import load_dotenv

    load_dotenv()
    url = explicit or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit(
            "DATABASE_URL not set (pass --database-url or set it in .env)"
        )
    return url


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--database-url",
        default=None,
        help="SQLAlchemy URL (default: DATABASE_URL from env/.env)",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--deterministic",
        dest="deterministic",
        action="store_true",
        help="offline deterministic embeddings, no spend (DEFAULT)",
    )
    mode.add_argument(
        "--live",
        dest="live",
        action="store_true",
        help="real OpenAI embeddings — COSTS MONEY",
    )
    p.add_argument(
        "--ks",
        type=int,
        nargs="+",
        default=[10, 25, 50, 100],
        help="K values for Recall@K (default: 10 25 50 100)",
    )
    p.add_argument(
        "--allow-known-successes",
        action="store_true",
        help=(
            "do NOT strip known_successes from target fingerprints "
            "(measures deployed-as-is; mildly optimistic via telemetry leakage)"
        ),
    )
    p.add_argument(
        "--runtag",
        default=None,
        help="output filename tag (default: <mode>_<unixtime>)",
    )
    args = p.parse_args(argv)

    # Default is deterministic: live only when --live is explicitly passed.
    live = bool(args.live)
    mode_name = "live" if live else "deterministic"

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from rogue.retrieval.embed import default_embed_fn, deterministic_embed_fn
    from rogue.retrieval.evaluation import evaluate_recall, render_report

    if live:
        logging.warning(
            "--live: using real OpenAI embeddings. THIS COSTS MONEY (one embedding "
            "per technique + one per distinct target)."
        )
        embed_fn = default_embed_fn()
    else:
        embed_fn = deterministic_embed_fn()

    url = _db_url(args.database_url)
    engine = create_engine(url)

    with Session(engine) as session:
        result = evaluate_recall(
            session,
            embed_fn=embed_fn,
            ks=tuple(args.ks),
            suppress_known_successes=not args.allow_known_successes,
        )

    # Persist JSON (keys must be JSON-safe: convert int-keyed dicts to strings).
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    runtag = args.runtag or f"{mode_name}_{int(time.time())}"
    out_path = _OUT_DIR / f"recall_{runtag}.json"
    out_path.write_text(json.dumps(_jsonable(result), indent=2, sort_keys=True))

    # Print the human report.
    print()
    print(render_report(result))
    print()
    print(f"JSON report written to: {out_path}")
    return 0


def _jsonable(obj):
    """Recursively stringify non-str dict keys (Recall@K uses int keys)."""
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


if __name__ == "__main__":
    raise SystemExit(main())
