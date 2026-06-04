"""Offline tests for the MCP **action** tools (``rogue.mcp_server.scan_tools``).

No live MCP, no network, no DB, no spend: ``register_scan_tools`` is driven with a FAKE
``scan_service`` (create_scan → a QUEUED ScanRecord; get_scan → a COMPLETED ScanRecord with
n_breaches=7, top_attack="Crescendo", score=81) and a fake ``engine`` (validate → a
ValidationResult). The tool callables returned by ``register_scan_tools`` are exercised directly.

pytest-asyncio is in STRICT mode, so every async test is explicitly marked. The optional
registration sanity-check against a real ``FastMCP("test")`` is guarded with ``importorskip``.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from rogue.mcp_server.scan_tools import register_scan_tools
from rogue.platform.schemas import ScanRecord, ScanStatus
from rogue.report import ValidationResult


# --------------------------------------------------------------------------- #
# Fakes — only the surface the tools touch
# --------------------------------------------------------------------------- #


class FakeScanService:
    """Stand-in ScanService: records create_scan calls; hands back canned records."""

    def __init__(self) -> None:
        self.created: list[tuple[object, str]] = []  # (spec, org_id)
        self.get_calls: list[tuple[str, str]] = []  # (scan_id, org_id)
        self._completed = ScanRecord(
            scan_id="scan_done",
            org_id="org_x",
            status=ScanStatus.COMPLETED,
            progress=100,
            n_tests=20,
            n_completed=20,
            n_breaches=7,
            top_attack="Crescendo",
            score=81.0,
        )

    async def create_scan(self, spec, *, org_id, **kw):
        self.created.append((spec, org_id))
        return ScanRecord(
            scan_id="scan_new",
            org_id=org_id,
            status=ScanStatus.QUEUED,
            created_at=datetime.now(timezone.utc),
        )

    async def get_scan(self, scan_id, *, org_id):
        self.get_calls.append((scan_id, org_id))
        return self._completed if scan_id == "scan_done" else None


class FakeEngine:
    """Stand-in ScanEngine: validate() returns a fixed ValidationResult; records the spec."""

    def __init__(self) -> None:
        self.validated: list[object] = []

    async def validate(self, spec):
        self.validated.append(spec)
        return ValidationResult(
            target="https://staging.example.com/v1",
            reachable=True,
            authenticated=True,
            model_responds=True,
            supports_image=False,
            supports_audio=False,
        )


@pytest.fixture
def tools():
    service = FakeScanService()
    engine = FakeEngine()
    start_scan, get_scan, validate = register_scan_tools(
        _NullMcp(), scan_service=service, engine=engine, org_id="org_x"
    )
    return start_scan, get_scan, validate, service, engine


class _NullMcp:
    """Minimal FastMCP stand-in: its ``.tool()`` decorator is an identity, so registration is a
    no-op we can exercise without importing the real ``mcp`` package."""

    def tool(self, *a, **k):
        def deco(fn):
            return fn

        return deco


# --------------------------------------------------------------------------- #
# start_scan
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_start_scan_queues_and_returns_id(tools):
    start_scan, _get, _val, service, _engine = tools
    out = await start_scan(endpoint="https://staging.example.com/v1", api_key="sk-secret")

    assert out["scan_id"] == "scan_new"
    assert out["status"] == "queued"

    # Routed through the service under the SERVER-bound org — never a tool argument.
    assert len(service.created) == 1
    spec, org_id = service.created[0]
    assert org_id == "org_x"
    assert spec.target.endpoint == "https://staging.example.com/v1"
    assert spec.pack == "default"
    assert spec.max_tests == 20


@pytest.mark.asyncio
async def test_start_scan_requires_endpoint_or_provider(tools):
    start_scan, *_ = tools
    # TargetSpec's validator must reject a target with neither endpoint nor provider.
    with pytest.raises(ValueError):
        await start_scan()


@pytest.mark.asyncio
async def test_start_scan_passes_provider_and_overrides(tools):
    start_scan, _get, _val, service, _engine = tools
    await start_scan(provider="openai", model="gpt-4o-mini", pack="quick", max_tests=5)
    spec, _org = service.created[-1]
    assert spec.target.provider == "openai"
    assert spec.target.model == "gpt-4o-mini"
    assert spec.pack == "quick"
    assert spec.max_tests == 5


# --------------------------------------------------------------------------- #
# get_scan
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_get_scan_returns_status_score_and_summary(tools):
    _start, get_scan, _val, _service, _engine = tools
    out = await get_scan("scan_done")

    assert out["status"] == "completed"
    assert out["progress"] == 100
    assert out["n_breaches"] == 7
    assert out["top_attack"] == "Crescendo"
    assert out["score"] == 81.0
    # The headline-flow human-friendly string.
    assert out["summary"] == "7 vulnerabilities found, top: Crescendo"


@pytest.mark.asyncio
async def test_get_scan_uses_bound_org(tools):
    _start, get_scan, _val, service, _engine = tools
    await get_scan("scan_done")
    # The get routed through the service under the server-bound org, not a tool argument.
    assert service.get_calls[-1] == ("scan_done", "org_x")


@pytest.mark.asyncio
async def test_get_scan_unknown_id_raises(tools):
    _start, get_scan, *_ = tools
    with pytest.raises(ValueError):
        await get_scan("nope")


# --------------------------------------------------------------------------- #
# validate
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_validate_returns_fields(tools):
    _start, _get, validate, _service, engine = tools
    out = await validate(endpoint="https://staging.example.com/v1", api_key="sk-secret")

    assert out["target"] == "https://staging.example.com/v1"
    assert out["reachable"] is True
    assert out["authenticated"] is True
    assert out["model_responds"] is True
    assert out["supports_image"] is False
    assert out["supports_audio"] is False
    # Delegated to engine.validate with a spec carrying the endpoint.
    assert len(engine.validated) == 1
    assert engine.validated[0].target.endpoint == "https://staging.example.com/v1"


# --------------------------------------------------------------------------- #
# summary variants
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_summary_singular_and_none():
    from rogue.mcp_server.scan_tools import _summarize

    one = ScanRecord(scan_id="s", org_id="o", status=ScanStatus.COMPLETED, n_breaches=1, top_attack="Crescendo")
    assert _summarize(one) == "1 vulnerability found, top: Crescendo"

    clean = ScanRecord(scan_id="s", org_id="o", status=ScanStatus.COMPLETED, n_breaches=0)
    assert _summarize(clean) == "No vulnerabilities found"

    running = ScanRecord(scan_id="s", org_id="o", status=ScanStatus.RUNNING, progress=40)
    assert _summarize(running) == "Scan running — 40% complete"

    failed = ScanRecord(scan_id="s", org_id="o", status=ScanStatus.FAILED, error="boom")
    assert _summarize(failed) == "Scan failed: boom"


# --------------------------------------------------------------------------- #
# registration against a real FastMCP (skipped if `mcp` isn't installed)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_registers_on_real_fastmcp():
    pytest.importorskip("mcp")
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("test")
    fns = register_scan_tools(mcp, scan_service=FakeScanService(), engine=FakeEngine(), org_id="org_x")
    assert len(fns) == 3

    # The three action tools are now registered on the server.
    listed = await mcp.list_tools()
    names = {t.name for t in listed}
    assert {"start_scan", "get_scan", "validate"} <= names
