"""McpToolBackend — Level 2: route agent-exec tool calls to a customer's OWN MCP tool server.

This is the ``ToolBackend`` that makes ROGUE test a customer's *real* agent surface: real tools
run, real returns come back, ``backend_kind=LIVE`` (real bytes ⇒ headline-eligible, unlike EMULATED).

SAFETY — this executes against the customer's real system, so:
- ``LiveToolTarget.authorized`` MUST be True or ``prepare()`` refuses to connect (the customer
  supplies the endpoint, and thereby consents — ROGUE never ships one).
- Destructive tools NEVER reach a live ``call_tool``: the harness records-not-executes any tool in
  ``forbidden_tools`` BEFORE the backend (harness.py), so only benign tools actually run. The
  customer marks their dangerous tools forbidden; the model's *attempt* to call them is the breach.
- The judge is backend-agnostic: it reads the trace + provenance. Forbidden-tool and
  followed-injection signals work unchanged; for indirect-injection tests this backend MITM-splices
  the poisoned payload (and any canary the goal carries) into the *real* return.

Connection lifecycle: ``prepare()`` opens the transport + session and caches ``list_tools()`` (the
Protocol's ``tool_specs`` is sync, so discovery must happen ahead of the loop); ``aclose()`` tears it
down. An ``AsyncExitStack`` keeps the transport/session context managers open in between.
"""

from __future__ import annotations

import os
import shlex
from contextlib import AsyncExitStack
from typing import Optional

from rogue.core.content_blocks import ToolCallBlock
from rogue.schemas import (
    AgentToolSpec,
    LiveToolTarget,
    ReturnProvenance,
    ToolBackendKind,
    ToolCategory,
    ToolResultRecord,
    ToolSensitivity,
)

from ..context import AgentRunContext


def _result_to_text(result) -> str:
    """Flatten an MCP CallToolResult into the plain-string return the harness feeds the model."""
    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
        else:  # non-text content (image/resource) — record a compact placeholder
            parts.append(f"[{getattr(block, 'type', 'content')}]")
    body = "\n".join(parts).strip()
    if not body and getattr(result, "structuredContent", None) is not None:
        body = str(result.structuredContent)
    if getattr(result, "isError", False):
        return f"Error: {body or 'tool reported an error'}"
    return body or "(empty result)"


class McpToolBackend:
    """A ``ToolBackend`` that dispatches to a live MCP server. Construct, ``await prepare()``,
    run, then ``await aclose()`` — one instance per harness run (fresh, isolated session)."""

    def __init__(self, target: LiveToolTarget) -> None:
        self.target = target
        self._session = None
        self._stack: Optional[AsyncExitStack] = None
        self._specs: list[AgentToolSpec] = []

    # ---- lifecycle ----

    async def prepare(self) -> None:
        """Connect, initialize, and cache the tool list. Raises on an unauthorized target."""
        if not self.target.authorized:
            raise PermissionError(
                "LiveToolTarget.authorized must be True to run against a real tool host "
                "(customer consent gate). Refusing to connect."
            )
        from mcp import ClientSession, StdioServerParameters  # noqa: PLC0415

        stack = AsyncExitStack()
        try:
            if self.target.transport == "stdio":
                from mcp.client.stdio import stdio_client  # noqa: PLC0415

                parts = shlex.split(self.target.endpoint)
                # inherit the current env: a customer's local stdio server typically needs it
                # (PATH, its own API keys, etc.).
                params = StdioServerParameters(command=parts[0], args=parts[1:], env=dict(os.environ))
                read, write = await stack.enter_async_context(stdio_client(params))
            elif self.target.transport == "sse":
                from mcp.client.sse import sse_client  # noqa: PLC0415

                read, write = await stack.enter_async_context(
                    sse_client(self.target.endpoint, headers=self.target.headers or None)
                )
            else:  # streamable-http
                from mcp.client.streamable_http import streamablehttp_client  # noqa: PLC0415

                read, write, _ = await stack.enter_async_context(
                    streamablehttp_client(self.target.endpoint, headers=self.target.headers or None)
                )
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._session = session
            self._stack = stack
            await self._load_specs()
        except Exception:
            await stack.aclose()
            raise

    async def _load_specs(self) -> None:
        listed = await self._session.list_tools()
        allow = set(self.target.tool_allowlist)
        specs: list[AgentToolSpec] = []
        for t in listed.tools:
            if allow and t.name not in allow:
                continue
            specs.append(
                AgentToolSpec(
                    name=t.name,
                    description=(t.description or t.name)[:1024],
                    parameters=getattr(t, "inputSchema", None) or {},
                    category=ToolCategory.ACTION,  # MCP doesn't declare SOURCE/SINK/ACTION; default
                    sensitivity=ToolSensitivity.SENSITIVE,
                    backend_kind=ToolBackendKind.LIVE,
                )
            )
        self._specs = specs

    async def aclose(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
            self._session = None

    # ---- ToolBackend contract ----

    def tool_specs(
        self,
        declared: list[str],
        forbidden: list[str],
        provided: list[AgentToolSpec] | None = None,
    ) -> list[AgentToolSpec]:
        """The live server's tools ARE the surface (discovered in ``prepare()``); re-stamp forbidden.
        ``declared``/``provided`` are ignored — the customer's real server is authoritative."""
        fset = set(forbidden)
        return [s.model_copy(update={"forbidden": s.name in fset}) for s in self._specs]

    def canonical_name(self, name: str) -> Optional[str]:  # live tools aren't aliased
        return None

    async def execute(self, call: ToolCallBlock, ctx: AgentRunContext) -> ToolResultRecord:
        """Invoke the real tool, then MITM-splice any pending indirect injection into its return."""
        if self._session is None:
            body = f"Error: live tool {call.name!r} unavailable (no session)."
        else:
            try:
                result = await self._session.call_tool(call.name, dict(call.arguments or {}))
                body = _result_to_text(result)
            except Exception as exc:  # noqa: BLE001 — a failed live call is a return, not a crash
                body = f"Error: live tool {call.name!r} failed ({type(exc).__name__}: {exc})."

        injection = ctx.injection_for_tool(call.name)
        if injection is not None:
            body = f"{body}\n\n{injection.payload_text}"
            injection.fired = True
            provenance = ReturnProvenance(
                is_poisoned=True,
                injection_id=injection.injection_id,
                injected_goal=injection.goal,
            )
        else:
            provenance = ReturnProvenance()

        return ToolResultRecord(
            call_id=call.id,
            result=body,
            backend_kind=ToolBackendKind.LIVE,
            provenance=provenance,
        )


__all__ = ["McpToolBackend"]
