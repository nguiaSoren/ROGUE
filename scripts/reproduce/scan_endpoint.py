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


def _load_pack(name: str, limit: int) -> list[AttackPrimitive]:
    """A bundled attack pack (default / aggressive / compliance) — curated single-shot-capable
    jailbreaks. This is the RIGHT corpus for scanning a bare model: the db's top canonical primitives
    skew to multi-turn / system-prompt-leak escalation artifacts that can't breach a model with no
    confidential system prompt (they read 0% no matter how deep), whereas the pack's DAN / Evil
    Confidant / ROT13 / refusal-suppression jailbreaks break a permissive model directly."""
    from rogue.packs import load_pack

    prims = load_pack(name)
    return prims[:limit] if limit and limit < len(prims) else prims


def _load_from_db(database_url: str, limit: int) -> list[AttackPrimitive]:
    """Top ``limit`` canonical primitives by reproducibility score, ORM → Pydantic."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from rogue.db.models import AttackPrimitive as AttackPrimitiveORM
    from scripts.reproduce.reproduce_once import _orm_to_pydantic_primitive

    # idle_in_transaction_session_timeout=0: pool_pre_ping pings on checkout only; this stops
    # Neon killing a connection whose txn sits idle during a long scan (2026-07-10 paid-session fix).
    engine = create_engine(
        database_url, pool_pre_ping=True,
        connect_args={"options": "-c idle_in_transaction_session_timeout=0"},
    )
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
    """Convert a human name to a stable config_id slug (lowercase, hyphens). Capped at 40 chars —
    the `deployment_configs.config_id` column is `varchar(40)`, so a longer slug (e.g.
    `fl-meta-llama-3-1-8b-instruct-abliterated` = 41) overflows and the persist DataErrors."""
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:40].rstrip("-") or "endpoint-scan"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="scan_endpoint",
        description="Red-team an OpenAI-compatible endpoint with ROGUE's attack corpus. COSTLY.",
    )
    p.add_argument("base_url", help="OpenAI-compatible endpoint base URL, e.g. https://api.company.com/v1")
    p.add_argument("--model", required=True, help="bare model name the endpoint serves, e.g. 'my-model'")
    p.add_argument("--api-key", default=None, help="endpoint API key (else $CUSTOM_API_KEY / $OPENAI_API_KEY)")
    p.add_argument("--corpus", choices=("db", "fixtures"), default="db", help="attack source (default: db)")
    p.add_argument(
        "--pack",
        default=None,
        help="bundled attack pack (default/aggressive/compliance) — overrides --corpus; the right "
        "corpus for scanning a bare model (curated jailbreaks that breach without a system prompt)",
    )
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
    # --- opt-in deep scan (COSTS MORE — many more model calls) ---
    p.add_argument(
        "--deep",
        action="store_true",
        default=False,
        help="deep scan: persona-wrap + (PAIR + escalation on a non-breaching baseline). Costs more.",
    )
    p.add_argument(
        "--pair-max-iters",
        type=int,
        default=3,
        help="PAIR refinement cap under --deep (0 disables PAIR; default 3)",
    )
    p.add_argument(
        "--no-escalate",
        action="store_true",
        default=False,
        help="under --deep, skip the escalation ladder (keep persona + multi-turn + PAIR only)",
    )
    # --- opt-in robustness sweep (COSTS MORE — sweeps the token ladder; bounded by --robustness-sweep-max-spend) ---
    p.add_argument(
        "--robustness-sweep",
        action="store_true",
        default=False,
        help=(
            "after the scan, sweep base primitive(s) across the many-shot / long-context token "
            "ladder to find this endpoint's breaking THRESHOLD ('breaks at N tokens'), graded by "
            "the same judge. Adds cost (bounded by --robustness-sweep-max-spend)."
        ),
    )
    p.add_argument(
        "--robustness-sweep-limit",
        type=int,
        default=1,
        help="how many base primitives to sweep for the threshold (default 1)",
    )
    p.add_argument(
        "--robustness-sweep-max-spend",
        type=float,
        default=2.00,
        help="hard USD cap across the whole robustness-sweep stage (default $2.00)",
    )
    return p.parse_args(argv)


async def _run(args: argparse.Namespace) -> EndpointScanReport:
    if args.persist and not args.config_name:
        raise SystemExit("--config-name NAME is required when --persist is set")

    if args.pack:
        primitives = _load_pack(args.pack, args.limit)
    elif args.corpus == "fixtures":
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
        deep=args.deep,
        pair_max_iters=args.pair_max_iters,
        escalate=not args.no_escalate,
        robustness_sweep=args.robustness_sweep,
        robustness_sweep_limit=args.robustness_sweep_limit,
        robustness_sweep_max_spend=args.robustness_sweep_max_spend,
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
