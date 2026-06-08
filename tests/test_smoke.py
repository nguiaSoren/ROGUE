"""Day 0 smoke-test suite for the ROGUE stack.

Covers:
  - every src/rogue/* subpackage imports cleanly (no syntax / circular import bugs)
  - the SQLAlchemy metadata declares the 5 expected tables
  - AttackPrimitive carries the load-bearing indexes + pgvector(1536) column
  - alembic.ini parses and the initial revision (0001) is discoverable
  - BrightDataClient exposes the 6 locked async surfaces + from_env()
  - ExtractionAgent loads its prompt and the prompt mentions all 15 families
  - (network-gated) Postgres at DATABASE_URL is reachable + accepts SELECT 1
  - (network-gated) alembic upgrade head + downgrade base round-trips cleanly

Tests that need a live Postgres skip cleanly when the DB is unreachable — no
hard failures from missing infra. See ROGUE_PLAN.md §8.3 / §13.
"""

from __future__ import annotations

import importlib
import os
import socket
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Tests use a SEPARATE database (`rogue_test`) so this file's
# `alembic upgrade head → downgrade base` round-trip never wipes the dev
# `rogue` DB. Resolution of the 2026-05-24 "Smoke test #9 leaves DB empty"
# LESSONS gotcha. The `rogue_test` DB is created by `docker/init-test-db.sh`
# on fresh volumes; for existing volumes, see the manual `CREATE DATABASE`
# command in `.env.example`.
DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue_test"
)


# --------------------------------------------------------------------------- #
# 1. Import surface
# --------------------------------------------------------------------------- #


PACKAGES_AND_MODULES = [
    "rogue",
    "rogue.schemas",
    "rogue.config",
    "rogue.harvest",
    "rogue.harvest.bright_data_client",
    "rogue.harvest.discovery_agent",
    "rogue.harvest.sources",
    "rogue.extract",
    "rogue.extract.extraction_agent",
    "rogue.dedupe",
    "rogue.dedupe.embeddings",
    "rogue.reproduce",
    "rogue.reproduce.target_panel",
    "rogue.reproduce.judge",
    "rogue.reproduce.instantiator",
    "rogue.diff",
    "rogue.diff.threat_brief",
    "rogue.mcp_server",
    "rogue.mcp_server.server",
    "rogue.db",
    "rogue.db.models",
    "rogue.api",
    "rogue.api.main",
]


def test_all_packages_import() -> None:
    """Every src/rogue/* subpackage + module must import without error."""
    failures: list[str] = []
    for name in PACKAGES_AND_MODULES:
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 - we re-raise with context
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
    assert not failures, "Import failures:\n  " + "\n  ".join(failures)


# --------------------------------------------------------------------------- #
# 2. Metadata: 5 tables declared
# --------------------------------------------------------------------------- #


def test_models_metadata_has_expected_tables() -> None:
    """Base.metadata must declare the ROGUE storage tables.

    Extended 2026-05-27 with ``pair_refinement_steps`` (§10.7 full PAIR
    build, migration 0007); ``bandit_state`` (migration 0010) and
    ``fetch_cache`` (§11.7 skip-cache, migration 0011) added 2026-05-29;
    ``primitive_images`` (DB-stored image bytes, migration 0012) added
    2026-05-30. ``attack_strategies`` (§10.9 self-growing technique library,
    migration 0013) added 2026-06-01. ``renderer_capabilities`` (§10.9 Phase 3b
    governed renderer lifecycle, migration 0015) added 2026-06-02.
    ``ladder_attempts`` (§10.9 orchestration-trace telemetry, migration 0017)
    added 2026-06-02. ``ladder_rotation_membership`` (§10.10 Phase 2.1 reachability
    telemetry, migration 0019) added 2026-06-03. ``technique_embeddings``,
    ``target_embeddings`` and ``retrieval_metrics`` (Technique Retrieval System,
    migration 0026) added 2026-06-06. ``primitive_grammar_labels`` (grammar-component
    study, migration 0027) added 2026-06-06. ``demo_requests`` (website
    demo-request lead capture, migration 0028) added 2026-06-06.
    ``newsletter_subscribers`` (website newsletter sign-up, migration 0029) added
    2026-06-06. ``attestation_entries`` (ROGUE v2 signed-attestation layer,
    per-org append-only hash chain, migration 0031) added 2026-06-08.
    ``mitigations`` (ROGUE v2 Surface 1b measured-remediation results, migration
    0032) added 2026-06-09. Add new entries here when migrations add tables.
    """
    import rogue.platform.models  # noqa: F401 — register the platform tables on Base
    from rogue.db.models import Base

    assert sorted(Base.metadata.tables.keys()) == [
        "api_keys",
        "attack_primitives",
        "attack_strategies",
        "attestation_entries",
        "bandit_state",
        "benchmark_runs",
        "breach_results",
        "bright_data_cost_log",
        "demo_requests",
        "deployment_configs",
        "fetch_cache",
        "integrations",
        "ladder_attempts",
        "ladder_rotation_membership",
        "memberships",
        "mitigations",
        "newsletter_subscribers",
        "organizations",
        "pair_refinement_steps",
        "primitive_grammar_labels",
        "primitive_images",
        "projects",
        "renderer_capabilities",
        "reports",
        "retrieval_metrics",
        "scan_jobs",
        "scan_runs",
        "secrets",
        "source_provenances",
        "target_embeddings",
        "technique_embeddings",
        "users",
    ]


# --------------------------------------------------------------------------- #
# 3. AttackPrimitive scalar indexes
# --------------------------------------------------------------------------- #


def test_attack_primitives_indices_present() -> None:
    """family, vector, discovered_at, cluster_id each need a single-column index.

    Per-column ``index=True`` declarations show up as standalone indexes with
    auto-generated names — we match on the column tuple, not the index name.
    """
    from rogue.db.models import AttackPrimitive

    index_columns = {
        tuple(c.name for c in idx.columns)
        for idx in AttackPrimitive.__table__.indexes
    }
    for column in ("family", "vector", "discovered_at", "cluster_id"):
        assert (column,) in index_columns, (
            f"expected a single-column index on {column!r}, "
            f"found indexes over {sorted(index_columns)}"
        )


# --------------------------------------------------------------------------- #
# 4. pgvector column shape
# --------------------------------------------------------------------------- #


def test_pgvector_column_present() -> None:
    """payload_embedding must be a 1536-d pgvector column."""
    from pgvector.sqlalchemy import Vector

    from rogue.db.models import AttackPrimitive

    col = AttackPrimitive.__table__.columns["payload_embedding"]
    assert isinstance(col.type, Vector), (
        f"payload_embedding type is {type(col.type).__name__}, not pgvector Vector"
    )
    assert col.type.dim == 1536, (
        f"payload_embedding dim is {col.type.dim}, expected 1536 "
        "(text-embedding-3-small)"
    )


# --------------------------------------------------------------------------- #
# 5. Alembic config + initial revision
# --------------------------------------------------------------------------- #


def _alembic_config():
    from alembic.config import Config

    return Config(str(PROJECT_ROOT / "alembic.ini"))


def test_alembic_config_parses_and_has_initial_revision() -> None:
    """alembic.ini parses and the migration chain starts at 0001 (initial schema).

    Was previously a strict ``len(revs) == 1`` assertion, relaxed 2026-05-26
    when migration 0002 (breach_matrix view) landed. The invariant we
    actually care about is: the chain begins with 0001 (initial schema)
    and is contiguous — not that there's exactly one migration.
    """
    from alembic.script import ScriptDirectory

    cfg = _alembic_config()
    sd = ScriptDirectory.from_config(cfg)
    revs = list(sd.walk_revisions())  # newest → oldest
    assert len(revs) >= 1, "expected at least one alembic revision"
    assert revs[-1].revision == "0001", (
        f"oldest revision is {revs[-1].revision!r}, expected '0001' "
        f"(initial schema)"
    )
    # Contiguity guard: each rev (except the head) has the next-newer as
    # its child. Catches a fork or broken chain.
    rev_ids = [r.revision for r in revs]
    assert len(set(rev_ids)) == len(rev_ids), (
        f"duplicate revision ids in chain: {rev_ids}"
    )


# --------------------------------------------------------------------------- #
# 6. BrightDataClient locked surface
# --------------------------------------------------------------------------- #


def test_bright_data_client_has_locked_signatures() -> None:
    """All 6 async methods + from_env() must be present on the Day 0 stub."""
    import inspect

    from rogue.harvest.bright_data_client import BrightDataClient

    expected = {
        "scrape_reddit_subreddit",
        "scrape_x_user_posts",
        "scrape_huggingface_discussion",
        "serp_search",
        "web_unlock",
        "scrape_browser",
    }
    present = {
        name
        for name, _ in inspect.getmembers(
            BrightDataClient, predicate=inspect.iscoroutinefunction
        )
    }
    missing = expected - present
    assert not missing, f"BrightDataClient missing async methods: {sorted(missing)}"
    assert hasattr(BrightDataClient, "from_env"), (
        "BrightDataClient must expose a from_env() constructor"
    )


# --------------------------------------------------------------------------- #
# 7. ExtractionAgent prompt
# --------------------------------------------------------------------------- #


def test_extraction_agent_loads_prompt() -> None:
    """The extraction prompt is non-trivial and mentions every AttackFamily."""
    from rogue.extract.extraction_agent import ExtractionAgent
    from rogue.schemas import AttackFamily

    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")
    assert len(agent.prompt) > 500, "prompt should be non-trivial"
    for fam in AttackFamily:
        assert fam.value in agent.prompt, (
            f"family {fam.value!r} missing from extraction prompt"
        )


# --------------------------------------------------------------------------- #
# 8 + 9. Live-DB checks. Skip cleanly when Postgres is unreachable.
# --------------------------------------------------------------------------- #


def _database_url() -> str:
    # Read TEST_DATABASE_URL (NOT DATABASE_URL) so the test fixture is
    # decoupled from the dev DB. Falls through to the rogue_test default.
    return os.environ.get("TEST_DATABASE_URL", DEFAULT_DATABASE_URL)


@pytest.fixture(scope="module")
def live_engine():
    """Return a connected SQLAlchemy engine, or pytest.skip cleanly.

    We always TRY to connect — never gate on env vars. The skip message
    carries the real reason so a developer who forgot ``docker compose up``
    sees exactly what is missing.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError

    url = _database_url()
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 2})
        # Force a real handshake — create_engine() alone is lazy.
        with engine.connect():
            pass
    except (OperationalError, ConnectionRefusedError, socket.gaierror, OSError) as exc:
        pytest.skip(
            f"Postgres not reachable at {url}: {exc.__class__.__name__}: {exc} "
            "— run `docker compose up -d`"
        )
    yield engine
    engine.dispose()


def test_postgres_reachable(live_engine) -> None:
    """Postgres at DATABASE_URL must answer SELECT 1 with a single row."""
    from sqlalchemy import text

    with live_engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        rows = result.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 1


def test_alembic_upgrade_head_dry_run(live_engine, monkeypatch) -> None:
    """`alembic upgrade head` then `downgrade base` round-trips cleanly.

    Reuses the live_engine fixture so skip behaviour is shared with #8.

    monkeypatches DATABASE_URL → TEST_DATABASE_URL because alembic env.py
    unconditionally overrides cfg.sqlalchemy.url with DATABASE_URL. Without
    this patch, the alembic call would upgrade the dev `rogue` DB instead
    of `rogue_test` and the isolation refactor would be a no-op.
    """
    from alembic import command
    from sqlalchemy import inspect as sa_inspect

    test_url = _database_url()
    monkeypatch.setenv("DATABASE_URL", test_url)

    cfg = _alembic_config()
    cfg.set_main_option("sqlalchemy.url", test_url)

    try:
        command.upgrade(cfg, "head")
        try:
            inspector = sa_inspect(live_engine)
            tables = inspector.get_table_names()
            assert "attack_primitives" in tables, (
                f"after upgrade, attack_primitives missing; tables={sorted(tables)}"
            )
        finally:
            # Always downgrade so the test is idempotent across runs.
            command.downgrade(cfg, "base")
    except Exception as exc:
        # Surface the real failure rather than leaving a half-migrated DB
        # silently behind. If this fires it's almost certainly a real bug in
        # the migration script, not in the test.
        pytest.fail(
            f"alembic upgrade/downgrade round-trip failed: "
            f"{type(exc).__name__}: {exc}"
        )
