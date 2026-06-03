"""One-shot daily harvest: SERP discovery → extract → dedup → persist.

Wires all four Day-1 layers end-to-end. Run from the repo root::

    uv run python scripts/harvest_once.py --since 1d

Pipeline (one ``--since N`` window per invocation, ROGUE_PLAN.md §3.1):

    LAYER 1 HARVEST
        DiscoveryAgent.run(since)                         ─►  list[RawDocument]
        (10 plugins via default_plugins(); per-plugin error isolation)
            │
            ▼
    LAYER 2 EXTRACT
        ExtractionAgent.extract_from_raw_document(doc)    ─►  AttackPrimitive | None
        (one Anthropic/OpenAI structured-output call per doc; commentary → None)
            │
            ▼
    LAYER 3 DEDUP
        Deduplicator.assign_cluster(primitive_orm,        ─►  cluster_id + canonical
                                    daily_bd_spend_usd=…)     in-place on the ORM
        (pgvector cosine `<=>` against canonical-only rows;
         §3.5 quarantine gate clamps low-score over-budget primitives)
            │
            ▼
    PERSIST
        session.add(primitive_orm); session.commit()

Failure handling: per-plugin errors are isolated inside DiscoveryAgent (logged
into ``agent.last_run_reports``); per-document extraction errors are caught
here and logged with the source URL so a single bad doc never tanks the run.
Anthropic content-policy / OpenAI refusal paths return ``None`` from
extraction and are accounted in the ``skipped`` counter.

Embedder injection (Day-1 wire): the OpenAI embeddings SDK client is
constructed inside ``main()`` and passed as ``embed_fn`` to ``Deduplicator``
— the dedup module itself is import-safe without OpenAI credentials per
§A.22 / §9.5. Production wiring uses sync ``openai.OpenAI`` (one embed call
per primitive; the harvest loop doesn't benefit from parallel embeddings at
~30-60 primitives/day).

Idempotency: this script does NOT delete previously-harvested rows. The
dedup layer is what prevents duplicate insertion across daily runs (same
primitive → same cluster, ``canonical = False`` on the duplicate). For a
clean slate, run ``uv run python scripts/seed_demo_data.py`` first.

Env vars required (Day-1 morning): ``BRIGHTDATA_API_KEY``,
``BRIGHTDATA_SERP_ZONE``, ``BRIGHTDATA_UNLOCKER_ZONE``,
``BRIGHTDATA_BROWSER_ZONE``, ``OPENAI_API_KEY``, plus one of
``ANTHROPIC_API_KEY`` (default extraction model is
``anthropic/claude-haiku-4-5``) or ``OPENAI_API_KEY`` if ``EXTRACTION_MODEL``
is set to an ``openai/*`` id. ``DATABASE_URL`` defaults to the docker-compose
dev URL.

**Order-matters DB warning**: ``tests/test_smoke.py::test_alembic_upgrade_head_dry_run``
runs ``upgrade head → downgrade base`` as part of its dry-run round-trip,
which empties the dev DB. If you ran ``uv run pytest`` recently, run
``uv run alembic upgrade head`` BEFORE invoking this script — otherwise
every DB call will fail with ``UndefinedTable``. See ``tasks/LESSONS.md``
2026-05-24 entry "Smoke test #9 leaves the DB empty."

Spec: ROGUE_PLAN.md §A.12, §9.5.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# Load .env BEFORE importing any module that reads provider keys at import
# time (OpenAI / Anthropic SDKs construct their clients eagerly on the first
# call but read the key from os.environ at that moment). Mirrors the same
# pattern used by `src/rogue/db/migrations/env.py`. Without this, running
# `uv run python scripts/harvest_once.py ...` from a fresh shell crashes on
# the embedder construction because the parent shell hasn't `source .env`'d.
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import create_engine, func, select  # noqa: E402 — must come after load_dotenv
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from rogue.db.models import (  # noqa: E402
    AttackPrimitive as AttackPrimitiveORM,
    BrightDataCostLog,
    SourceProvenance as SourceProvenanceORM,
)
from rogue.dedupe.embeddings import Deduplicator  # noqa: E402
from rogue.extract.extraction_agent import ExtractionAgent, ExtractionImage  # noqa: E402
from rogue.harvest.bright_data_client import BrightDataClient  # noqa: E402
from rogue.harvest.discovery_agent import DiscoveryAgent  # noqa: E402
from rogue.harvest.fetch_cache import FetchCache, load_snapshot  # noqa: E402
from rogue.harvest.media_ingest import MediaIngestor  # noqa: E402
from rogue.reproduce.strategy_library import persist_technique  # noqa: E402
from rogue.schemas import AttackPrimitive, RawDocument, TechniqueSpec  # noqa: E402
from rogue.schemas.source_provenance import SourceProvenance  # noqa: E402

logger = logging.getLogger("rogue.scripts.harvest_once")

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"
)
DEFAULT_EXTRACTION_MODEL = "anthropic/claude-haiku-4-5"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


# --------------------------------------------------------------------------- #
# --since parsing
# --------------------------------------------------------------------------- #


_SINCE_RE = re.compile(r"^(\d+)([dh])$")


def parse_since(value: str) -> datetime:
    """Convert ``--since`` ('1d', '14d', '6h') into a UTC datetime.

    Supports days (``d``) and hours (``h``). Anything else raises so the
    misconfiguration is loud rather than silently harvesting the wrong window.
    """
    match = _SINCE_RE.fullmatch(value.strip())
    if match is None:
        raise ValueError(
            f"--since must look like '1d', '14d', or '6h' (got {value!r})"
        )
    n, unit = int(match.group(1)), match.group(2)
    delta = timedelta(days=n) if unit == "d" else timedelta(hours=n)
    return datetime.now(timezone.utc) - delta


# --------------------------------------------------------------------------- #
# Pydantic AttackPrimitive → ORM mirror
# --------------------------------------------------------------------------- #


def _to_orm_primitive(p: AttackPrimitive) -> AttackPrimitiveORM:
    """Mirror ``scripts/seed_demo_data.py::_to_orm_primitive``.

    Enum fields use ``.value`` so the Postgres-side enum types (which
    accept lowercase values per the 0001 migration) line up. ``sources``
    cascades via the parent's relationship config; ``payload_embedding``
    is populated separately by the dedup pass before commit.
    """
    return AttackPrimitiveORM(
        primitive_id=p.primitive_id,
        cluster_id=p.cluster_id,
        canonical=p.canonical,
        family=p.family.value,
        secondary_families=[f.value for f in p.secondary_families],
        vector=p.vector.value,
        title=p.title,
        short_description=p.short_description,
        payload_template=p.payload_template,
        payload_slots=p.payload_slots,
        multi_turn_sequence=p.multi_turn_sequence,
        target_models_claimed=p.target_models_claimed,
        claimed_success_rate=p.claimed_success_rate,
        claimed_first_seen=p.claimed_first_seen,
        reproducibility_score=p.reproducibility_score,
        requires_multi_turn=p.requires_multi_turn,
        requires_system_prompt_access=p.requires_system_prompt_access,
        requires_tools=p.requires_tools,
        requires_multimodal=p.requires_multimodal,
        discovered_at=p.discovered_at,
        base_severity=p.base_severity.value,
        severity_rationale=p.severity_rationale,
        notes=p.notes,
        sources=[
            SourceProvenanceORM(
                url=str(s.url),
                source_type=s.source_type,
                author=s.author,
                published_at=s.published_at,
                fetched_at=s.fetched_at,
                archive_hash=s.archive_hash,
                bright_data_product=s.bright_data_product,
            )
            for s in p.sources
        ],
    )


# --------------------------------------------------------------------------- #
# Source-provenance synthesis (when extraction emits a primitive without one)
# --------------------------------------------------------------------------- #


def _synthesize_source(raw_doc: RawDocument) -> dict:
    """Build a SourceProvenance dict from a RawDocument.

    The extraction LLM is encouraged by the §A.8 prompt to populate
    ``sources`` itself, but the source URL + fetched_at + archive_hash
    are always known to *us* (the harvest side) — so if the LLM omits
    them, we attach a minimal record so dedup / dataset export never
    loses the upstream pointer.
    """
    return {
        "url": str(raw_doc.url),
        "source_type": raw_doc.source_type,
        "author": None,
        "published_at": None,
        "fetched_at": raw_doc.fetched_at,
        "archive_hash": raw_doc.archive_hash,
        "bright_data_product": raw_doc.bright_data_product,
    }


def _ensure_primitive_has_provenance(
    primitive: AttackPrimitive,
    raw_doc: RawDocument,
) -> AttackPrimitive:
    """If the extraction LLM didn't emit a ``sources`` entry, add one."""
    if primitive.sources:
        return primitive
    return primitive.model_copy(
        update={
            "sources": [SourceProvenance.model_validate(_synthesize_source(raw_doc))],
        },
    )


# --------------------------------------------------------------------------- #
# Run-level counters
# --------------------------------------------------------------------------- #


@dataclass
class HarvestRunStats:
    raw_docs: int = 0
    extracted: int = 0
    skipped_commentary: int = 0
    skipped_unchanged: int = 0
    extract_errors: int = 0
    dedup_errors: int = 0
    new_clusters: int = 0
    duplicates: int = 0
    images_ingested: int = 0
    # §10.9 — harvested attack *techniques* (methods) routed into attack_strategies.
    techniques_harvested: int = 0

    def summary_line(self) -> str:
        return (
            f"raw_docs={self.raw_docs} extracted={self.extracted} "
            f"skipped_commentary={self.skipped_commentary} "
            f"skipped_unchanged={self.skipped_unchanged} "
            f"extract_errors={self.extract_errors} "
            f"dedup_errors={self.dedup_errors} "
            f"new_clusters={self.new_clusters} duplicates={self.duplicates} "
            f"images_ingested={self.images_ingested} "
            f"techniques_harvested={self.techniques_harvested}"
        )


# --------------------------------------------------------------------------- #
# Per-day BD spend helper for the §3.5 quarantine gate
# --------------------------------------------------------------------------- #


def daily_bd_spend_usd(session: Session) -> Decimal:
    """Sum today's (UTC) Bright Data cost-log rows.

    Returns 0 when the cost log is empty OR when the table/column doesn't
    match the ORM (a known §STATUS-tracked drift between
    `db/models.py::BrightDataCostLog` (`cost_usd` / `ran_at`) and the
    0001 migration (`estimated_cost_usd` / `latency_ms`)). The drift fix
    is Day-1+ work; until it lands, the spend query must NOT abort the
    harvest — that would lock out the §3.5 quarantine gate input and
    force the entire run to skip, which is strictly worse than
    pretending today's spend is $0 (the quarantine gate stays inert at
    $0, and every primitive becomes canonical until reproduction-layer
    cost data is wired through).
    """
    from sqlalchemy.exc import ProgrammingError

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    try:
        total = session.execute(
            select(func.coalesce(func.sum(BrightDataCostLog.cost_usd), 0.0))
            .where(BrightDataCostLog.ran_at >= today_start)
        ).scalar_one()
    except ProgrammingError as exc:
        # Wraps psycopg's UndefinedTable + UndefinedColumn — both surface
        # the same way to SQLAlchemy when the schema doesn't match the ORM.
        # Roll back so the session isn't left in an aborted-transaction state
        # (subsequent session.add(...) calls in the harvest loop would fail
        # otherwise with "current transaction is aborted").
        session.rollback()
        logger.warning(
            "daily_bd_spend_usd: cost-log query failed (%s) — quarantine "
            "gate input forced to $0 for this run. See §STATUS Day-1 "
            "item (c) for the underlying ORM/migration drift fix.",
            type(exc).__name__,
        )
        return Decimal("0")
    return Decimal(str(total))


# --------------------------------------------------------------------------- #
# Main async entrypoint
# --------------------------------------------------------------------------- #


def _default_openai_embed_fn(embedding_model: str):
    """Build the production sync-OpenAI embedder. Constructed on demand so
    importing this module doesn't require ``OPENAI_API_KEY``."""
    from openai import OpenAI

    openai_client = OpenAI()  # picks up OPENAI_API_KEY from env

    def embed_fn(text: str) -> list[float]:
        resp = openai_client.embeddings.create(model=embedding_model, input=text)
        return list(resp.data[0].embedding)

    return embed_fn


def _assert_schema_present(database_url: str) -> None:
    """Fail-fast preflight: confirm ``attack_primitives`` exists.

    Without this check, the harvest silently runs the entire harvest →
    extract pipeline against missing tables; per-doc error isolation
    catches each ``UndefinedTable`` raised by the dedup/persist step
    and just continues, burning credits with zero DB output. The
    failure mode is invisible until the final ``done:`` line shows
    ``dedup_errors=N`` matching the harvest count.

    Most common root cause: ``tests/test_smoke.py::test_alembic_upgrade_head_dry_run``
    downgrades the schema after every pytest run. Recovery is
    ``uv run alembic upgrade head``; this check surfaces it before
    we start spending money.
    """
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.exc import OperationalError

    try:
        engine = create_engine(database_url, connect_args={"connect_timeout": 5})
        with engine.connect():
            pass
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
    except OperationalError as exc:
        raise RuntimeError(
            f"Postgres at {database_url!r} is not reachable: {exc.__class__.__name__}: {exc}. "
            "Start it with: docker compose up -d --wait"
        ) from exc
    finally:
        try:
            engine.dispose()
        except Exception:  # pragma: no cover - dispose failure is benign here
            pass

    required = {"attack_primitives", "source_provenances", "deployment_configs"}
    missing = required - tables
    if missing:
        raise RuntimeError(
            f"Postgres at {database_url!r} is missing tables {sorted(missing)}. "
            "Run: uv run alembic upgrade head  "
            "(pytest's smoke test downgrades the schema after each run — see "
            "tasks/LESSONS.md 2026-05-24 entry on test_alembic_upgrade_head_dry_run.)"
        )


async def run_harvest(
    since: datetime,
    database_url: str,
    extraction_model: str | None = None,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    embed_fn=None,
    bd_client: BrightDataClient | None = None,
    extractor: ExtractionAgent | None = None,
    bandit_state_path: Path | None = None,
    media_ingestor: MediaIngestor | None = None,
    x_handles: list[str] | None = None,
    x_only: bool = False,
    multimodal_only: bool = False,
    harvest_run_id: str | None = None,
) -> HarvestRunStats:
    """End-to-end Day-1 daily run. Returns per-run counters for the logs.

    ``embed_fn`` / ``bd_client`` / ``extractor`` / ``bandit_state_path`` /
    ``media_ingestor`` are injection seams used by the test suite to swap out
    the network-dependent components and isolate the bandit state file. In
    production they default to None and are constructed here from env vars per
    ``BrightDataClient.from_env()`` + ``OpenAI()`` + ``ExtractionAgent`` +
    ``MediaIngestor(bd_client)``; ``bandit_state_path`` falls back to
    ``data/discovery_bandit.json``. Tests MUST pass a ``tmp_path`` so the
    production bandit file isn't overwritten with the mock-driven zero state.

    Multimodal ingestion (Feature A): unless ``HARVEST_INGEST_IMAGES=0``, each
    harvested document's own images (X ``photos``, blog ``<img>`` …) are
    downloaded via Web Unlocker and vision-read by the extraction agent. Bounded
    by ``MEDIA_INGEST_MAX_PER_DOC`` (default 4) and ``MEDIA_INGEST_MAX_TOTAL``
    (default 60) so image download can't blow the BD budget.
    """
    # Preflight: verify the schema is present BEFORE we start spending money
    # on BD + LLM calls that would otherwise all fail at the persist step.
    _assert_schema_present(database_url)

    stats = HarvestRunStats()

    # --- Layer-0 wiring (each line either uses the injected double or
    #     constructs the real client from env vars). ---
    if bd_client is None:
        bd_client = BrightDataClient.from_env()
    if embed_fn is None:
        embed_fn = _default_openai_embed_fn(embedding_model)
    if extractor is None:
        # §10.9 Phase 3a — harvest runs the v4 extractor so the 3-way classifier
        # is active and technique documents are routed into attack_strategies.
        # (The ExtractionAgent default stays v3 so ad-hoc/test callers and the
        # live extraction fixtures keep byte-for-byte legacy behaviour; only the
        # production harvest pipeline opts into v4.)
        extractor = ExtractionAgent(model=extraction_model, prompt_version="v4")
    # Multimodal ingestion (Feature A) — construct unless explicitly disabled.
    # Reuses the same BD client (Web Unlocker) for image downloads.
    if media_ingestor is None and os.environ.get("HARVEST_INGEST_IMAGES", "1") != "0":
        media_ingestor = MediaIngestor(
            bd_client,
            max_images_per_doc=int(os.environ.get("MEDIA_INGEST_MAX_PER_DOC", "4")),
        )

    engine = create_engine(database_url)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    try:
        # --- §11.6 bandit wiring (locked-as-committed) ---
        # Load (or cold-start) the persisted bandit state from
        # `data/discovery_bandit.json`, hand the agent the bandit so
        # `serp_queries()` calls `bandit.select(k=10)` instead of the
        # hand-tuned static list. Post-run we credit each selected arm with
        # the count of NEW canonical primitives it surfaced + the dedup-attributed
        # cost, then `to_disk` so tomorrow's run learns from today's yield.
        from rogue.harvest.bandit import EpsilonGreedyBandit
        from rogue.harvest.discovery_agent import MULTIMODAL_ARM_IDS, default_bandit_arms
        bandit_arms = default_bandit_arms()
        if multimodal_only:
            # Restrict the SERP phase to the 6 multimodal arms and use an
            # ISOLATED bandit state file so the main 45-arm state (and the DB
            # mirror behind /api/bandit/stats) is never clobbered by a partial
            # `to_disk`. The multimodal arms are cold-start anyway, so nothing
            # learned is lost. (#1b focused harvest.)
            bandit_arms = [a for a in bandit_arms if a.arm_id in MULTIMODAL_ARM_IDS]
            BANDIT_STATE_PATH = bandit_state_path or Path(
                "data/discovery_bandit_multimodal.json"
            )
            logger.info(
                "MULTIMODAL-ONLY harvest: %d SERP arms, plugins skipped, "
                "isolated bandit state", len(bandit_arms),
            )
        else:
            BANDIT_STATE_PATH = bandit_state_path or Path("data/discovery_bandit.json")
        bandit = EpsilonGreedyBandit.from_disk(bandit_arms, BANDIT_STATE_PATH)

        # --- Layer 1: HARVEST ---
        # Feature C: post→link following is on unless HARVEST_FOLLOW_LINKS=0
        # (spends Web-Unlocker credit, bounded by the phase caps).
        follow_links = os.environ.get("HARVEST_FOLLOW_LINKS", "1") != "0"
        # X timeline scraping is OFF by default (BD's discover-by-profile-url
        # scraper is slow, ~5-15 min/handle). Opt in via --x-handles to harvest
        # specific accounts' recent posts (then Feature-A image ingestion +
        # Feature-C link following apply to them like any source).
        plugins = None
        agent_bandit = bandit
        if multimodal_only:
            # SERP-only: run just the 6 multimodal arms, skip ALL plugins —
            # crucially the cs.CV/cs.MM /new listing crawl, which over a 21-day
            # window is high-volume + unfiltered (the expensive, low-precision
            # path). The SERP arms target attack papers directly (high precision).
            plugins = []
        elif x_only:
            # Harvest ONLY X (skip the other 9 plugins + the bandit SERP
            # discovery phase). Link-following stays on so Pliny's outbound
            # links are still followed (Feature C). Fast/cheap focused run.
            from rogue.harvest.sources import XViaUnlockerPlugin

            plugins = [XViaUnlockerPlugin(handles=list(x_handles) if x_handles else None)]
            agent_bandit = None  # no SERP phase in X-only mode
            logger.info("X-ONLY harvest for handles: %s", ", ".join(x_handles or ["<defaults>"]))
        elif x_handles:
            from rogue.harvest.discovery_agent import default_plugins
            from rogue.harvest.sources import XViaUnlockerPlugin

            plugins = default_plugins() + [XViaUnlockerPlugin(handles=list(x_handles))]
            logger.info("X (SERP+Unlocker) ENABLED for handles: %s", ", ".join(x_handles))
        agent = DiscoveryAgent(
            bd_client, plugins=plugins, bandit=agent_bandit, follow_links=follow_links
        )

        # §11.7 Tier B — preload the fetch_cache ledger so harvest can skip
        # re-spend up front: (1) the SERP phase skips URLs we've already
        # Web-Unlocked on a prior day (cross-run seed); (2) plugins that expose
        # a cheap pre-fetch freshness token (github blob-SHA) skip the fetch
        # when the token is unchanged. Best-effort — a missing table (pre-0011)
        # just yields an empty cache, so the harvest behaves exactly as before.
        prefetched_urls: set[str] = set()
        version_cache: dict[str, str] = {}
        try:
            with SessionLocal() as _pre_session:
                _snap = load_snapshot(_pre_session)
            prefetched_urls = set(_snap)
            version_cache = {
                u: cv.version_token for u, cv in _snap.items() if cv.version_token
            }
            logger.info(
                "fetch_cache: preloaded %d urls (%d with a pre-fetch token)",
                len(prefetched_urls),
                len(version_cache),
            )
        except Exception as exc:  # noqa: BLE001 — cache miss must never block harvest
            logger.warning("fetch_cache preload skipped: %s", exc)
        # Inject the pre-fetch token map into every plugin. The base
        # SourcePlugin.should_skip_fetch reads it, so plugins that only
        # direct-fetch (or never call should_skip_fetch) are unaffected.
        for _plugin in agent.plugins:
            _plugin.version_cache = version_cache

        raw_docs = await agent.run(since=since, prefetched_urls=prefetched_urls)
        stats.raw_docs = len(raw_docs)
        # Per-plugin visibility — one INFO line per plugin so a "0" never
        # again hides because the plugin ate the underlying BD error. ERROR
        # at the top level is still escalated; per-call errors come through
        # as a count + a 3-sample preview so the line stays readable when a
        # plugin makes dozens of calls.
        for report in agent.last_run_reports:
            logger.info(
                "harvest plugin %-22s docs=%-4d call_errors=%d%s",
                report.plugin_name,
                report.n_docs,
                len(report.call_errors),
                (
                    f"  sample={list(report.call_errors[:3])}"
                    if report.call_errors
                    else ""
                ),
            )
            if report.error:
                logger.warning(
                    "harvest plugin %s failed at top level: %s",
                    report.plugin_name, report.error,
                )

        # Feature C telemetry — how many post→links were followed this run.
        if getattr(agent, "last_link_follow_count", 0):
            logger.info(
                "post→link follow: %d links followed ($%.4f Unlocker spend, %d errors)",
                agent.last_link_follow_count,
                agent.last_link_follow_cost,
                len(agent.last_link_follow_errors),
            )

        # --- Layer 2 + 3 + persist: concurrent extract + serial dedup ---
        # Extraction is the wall-clock bottleneck (Anthropic TPM cap dominates).
        # Fan out extract_from_raw_document with a Semaphore-bounded concurrency
        # limit so we burst the LLM up to its rate cap without overshooting;
        # tenacity inside the SDK handles 429-backoff if we do. Dedup + DB
        # persist STAYS serial — pgvector cosine query + INSERT is not the
        # bottleneck and racing two primitives through the dedup gate could
        # create cluster-id collisions (the assign_cluster method is not
        # thread-safe).
        #
        # Default chosen for Tier-2 (450K input TPM). Tier-aware table
        # documented in tasks/LESSONS.md "TPM-cap drop confirmed" entry; if
        # you're on a different Anthropic tier, override the env var:
        #
        #     Tier 1 (50K TPM):   EXTRACTION_CONCURRENCY=1
        #     Tier 2 (450K TPM):  EXTRACTION_CONCURRENCY=3   (default)
        #     Tier 3 (1M TPM):    EXTRACTION_CONCURRENCY=5
        #     Tier 4 (2M TPM):    EXTRACTION_CONCURRENCY=10
        #
        # Wrong tier × wrong concurrency = 429 storms + dropped docs (verified
        # 2026-05-26 lost 800/1644 on Tier-1 at 5; verified 2026-05-27 lost
        # 517/1522 on Tier-2 at 5 before this default was lowered).
        EXTRACTION_CONCURRENCY = int(os.environ.get("EXTRACTION_CONCURRENCY", "3"))
        sem = asyncio.Semaphore(EXTRACTION_CONCURRENCY)

        # Feature A run-level image budget — a hard cap on how many images the
        # whole run will download (Web Unlocker credit). `used` is mutated under
        # the asyncio single-thread model (no lock needed; tasks yield only at
        # awaits). Per-doc count is bounded separately by the ingestor.
        media_budget = {
            "used": 0,
            "cap": int(os.environ.get("MEDIA_INGEST_MAX_TOTAL", "60")),
        }

        async def _ingest_images(raw_doc: RawDocument) -> "list[ExtractionImage] | None":
            """Download (cache-first) the doc's images → ExtractionImages, or None.

            No-op when ingestion is disabled, the run budget is spent, or the doc
            carries no images. Failures are isolated — a bad image never sinks
            the doc's extraction (it just runs text-only)."""
            if media_ingestor is None or media_budget["used"] >= media_budget["cap"]:
                return None
            try:
                ingested = await media_ingestor.ingest_for_document(raw_doc)
            except Exception as exc:  # noqa: BLE001 — image failure ⇒ text-only
                logger.warning("media ingest failed: url=%s err=%s", raw_doc.url, exc)
                return None
            if not ingested:
                return None
            media_budget["used"] += len(ingested)
            stats.images_ingested += len(ingested)
            return [
                ExtractionImage(
                    b64=im.b64,
                    media_type=im.media_type,
                    source_url=im.url,
                    path=str(im.path),
                )
                for im in ingested
            ]

        async def extract_one(
            raw_doc: RawDocument,
        ) -> tuple[RawDocument, "AttackPrimitive | TechniqueSpec | None | Exception"]:
            async with sem:
                try:
                    images = await _ingest_images(raw_doc)
                    # §10.9 — the 3-way union: a payload (AttackPrimitive), a
                    # technique (TechniqueSpec), or None (commentary).
                    result = await extractor.extract_any_from_raw_document(
                        raw_doc, images=images
                    )
                    return (raw_doc, result)
                except Exception as exc:  # noqa: BLE001 - we surface every error
                    return (raw_doc, exc)

        # Track URLs of NEW canonical primitives produced THIS run, for
        # per-arm bandit attribution at the end (replacing the prior even-
        # split heuristic — see §11.6 attribution block below).
        new_canonical_urls: list[str] = []

        with SessionLocal() as session:
            spend = daily_bd_spend_usd(session)
            dedup = Deduplicator(session=session, embed_fn=embed_fn)

            # §11.7 Tier A — universal pre-extraction skip. Drop docs whose body
            # is byte-identical to what we already extracted (same url +
            # archive_hash in the fetch_cache ledger): re-extracting only
            # re-derives the primitive we already have, then cosine-dedups it
            # away. Skipping here saves the LLM extraction call (the wall-clock
            # + $ bottleneck). Works for every source.
            fetch_cache = FetchCache(session)
            docs_to_extract: list[RawDocument] = []
            for d in raw_docs:
                if fetch_cache.should_skip_extract(str(d.url), d.archive_hash):
                    stats.skipped_unchanged += 1
                else:
                    docs_to_extract.append(d)

            logger.info(
                "extracting %d raw_docs (%d skipped as unchanged; concurrency=%d)",
                len(docs_to_extract),
                stats.skipped_unchanged,
                EXTRACTION_CONCURRENCY,
            )
            extract_results = await asyncio.gather(
                *(extract_one(d) for d in docs_to_extract)
            )

            # §11.7 ledger writes accumulated during the persist loop, flushed
            # once after it so cache rows aren't tangled with per-doc rollbacks.
            cache_records: list[dict] = []

            # Serial dedup + persist loop on the now-extracted primitives.
            # Per-doc errors stay isolated; one bad primitive doesn't tank
            # the rest of the run.
            for raw_doc, result in extract_results:
                if isinstance(result, Exception):
                    stats.extract_errors += 1
                    logger.warning(
                        "extract failed: url=%s err=%s", raw_doc.url, result,
                    )
                    continue

                # §10.9 Phase 3a — a harvested *technique* (a reusable method)
                # goes into attack_strategies, not the primitive corpus. The
                # planner picks it up on the next run (text/multi_turn techniques
                # carry a synthesized directive; image/audio land as
                # needs_implementation). Isolated per-doc like the primitive path.
                if isinstance(result, TechniqueSpec):
                    try:
                        from rogue.harvest.source_date import derive_source_date
                        _src_date, _ = derive_source_date(raw_doc)
                        persist_technique(
                            session, result,
                            source_date=_src_date, harvest_run_id=harvest_run_id,
                        )
                        session.commit()
                        stats.techniques_harvested += 1
                        logger.info(
                            "harvested technique: name=%r modality=%s status=%s url=%s",
                            result.name,
                            result.modality.value,
                            result.status.value,
                            raw_doc.url,
                        )
                    except Exception as exc:
                        stats.extract_errors += 1
                        session.rollback()
                        logger.exception(
                            "technique persist failed: url=%s err=%s", raw_doc.url, exc,
                        )
                    cache_records.append(
                        {
                            "url": str(raw_doc.url),
                            "source_type": str(raw_doc.source_type),
                            "content_hash": raw_doc.archive_hash,
                            "version_token": raw_doc.metadata.get("version_token"),
                            "last_status": "technique",
                            "n_primitives_yielded": 0,
                        }
                    )
                    continue

                primitive = result
                if primitive is None:
                    stats.skipped_commentary += 1
                    # Record so an identical re-fetch next run skips the LLM
                    # re-classification of known-commentary content.
                    cache_records.append(
                        {
                            "url": str(raw_doc.url),
                            "source_type": str(raw_doc.source_type),
                            "content_hash": raw_doc.archive_hash,
                            "version_token": raw_doc.metadata.get("version_token"),
                            "last_status": "commentary",
                            "n_primitives_yielded": 0,
                        }
                    )
                    continue

                # Ensure provenance is attached (LLM may omit; we always know it).
                primitive = _ensure_primitive_has_provenance(primitive, raw_doc)

                try:
                    orm_row = _to_orm_primitive(primitive)
                    dedup.assign_cluster(orm_row, daily_bd_spend_usd=spend)
                    if orm_row.canonical:
                        stats.new_clusters += 1
                        # Capture the source URL for per-arm bandit attribution.
                        # Use raw_doc.url (the actual fetch target) — falls back
                        # to the first SourceProvenance URL if multiple are
                        # attached (rare; harvest-side always sets raw_doc.url
                        # to the canonical source URL).
                        new_canonical_urls.append(str(raw_doc.url))
                    else:
                        stats.duplicates += 1
                    session.add(orm_row)
                    session.commit()
                    stats.extracted += 1
                    # §11.7 — stage ledger row (content_hash for Tier A;
                    # version_token from the plugin's listing for Tier B).
                    cache_records.append(
                        {
                            "url": str(raw_doc.url),
                            "source_type": str(raw_doc.source_type),
                            "content_hash": raw_doc.archive_hash,
                            "version_token": raw_doc.metadata.get("version_token"),
                            "last_status": "ok",
                            "n_primitives_yielded": 1 if orm_row.canonical else 0,
                        }
                    )
                except Exception as exc:
                    stats.dedup_errors += 1
                    session.rollback()
                    logger.exception(
                        "dedup/persist failed: url=%s err=%s", raw_doc.url, exc,
                    )

            # §11.7 — flush the fetch-cache ledger once, isolated from the
            # per-doc primitive commits above so a mid-loop rollback can't drop
            # cache rows. Best-effort: a ledger failure must never fail the
            # harvest — worst case we re-crawl next run. Extract/dedup errors
            # are intentionally NOT recorded so they retry next run.
            if cache_records:
                try:
                    for rec in cache_records:
                        fetch_cache.record(**rec)
                    session.commit()
                    logger.info(
                        "fetch_cache: recorded %d urls (%d skipped as unchanged this run)",
                        len(cache_records),
                        stats.skipped_unchanged,
                    )
                except Exception as exc:  # noqa: BLE001 — ledger must not fail harvest
                    session.rollback()
                    logger.warning("fetch_cache ledger write failed: %s", exc)
        # --- §11.6 bandit reward attribution + persist ---
        # Per-arm attribution via URL site-pattern matching (see
        # `rogue.harvest.bandit_attribution`). For each picked arm, novel =
        # count of THIS RUN's new canonical primitives whose URL matches the
        # arm's `site:` operator with the longest specificity (most-specific-
        # wins: a github.com/elder-plinius URL routes to `github_pliny_umbrella`,
        # not the generic `github_pi_trending`). Restricted to picked arms
        # only — an arm that wasn't selected this run gets no credit even if
        # its pattern matches today's URLs, preserving the bandit's "I picked
        # these, this is what they returned" learning semantics.
        #
        # Cost: $0.0015 per pick (conservative SERP-call estimate). Arms that
        # were picked but matched no URLs get pulls=1, novel=0 — the bandit
        # correctly learns they were unproductive this run.
        #
        # Replaces the prior even-split heuristic (`new_clusters // n_arms`)
        # which credited unrelated arms with phantom yield from primitives
        # they couldn't have surfaced. See ROGUE_PLAN.md §11.6 (c-full)
        # closure 2026-05-27.
        try:
            arms_used = agent.last_selected_arms or []
            n_arms = len(arms_used)
            if n_arms > 0:
                from rogue.harvest.bandit_attribution import (
                    attribute_urls_to_arms,
                    build_arm_pattern_map,
                )

                arm_pattern_map = build_arm_pattern_map(bandit.arms)
                picked_arm_ids = {arm_id for arm_id, _ in arms_used}
                per_arm_novel = attribute_urls_to_arms(
                    new_canonical_urls,
                    arm_pattern_map,
                    restrict_to_arms=picked_arm_ids,
                )
                # Per-arm cost: prefer the real SERP-phase spend from
                # `agent.last_serp_phase_cost` (populated by (c-serp) when the
                # bandit-driven SERP phase fires). Fall back to the flat
                # $0.0015 SERP-only estimate when the SERP phase was skipped
                # (no bandit wired, or no arms picked, or phase errored out).
                serp_phase_cost = getattr(agent, "last_serp_phase_cost", None) or {}
                fallback_cost = 0.0015
                attributed_total = 0
                for arm_id, _ in arms_used:
                    novel = per_arm_novel.get(arm_id, 0)
                    attributed_total += novel
                    cost = serp_phase_cost.get(arm_id, fallback_cost)
                    bandit.record(arm_id, novel=novel, cost_usd=cost)
                logger.info(
                    "bandit attribution: %d/%d new canonicals credited across "
                    "%d picked arms (%d arms got novel>0); total SERP-phase "
                    "spend $%.4f",
                    attributed_total,
                    stats.new_clusters,
                    n_arms,
                    sum(1 for v in per_arm_novel.values() if v > 0),
                    sum(serp_phase_cost.values()),
                )
            bandit.to_disk(BANDIT_STATE_PATH)
            logger.info(
                "bandit: persisted %d arms (%d picked this run)",
                len(bandit.arms), n_arms,
            )
            # Mirror the state into the DB so /api/bandit/stats is live (no
            # redeploy). SKIP in multimodal-only mode — that run holds only the
            # 6-arm subset, so mirroring would overwrite the live 45-arm view.
            if multimodal_only:
                logger.info(
                    "bandit: DB mirror skipped (multimodal-only 6-arm subset)"
                )
            else:
                try:
                    from rogue.db.bandit_state import save_bandit_state

                    with SessionLocal() as bandit_session:
                        save_bandit_state(bandit_session, bandit.to_dict())
                    logger.info("bandit: mirrored state to DB (bandit_state row)")
                except Exception as exc:  # never let DB-mirroring break the harvest
                    logger.warning(
                        "bandit: DB mirror failed (file still written): %s", exc
                    )
        except Exception as exc:  # noqa: BLE001 - bandit failure must not block harvest
            logger.warning("bandit: persist failed (%s) — state may be stale", exc)
    finally:
        await bd_client.aclose()
        engine.dispose()

    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="One-shot ROGUE harvest run (§A.12)."
    )
    parser.add_argument(
        "--since",
        default="1d",
        help="Time window to harvest (e.g. '1d', '14d', '6h'). Default: 1d.",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        help="SQLAlchemy URL. Default: DATABASE_URL env var or local docker-compose.",
    )
    parser.add_argument(
        "--extraction-model",
        default=os.environ.get("EXTRACTION_MODEL", DEFAULT_EXTRACTION_MODEL),
        help="Provider-prefixed model id, e.g. 'anthropic/claude-haiku-4-5'.",
    )
    parser.add_argument(
        "--embedding-model",
        default=os.environ.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        help="OpenAI embedding model id (1536-d to match the pgvector column).",
    )
    parser.add_argument(
        "--x-handles",
        default=None,
        help=(
            "Comma-separated X/Twitter handles to scrape this run (e.g. "
            "'elder_plinius' or 'elder_plinius,wunderwuzzi23'). X is OFF by "
            "default — BD's discover-by-profile-url scraper is slow (~5-15 "
            "min/handle), so opt in only when you want it. Pulls each handle's "
            "recent posts within --since; attached images are ingested (Feature "
            "A) and outbound links followed (Feature C). Needs "
            "BRIGHTDATA_X_POSTS_DATASET_ID set."
        ),
    )
    parser.add_argument(
        "--x-only",
        action="store_true",
        help=(
            "Harvest ONLY X (the handles from --x-handles, or the 4 defaults) — "
            "skip the other 9 sources + the SERP discovery phase. Fast, focused "
            "re-run; link-following from the posts stays on. Pair with a bumped "
            "BRIGHTDATA_POLL_TIMEOUT_SECONDS (X is slow)."
        ),
    )
    parser.add_argument(
        "--multimodal-only",
        action="store_true",
        help=(
            "Harvest ONLY the 6 multimodal SERP arms (vision-language / "
            "multimodal / cross-modal / typographic-VLM / audio + github), "
            "skipping ALL plugins (incl. the broad cs.CV/cs.MM listing crawl). "
            "Focused, cheap multimodal probe; uses an isolated bandit state file "
            "so the main 45-arm pool + /api/bandit/stats are untouched. (#1b.)"
        ),
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Override for the per-run correlation id (default: a fresh UUID).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    run_id = args.run_id or uuid.uuid4().hex[:12]
    logger.info("run_id=%s start: --since=%s", run_id, args.since)

    since = parse_since(args.since)
    logger.info("harvest window: since=%s", since.isoformat())

    x_handles = (
        [h.strip() for h in args.x_handles.split(",") if h.strip()]
        if args.x_handles
        else None
    )
    stats = asyncio.run(
        run_harvest(
            since=since,
            database_url=args.database_url,
            extraction_model=args.extraction_model,
            embedding_model=args.embedding_model,
            x_handles=x_handles,
            x_only=args.x_only,
            multimodal_only=args.multimodal_only,
            harvest_run_id=run_id,
        )
    )
    logger.info("run_id=%s done: %s", run_id, stats.summary_line())

    # Cache any ingested images into the DB, then auto-push to Neon — both
    # data-only, no spend, no-op when NEON_DATABASE_URL is unset / on Neon.
    from rogue.db.image_cache import maybe_cache_images
    from rogue.db.neon_sync import maybe_auto_sync
    from rogue.notify import revalidate_frontend

    maybe_cache_images(args.database_url)
    maybe_auto_sync(args.database_url)
    # New primitives are in Neon now — regenerate the cached dashboard pages
    # immediately (no-op if the revalidate env vars are unset).
    revalidate_frontend()

    # Append a backlog snapshot — this is the only moment needs_implementation
    # can change, so the 3b-v2 trigger time series builds itself (no cron).
    # Best-effort: a tracking failure must never fail a successful harvest.
    try:
        import sys as _sys
        from datetime import datetime, timezone
        from pathlib import Path as _Path

        # When run as `python scripts/harvest_once.py`, sys.path[0] is scripts/,
        # not the repo root — so `from scripts.track_backlog` fails. Put the repo
        # root on the path so the namespace import resolves.
        _root = str(_Path(__file__).resolve().parent.parent)
        if _root not in _sys.path:
            _sys.path.insert(0, _root)
        from scripts.track_backlog import snapshot
        c = snapshot(args.database_url, run_id=run_id,
                     ts=datetime.now(timezone.utc).isoformat())
        logger.info("backlog snapshot: needs_implementation=%d (audio=%d image=%d) "
                    "discoverable=%d testable=%d actionable=%d",
                    c["needs_implementation"], c["audio"], c["image"],
                    c["discoverable"], c["testable"], c["actionable"])
    except Exception as exc:  # noqa: BLE001 — tracking is non-critical
        logger.warning("backlog snapshot skipped: %s", exc)
    return 0


# Hash util kept around for downstream callers that need to recompute
# RawDocument provenance hashes outside this script (e.g. backfill runs).
def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess in test
    sys.exit(main())
