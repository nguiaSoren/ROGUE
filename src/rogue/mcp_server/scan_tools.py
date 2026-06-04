"""ROGUE MCP **action** tools — the write surface of the producer-side MCP server.

The six tools in :mod:`rogue.mcp_server.server` are read-only: they query the harvested
threat-intelligence DB. This module adds the *action* tools that let a Claude-Desktop / Cursor /
Windsurf user run the WHOLE scan lifecycle against their own endpoint from inside the IDE — not
just start/poll, but validate → scan → status → cancel → list → report → findings, plus standalone
dataset benchmarks. The headline flow stays:

    "Scan my staging endpoint"   → start_scan(endpoint=...)        → {scan_id, status: "queued"}
    "Is it done?"                → get_scan_status(scan_id)        → poll until status: "completed"
    "Show me the report"         → get_report(scan_id)            → a pasteable markdown summary
                                                                     (score + risk + remediations)

Critically, these tools route through the SAME :class:`~rogue.platform.interfaces.ScanService` /
:class:`~rogue.platform.interfaces.ReportService` / :class:`~rogue.platform.interfaces.ScanEngine`
(and ``BenchmarkService``) that back the SDK, the HTTP API and the dashboard. There is no scan
logic here — every tool builds a request, hands it to a service, and reshapes the result for the
MCP JSON-RPC layer. The one execution path stays singular.

Tenancy note — org is NEVER an LLM-supplied argument. For an HTTP API call the org comes from the
API key; for MCP it comes from the connection's auth context. The server resolves it and binds it
here via ``register_scan_tools(mcp, scan_service=..., report_service=..., benchmark_service=...,
engine=..., org_id=...)`` (a closure), so no tool ever takes an ``org_id`` parameter the model
could spoof.

The tool callables are plain ``async`` functions returned by :func:`register_scan_tools`, so they
are unit-testable directly with fake services and no live MCP, no network. The ``FastMCP`` instance
is passed in already-built — this module never imports or instantiates one.

Spec: docs/platform/ARCHITECTURE.md (ScanService/ReportService/ScanEngine spine) + ROGUE_PLAN.md
§6.2 / §11.2 + the pinned MCP v1 action-tool catalog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable

from rogue.platform.schemas import ScanRecord, ScanSpec, ScanStatus, TargetSpec

if TYPE_CHECKING:
    from rogue.platform.benchmark_service import DefaultBenchmarkService
    from rogue.platform.interfaces import ScanEngine, ReportService, ScanService


# --------------------------------------------------------------------------- #
# Tool callable bundle
# --------------------------------------------------------------------------- #


# The bound tool callables `register_scan_tools` produces, surfaced as a return value so tests can
# drive them directly without a live MCP, and so a caller can register them by hand. A dict keyed by
# tool name (rather than a fixed-arity tuple) so the catalog can grow without breaking call sites.
ScanToolFns = dict[str, Callable[..., Awaitable[dict[str, Any]]]]


def _status_str(status: Any) -> str:
    """Stringify a ScanStatus to its wire value; pass through a bare string.

    ScanRecord / BenchmarkRecord pin ``use_enum_values: False``, so ``record.status`` is a
    ScanStatus member, not a string. The MCP JSON-RPC layer wants a plain string — coerce here so
    every tool result is JSON-clean regardless of whether the fake/real service hands back an enum
    or a str.
    """
    return status.value if isinstance(status, ScanStatus) else str(status)


def _summarize(record: ScanRecord) -> str:
    """The human-friendly one-liner shown for a finished scan.

    Completed → "7 vulnerabilities found, top: Crescendo" (the headline-flow string). With no
    breaches it reads cleanly ("No vulnerabilities found"); a non-terminal scan reports progress;
    a failed scan surfaces the error.
    """
    status = record.status
    if status is ScanStatus.COMPLETED:
        n = record.n_breaches
        noun = "vulnerability" if n == 1 else "vulnerabilities"
        if n and record.top_attack:
            return f"{n} {noun} found, top: {record.top_attack}"
        if n:
            return f"{n} {noun} found"
        return "No vulnerabilities found"
    if status is ScanStatus.FAILED:
        return f"Scan failed: {record.error}" if record.error else "Scan failed"
    if status is ScanStatus.CANCELED:
        return "Scan canceled"
    # QUEUED / RUNNING — still in flight; report progress so the user knows to keep polling.
    return f"Scan {_status_str(status)} — {record.progress}% complete"


def _markdown(report: dict[str, Any]) -> str:
    """Render a `ReportService.build_json` dict as a concise, pasteable markdown summary.

    The shape an agent hands a user verbatim: the headline score + risk level, the "N/M breached"
    line, and the top breached findings each with technique, severity, and the concrete
    remediation. Defensive about missing keys (a forward-compatible report payload is tolerated)
    and never raises — the JSON tool already covers the machine-readable path.
    """
    score = report.get("score")
    risk = report.get("risk_level", "unknown")
    n_tests = report.get("n_tests", 0)
    n_breaches = report.get("n_breaches", 0)
    findings = report.get("findings") or []

    head = f"**ROGUE scan — risk {score:g}/100 ({risk})**" if isinstance(score, (int, float)) \
        else f"**ROGUE scan — risk {score} ({risk})**"
    lines = [head, "", f"{n_breaches}/{n_tests} attacks breached the target."]

    # Lead with what actually broke. Breached findings only, severity-ordered as the report already
    # ranks them; cap at a handful so the paste stays scannable. Each carries its remediation, the
    # single most actionable line for the user.
    breached = [f for f in findings if f.get("breached")]
    shown = breached or findings  # nothing breached → show the (clean) top findings anyway
    if shown:
        lines.append("")
        lines.append("**Top findings:**")
        for f in shown[:5]:
            technique = f.get("technique", "Unknown technique")
            severity = f.get("severity", "?")
            rate = f.get("success_rate")
            rate_str = f" — {round(rate * 100)}% success" if isinstance(rate, (int, float)) else ""
            lines.append(f"- **{technique}** ({severity}){rate_str}")
            remediation = f.get("remediation")
            if remediation:
                lines.append(f"  - _Fix:_ {remediation}")
    else:
        lines.append("")
        lines.append("No vulnerabilities found.")

    return "\n".join(lines)


def _finding_row(f: dict[str, Any]) -> dict[str, Any]:
    """Project a `build_json` finding onto the flat `list_findings` row shape."""
    return {
        "family": f.get("family"),
        "technique": f.get("technique"),
        "vector": f.get("vector"),
        "severity": f.get("severity"),
        "breached": bool(f.get("breached")),
        "success_rate": f.get("success_rate"),
        "remediation": f.get("remediation"),
    }


def register_scan_tools(
    mcp: Any,
    *,
    scan_service: ScanService,
    report_service: ReportService,
    benchmark_service: DefaultBenchmarkService,
    engine: ScanEngine,
    org_id: str = "default",
) -> ScanToolFns:
    """Attach the full action-tool surface to an already-built FastMCP, all routed through services.

    Args:
        mcp: a live ``FastMCP`` instance (this module never builds one). Its ``.tool()`` decorator
            registers each callable as an MCP tool.
        scan_service: the shared :class:`ScanService` — start/status/cancel/list route through it,
            so MCP scans land on the same queue + store as SDK / API / dashboard scans.
        report_service: the shared :class:`ReportService` — ``get_report`` / ``list_findings``
            read its ``build_json`` output (the full report dict incl. score + remediation).
        benchmark_service: the shared benchmark service — ``run_benchmark`` / ``get_benchmark``
            route through its ``create`` / ``get``.
        engine: the shared :class:`ScanEngine` — ``validate_target`` delegates to ``engine.validate``.
        org_id: the tenant the connection authenticated as. The SERVER resolves this from the MCP
            connection's auth context and binds it here; it is deliberately NOT a tool argument, so
            an LLM can never supply or spoof the org it scans under.

    Returns:
        A name → bound-async-callable dict for every action tool, so they can be driven directly in
        tests and by any non-MCP caller.
    """

    def _spec(
        *,
        endpoint: str | None,
        provider: str | None,
        api_key: str | None,
        model: str | None,
        mode: str = "pack",
        pack: str = "default",
        max_tests: int = 20,
        budget: float | None = None,
    ) -> ScanSpec:
        """Build a validated ScanSpec from the LLM-supplied target fields.

        TargetSpec's model_validator enforces endpoint-or-provider; a ValueError propagates as the
        tool's error so the model sees a clear "needs endpoint or provider" message.
        """
        return ScanSpec(
            target=TargetSpec(endpoint=endpoint, provider=provider, model=model, api_key=api_key),
            mode=mode,
            pack=pack,
            max_tests=max_tests,
            budget=budget,
        )

    # --- validate_target ------------------------------------------------------------------------

    async def validate_target(
        endpoint: str | None = None,
        provider: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Cheap pre-flight check on a target BEFORE spending on a scan.

        Confirms the endpoint is reachable, the credential authenticates, the model responds, and
        which modalities (image / audio) it supports. No attacks are run; near-zero cost. Run this
        first when a user gives you an endpoint, then ``start_scan`` once it reports ``ok``.

        Args:
            endpoint: custom OpenAI-compatible endpoint URL to validate.
            provider: hosted provider name (alternative to ``endpoint``).
            api_key: the target's API key (used for the live check; not stored).
            model: model id; defaults per provider when omitted.

        Returns:
            ``{target, reachable, authenticated, model_responds, supports_image, supports_audio,
            ok, error}`` — ``ok`` is true only when reachable + authenticated + model_responds.
        """
        spec = _spec(endpoint=endpoint, provider=provider, api_key=api_key, model=model)
        result = await engine.validate(spec)
        # `to_dict` is an asdict() of the dataclass fields; `ok` is a derived property, so add it
        # explicitly — the catalog pins `ok` as the at-a-glance "ready to scan?" flag.
        out = result.to_dict()
        out["ok"] = result.ok
        return out

    # --- start_scan -----------------------------------------------------------------------------

    async def start_scan(
        endpoint: str | None = None,
        provider: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        pack: str = "default",
        mode: str = "pack",
        max_tests: int = 20,
        budget: float | None = None,
    ) -> dict[str, Any]:
        """Start a red-team scan against your model endpoint. Returns immediately — poll get_scan_status.

        Provide EITHER ``endpoint`` (a custom OpenAI-compatible URL) OR ``provider`` (e.g.
        "openai", "anthropic"). ``model`` and ``api_key`` are optional; ``api_key`` is the target's
        credential — it is redacted before the scan is persisted and never logged. The scan is
        queued and runs asynchronously; this returns ``{scan_id, status}`` so you can poll
        ``get_scan_status(scan_id)`` until it completes, then ``get_report(scan_id)``.

        Args:
            endpoint: custom OpenAI-compatible endpoint URL to scan.
            provider: hosted provider name (alternative to ``endpoint``).
            api_key: the target's API key (redacted on persist; never stored raw).
            model: model id (e.g. "gpt-4o-mini"); defaults per provider when omitted.
            pack: attack pack to run when ``mode="pack"`` (default "default").
            mode: "pack" (curated pack), "repertoire" (live harvested corpus), or "ladder" (full
                escalation arsenal — deepest + most expensive). Default "pack".
            max_tests: max attacks to attempt (default 20).
            budget: optional USD spend cap for the run.

        Returns:
            ``{"scan_id": str, "status": str}`` — the queued scan's id + status ("queued").
        """
        spec = _spec(
            endpoint=endpoint,
            provider=provider,
            api_key=api_key,
            model=model,
            mode=mode,
            pack=pack,
            max_tests=max_tests,
            budget=budget,
        )
        # org is the server-bound tenant — NOT a model-supplied argument.
        record = await scan_service.create_scan(spec, org_id=org_id)
        return {"scan_id": record.scan_id, "status": _status_str(record.status)}

    # --- get_scan_status (+ get_scan back-compat alias) -----------------------------------------

    async def get_scan_status(scan_id: str) -> dict[str, Any]:
        """Poll a scan's status and results by id (from start_scan).

        While the scan runs, ``status`` is "queued"/"running" and ``summary`` reports progress. Once
        ``status`` is "completed", ``n_breaches`` / ``top_attack`` / ``score`` are populated and
        ``summary`` reads like "7 vulnerabilities found, top: Crescendo". Then call
        ``get_report(scan_id)`` for the full write-up.

        Args:
            scan_id: the id returned by ``start_scan``.

        Returns:
            ``{scan_id, status, progress, n_tests, n_completed, n_breaches, top_attack, score,
            summary}`` — or ``{error: ...}`` if the scan id is unknown to this org.
        """
        record = await scan_service.get_scan(scan_id, org_id=org_id)
        if record is None:
            return {"error": f"scan not found: {scan_id}"}
        return {
            "scan_id": record.scan_id,
            "status": _status_str(record.status),
            "progress": record.progress,
            "n_tests": record.n_tests,
            "n_completed": record.n_completed,
            "n_breaches": record.n_breaches,
            "top_attack": record.top_attack,
            "score": record.score,
            "summary": _summarize(record),
        }

    # --- cancel_scan ----------------------------------------------------------------------------

    async def cancel_scan(scan_id: str) -> dict[str, Any]:
        """Cancel a queued or running scan by id; a no-op on an already-finished scan.

        Args:
            scan_id: the id returned by ``start_scan``.

        Returns:
            ``{scan_id, status}`` (status "canceled" once stopped) — or ``{error: ...}`` if the
            scan id is unknown to this org.
        """
        # cancel_scan raises KeyError on a missing/cross-tenant scan — map it to a clean error dict.
        try:
            record = await scan_service.cancel_scan(scan_id, org_id=org_id)
        except KeyError:
            return {"error": f"scan not found: {scan_id}"}
        return {"scan_id": record.scan_id, "status": _status_str(record.status)}

    # --- list_scans -----------------------------------------------------------------------------

    async def list_scans(limit: int = 20) -> dict[str, Any]:
        """List this org's recent scans, newest first.

        Args:
            limit: max scans to return (default 20).

        Returns:
            ``{scans: [{scan_id, status, target, score, n_breaches, created_at}], count}``.
        """
        records = await scan_service.list_scans(org_id=org_id, limit=limit)
        scans = [
            {
                "scan_id": r.scan_id,
                "status": _status_str(r.status),
                # The redacted TargetSpec snapshot's endpoint/provider — never a raw key.
                "target": r.target.get("endpoint") or r.target.get("provider"),
                "score": r.score,
                "n_breaches": r.n_breaches,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ]
        return {"scans": scans, "count": len(scans)}

    # --- get_report -----------------------------------------------------------------------------

    async def get_report(scan_id: str, format: str = "summary") -> Any:
        """Fetch a completed scan's report by id.

        Args:
            scan_id: the id of a COMPLETED scan (poll ``get_scan_status`` first).
            format: "summary" (default) → a concise human-readable MARKDOWN string (score + risk
                level + "N/M breached" + top findings with technique, severity, and remediation)
                you can paste straight to a user. "json" → the full report dict (score, risk_level,
                score_methodology, findings each with remediation) for programmatic use.

        Returns:
            A markdown string ("summary") or the full report dict ("json") — or ``{error: ...}`` if
            the scan is unknown, not completed, or has no report yet.
        """
        # build_json raises ValueError when the scan is unknown / not completed / report missing —
        # surface that as a clean error rather than an exception across the MCP boundary.
        try:
            report = await report_service.build_json(scan_id)
        except ValueError as exc:
            return {"error": str(exc)}
        if format == "json":
            return report
        return _markdown(report)

    # --- list_findings --------------------------------------------------------------------------

    async def list_findings(scan_id: str) -> dict[str, Any]:
        """List a completed scan's findings as flat rows (one per reproduced attack).

        Args:
            scan_id: the id of a COMPLETED scan.

        Returns:
            ``{findings: [{family, technique, vector, severity, breached, success_rate,
            remediation}]}`` — or ``{error: ...}`` if the scan is unknown / not completed.
        """
        try:
            report = await report_service.build_json(scan_id)
        except ValueError as exc:
            return {"error": str(exc)}
        return {"findings": [_finding_row(f) for f in (report.get("findings") or [])]}

    # --- run_benchmark --------------------------------------------------------------------------

    async def run_benchmark(
        endpoint: str | None = None,
        provider: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        dataset: str = "advbench_100",
        max_goals: int = 25,
    ) -> dict[str, Any]:
        """Run a standard-dataset ASR benchmark (e.g. AdvBench / JailbreakBench) against a target.

        Unlike a scan (which reproduces ROGUE's harvested corpus), a benchmark measures
        attack-success-rate on a fixed public dataset so a result is comparable to published
        numbers. Provide EITHER ``endpoint`` OR ``provider``; ``api_key`` is redacted on persist.

        Args:
            endpoint: custom OpenAI-compatible endpoint URL to benchmark.
            provider: hosted provider name (alternative to ``endpoint``).
            api_key: the target's API key (redacted on persist; never stored raw).
            model: model id; defaults per provider when omitted.
            dataset: benchmark dataset id (default "advbench_100").
            max_goals: max goals to attempt (default 25).

        Returns:
            ``{benchmark_id, status}`` — poll ``get_benchmark(benchmark_id)`` for the result.
        """
        spec = _spec(endpoint=endpoint, provider=provider, api_key=api_key, model=model)
        out = await benchmark_service.create(
            spec, dataset=dataset, max_goals=max_goals, org_id=org_id
        )
        return {"benchmark_id": out["benchmark_id"], "status": _status_str(out["status"])}

    # --- get_benchmark --------------------------------------------------------------------------

    async def get_benchmark(benchmark_id: str) -> dict[str, Any]:
        """Fetch a benchmark's status + result by id (from run_benchmark).

        Args:
            benchmark_id: the id returned by ``run_benchmark``.

        Returns:
            The BenchmarkRecord dict ``{dataset, status, n_goals, n_success, asr,
            cost_per_success, winner_rank, ...}`` — or ``{error: ...}`` if unknown to this org.
        """
        record = await benchmark_service.get(benchmark_id, org_id=org_id)
        if record is None:
            return {"error": f"benchmark not found: {benchmark_id}"}
        out = record.model_dump(mode="json")
        out["status"] = _status_str(record.status)
        return out

    # Back-compat alias: the original tool name before the catalog grew. Same callable as
    # `get_scan_status`, registered under both names so existing clients keep working.
    get_scan = get_scan_status

    # Register each on the passed FastMCP. `.tool()` reads the function's signature + docstring to
    # build the tool schema the IDE shows — nothing MCP-specific lives in the callables themselves.
    tools: ScanToolFns = {
        "validate_target": validate_target,
        "start_scan": start_scan,
        "get_scan_status": get_scan_status,
        "get_scan": get_scan,  # back-compat alias
        "cancel_scan": cancel_scan,
        "list_scans": list_scans,
        "get_report": get_report,
        "list_findings": list_findings,
        "run_benchmark": run_benchmark,
        "get_benchmark": get_benchmark,
    }
    for fn in tools.values():
        mcp.tool()(fn)

    return tools


__all__ = ["register_scan_tools", "ScanToolFns"]
