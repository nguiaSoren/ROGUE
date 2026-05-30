"""Tests for the data-only local → Neon sync (offline — no DB touched).

The cross-DB upsert itself needs two live Postgres instances, so it's verified
by running the script; these lock the safe-guards that DON'T need a DB: the
source==dest skip, the env-gated auto-hook, FK-safe table ordering, and the CLI
contract.
"""

from __future__ import annotations

from rogue.db.neon_sync import (
    SYNC_TABLE_NAMES,
    looks_like_placeholder,
    maybe_auto_sync,
    sync,
)

# Import at module top so the CLI's import-time load_dotenv() runs ONCE at
# collection; per-test monkeypatch of NEON_DATABASE_URL then controls
# os.environ at main() call time (argparse reads it lazily).
from scripts.sync_to_neon import main as sync_cli_main

_URL = "postgresql+psycopg://rogue:pw@localhost:5432/rogue"
_NEON = "postgresql+psycopg://u:p@neon.example/neondb"


def test_sync_skips_when_source_equals_dest() -> None:
    # Same DB (even with a trailing slash) → no-op, never opens a connection.
    out = sync(_URL, _URL + "/")
    assert out["synced"] is False
    assert "source == dest" in out["reason"]


def test_table_order_is_fk_safe() -> None:
    order = list(SYNC_TABLE_NAMES)
    # parents must precede children
    assert order.index("deployment_configs") < order.index("breach_results")
    assert order.index("attack_primitives") < order.index("source_provenances")
    assert order.index("attack_primitives") < order.index("breach_results")
    assert order.index("breach_results") < order.index("pair_refinement_steps")
    # operational tables are intentionally excluded
    assert "bright_data_cost_log" not in order
    assert "fetch_cache" not in order


def test_auto_sync_noop_without_neon_url(monkeypatch) -> None:
    monkeypatch.delenv("NEON_DATABASE_URL", raising=False)
    assert maybe_auto_sync(_URL) is None


def test_auto_sync_noop_when_neon_equals_local(monkeypatch) -> None:
    monkeypatch.setenv("NEON_DATABASE_URL", _URL)
    assert maybe_auto_sync(_URL) is None


def test_auto_sync_never_raises_on_bad_dest(monkeypatch) -> None:
    # A bogus Neon URL must NOT crash the pipeline — it's logged and swallowed.
    monkeypatch.setenv("NEON_DATABASE_URL", "postgresql+psycopg://x:y@127.0.0.1:1/none")
    out = maybe_auto_sync(_URL)
    assert out is not None and out["synced"] is False


def test_cli_errors_without_dest(monkeypatch, capsys) -> None:
    monkeypatch.delenv("NEON_DATABASE_URL", raising=False)
    rc = sync_cli_main(["--source", _URL])
    assert rc == 2
    assert "no destination" in capsys.readouterr().err


def test_placeholder_detection() -> None:
    assert looks_like_placeholder("postgresql+psycopg://USER:PASS@HOST/neondb?sslmode=require")
    assert looks_like_placeholder("postgresql://u:p@HOST/db")
    # A real Neon URL (default db name `neondb`) must NOT be flagged.
    assert not looks_like_placeholder(
        "postgresql+psycopg://alex:npg_xY@ep-cool-123.us-east-2.aws.neon.tech/neondb?sslmode=require"
    )
    assert not looks_like_placeholder(_NEON)


def test_auto_sync_skips_placeholder(monkeypatch) -> None:
    monkeypatch.setenv(
        "NEON_DATABASE_URL", "postgresql+psycopg://USER:PASS@HOST/neondb?sslmode=require"
    )
    out = maybe_auto_sync(_URL)
    assert out is not None and out["synced"] is False
    assert "placeholder" in out["reason"]


def test_cli_rejects_placeholder_dest(capsys) -> None:
    rc = sync_cli_main(["--source", _URL, "--dest", "postgresql+psycopg://USER:PASS@HOST/neondb"])
    assert rc == 2
    assert "placeholder" in capsys.readouterr().err


def test_cli_skips_when_source_equals_dest(capsys) -> None:
    rc = sync_cli_main(["--source", _URL, "--dest", _URL])
    assert rc == 0
    assert "skipped" in capsys.readouterr().out
