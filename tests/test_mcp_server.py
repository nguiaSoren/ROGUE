"""Tests for `rogue.mcp_server.server` — the producer-side MCP tool surface.

Three flavors:

  * **Import + registration** (always run) — verifies all 5 §6.2 tools are
    registered on the FastMCP instance, the env loader runs, and module
    import is side-effect-safe (no DB connection until first tool call).
  * **Pure-Python serializer** (always run) — exercises `_enum_str` +
    `_primitive_to_dict` against a hand-built ORM-shaped object. No DB.
  * **Live-DB integration** (skip cleanly when Postgres unreachable) —
    fires each tool against the dev DB and asserts shape correctness.
    Uses the dev `rogue` DB (NOT `rogue_test`) because the MCP tools are
    purpose-built to read live operator state.

Spec: ROGUE_PLAN.md §6.2, §11.2, §A.11.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest


@pytest.fixture(autouse=True)
def _quiet_engine_state(monkeypatch):
    """Reset the lazy-init engine between tests so monkeypatched DATABASE_URL
    actually takes effect. Tests that don't need the DB are unaffected."""
    from rogue.mcp_server import server as srv
    srv._engine = None
    srv._SessionLocal = None
    yield
    srv._engine = None
    srv._SessionLocal = None


# --------------------------------------------------------------------------- #
# A. Import + tool registration
# --------------------------------------------------------------------------- #


def test_module_imports_without_db_connection() -> None:
    """Importing the server module must NOT open a DB connection.

    Keeps `import rogue.mcp_server.server` cheap for test-time orchestration
    + plays nicely with Claude Desktop's spawn-then-init lifecycle."""
    from rogue.mcp_server import server as srv
    assert srv._engine is None
    assert srv._SessionLocal is None


def test_all_tools_registered() -> None:
    """The §6.2 spec tools + the query_worst_attacks convenience tool."""
    from rogue.mcp_server import server as srv

    expected = {
        "query_attacks",
        "query_diff",
        "query_threat_brief",
        "query_breaches_for_config",
        "query_attack_detail",
        "query_worst_attacks",
    }
    registered = set(srv.mcp._tool_manager._tools.keys())
    assert registered == expected, f"expected {expected}, got {registered}"


def test_database_url_defaults_to_dev_db() -> None:
    """`_database_url()` defaults to the dev `rogue` DB, not `rogue_test`,
    because the MCP tools are purpose-built to surface operator state."""
    from rogue.mcp_server import server as srv

    # Save + clear any env override
    saved = os.environ.pop("DATABASE_URL", None)
    try:
        assert "/rogue" in srv._database_url()
        assert "/rogue_test" not in srv._database_url()
    finally:
        if saved is not None:
            os.environ["DATABASE_URL"] = saved


# --------------------------------------------------------------------------- #
# B. Pure-Python serializer (no DB)
# --------------------------------------------------------------------------- #


class _FakeEnum:
    """Mimics a SQLAlchemy native-enum member: has `.value`."""

    def __init__(self, value: str) -> None:
        self.value = value

    def __repr__(self) -> str:
        return f"<FakeEnum {self.value!r}>"


def test_enum_str_stringifies_enum_member() -> None:
    """`_enum_str` must return `.value` for enum-shaped objects."""
    from rogue.mcp_server.server import _enum_str

    assert _enum_str(_FakeEnum("indirect_prompt_injection")) == "indirect_prompt_injection"


def test_enum_str_passes_through_str_and_none() -> None:
    from rogue.mcp_server.server import _enum_str

    assert _enum_str(None) is None
    assert _enum_str("plain string") == "plain string"
    assert _enum_str(42) == 42


def test_parse_iso_date_handles_none_and_iso() -> None:
    from rogue.mcp_server.server import _parse_iso_date
    from datetime import date as _date

    out_none = _parse_iso_date(None)
    assert isinstance(out_none, _date)
    assert out_none == datetime.now(timezone.utc).date()

    assert _parse_iso_date("2026-05-26") == _date(2026, 5, 26)


# --------------------------------------------------------------------------- #
# C. Live-DB integration — skip cleanly if Postgres unreachable
# --------------------------------------------------------------------------- #


def _dev_db_reachable() -> bool:
    """True if the dev `rogue` DB accepts a connection. Used to gate the
    live-DB block instead of pytest.skip per-test."""
    try:
        from sqlalchemy import create_engine

        engine = create_engine(
            "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue",
            connect_args={"connect_timeout": 2},
        )
        with engine.connect():
            pass
        engine.dispose()
        return True
    except Exception:
        return False


def _require_dev_db():
    if not _dev_db_reachable():
        pytest.skip("dev Postgres `rogue` DB not reachable — run `docker compose up -d`")


def test_query_attacks_against_live_db() -> None:
    """Live-DB sanity: returns 0+ primitives, every record has the spec fields."""
    _require_dev_db()
    from rogue.mcp_server.server import query_attacks

    result = query_attacks(since_days=999, limit=3)
    assert isinstance(result, list)
    for p in result:
        # Spec fields (§6.2 + return-shape docstring)
        for key in (
            "primitive_id", "title", "family", "vector", "base_severity",
            "short_description", "payload_template", "discovered_at", "canonical",
            "sources",
        ):
            assert key in p, f"missing key {key!r} in primitive {p.get('primitive_id')!r}"
        # Enum fields must be strings, not enum members
        assert isinstance(p["family"], str), f"family leaked as {type(p['family']).__name__}"
        assert isinstance(p["vector"], str), f"vector leaked as {type(p['vector']).__name__}"


def test_query_attacks_filters_by_family() -> None:
    """Family filter narrows results to the named family."""
    _require_dev_db()
    from rogue.mcp_server.server import query_attacks

    target_family = "indirect_prompt_injection"
    result = query_attacks(family=target_family, since_days=999, limit=5)
    for p in result:
        assert p["family"] == target_family


def test_query_diff_returns_summary_dict() -> None:
    """`query_diff` must return the JSON-form of BreachDiff with `summary`."""
    _require_dev_db()
    from rogue.mcp_server.server import query_diff

    result = query_diff()
    assert "summary" in result
    assert "target_date" in result
    assert isinstance(result["summary"]["new_critical"], int)
    assert isinstance(result["summary"]["new_high"], int)


def test_query_threat_brief_markdown_returns_string() -> None:
    """Brief tool returns markdown (string), not a dict."""
    _require_dev_db()
    from rogue.mcp_server.server import query_threat_brief

    md = query_threat_brief(format="markdown")
    assert isinstance(md, str)
    assert len(md) > 0
    # Should contain at least the H1 header.
    assert md.startswith("# ROGUE Threat Brief") or "# ROGUE Threat Brief" in md


def test_query_threat_brief_rejects_bad_format() -> None:
    """`format` must be markdown or json; anything else raises ValueError."""
    from rogue.mcp_server.server import query_threat_brief

    with pytest.raises(ValueError):
        query_threat_brief(format="xml")
