"""Tool backends for the agent execution harness (Phase 2) — the ``ToolBackend`` contract.

A backend turns a tool call the target model emitted into a tool RETURN, safely and with
no real side effect. Two implementations compose via :class:`HybridBackend`:

- :class:`HoneytokenBackend` — a deterministic, ROGUE-authored stub library for known tool
  names (headline-eligible; plants canaries into SOURCE returns, splices poisoned payloads
  into carrier returns).
- :class:`EmulatorBackend` — a ToolEmu-style LM fallback for unknown/custom tool names
  (nondeterministic; ``backend_kind=EMULATED``, never headline-eligible — reversed Q3).

The backend deals in the RICH schema types (``ToolResultRecord`` carries ``backend_kind`` +
``ReturnProvenance``); the harness (Phase 3) converts to/from the core ``ToolCallBlock`` /
``ToolResultBlock`` wire types at the adapter boundary. Forbidden-call *blocking*
(recorded-not-executed) is the harness's job, not the backend's; the backend only produces
returns for the calls it is asked to execute.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from rogue.core.content_blocks import ToolCallBlock
from rogue.schemas import AgentToolSpec, ToolResultRecord

from ..context import AgentRunContext


@runtime_checkable
class ToolBackend(Protocol):
    """The one seam the harness dispatches through. Implementations must be pure over
    ``(call, ctx, ctx.run_secret, ctx.seed)`` and cause NO real side effect."""

    def tool_specs(
        self,
        declared: list[str],
        forbidden: list[str],
        provided: list[AgentToolSpec] | None = None,
    ) -> list[AgentToolSpec]:
        """Resolve the tool surface offered to the model.

        Normally resolves bare ``declared`` names → full specs, stamping ``forbidden``.
        When ``provided`` is given (Level 1 — the customer's real tool schemas), those specs
        define the surface verbatim (only ``forbidden`` is re-stamped); the backend does NOT
        synthesize from ``declared``. Names not resolvable to a known stub still get a spec
        (emulated)."""
        ...

    async def execute(
        self, call: ToolCallBlock, ctx: AgentRunContext
    ) -> ToolResultRecord:
        """Produce the tool RETURN for ``call``. Records exactly one result; plants any
        canary/poisoned bytes via ``ctx``; sets ``backend_kind`` + ``provenance``."""
        ...


__all__ = ["ToolBackend"]
