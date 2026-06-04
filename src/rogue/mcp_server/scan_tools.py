"""ROGUE MCP **action** tools — the write surface of the producer-side MCP server.

The six tools in :mod:`rogue.mcp_server.server` are read-only: they query the harvested
threat-intelligence DB. This module adds the *action* tools that let a Claude-Desktop / Cursor /
Windsurf user actually run a scan against their own endpoint from inside the IDE — the headline
flow being:

    "Scan my staging endpoint"   → start_scan(endpoint=...)        → {scan_id, status: "queued"}
    "Is it done?"                → get_scan(scan_id)               → poll until status: "completed"
    (completed)                  →                                   summary: "7 vulnerabilities
                                                                       found, top: Crescendo"

Critically, these tools route through the SAME :class:`~rogue.platform.interfaces.ScanService` /
:class:`~rogue.platform.interfaces.ScanEngine` that back the SDK, the HTTP API and the dashboard.
There is no scan logic here — ``start_scan`` builds a :class:`~rogue.platform.schemas.ScanSpec` and
hands it to ``scan_service.create_scan``; ``get_scan`` reads back the persisted
:class:`~rogue.platform.schemas.ScanRecord`; ``validate`` delegates to ``engine.validate``. The one
execution path stays singular.

Tenancy note — org is NEVER an LLM-supplied argument. For an HTTP API call the org comes from the
API key; for MCP it comes from the connection's auth context. The server resolves it and binds it
here via ``register_scan_tools(mcp, scan_service=..., engine=..., org_id=...)`` (a closure/partial),
so no tool ever takes an ``org_id`` parameter the model could spoof.

The tool callables are plain ``async`` functions returned by :func:`register_scan_tools`, so they
are unit-testable directly with a fake ``scan_service`` / ``engine`` and no live MCP, no network.
The ``FastMCP`` instance is passed in already-built — this module never imports or instantiates one.

Spec: docs/platform/ARCHITECTURE.md (ScanService/ScanEngine spine) + ROGUE_PLAN.md §6.2 / §11.2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable

from rogue.platform.schemas import ScanRecord, ScanSpec, ScanStatus, TargetSpec

if TYPE_CHECKING:
    from rogue.platform.interfaces import ScanEngine, ScanService


# --------------------------------------------------------------------------- #
# Tool callable factory
# --------------------------------------------------------------------------- #


# The trio of bound tool callables `register_scan_tools` produces — surfaced as a return value so
# tests can drive them directly without a live MCP, and so a caller can register them by hand.
ScanToolFns = tuple[
    Callable[..., Awaitable[dict[str, Any]]],  # start_scan
    Callable[..., Awaitable[dict[str, Any]]],  # get_scan
    Callable[..., Awaitable[dict[str, Any]]],  # validate
]


def _status_str(status: Any) -> str:
    """Stringify a ScanStatus to its wire value; pass through a bare string.

    ScanRecord pins ``use_enum_values: False``, so ``record.status`` is a ScanStatus member, not a
    string. The MCP JSON-RPC layer wants a plain string — coerce here so every tool result is
    JSON-clean regardless of whether the fake/real service hands back an enum or a str.
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


def register_scan_tools(
    mcp: Any,
    *,
    scan_service: ScanService,
    engine: ScanEngine,
    org_id: str = "default",
) -> ScanToolFns:
    """Attach the action tools (start_scan / get_scan / validate) to an already-built FastMCP.

    Args:
        mcp: a live ``FastMCP`` instance (this module never builds one). Its ``.tool()`` decorator
            registers each callable as an MCP tool.
        scan_service: the shared :class:`ScanService` — ``start_scan`` / ``get_scan`` route through
            it, so MCP scans land on the same queue + store as SDK / API / dashboard scans.
        engine: the shared :class:`ScanEngine` — ``validate`` delegates to ``engine.validate``.
        org_id: the tenant the connection authenticated as. The SERVER resolves this from the MCP
            connection's auth context and binds it here; it is deliberately NOT a tool argument, so
            an LLM can never supply or spoof the org it scans under.

    Returns:
        ``(start_scan, get_scan, validate)`` — the bound async callables, so they can be driven
        directly in tests and by any non-MCP caller.
    """

    async def start_scan(
        endpoint: str | None = None,
        provider: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        pack: str = "default",
        max_tests: int = 20,
    ) -> dict[str, Any]:
        """Start a red-team scan against your model endpoint. Returns immediately — poll get_scan.

        Provide EITHER ``endpoint`` (a custom OpenAI-compatible URL) OR ``provider`` (e.g.
        "openai", "anthropic"). ``model`` and ``api_key`` are optional; ``api_key`` is the target's
        credential — it is redacted before the scan is persisted and never logged. The scan is
        queued and runs asynchronously; this returns ``{scan_id, status}`` so you can poll
        ``get_scan(scan_id)`` until it completes.

        Args:
            endpoint: custom OpenAI-compatible endpoint URL to scan.
            provider: hosted provider name (alternative to ``endpoint``).
            api_key: the target's API key (redacted on persist; never stored raw).
            model: model id (e.g. "gpt-4o-mini"); defaults per provider when omitted.
            pack: attack pack to run (default "default").
            max_tests: max attacks to attempt (default 20).

        Returns:
            ``{"scan_id": str, "status": str}`` — the queued scan's id + status ("queued").
        """
        # TargetSpec's model_validator enforces endpoint-or-provider; let a ValueError propagate as
        # the tool's error so the model sees a clear "needs endpoint or provider" message.
        spec = ScanSpec(
            target=TargetSpec(
                endpoint=endpoint,
                provider=provider,
                model=model,
                api_key=api_key,
            ),
            pack=pack,
            max_tests=max_tests,
        )
        # org is the server-bound tenant — NOT a model-supplied argument.
        record = await scan_service.create_scan(spec, org_id=org_id)
        return {"scan_id": record.scan_id, "status": _status_str(record.status)}

    async def get_scan(scan_id: str) -> dict[str, Any]:
        """Poll a scan's status and results by id (from start_scan).

        While the scan runs, ``status`` is "queued"/"running" and ``summary`` reports progress. Once
        ``status`` is "completed", ``n_breaches`` / ``top_attack`` / ``score`` are populated and
        ``summary`` reads like "7 vulnerabilities found, top: Crescendo".

        Args:
            scan_id: the id returned by ``start_scan``.

        Returns:
            ``{scan_id, status, progress, n_tests, n_completed, n_breaches, top_attack, score,
            summary}``. Raises if the scan id is unknown to this org.
        """
        record = await scan_service.get_scan(scan_id, org_id=org_id)
        if record is None:
            raise ValueError(f"scan not found: {scan_id!r}")
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

    async def validate(
        endpoint: str | None = None,
        provider: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Cheap pre-flight check on a target BEFORE spending on a scan.

        Confirms the endpoint is reachable, the credential authenticates, the model responds, and
        which modalities (image / audio) it supports. No attacks are run; near-zero cost. Run this
        first when a user gives you an endpoint, then ``start_scan`` once it reports ready.

        Args:
            endpoint: custom OpenAI-compatible endpoint URL to validate.
            provider: hosted provider name (alternative to ``endpoint``).
            api_key: the target's API key (used for the live check; not stored).
            model: model id; defaults per provider when omitted.

        Returns:
            ``{target, reachable, authenticated, model_responds, supports_image, supports_audio,
            ok, error}`` — ``ok`` is true only when reachable + authenticated + model_responds.
        """
        spec = ScanSpec(
            target=TargetSpec(
                endpoint=endpoint,
                provider=provider,
                model=model,
                api_key=api_key,
            ),
        )
        result = await engine.validate(spec)
        return result.to_dict()

    # Register each on the passed FastMCP. `.tool()` reads the function's signature + docstring to
    # build the tool schema the IDE shows — nothing MCP-specific lives in the callables themselves.
    mcp.tool()(start_scan)
    mcp.tool()(get_scan)
    mcp.tool()(validate)

    return start_scan, get_scan, validate


__all__ = ["register_scan_tools", "ScanToolFns"]
