"""Smoke tests for ``scripts/harvest/harvest_once.py``.

Two flavours:

  * **Pure-Python helpers** (always run) — ``parse_since``,
    ``_synthesize_source``, ``_ensure_primitive_has_provenance``,
    ``HarvestRunStats.summary_line``. No DB, no network.

  * **End-to-end mocked pipeline** (skip cleanly when Postgres unreachable)
    — ``run_harvest`` exercised with mocked BD client + extractor + embedder
    against a live migrated DB; verifies stats counters and that rows land
    in ``attack_primitives``.

The end-to-end test is what proves the Day-1 glue is wired correctly
without paying the real-API tax.

Spec: ROGUE_PLAN.md §A.12, §9.5.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rogue.schemas import AttackPrimitive, RawDocument
from scripts.harvest.harvest_once import (
    HarvestRunStats,
    _ensure_primitive_has_provenance,
    _synthesize_source,
    parse_since,
    run_harvest,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"
DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue_test"
)


def _database_url() -> str:
    # TEST_DATABASE_URL (NOT DATABASE_URL) — tests must NEVER touch the
    # dev DB. See test_smoke.py docstring for the gotcha resolution.
    return os.environ.get("TEST_DATABASE_URL", DEFAULT_DATABASE_URL)


# --------------------------------------------------------------------------- #
# A. Pure-Python helpers
# --------------------------------------------------------------------------- #


def test_parse_since_days() -> None:
    now = datetime.now(timezone.utc)
    parsed = parse_since("3d")
    expected = now - timedelta(days=3)
    # 5-second tolerance so the test is wall-clock-robust.
    assert abs((parsed - expected).total_seconds()) < 5


def test_parse_since_hours() -> None:
    now = datetime.now(timezone.utc)
    parsed = parse_since("6h")
    expected = now - timedelta(hours=6)
    assert abs((parsed - expected).total_seconds()) < 5


def test_parse_since_rejects_invalid_format() -> None:
    """Misconfiguration must be loud, not silently default."""
    for bad in ["1w", "1", "d", "abc", "", "1.5d"]:
        with pytest.raises(ValueError):
            parse_since(bad)


def test_synthesize_source_mirrors_raw_document_fields() -> None:
    raw = _make_raw_document()
    out = _synthesize_source(raw)
    assert out["url"] == str(raw.url)
    assert out["source_type"] == raw.source_type
    assert out["bright_data_product"] == raw.bright_data_product
    assert out["fetched_at"] == raw.fetched_at
    assert out["archive_hash"] == raw.archive_hash
    assert out["author"] is None
    assert out["published_at"] is None


def test_ensure_primitive_has_provenance_adds_when_missing() -> None:
    raw = _make_raw_document()
    primitive = _load_golden_primitive()
    # Strip the source list so we hit the synthesis branch.
    stripped = primitive.model_copy(update={"sources": []})
    assert stripped.sources == []

    patched = _ensure_primitive_has_provenance(stripped, raw)

    assert len(patched.sources) == 1
    assert str(patched.sources[0].url) == str(raw.url)
    assert patched.sources[0].archive_hash == raw.archive_hash


def test_ensure_primitive_has_provenance_preserves_existing() -> None:
    """When the LLM already populated sources, don't touch them."""
    raw = _make_raw_document()
    primitive = _load_golden_primitive()
    assert len(primitive.sources) >= 1  # golden fixture invariant

    out = _ensure_primitive_has_provenance(primitive, raw)
    assert out.sources == primitive.sources


def test_harvest_run_stats_summary_line_includes_all_counters() -> None:
    stats = HarvestRunStats(
        raw_docs=10,
        extracted=7,
        skipped_commentary=2,
        extract_errors=1,
        dedup_errors=0,
        new_clusters=5,
        duplicates=2,
    )
    line = stats.summary_line()
    for token in (
        "raw_docs=10", "extracted=7", "skipped_commentary=2",
        "extract_errors=1", "dedup_errors=0", "new_clusters=5", "duplicates=2",
    ):
        assert token in line


# --------------------------------------------------------------------------- #
# B. End-to-end mocked pipeline
# --------------------------------------------------------------------------- #


@pytest.fixture
def live_db(monkeypatch) -> Iterator[str]:
    """Run alembic upgrade head; yield the URL; downgrade for idempotency.

    Skips cleanly when Postgres is unreachable (mirrors test_smoke pattern).

    monkeypatches DATABASE_URL → TEST_DATABASE_URL because alembic env.py
    overrides cfg.sqlalchemy.url with DATABASE_URL. Without the patch,
    alembic would migrate the dev `rogue` DB instead of `rogue_test`.
    """
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError

    url = _database_url()
    monkeypatch.setenv("DATABASE_URL", url)
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect():
            pass
    except (OperationalError, ConnectionRefusedError, socket.gaierror, OSError) as exc:
        pytest.skip(
            f"Postgres not reachable at {url}: {exc.__class__.__name__}: {exc} "
            "— run `docker compose up -d`"
        )
    finally:
        try:
            engine.dispose()
        except Exception:
            pass

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    try:
        command.upgrade(cfg, "head")
        yield url
    finally:
        command.downgrade(cfg, "base")


@pytest.mark.asyncio
async def test_run_harvest_end_to_end_with_mocks(live_db, tmp_path) -> None:
    """Run the full pipeline against the migrated DB with mocked BD/LLM/embedder.

    Verifies that:
      * the discovery agent's RawDocuments flow through extraction → dedup
      * canonical primitives land in attack_primitives with cluster_id set
      * a duplicate-on-the-second-call goes in as canonical=False
      * stats counters reflect the run shape
    """
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import sessionmaker

    from rogue.db.models import (
        AttackPrimitive as AttackPrimitiveORM,
        SourceProvenance as SourceProvenanceORM,
    )

    # Two RawDocuments that both extract to the SAME primitive (different
    # primitive_ids though, so the dedup engine has to make the cluster call).
    raw_a = _make_raw_document(url="https://a.example.com/post", content="aaa")
    raw_b = _make_raw_document(url="https://b.example.com/post", content="bbb")

    golden = _load_golden_primitive()
    primitive_a = golden.model_copy(
        update={"primitive_id": "01HFGZRX4QHARVESTONCEAAAAA001", "sources": []},
    )
    primitive_b = golden.model_copy(
        update={"primitive_id": "01HFGZRX4QHARVESTONCEBBBBB002", "sources": []},
    )

    # Injected doubles: DiscoveryAgent (patched at import site), extractor,
    # BD client, and embed_fn (passed positionally so OpenAI is never imported).
    mock_extractor = MagicMock()
    mock_extractor.extract_any_from_raw_document = AsyncMock(
        side_effect=[primitive_a, primitive_b],
    )
    mock_bd_client = MagicMock()
    mock_bd_client.aclose = AsyncMock()

    fixed_vec = [0.0] * 1536
    fixed_vec[42] = 1.0

    def fixed_embed_fn(text: str) -> list[float]:
        return list(fixed_vec)

    # Patch daily_bd_spend_usd around a known pre-existing ORM/migration drift
    # in `bright_data_cost_log` (ORM declares cost_usd/ran_at; the 0001
    # migration created estimated_cost_usd/latency_ms — see ORM model
    # docstring). Spend semantics aren't load-bearing for this wiring test.
    from decimal import Decimal as _Decimal
    with patch("scripts.harvest.harvest_once.DiscoveryAgent") as mock_discovery_cls, \
         patch("scripts.harvest.harvest_once.daily_bd_spend_usd", return_value=_Decimal("0.00")):
        agent_instance = MagicMock()
        agent_instance.run = AsyncMock(return_value=[raw_a, raw_b])
        agent_instance.last_run_reports = []
        mock_discovery_cls.return_value = agent_instance

        stats = await run_harvest(
            since=datetime.now(timezone.utc) - timedelta(days=1),
            database_url=live_db,
            bd_client=mock_bd_client,
            extractor=mock_extractor,
            embed_fn=fixed_embed_fn,
            bandit_state_path=tmp_path / "discovery_bandit.json",
        )

    # --- Stats assertions ---
    assert stats.raw_docs == 2
    assert stats.extracted == 2
    assert stats.skipped_commentary == 0
    assert stats.extract_errors == 0
    assert stats.dedup_errors == 0
    # First primitive seeds its own cluster (canonical); second clusters with
    # it because the fixed vector forces cosine-similarity 1.0.
    assert stats.new_clusters == 1
    assert stats.duplicates == 1

    # --- DB-level assertions ---
    engine = create_engine(live_db)
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        total = session.execute(
            select(func.count()).select_from(AttackPrimitiveORM)
        ).scalar_one()
        assert total == 2
        canonical_count = session.execute(
            select(func.count())
            .select_from(AttackPrimitiveORM)
            .where(AttackPrimitiveORM.canonical.is_(True))
        ).scalar_one()
        assert canonical_count == 1
        # Both rows must share a cluster_id.
        cluster_ids = set(
            row[0] for row in session.execute(
                select(AttackPrimitiveORM.cluster_id)
            ).all()
        )
        assert len(cluster_ids) == 1
        # Source provenance attached (one per primitive, via either the
        # extractor-emitted list or the synthesizer).
        n_sources = session.execute(
            select(func.count()).select_from(SourceProvenanceORM)
        ).scalar_one()
        assert n_sources >= 2
    engine.dispose()


@pytest.mark.asyncio
async def test_run_harvest_isolates_extract_errors(live_db, tmp_path) -> None:
    """A single extract exception must NOT abort the run; the counter ticks."""
    raw_good = _make_raw_document(url="https://good.example.com/", content="ok")
    raw_bad = _make_raw_document(url="https://bad.example.com/", content="x")
    primitive = _load_golden_primitive().model_copy(
        update={"primitive_id": "01HFGZRX4QHARVESTONCEISOLA003", "sources": []},
    )

    mock_extractor = MagicMock()
    mock_extractor.extract_any_from_raw_document = AsyncMock(
        side_effect=[primitive, RuntimeError("extraction blew up")],
    )

    mock_bd_client = MagicMock()
    mock_bd_client.aclose = AsyncMock()

    def zero_embed_fn(text: str) -> list[float]:
        return [0.0] * 1536

    from decimal import Decimal as _Decimal
    with patch("scripts.harvest.harvest_once.DiscoveryAgent") as mock_discovery_cls, \
         patch("scripts.harvest.harvest_once.daily_bd_spend_usd", return_value=_Decimal("0.00")):
        agent_instance = MagicMock()
        agent_instance.run = AsyncMock(return_value=[raw_good, raw_bad])
        agent_instance.last_run_reports = []
        mock_discovery_cls.return_value = agent_instance

        stats = await run_harvest(
            since=datetime.now(timezone.utc) - timedelta(days=1),
            database_url=live_db,
            bd_client=mock_bd_client,
            extractor=mock_extractor,
            embed_fn=zero_embed_fn,
            bandit_state_path=tmp_path / "discovery_bandit.json",
        )

    assert stats.raw_docs == 2
    assert stats.extracted == 1
    assert stats.extract_errors == 1


@pytest.mark.asyncio
async def test_run_harvest_x_handles_adds_x_plugin(live_db, tmp_path) -> None:
    """--x-handles → the X timeline plugin is added to the DiscoveryAgent's
    plugin list (it's off by default)."""
    from rogue.harvest.sources import XViaUnlockerPlugin

    mock_extractor = MagicMock()
    mock_extractor.extract_any_from_raw_document = AsyncMock(return_value=None)
    mock_bd_client = MagicMock()
    mock_bd_client.aclose = AsyncMock()

    from decimal import Decimal as _Decimal
    with patch("scripts.harvest.harvest_once.DiscoveryAgent") as mock_discovery_cls, \
         patch("scripts.harvest.harvest_once.daily_bd_spend_usd", return_value=_Decimal("0.00")):
        agent_instance = MagicMock()
        agent_instance.run = AsyncMock(return_value=[])
        agent_instance.last_run_reports = []
        mock_discovery_cls.return_value = agent_instance

        await run_harvest(
            since=datetime.now(timezone.utc) - timedelta(days=1),
            database_url=live_db,
            bd_client=mock_bd_client,
            extractor=mock_extractor,
            embed_fn=lambda t: [0.0] * 1536,
            bandit_state_path=tmp_path / "discovery_bandit.json",
            x_handles=["elder_plinius"],
        )

        plugins = mock_discovery_cls.call_args.kwargs["plugins"]
        x_plugins = [p for p in plugins if isinstance(p, XViaUnlockerPlugin)]
        assert len(x_plugins) == 1
        assert x_plugins[0].handles == ["elder_plinius"]


@pytest.mark.asyncio
async def test_run_harvest_no_x_handles_keeps_default_plugins(live_db, tmp_path) -> None:
    """Without --x-handles, plugins=None (DiscoveryAgent uses its default set, no X)."""
    mock_extractor = MagicMock()
    mock_extractor.extract_any_from_raw_document = AsyncMock(return_value=None)
    mock_bd_client = MagicMock()
    mock_bd_client.aclose = AsyncMock()

    from decimal import Decimal as _Decimal
    with patch("scripts.harvest.harvest_once.DiscoveryAgent") as mock_discovery_cls, \
         patch("scripts.harvest.harvest_once.daily_bd_spend_usd", return_value=_Decimal("0.00")):
        agent_instance = MagicMock()
        agent_instance.run = AsyncMock(return_value=[])
        agent_instance.last_run_reports = []
        mock_discovery_cls.return_value = agent_instance

        await run_harvest(
            since=datetime.now(timezone.utc) - timedelta(days=1),
            database_url=live_db,
            bd_client=mock_bd_client,
            extractor=mock_extractor,
            embed_fn=lambda t: [0.0] * 1536,
            bandit_state_path=tmp_path / "discovery_bandit.json",
        )
        assert mock_discovery_cls.call_args.kwargs["plugins"] is None


@pytest.mark.asyncio
async def test_run_harvest_x_only_runs_just_x_and_skips_serp(live_db, tmp_path) -> None:
    """--x-only → plugins == [X plugin] and bandit=None (no SERP discovery phase)."""
    from rogue.harvest.sources import XViaUnlockerPlugin

    mock_extractor = MagicMock()
    mock_extractor.extract_any_from_raw_document = AsyncMock(return_value=None)
    mock_bd_client = MagicMock()
    mock_bd_client.aclose = AsyncMock()

    from decimal import Decimal as _Decimal
    with patch("scripts.harvest.harvest_once.DiscoveryAgent") as mock_discovery_cls, \
         patch("scripts.harvest.harvest_once.daily_bd_spend_usd", return_value=_Decimal("0.00")):
        agent_instance = MagicMock()
        agent_instance.run = AsyncMock(return_value=[])
        agent_instance.last_run_reports = []
        agent_instance.last_selected_arms = []
        mock_discovery_cls.return_value = agent_instance

        await run_harvest(
            since=datetime.now(timezone.utc) - timedelta(days=2),
            database_url=live_db,
            bd_client=mock_bd_client,
            extractor=mock_extractor,
            embed_fn=lambda t: [0.0] * 1536,
            bandit_state_path=tmp_path / "discovery_bandit.json",
            x_handles=["elder_plinius"],
            x_only=True,
        )

        kw = mock_discovery_cls.call_args.kwargs
        plugins = kw["plugins"]
        assert len(plugins) == 1 and isinstance(plugins[0], XViaUnlockerPlugin)
        assert plugins[0].handles == ["elder_plinius"]
        assert kw["bandit"] is None  # SERP discovery phase skipped


@pytest.mark.asyncio
async def test_run_harvest_ingests_images_and_passes_to_extractor(
    live_db, tmp_path
) -> None:
    """Feature A end-to-end: a doc with an image → the injected MediaIngestor
    downloads it → the ExtractionImages reach extract_from_raw_document, and the
    images_ingested counter ticks."""
    from rogue.extract.extraction_agent import ExtractionImage
    from rogue.harvest.media_ingest import IngestedImage

    # A real on-disk PNG so ExtractionImage carries a usable verbatim path.
    img_path = tmp_path / "shot.png"
    img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"bytes")

    raw = _make_raw_document(url="https://x.com/elder_plinius/status/1", content="img post")
    primitive = _load_golden_primitive().model_copy(
        update={"primitive_id": "01HFGZRX4QHARVESTONCEIMG00004", "sources": []},
    )

    captured: dict = {}

    async def _extract(raw_doc, images=None):
        captured["images"] = images
        return primitive

    mock_extractor = MagicMock()
    mock_extractor.extract_any_from_raw_document = AsyncMock(side_effect=_extract)

    # Fake ingestor: returns one IngestedImage for the doc.
    ingested = IngestedImage(
        url="https://pbs.twimg.com/media/a.png",
        path=img_path,
        media_type="image/png",
        b64="QUJD",
    )
    mock_ingestor = MagicMock()
    mock_ingestor.ingest_for_document = AsyncMock(return_value=[ingested])

    mock_bd_client = MagicMock()
    mock_bd_client.aclose = AsyncMock()

    def zero_embed_fn(text: str) -> list[float]:
        return [0.0] * 1536

    from decimal import Decimal as _Decimal
    with patch("scripts.harvest.harvest_once.DiscoveryAgent") as mock_discovery_cls, \
         patch("scripts.harvest.harvest_once.daily_bd_spend_usd", return_value=_Decimal("0.00")):
        agent_instance = MagicMock()
        agent_instance.run = AsyncMock(return_value=[raw])
        agent_instance.last_run_reports = []
        mock_discovery_cls.return_value = agent_instance

        stats = await run_harvest(
            since=datetime.now(timezone.utc) - timedelta(days=1),
            database_url=live_db,
            bd_client=mock_bd_client,
            extractor=mock_extractor,
            embed_fn=zero_embed_fn,
            bandit_state_path=tmp_path / "discovery_bandit.json",
            media_ingestor=mock_ingestor,
        )

    assert stats.images_ingested == 1
    mock_ingestor.ingest_for_document.assert_awaited_once()
    # The extractor received exactly one ExtractionImage carrying the cached path.
    imgs = captured["images"]
    assert imgs is not None and len(imgs) == 1
    assert isinstance(imgs[0], ExtractionImage)
    assert imgs[0].path == str(img_path)
    assert imgs[0].media_type == "image/png"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _make_raw_document(
    *,
    url: str = "https://example.com/post",
    content: str = "Document body about prompt injection.",
) -> RawDocument:
    return RawDocument(
        url=url,
        source_type="blog",
        bright_data_product="web_unlocker",
        fetched_at=datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc),
        raw_content=content,
        content_format="markdown",
        archive_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        http_status=200,
        metadata={"test": True},
        discovered_via=None,
    )


def _load_golden_primitive() -> AttackPrimitive:
    fp = FIXTURES_DIR / "01_multilingual_african_languages.json"
    return AttackPrimitive.model_validate(json.loads(fp.read_text(encoding="utf-8")))
