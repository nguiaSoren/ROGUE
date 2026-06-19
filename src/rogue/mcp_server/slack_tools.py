"""ROGUE MCP **Slack action** tools — the Surface-1 Slack-agent surface of the producer MCP server.

`scan_tools.py` adds the generic scan/benchmark/integration lifecycle. THIS module adds the
build-area 06 §8 **Surface-1** tools: the actions a Claude-Desktop / Cursor / Windsurf user runs to
red-team their own consented Slack agent end-to-end — register the agent, run a sandbox cycle, read
the signed ChangeWitness back, and get an inbound-message Tripwire prediction / RedlineGuard gate
rule. Each tool is a thin wrapper: it builds a request, calls the `rogue.integrations.slack` package
(or the shared `ScanService` / `AttestationService` it already depends on), and reshapes the result
for the MCP JSON-RPC layer. There is NO business logic here — registration, cycle scheduling, the
attestation reads, and the prediction/rule emission all live in the slack package.

Tenancy note — org is NEVER an LLM-supplied argument (identical to `scan_tools.py`). The SERVER
resolves the tenant from the connection's auth context and binds it here via
``register_slack_tools(mcp, ..., org_id=...)`` (a closure), so no tool ever takes an ``org_id``
parameter the model could spoof. `SlackAgentTarget.create(org_id=<bound>, ...)` always receives the
closure's org, never a tool argument.

The tool callables are plain ``async`` functions returned by :func:`register_slack_tools`, so they
are unit-testable directly with fake stores/services and no live MCP, no network. The ``FastMCP``
instance is passed in already-built — this module never imports or instantiates one.

Spec: docs/v2/build/06_* §8; reuses the §2 registration (`SlackAgentTarget`/`register_slack_agent`),
§3 sandbox cycle (`run_sandbox_cycle`), §5 ChangeWitness (`latest_change_witness`), §6 Tripwire
(`predict_breach`), §7 RedlineGuard (`score_inbound`).
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from rogue.integrations import slack

if TYPE_CHECKING:
    from rogue.attestation.service import AttestationService
    from rogue.integrations.slack import SlackAgentStore
    from rogue.platform.integration_store import IntegrationStore
    from rogue.platform.interfaces import ScanService


# Module-level test seam for the time source. Production leaves it ``None`` so the cycle's
# ``since`` window is computed off ``datetime.now(timezone.utc)``; an offline test sets it to a
# fixed-clock callable so the window is deterministic. At module scope (NOT a tool argument) so an
# LLM can never inject a clock.
_NOW: Callable[[], datetime] | None = None


# The bound tool callables `register_slack_tools` produces, surfaced as a return value so tests can
# drive them directly without a live MCP, and so a caller can register them by hand. A dict keyed by
# tool name so the catalog can grow without breaking call sites.
SlackToolFns = dict[str, Callable[..., Awaitable[Any]]]


def _now() -> datetime:
    """The current UTC time, via the module test seam when set (else real now)."""
    return _NOW() if _NOW is not None else datetime.now(timezone.utc)


def _jsonable(value: Any) -> Any:
    """Coerce a dataclass-derived value tree to JSON-clean primitives.

    The slack-package dataclasses carry tuples (`TripwirePrediction.ci`) and, for
    `RedlineScore.rule`, a Pydantic `MitigationCandidate`. The MCP JSON-RPC layer wants plain
    JSON — so tuples become lists, and any object exposing `model_dump` is dumped. Plain dicts /
    lists recurse; everything else passes through unchanged.
    """
    if hasattr(value, "model_dump"):  # Pydantic model (MitigationCandidate)
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def register_slack_tools(
    mcp: Any,
    *,
    agent_store: "SlackAgentStore",
    scan_service: "ScanService",
    attestation_service: "AttestationService",
    org_id: str = "default",
    secret_store: Any = None,
    integration_store: "IntegrationStore | None" = None,
) -> SlackToolFns:
    """Attach the Surface-1 Slack action tools to an already-built FastMCP.

    Args:
        mcp: a live ``FastMCP`` instance (this module never builds one). Its ``.tool()`` decorator
            registers each callable as an MCP tool.
        agent_store: the :class:`SlackAgentStore` registrations persist to / cycles read from.
        scan_service: the shared :class:`ScanService` — the sandbox cycle enqueues scans through it,
            so they land on the same queue + store as SDK / API / dashboard scans.
        attestation_service: the area-03 :class:`AttestationService` — the ChangeWitness read,
            Tripwire prediction, and RedlineGuard prior all read the signed chain through it.
        org_id: the tenant the connection authenticated as. The SERVER binds it here; it is
            deliberately NOT a tool argument, so an LLM can never supply or spoof the org it
            registers / scans / reads under.
        secret_store: optional :class:`SecretStore`, passed through to the registration store path
            for a sensitive system prompt (unused by the tools directly; kept symmetric with the
            scan-tool wiring so the server builds the same stores the same way).
        integration_store: optional per-org :class:`IntegrationStore` — when a Slack-app credential
            is supplied at registration it is stored here (the existing `integrations` table path);
            ``None`` leaves the agent registered without an app credential.

    Returns:
        A name → bound-async-callable dict for every Slack tool, so they can be driven directly in
        tests and by any non-MCP caller.
    """

    # --- register_slack_agent -------------------------------------------------------------------

    async def register_slack_agent(
        agent_name: str,
        base_url: str,
        model: str,
        system_prompt: str,
        workspace: str,
        sandbox_channel_id: str,
        security_channel_id: str,
        declared_tools: list[str] | None = None,
        forbidden_topics: list[str] | None = None,
        rule_pack_ref: str | None = None,
    ) -> dict[str, Any]:
        """Register a consented Slack agent so ROGUE can continuously red-team its deployed config.

        You SUPPLY the agent's effective system prompt + declared tools (ROGUE does not introspect
        Slack). The agent must be reachable at an OpenAI-compatible ``base_url`` — that is what routes
        it through ROGUE's custom-endpoint adapter. The sandbox + security channel bindings are
        mandatory: cycles run in the sandbox channel and breach diffs post to the security channel.

        Args:
            agent_name: a name for the agent (combines with ``workspace`` into the config id).
            base_url: the agent's OpenAI-compatible endpoint URL.
            model: the bare model name the endpoint serves.
            system_prompt: the agent's EFFECTIVE system prompt (customer-supplied).
            workspace: the Slack workspace id/slug (used in the config id).
            sandbox_channel_id: the Slack channel id sandbox cycles run in (mandatory).
            security_channel_id: the Slack channel id breach diffs post to (mandatory).
            declared_tools: optional list of tool names the agent exposes.
            forbidden_topics: optional list of topics the agent must refuse.
            rule_pack_ref: optional area-04 rule-pack handle.

        Returns:
            ``{agent_id: str, config_id: str, name: str}`` — or ``{error: <message>}`` on
            fail-closed validation (a missing/blank required field, or a too-short config id).
        """
        # org is the server-bound tenant — NEVER a model-supplied argument.
        try:
            target = slack.SlackAgentTarget.create(
                org_id=org_id,
                agent_name=agent_name,
                workspace=workspace,
                base_url=base_url,
                model=model,
                system_prompt=system_prompt,
                declared_tools=declared_tools or [],
                forbidden_topics=forbidden_topics or [],
                sandbox_channel_id=sandbox_channel_id,
                security_channel_id=security_channel_id,
                rule_pack_ref=rule_pack_ref,
            )
            reg = slack.register_slack_agent(
                target, agent_store=agent_store, integration_store=integration_store
            )
        except ValueError as exc:
            # Fail-closed registration validation — surface a clean message, never raise to MCP.
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001 — never raise across the MCP boundary
            return {"error": str(exc)}
        return {
            "agent_id": reg.agent_id,
            "config_id": reg.config.config_id,
            "name": agent_name,
        }

    # --- run_sandbox_cycle ----------------------------------------------------------------------

    async def run_sandbox_cycle(
        since_hours: int = 24,
        max_tests: int = 50,
        n_trials: int = 1,
    ) -> dict[str, Any]:
        """Enqueue a sandbox red-team cycle over the agents that newly-landed primitives apply to.

        COSTLY DOWNSTREAM — each enqueued scan spends real money on endpoint + judge LLM calls. This
        is a DELIBERATE invocation; never run it on a loop or timer. It enqueues the scans and returns
        immediately; poll each ``scan_id`` via the scan tools to follow progress.

        Args:
            since_hours: look-back window — test against primitives that landed within this many
                hours (default 24).
            max_tests: max attacks per cycle (default 50).
            n_trials: trials per attack (default 1).

        Returns:
            ``{enqueued: [{scan_id: str}], count: int}`` — or ``{error: <message>}``.
        """
        try:
            since = _now() - timedelta(hours=since_hours)
            records = await slack.run_sandbox_cycle(
                org_id,
                agent_store=agent_store,
                scan_service=scan_service,
                since=since,
                max_tests=max_tests,
                n_trials=n_trials,
            )
        except Exception as exc:  # noqa: BLE001 — never raise across the MCP boundary
            return {"error": str(exc)}
        return {
            "enqueued": [{"scan_id": r.scan_id} for r in records],
            "count": len(records),
        }

    # --- get_change_witness ---------------------------------------------------------------------

    async def get_change_witness(agent_name: str) -> dict[str, Any]:
        """Read the latest signed ChangeWitness for one Slack agent (the auditable cycle result).

        Returns the render-ready projection of the agent's most-recent signed sandbox ``scan`` entry:
        who was tested, the signed-entry coordinates (entry id + hash, for the audit trail), the
        breaching rules with their "holds N/M" + CI, the verified mitigations folded onto the same
        chain, and the non-negotiable scope framing line.

        Args:
            agent_name: the registered Slack agent's name.

        Returns:
            The ChangeWitness summary dict — or ``{error: "no signed ChangeWitness for <agent>"}``
            when the agent has no signed scan entry yet.
        """
        try:
            summary = slack.latest_change_witness(
                org_id, agent_name, attestation_service=attestation_service
            )
        except Exception as exc:  # noqa: BLE001 — never raise across the MCP boundary
            return {"error": str(exc)}
        if summary is None:
            return {"error": f"no signed ChangeWitness for {agent_name}"}
        return _jsonable(dataclasses.asdict(summary))

    # --- tripwire_predict -----------------------------------------------------------------------

    async def tripwire_predict(agent_name: str, message: str) -> dict[str, Any]:
        """Predict — from this agent's prior signed scan — whether an inbound message breaks it.

        ADVISORY ONLY (ADR-0010): ROGUE never sits in the request path. This classifies the message
        to an attack family and, from the agent's most-recent signed sandbox scan, returns the prior
        breach rate + CI for that family and a ready-to-post advisory line — never an enforced block.

        Args:
            agent_name: the registered Slack agent's name.
            message: the inbound message text to assess.

        Returns:
            The Tripwire prediction dict ``{inbound_excerpt, matched_family, calibrated,
            prior_breach_rate, ci, n_trials, n_breaches, scan_id, recommendation, advisory}`` — or
            ``{error: <message>}``.
        """
        try:
            pred = slack.predict_breach(
                org_id, agent_name, message, attestation_service=attestation_service
            )
        except Exception as exc:  # noqa: BLE001 — never raise across the MCP boundary
            return {"error": str(exc)}
        return _jsonable(dataclasses.asdict(pred))

    # --- redline_score --------------------------------------------------------------------------

    async def redline_score(agent_name: str, message: str) -> dict[str, Any]:
        """Emit a deployable inbound-gate RULE for a message, with the judge's calibrated precision.

        ADR-0010: ROGUE generates + verifies the rule; the CLIENT deploys + enforces it — ROGUE never
        blocks. The rule's confidence is the area-02 calibrated judge's measured precision for the
        message's breach class (``None`` with an honest "uncalibrated" status when that class wasn't
        shipped — never a fabricated number, ADR-0011).

        Args:
            agent_name: the registered Slack agent's name (used for the optional empirical prior).
            message: the inbound message text to classify + gate.

        Returns:
            The RedlineGuard score dict ``{matched_family, breach_type, risk, confidence,
            calibration_status, over_block, recommendation, rule}`` (``rule`` is the deployable
            ``GUARDRAIL_RULE`` candidate, or ``null``) — or ``{error: <message>}``.
        """
        try:
            score = slack.score_inbound(
                org_id, agent_name, message, attestation_service=attestation_service
            )
        except Exception as exc:  # noqa: BLE001 — never raise across the MCP boundary
            return {"error": str(exc)}
        return _jsonable(dataclasses.asdict(score))

    # Register each on the passed FastMCP. `.tool()` reads the function's signature + docstring to
    # build the tool schema the IDE shows — nothing MCP-specific lives in the callables themselves.
    tools: SlackToolFns = {
        "register_slack_agent": register_slack_agent,
        "run_sandbox_cycle": run_sandbox_cycle,
        "get_change_witness": get_change_witness,
        "tripwire_predict": tripwire_predict,
        "redline_score": redline_score,
    }
    for fn in tools.values():
        mcp.tool()(fn)

    return tools


__all__ = ["register_slack_tools", "SlackToolFns"]
