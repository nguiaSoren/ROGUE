"""Offline tests for the MCP **action** tools (``rogue.mcp_server.scan_tools``).

No live MCP, no network, no DB, no spend: ``register_scan_tools`` is driven with FAKE services —
a ``scan_service`` (create_scan → a QUEUED ScanRecord; get_scan → a COMPLETED ScanRecord with
n_breaches=7, top_attack="Crescendo", score=81; cancel → CANCELED; list → [records]), a
``report_service`` (build_json → a report dict with findings + remediation + score + risk_level),
a ``benchmark_service`` (create → {benchmark_id, status}; get → a record), and an ``engine``
(validate → a ValidationResult). The tool callables returned by ``register_scan_tools`` (a
name→callable dict) are exercised directly.

pytest-asyncio is in STRICT mode, so every async test is explicitly marked. The optional
registration sanity-check against a real ``FastMCP("test")`` is guarded with ``importorskip``.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from rogue.mcp_server.scan_tools import register_scan_tools
from rogue.platform.benchmark_service import BenchmarkRecord
from rogue.platform.integration_store import InMemoryIntegrationStore
from rogue.platform.schemas import ScanRecord, ScanStatus
from rogue.report import ValidationResult


# --------------------------------------------------------------------------- #
# Fakes — only the surface the tools touch
# --------------------------------------------------------------------------- #


class FakeScanService:
    """Stand-in ScanService: records calls; hands back canned records."""

    def __init__(self) -> None:
        self.created: list[tuple[object, str]] = []  # (spec, org_id)
        self.get_calls: list[tuple[str, str]] = []  # (scan_id, org_id)
        self.cancel_calls: list[tuple[str, str]] = []
        self.list_calls: list[tuple[str, int]] = []  # (org_id, limit)
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
            target={"endpoint": "https://staging.example.com/v1"},
            created_at=datetime(2026, 6, 5, tzinfo=timezone.utc),
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

    async def cancel_scan(self, scan_id, *, org_id):
        self.cancel_calls.append((scan_id, org_id))
        if scan_id != "scan_done":
            raise KeyError(scan_id)
        return self._completed.model_copy(update={"status": ScanStatus.CANCELED})

    async def list_scans(self, *, org_id, project_id=None, limit=50):
        self.list_calls.append((org_id, limit))
        return [self._completed]


class FakeReportService:
    """Stand-in ReportService: build_json → a report dict with findings + remediation + score."""

    def __init__(self) -> None:
        self.build_calls: list[str] = []

    async def build_json(self, scan_id):
        self.build_calls.append(scan_id)
        if scan_id != "scan_done":
            raise ValueError(f"scan {scan_id!r} not found")
        return {
            "target": "https://staging.example.com/v1",
            "n_tests": 20,
            "n_breaches": 7,
            "score": 81.0,
            "risk_level": "critical",
            "score_methodology": "Risk score 0-100 — weighted by severity x success rate.",
            "findings": [
                {
                    "family": "multi_turn_gradient",
                    "technique": "Crescendo",
                    "vector": "User (multi-turn)",
                    "severity": "critical",
                    "title": "Gradual escalation extracted disallowed content",
                    "success_rate": 0.8,
                    "breached": True,
                    "remediation": "Evaluate the cumulative trajectory of a conversation.",
                },
                {
                    "family": "role_hijack",
                    "technique": "Role Hijack",
                    "vector": "User turn",
                    "severity": "high",
                    "title": "Persona reassignment accepted",
                    "success_rate": 0.4,
                    "breached": False,
                    "remediation": "Pin the assistant's role server-side.",
                },
            ],
        }


    async def build_executive_summary(self, scan_id):
        # Mirror DefaultReportService.build_executive_summary's shape from the same canned findings,
        # so the offline test exercises the tool's plumbing without the real report-store load.
        self.build_calls.append(scan_id)
        if scan_id != "scan_done":
            raise ValueError(f"scan {scan_id!r} not found")
        return (
            "# ROGUE security scan — executive summary\n\n"
            "**Risk 81/100 (critical)** — 7/20 attacks breached the target.\n\n"
            "## Critical & high findings\n\n"
            "- **Crescendo** (critical, 80% success) — "
            "Evaluate the cumulative trajectory of a conversation.\n\n"
            "**Business impact:** Exploitable critical weaknesses are present today."
        )


class FakeBenchmarkService:
    """Stand-in BenchmarkService: create → {benchmark_id, status}; get → a BenchmarkRecord."""

    def __init__(self) -> None:
        self.created: list[tuple[object, str, int, str]] = []  # (spec, dataset, max_goals, org_id)
        self.get_calls: list[tuple[str, str]] = []

    async def create(self, spec, *, dataset, max_goals, org_id):
        self.created.append((spec, dataset, max_goals, org_id))
        return {"benchmark_id": "bench_new", "status": ScanStatus.QUEUED}

    async def get(self, benchmark_id, *, org_id):
        self.get_calls.append((benchmark_id, org_id))
        if benchmark_id != "bench_done":
            return None
        return BenchmarkRecord(
            benchmark_id="bench_done",
            org_id=org_id,
            dataset="advbench_100",
            status=ScanStatus.COMPLETED,
            n_goals=25,
            n_success=11,
            asr=0.44,
            cost_usd=3.2,
            cost_per_success=0.29,
            winner_rank=2,
            created_at=datetime(2026, 6, 5, tzinfo=timezone.utc),
        )


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


class _NullMcp:
    """Minimal FastMCP stand-in: its ``.tool()`` decorator is an identity, so registration is a
    no-op we can exercise without importing the real ``mcp`` package."""

    def tool(self, *a, **k):
        def deco(fn):
            return fn

        return deco


@pytest.fixture
def ctx():
    scan_service = FakeScanService()
    report_service = FakeReportService()
    benchmark_service = FakeBenchmarkService()
    engine = FakeEngine()
    # Pre-load an integration store under the SERVER-bound org so the reference-by-name path
    # resolves the stored secret/config server-side — the tool callables only ever see the NAME.
    integration_store = InMemoryIntegrationStore()
    integration_store.put(
        org_id="org_x", kind="slack", name="slack-sec", config={},
        secret="https://hooks.slack/x",
    )
    integration_store.put(
        org_id="org_x", kind="jira", name="jira-prod",
        config={
            "base_url": "https://acme.atlassian.net",
            "project_key": "SEC",
            "email": "sec@acme.test",
        },
        secret="stored-tok",
    )
    tools = register_scan_tools(
        _NullMcp(),
        scan_service=scan_service,
        report_service=report_service,
        benchmark_service=benchmark_service,
        engine=engine,
        org_id="org_x",
        integration_store=integration_store,
    )
    return tools, scan_service, report_service, benchmark_service, engine


# --------------------------------------------------------------------------- #
# validate_target
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_validate_target_returns_fields(ctx):
    tools, _svc, _rpt, _bench, engine = ctx
    out = await tools["validate_target"](
        endpoint="https://staging.example.com/v1", api_key="sk-secret"
    )

    assert out["target"] == "https://staging.example.com/v1"
    assert out["reachable"] is True
    assert out["authenticated"] is True
    assert out["model_responds"] is True
    assert out["supports_image"] is False
    assert out["supports_audio"] is False
    assert out["ok"] is True
    # Delegated to engine.validate with a spec carrying the endpoint.
    assert len(engine.validated) == 1
    assert engine.validated[0].target.endpoint == "https://staging.example.com/v1"


# --------------------------------------------------------------------------- #
# start_scan
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_start_scan_queues_and_returns_id(ctx):
    tools, svc, *_ = ctx
    out = await tools["start_scan"](
        endpoint="https://staging.example.com/v1", api_key="sk-secret"
    )

    assert out["scan_id"] == "scan_new"
    assert out["status"] == "queued"

    # Routed through the service under the SERVER-bound org — never a tool argument.
    assert len(svc.created) == 1
    spec, org_id = svc.created[0]
    assert org_id == "org_x"
    assert spec.target.endpoint == "https://staging.example.com/v1"
    assert spec.pack == "default"
    assert spec.mode == "pack"
    assert spec.max_tests == 20


@pytest.mark.asyncio
async def test_start_scan_requires_endpoint_or_provider(ctx):
    tools, *_ = ctx
    # TargetSpec's validator must reject a target with neither endpoint nor provider.
    with pytest.raises(ValueError):
        await tools["start_scan"]()


@pytest.mark.asyncio
async def test_start_scan_passes_mode_budget_and_overrides(ctx):
    tools, svc, *_ = ctx
    await tools["start_scan"](
        provider="openai",
        model="gpt-4o-mini",
        pack="quick",
        mode="ladder",
        max_tests=5,
        budget=12.5,
    )
    spec, _org = svc.created[-1]
    assert spec.target.provider == "openai"
    assert spec.target.model == "gpt-4o-mini"
    assert spec.pack == "quick"
    assert spec.mode == "ladder"
    assert spec.max_tests == 5
    assert spec.budget == 12.5


# --------------------------------------------------------------------------- #
# get_scan_status (+ get_scan alias)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_get_scan_status_returns_status_score_and_summary(ctx):
    tools, *_ = ctx
    out = await tools["get_scan_status"]("scan_done")

    assert out["status"] == "completed"
    assert out["progress"] == 100
    assert out["n_breaches"] == 7
    assert out["top_attack"] == "Crescendo"
    assert out["score"] == 81.0
    assert out["summary"] == "7 vulnerabilities found, top: Crescendo"


@pytest.mark.asyncio
async def test_get_scan_alias_is_back_compat(ctx):
    tools, *_ = ctx
    # The original tool name still resolves to the same status callable.
    assert tools["get_scan"] is tools["get_scan_status"]
    out = await tools["get_scan"]("scan_done")
    assert out["scan_id"] == "scan_done"


@pytest.mark.asyncio
async def test_get_scan_status_uses_bound_org(ctx):
    tools, svc, *_ = ctx
    await tools["get_scan_status"]("scan_done")
    # Routed through the service under the server-bound org, not a tool argument.
    assert svc.get_calls[-1] == ("scan_done", "org_x")


@pytest.mark.asyncio
async def test_get_scan_status_unknown_id_returns_error(ctx):
    tools, *_ = ctx
    out = await tools["get_scan_status"]("nope")
    assert "error" in out
    assert "nope" in out["error"]


# --------------------------------------------------------------------------- #
# cancel_scan
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_cancel_scan_returns_canceled(ctx):
    tools, svc, *_ = ctx
    out = await tools["cancel_scan"]("scan_done")
    assert out == {"scan_id": "scan_done", "status": "canceled"}
    assert svc.cancel_calls[-1] == ("scan_done", "org_x")


@pytest.mark.asyncio
async def test_cancel_scan_unknown_id_returns_error(ctx):
    tools, *_ = ctx
    out = await tools["cancel_scan"]("nope")
    assert "error" in out


# --------------------------------------------------------------------------- #
# list_scans
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_list_scans_shape_and_org(ctx):
    tools, svc, *_ = ctx
    out = await tools["list_scans"](limit=10)
    assert out["count"] == 1
    row = out["scans"][0]
    assert row["scan_id"] == "scan_done"
    assert row["status"] == "completed"
    assert row["target"] == "https://staging.example.com/v1"
    assert row["score"] == 81.0
    assert row["n_breaches"] == 7
    assert row["created_at"] == "2026-06-05T00:00:00+00:00"
    # Routed under the bound org with the supplied limit.
    assert svc.list_calls[-1] == ("org_x", 10)


# --------------------------------------------------------------------------- #
# get_report
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_get_report_summary_is_markdown_with_score_and_remediation(ctx):
    tools, _svc, rpt, *_ = ctx
    md = await tools["get_report"]("scan_done")  # default format="summary"
    assert isinstance(md, str)
    # Headline score + risk level.
    assert "81" in md
    assert "critical" in md
    # "N/M breached" line.
    assert "7/20" in md
    # A breached finding's technique + its remediation surface in the paste.
    assert "Crescendo" in md
    assert "Evaluate the cumulative trajectory" in md
    assert rpt.build_calls[-1] == "scan_done"


@pytest.mark.asyncio
async def test_get_report_json_is_full_dict(ctx):
    tools, *_ = ctx
    out = await tools["get_report"]("scan_done", format="json")
    assert isinstance(out, dict)
    assert out["score"] == 81.0
    assert out["risk_level"] == "critical"
    assert "score_methodology" in out
    assert out["findings"][0]["remediation"]


@pytest.mark.asyncio
async def test_get_report_unknown_id_returns_error(ctx):
    tools, *_ = ctx
    out = await tools["get_report"]("nope")
    assert isinstance(out, dict)
    assert "error" in out


# --------------------------------------------------------------------------- #
# list_findings
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_list_findings_surfaces_remediation(ctx):
    tools, *_ = ctx
    out = await tools["list_findings"]("scan_done")
    findings = out["findings"]
    assert len(findings) == 2
    first = findings[0]
    assert first["family"] == "multi_turn_gradient"
    assert first["technique"] == "Crescendo"
    assert first["vector"] == "User (multi-turn)"
    assert first["severity"] == "critical"
    assert first["breached"] is True
    assert first["success_rate"] == 0.8
    assert first["remediation"] == "Evaluate the cumulative trajectory of a conversation."


@pytest.mark.asyncio
async def test_list_findings_unknown_id_returns_error(ctx):
    tools, *_ = ctx
    out = await tools["list_findings"]("nope")
    assert "error" in out


# --------------------------------------------------------------------------- #
# run_benchmark / get_benchmark
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_run_benchmark_queues_and_returns_id(ctx):
    tools, _svc, _rpt, bench, _engine = ctx
    out = await tools["run_benchmark"](
        endpoint="https://staging.example.com/v1", dataset="advbench_100", max_goals=10
    )
    assert out["benchmark_id"] == "bench_new"
    assert out["status"] == "queued"
    # Routed through the service under the bound org with the dataset + max_goals.
    spec, dataset, max_goals, org_id = bench.created[-1]
    assert org_id == "org_x"
    assert dataset == "advbench_100"
    assert max_goals == 10
    assert spec.target.endpoint == "https://staging.example.com/v1"


@pytest.mark.asyncio
async def test_get_benchmark_returns_record(ctx):
    tools, *_ = ctx
    out = await tools["get_benchmark"]("bench_done")
    assert out["dataset"] == "advbench_100"
    assert out["status"] == "completed"
    assert out["n_goals"] == 25
    assert out["n_success"] == 11
    assert out["asr"] == 0.44
    assert out["cost_per_success"] == 0.29
    assert out["winner_rank"] == 2


@pytest.mark.asyncio
async def test_get_benchmark_unknown_id_returns_error(ctx):
    tools, *_ = ctx
    out = await tools["get_benchmark"]("nope")
    assert "error" in out


# --------------------------------------------------------------------------- #
# tenancy — org is NEVER a tool argument
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_org_is_never_a_tool_argument(ctx):
    import inspect

    tools, *_ = ctx
    for name, fn in tools.items():
        params = inspect.signature(fn).parameters
        assert "org_id" not in params, f"{name} must not expose org_id"


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
# Level-3 workflow tools — executive summary / Slack alert / Jira ticket
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_create_executive_summary_returns_markdown(ctx):
    tools, _svc, rpt, *_ = ctx
    out = await tools["create_executive_summary"]("scan_done")
    summary = out["summary"]
    assert isinstance(summary, str)
    # Headline score + level, the breach ratio, a technique, and its remediation all surface.
    assert "81/100" in summary
    assert "critical" in summary
    assert "7/20" in summary
    assert "Crescendo" in summary
    assert "Evaluate the cumulative trajectory" in summary
    assert rpt.build_calls[-1] == "scan_done"


@pytest.mark.asyncio
async def test_create_executive_summary_unknown_id_returns_error(ctx):
    tools, *_ = ctx
    out = await tools["create_executive_summary"]("nope")
    assert "error" in out


@pytest.mark.asyncio
async def test_send_slack_alert_records_payload_with_injected_sender(ctx, monkeypatch):
    tools, _svc, *_ = ctx

    # Inject a fake sender via the module-level seam — no HTTP, just record (url, payload).
    sent: list[tuple[str, dict]] = []

    async def fake_sender(url, payload):
        sent.append((url, payload))

    import rogue.mcp_server.scan_tools as st

    monkeypatch.setattr(st, "_SLACK_SENDER", fake_sender)

    # Back-compat raw-args path: pass the webhook URL directly.
    out = await tools["send_slack_alert"]("scan_done", webhook_url="https://hooks.slack.test/abc")
    assert out == {"ok": True, "status": "sent"}

    assert len(sent) == 1
    url, payload = sent[0]
    assert url == "https://hooks.slack.test/abc"
    # The fallback text carries the score + breach ratio + top attack (no HTTP performed).
    text = payload["text"]
    assert "81/100" in text
    assert "7/20" in text
    assert "Crescendo" in text


@pytest.mark.asyncio
async def test_send_slack_alert_unknown_id_returns_error(ctx):
    tools, *_ = ctx
    out = await tools["send_slack_alert"]("nope", webhook_url="https://hooks.slack.test/abc")
    assert "error" in out


@pytest.mark.asyncio
async def test_send_slack_alert_resolves_stored_integration_by_name(ctx, monkeypatch):
    tools, *_ = ctx

    sent: list[tuple[str, dict]] = []

    async def fake_sender(url, payload):
        sent.append((url, payload))

    import rogue.mcp_server.scan_tools as st

    monkeypatch.setattr(st, "_SLACK_SENDER", fake_sender)

    # Reference the stored Slack integration by NAME — the agent never handles the webhook URL.
    out = await tools["send_slack_alert"]("scan_done", integration="slack-sec")
    assert out == {"ok": True, "status": "sent"}

    assert len(sent) == 1
    url, payload = sent[0]
    # The server resolved the stored webhook URL; the payload still carries score / breaches.
    assert url == "https://hooks.slack/x"
    text = payload["text"]
    assert "81/100" in text
    assert "7/20" in text
    assert "Crescendo" in text


@pytest.mark.asyncio
async def test_send_slack_alert_unknown_integration_returns_error(ctx):
    tools, *_ = ctx
    out = await tools["send_slack_alert"]("scan_done", integration="does-not-exist")
    assert "error" in out
    assert "does-not-exist" in out["error"]


@pytest.mark.asyncio
async def test_send_slack_alert_requires_integration_or_webhook(ctx):
    tools, *_ = ctx
    out = await tools["send_slack_alert"]("scan_done")
    assert "error" in out


@pytest.mark.asyncio
async def test_create_jira_ticket_creates_one_per_critical_high_breached(ctx, monkeypatch):
    tools, _svc, *_ = ctx

    class FakeJiraClient:
        """In-memory Jira: records created tickets; `find_open` checks the recorded fids."""

        def __init__(self, base_url, email, api_token, project_key):
            self.init_args = (base_url, email, api_token, project_key)
            self.created: list[object] = []
            self._open: dict[str, str] = {}

        async def find_open(self, fid):
            return self._open.get(fid)

        async def create(self, ticket):
            key = f"SEC-{len(self.created) + 1}"
            self.created.append(ticket)
            self._open[ticket.finding_id] = key
            return key

    instances: list[FakeJiraClient] = []

    def factory(base_url, email, api_token, project_key):
        client = FakeJiraClient(base_url, email, api_token, project_key)
        instances.append(client)
        return client

    import rogue.mcp_server.scan_tools as st

    monkeypatch.setattr(st, "_JIRA_CLIENT_FACTORY", factory)

    out = await tools["create_jira_ticket"](
        "scan_done",
        base_url="https://acme.atlassian.net",
        project_key="SEC",
        email="sec@acme.test",
        api_token="tok",
    )
    # The fake report has one breached critical (Crescendo); the high finding is NOT breached, and a
    # medium/low would be excluded too — so exactly one ticket is created, none skipped.
    assert out["created"] == ["SEC-1"]
    assert out["skipped"] == []
    client = instances[0]
    assert client.init_args == ("https://acme.atlassian.net", "sec@acme.test", "tok", "SEC")
    assert len(client.created) == 1
    ticket = client.created[0]
    assert "Crescendo" in ticket.title
    assert ticket.severity == "critical"


@pytest.mark.asyncio
async def test_create_jira_ticket_dedups_via_find_open(ctx, monkeypatch):
    tools, *_ = ctx

    class PrePopulatedJiraClient:
        """`find_open` always returns an existing key → every finding dedups to a skip."""

        def __init__(self, *a):
            self.created: list[object] = []

        async def find_open(self, fid):
            return "SEC-99"

        async def create(self, ticket):  # pragma: no cover - must not be reached on full dedup
            self.created.append(ticket)
            return "SEC-NEW"

    seen: list[PrePopulatedJiraClient] = []

    def factory(*a):
        c = PrePopulatedJiraClient(*a)
        seen.append(c)
        return c

    import rogue.mcp_server.scan_tools as st

    monkeypatch.setattr(st, "_JIRA_CLIENT_FACTORY", factory)

    out = await tools["create_jira_ticket"](
        "scan_done", base_url="https://acme.atlassian.net", project_key="SEC",
        email="sec@acme.test", api_token="tok",
    )
    # Already-open → nothing created, the finding is skipped (re-scans converge, no dupes).
    assert out["created"] == []
    assert len(out["skipped"]) == 1
    assert seen[0].created == []


@pytest.mark.asyncio
async def test_create_jira_ticket_unknown_id_returns_error(ctx):
    tools, *_ = ctx
    out = await tools["create_jira_ticket"](
        "nope", base_url="https://acme.atlassian.net", project_key="SEC",
        email="sec@acme.test", api_token="tok",
    )
    assert "error" in out


@pytest.mark.asyncio
async def test_create_jira_ticket_resolves_stored_integration_by_name(ctx, monkeypatch):
    tools, *_ = ctx

    class FakeJiraClient:
        def __init__(self, base_url, email, api_token, project_key):
            self.init_args = (base_url, email, api_token, project_key)
            self.created: list[object] = []
            self._open: dict[str, str] = {}

        async def find_open(self, fid):
            return self._open.get(fid)

        async def create(self, ticket):
            key = f"SEC-{len(self.created) + 1}"
            self.created.append(ticket)
            self._open[ticket.finding_id] = key
            return key

    instances: list[FakeJiraClient] = []

    def factory(base_url, email, api_token, project_key):
        client = FakeJiraClient(base_url, email, api_token, project_key)
        instances.append(client)
        return client

    import rogue.mcp_server.scan_tools as st

    monkeypatch.setattr(st, "_JIRA_CLIENT_FACTORY", factory)

    # Reference the stored Jira integration by NAME — config + token resolved server-side.
    out = await tools["create_jira_ticket"]("scan_done", integration="jira-prod")
    assert out["created"] == ["SEC-1"]
    assert out["skipped"] == []
    client = instances[0]
    # The client was built from the STORED config + the stored secret token, not from tool args.
    assert client.init_args == (
        "https://acme.atlassian.net", "sec@acme.test", "stored-tok", "SEC",
    )
    assert len(client.created) == 1
    ticket = client.created[0]
    assert "Crescendo" in ticket.title
    assert ticket.severity == "critical"


@pytest.mark.asyncio
async def test_create_jira_ticket_unknown_integration_returns_error(ctx):
    tools, *_ = ctx
    out = await tools["create_jira_ticket"]("scan_done", integration="does-not-exist")
    assert "error" in out
    assert "does-not-exist" in out["error"]


@pytest.mark.asyncio
async def test_create_jira_ticket_requires_integration_or_raw_creds(ctx):
    tools, *_ = ctx
    # Neither an integration name nor the full raw-creds set → a clean error, no raise.
    out = await tools["create_jira_ticket"]("scan_done", base_url="https://acme.atlassian.net")
    assert "error" in out


# --------------------------------------------------------------------------- #
# list_integrations — names + kinds, NEVER secrets
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_list_integrations_returns_names_and_kinds_no_secrets(ctx):
    tools, *_ = ctx
    out = await tools["list_integrations"]()
    integrations = out["integrations"]
    by_name = {i["name"]: i for i in integrations}
    assert by_name["slack-sec"]["kind"] == "slack"
    assert by_name["jira-prod"]["kind"] == "jira"
    # No secret value (webhook URL / api token) leaks anywhere in the payload.
    flat = repr(out)
    assert "hooks.slack/x" not in flat
    assert "stored-tok" not in flat
    # Each row is exactly {kind, name} — no extra secret-bearing fields.
    for i in integrations:
        assert set(i) == {"kind", "name"}


@pytest.mark.asyncio
async def test_list_integrations_no_store_reports_none_configured():
    tools = register_scan_tools(
        _NullMcp(),
        scan_service=FakeScanService(),
        report_service=FakeReportService(),
        benchmark_service=FakeBenchmarkService(),
        engine=FakeEngine(),
        org_id="org_x",
    )
    out = await tools["list_integrations"]()
    assert out["integrations"] == []
    assert "note" in out


# --------------------------------------------------------------------------- #
# registration against a real FastMCP (skipped if `mcp` isn't installed)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_registers_on_real_fastmcp():
    pytest.importorskip("mcp")
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("test")
    tools = register_scan_tools(
        mcp,
        scan_service=FakeScanService(),
        report_service=FakeReportService(),
        benchmark_service=FakeBenchmarkService(),
        engine=FakeEngine(),
        org_id="org_x",
    )
    # Every catalog tool is exposed (get_scan is the back-compat alias of get_scan_status).
    assert "get_scan" in tools

    listed = await mcp.list_tools()
    names = {t.name for t in listed}
    assert {
        "validate_target",
        "start_scan",
        "get_scan_status",
        "cancel_scan",
        "list_scans",
        "get_report",
        "list_findings",
        "run_benchmark",
        "get_benchmark",
        "create_executive_summary",
        "send_slack_alert",
        "create_jira_ticket",
        "list_integrations",
    } <= names
