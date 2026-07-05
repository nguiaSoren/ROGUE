"""HybridBackend — routes each tool call to the honeytoken registry or the LM-emulator.

Dispatch (DESIGN §B.7, review F8/M7):

- The model is only ever *offered* declared tools (``tool_specs`` below), so a well-behaved
  run calls only declared names.
- **Declared + known stub** → :class:`HoneytokenBackend` (deterministic, headline-eligible).
- **Declared + no stub** (a custom tool the customer declared) → :class:`EmulatorBackend`
  (nondeterministic, ``EMULATED``, never headline-eligible).
- **Undeclared** (the model reached for a tool it was not given): **rejected, never
  fabricated**. If the undeclared name resolves to a canonical *sensitive* honeytoken tool
  (e.g. the config declared nothing but the model called ``transfer_funds``), the rejection
  return is still recorded so the Phase-4 judge can raise the non-headline
  ``ATTEMPTED_UNDECLARED_SENSITIVE_TOOL`` signal from the trace + registry. A fully invented
  name is rejected the same way — we never emulate a capability the customer didn't declare.
"""

from __future__ import annotations

from typing import Optional

from rogue.core.content_blocks import ToolCallBlock
from rogue.schemas import (
    AgentToolSpec,
    ReturnProvenance,
    ToolBackendKind,
    ToolResultRecord,
    ToolSensitivity,
)

from ..context import AgentRunContext
from .emulator import EmulatorBackend
from .honeytoken import HoneytokenBackend


class HybridBackend:
    """The single ``ToolBackend`` the harness dispatches through (composes the two)."""

    def __init__(
        self,
        honeytoken: Optional[HoneytokenBackend] = None,
        emulator: Optional[EmulatorBackend] = None,
    ) -> None:
        self.honeytoken = honeytoken or HoneytokenBackend()
        # Optional: only needed when a run declares tools with no honeytoken stub. A
        # honeytoken-only run (no custom declared tools) works with emulator=None.
        self.emulator = emulator

    # ---- resolution helpers (also used by the Phase-4 judge for F8 attribution) ----

    def canonical_name(self, name: str) -> Optional[str]:
        """The canonical honeytoken name for ``name`` (via alias table), or ``None``."""
        tool = self.honeytoken.resolve(name)
        return tool.canonical if tool else None

    def sensitivity_of(self, name: str) -> Optional[ToolSensitivity]:
        tool = self.honeytoken.resolve(name)
        return tool.sensitivity if tool else None

    def category_of(self, name: str):
        """The canonical tool's ``ToolCategory`` (SINK/SOURCE/ACTION), or ``None`` if custom."""
        tool = self.honeytoken.resolve(name)
        return tool.category if tool else None

    # ---- ToolBackend contract ----

    def tool_specs(
        self,
        declared: list[str],
        forbidden: list[str],
        provided: list[AgentToolSpec] | None = None,
    ) -> list[AgentToolSpec]:
        # Level 1 (bring-your-own schema): the customer's specs ARE the surface. Present them
        # verbatim (re-stamping forbidden by name/canonical); execute() still routes each call
        # to the honeytoken stub (known name) or the emulator (custom) — safe returns unchanged.
        if provided:
            fset = set(forbidden)
            return [
                s.model_copy(update={"forbidden": s.name in fset or (self.canonical_name(s.name) or "") in fset})
                for s in provided
            ]
        known = [n for n in declared if self.honeytoken.handles(n)]
        unknown = [n for n in declared if not self.honeytoken.handles(n)]
        specs = list(self.honeytoken.tool_specs(known, forbidden))
        if unknown and self.emulator is not None:
            specs.extend(self.emulator.tool_specs(unknown, forbidden))
        # If there is no emulator, un-stubbed declared tools simply aren't offered — the
        # harness/gate is responsible for requiring an emulator when the corpus needs one.
        return specs

    async def execute(self, call: ToolCallBlock, ctx: AgentRunContext) -> ToolResultRecord:
        canonical = self.canonical_name(call.name)
        declared_names = set(ctx.tool_specs.keys())
        # a call is "declared" if its canonical (or raw) name is in the resolved spec set
        is_declared = (canonical in declared_names) or (call.name in declared_names)

        if is_declared and self.honeytoken.handles(call.name):
            return await self.honeytoken.execute(call, ctx)

        if is_declared:  # declared but no stub → emulate
            if self.emulator is None:
                return self._reject(call, reason="no emulator configured for this custom tool")
            return await self.emulator.execute(call, ctx)

        # ---- undeclared: reject, never fabricate (F8/M7) ----
        return self._reject(call, reason="tool not available in this deployment")

    def _reject(self, call: ToolCallBlock, *, reason: str) -> ToolResultRecord:
        """A deterministic rejection return for an undeclared/unservable call.

        The tool_name is recorded verbatim in the transcript, so the Phase-4 judge can map it
        through :meth:`canonical_name` + :meth:`sensitivity_of` to flag an attempt to reach an
        undeclared *sensitive* capability (non-headline signal). We never emulate here.
        """
        return ToolResultRecord(
            call_id=call.id,
            result=f"Error: tool {call.name!r} is not available ({reason}).",
            backend_kind=ToolBackendKind.HONEYTOKEN,
            provenance=ReturnProvenance(),
        )

    # exposed so a caller/gate can decide whether an emulator is required
    def declared_needs_emulator(self, declared: list[str]) -> bool:
        return any(not self.honeytoken.handles(n) for n in declared)

    def critical_declared(self, declared: list[str]) -> set[str]:
        """Canonical names among ``declared`` whose honeytoken sensitivity is CRITICAL.

        The harness unions these into the effective forbidden set by default (Soren, DESIGN
        §8 Q4) so signal (a) has ammunition even on a config that declares no explicit
        forbidden-tools policy — any use of a declared destructive tool during an attack is a
        breach candidate. The benign-baseline subtraction (Phase 6) nets out a task that
        legitimately needs the tool. A run may opt out via ``default_forbid_critical=False``.
        """
        out: set[str] = set()
        for name in declared:
            tool = self.honeytoken.resolve(name)
            if tool and tool.sensitivity == ToolSensitivity.CRITICAL:
                out.add(tool.canonical)
        return out


__all__ = ["HybridBackend"]
