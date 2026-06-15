"""`scan_endpoint` — red-team an arbitrary OpenAI-compatible endpoint with ROGUE's corpus.

The product promise, runnable:

    uv run python scripts/reproduce/scan_endpoint.py https://api.company.com/v1 \
        --model my-model --corpus fixtures --n-trials 3

No provider account, no bespoke integration — a customer's inference URL goes straight through
``CustomHTTPAdapter`` and the rest of the pipeline (render → panel → judge) is unchanged. (This is the
local/platform-side proof; the eventual `pip install rogue; rogue scan <url>` is the SDK + hosted-API
front for the same capability.)

⚠️  COSTLY — this makes REAL calls to the target endpoint AND to the judge LLM (≈ n_primitives ×
n_trials target calls + the same number of judge calls). Run it deliberately; never on a loop/timer.
With ``--corpus fixtures`` it scans only the 3 golden primitives (cheap trial); ``--corpus db`` scans
the top ``--limit`` canonical primitives from the database.

Persist to the dashboard DB (opt-in):

    uv run python scripts/reproduce/scan_endpoint.py https://api.company.com/v1 \
        --model my-model --corpus db --n-trials 3 \
        --persist --config-name "my-bot"

With ``--persist`` every judged trial is written to ``breach_results`` and the deployment config is
upserted, so ``/matrix``, ``/feed``, and ``/brief`` populate with YOUR data. The ``--config-name``
value is slugified to form the stable ``config_id`` that becomes a durable dashboard column.
``--database-url`` defaults to ``$DATABASE_URL`` or the local dev Postgres; override for Neon/prod.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT / "src"), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from rogue.reproduce.endpoint_scan import EndpointScanReport, scan_endpoint  # noqa: E402
from rogue.schemas import AttackPrimitive  # noqa: E402

logger = logging.getLogger("rogue.scripts.reproduce.scan_endpoint")

DEFAULT_DATABASE_URL = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"
_FIXTURES = _ROOT / "tests" / "fixtures"
_GOLDEN_FIXTURES = (
    "01_multilingual_african_languages.json",
    "02_copirate_365_cve_2026_24299.json",
    "03_hacking_claude_memory.json",
)


def _load_fixtures(limit: int) -> list[AttackPrimitive]:
    """The 3 golden AttackPrimitive fixtures — a cheap, DB-free corpus for a trial scan."""
    out: list[AttackPrimitive] = []
    for name in _GOLDEN_FIXTURES[:limit]:
        out.append(AttackPrimitive.model_validate_json((_FIXTURES / name).read_text()))
    return out


def _load_from_db(database_url: str, limit: int) -> list[AttackPrimitive]:
    """Top ``limit`` canonical primitives by reproducibility score, ORM → Pydantic."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from rogue.db.models import AttackPrimitive as AttackPrimitiveORM
    from scripts.reproduce.reproduce_once import _orm_to_pydantic_primitive

    engine = create_engine(database_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionLocal() as session:
        q = (
            select(AttackPrimitiveORM)
            .where(AttackPrimitiveORM.canonical.is_(True))
            .order_by(AttackPrimitiveORM.reproducibility_score.desc())
            .limit(limit)
        )
        orms = list(session.execute(q).scalars())
    return [_orm_to_pydantic_primitive(o) for o in orms]


def _slugify(name: str) -> str:
    """Convert a human name to a stable config_id slug (lowercase, hyphens, max 80 chars)."""
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:80] or "endpoint-scan"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="scan_endpoint",
        description="Red-team an OpenAI-compatible endpoint with ROGUE's attack corpus. COSTLY.",
    )
    p.add_argument("base_url", help="OpenAI-compatible endpoint base URL, e.g. https://api.company.com/v1")
    p.add_argument("--model", required=True, help="bare model name the endpoint serves, e.g. 'my-model'")
    p.add_argument("--api-key", default=None, help="endpoint API key (else $CUSTOM_API_KEY / $OPENAI_API_KEY)")
    p.add_argument("--corpus", choices=("db", "fixtures"), default="db", help="attack source (default: db)")
    p.add_argument("--limit", type=int, default=15, help="max primitives to scan (default: 15)")
    p.add_argument("--n-trials", type=int, default=3, help="trials per primitive (default: 3)")
    p.add_argument("--system-prompt", default="", help="system prompt the deployment runs with")
    p.add_argument("--output", default=None, help="write the Markdown report to this path")
    p.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    p.add_argument(
        "--persist",
        action="store_true",
        default=False,
        help="write judged trial rows to the dashboard DB so /matrix /feed /brief show YOUR data",
    )
    p.add_argument(
        "--config-name",
        default=None,
        metavar="NAME",
        help=(
            "human-readable label for this deployment (e.g. 'my-bot'). "
            "Slugified to form a stable config_id dashboard column. "
            "Required when --persist is set."
        ),
    )
    return p.parse_args(argv)


async def _run(args: argparse.Namespace) -> EndpointScanReport:
    if args.persist and not args.config_name:
        raise SystemExit("--config-name NAME is required when --persist is set")

    if args.corpus == "fixtures":
        primitives = _load_fixtures(args.limit)
    else:
        primitives = _load_from_db(args.database_url, args.limit)
    if not primitives:
        raise SystemExit("no attack primitives loaded — is the corpus seeded?")
    api_key = args.api_key or os.environ.get("CUSTOM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    logger.warning(
        "COSTLY: scanning %s with %d primitive(s) × %d trial(s) — real endpoint + judge calls",
        args.base_url, len(primitives), args.n_trials,
    )

    # derive stable config_id from --config-name when persisting
    config_id = _slugify(args.config_name) if args.config_name else "adhoc-endpoint-scan"

    return await scan_endpoint(
        args.base_url,
        args.model,
        primitives,
        api_key=api_key,
        system_prompt=args.system_prompt,
        n_trials=args.n_trials,
        persist=args.persist,
        database_url=args.database_url if args.persist else None,
        config_id=config_id,
        config_name=args.config_name,
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args(argv)
    report = asyncio.run(_run(args))
    print(report.summary())
    print()
    print(report.to_markdown())
    if args.output:
        Path(args.output).write_text(report.to_markdown(), encoding="utf-8")
        print(f"\nReport written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
