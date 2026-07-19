"""AgentRunContext — mutable per-run state shared across the tool backends (Phase 2).

A runtime dataclass, NOT persisted directly: its serializable subset is exactly the
transcript header + the planted-secret / injection lists (``schemas/agent_transcript.py``).
The tool backends read from it (which tool is which, whether a call's tool has a pending
injection, the emulator cache) and record into it (canaries a SOURCE tool planted). The
harness (Phase 3) owns turn assembly and the ``turn_index`` cursor.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from rogue.schemas import AgentToolSpec, InjectionGoal, PlantedSecret

if TYPE_CHECKING:  # avoid an import cycle; only a type reference is needed at runtime
    from .memory_channel import MemoryStore


@dataclass
class InjectionPayload:
    """A pending indirect-injection payload to splice into a carrier tool's RETURN.

    Populated before the run from an ``AttackVector.TOOL_OUTPUT`` primitive (Phase 6
    corpus). ``goal`` is the machine-checkable success condition the trace judge (Phase 4)
    evaluates; ``payload_text`` is the attacker-authored bytes spliced into the return.

    ``placement`` selects the DELIVERY CHANNEL (Wave-④ MCP-native carriers). The default
    ``"return"`` is byte-identical to the original behaviour (splice into the tool RETURN):

    - ``"return"``        — payload lives in the carrier tool's RETURN (the historical path).
    - ``"schema"``        — payload lives in the carrier tool's DESCRIPTION/schema (MCP
      tool-poisoning / "line jumping"): the backend splices it into the spec the model reads,
      and ARMS the ``goal`` on the tool's first return so signal (c) can attribute a downstream
      call. No payload text is duplicated into the return.
    - ``"schema_rugpull"`` — description is benign at ``list_tools`` time; the malicious payload
      appears in the RETURN only on/after the SECOND use (mutate-after-inspection). ``times_armed``
      tracks the per-injection call count the backend increments.

    ``rag_planted_answer`` (PoisonedRAG) is the unguessable answer token seeded into a
    ``retrieve_documents`` poison passage; the adoption grader reads it back out of the transcript.
    """

    injection_id: str
    carrier_tool: str
    payload_text: str
    goal: InjectionGoal
    fire_on_turn: Optional[int] = None  # only inject at/after this turn (None = any)
    fired: bool = False
    placement: str = "return"  # "return" | "schema" | "schema_rugpull" (see class docstring)
    rag_planted_answer: Optional[str] = None  # PoisonedRAG planted answer token (adoption grader)
    times_armed: int = 0  # rug-pull: count of times the carrier tool has been called this run


@dataclass
class AgentRunContext:
    """Shared, mutable state for one agent-harness run.

    ``run_secret`` mints the canaries (:mod:`rogue.reproduce.agent.canaries`) and is sealed
    (never published). ``tool_specs`` maps a canonical tool name → its resolved
    :class:`AgentToolSpec` (with ``forbidden`` already stamped from the config).
    """

    seed: int
    run_secret: str
    tool_specs: dict[str, AgentToolSpec] = field(default_factory=dict)
    planted_secrets: list[PlantedSecret] = field(default_factory=list)
    injections: list[InjectionPayload] = field(default_factory=list)
    emulator_cache: dict[str, str] = field(default_factory=dict)
    # Cross-session agent MEMORY (Q13 / AgentLeak C5). ``None`` in an ordinary run — the ``recall_memory``
    # / ``save_memory`` tools stay inert-benign, so a config without them is byte-identical. Attached only
    # by the memory-exfil probe (sealed like ``emulator_cache``; survives across runs for a 2-session pair).
    memory: Optional["MemoryStore"] = None
    turn_index: int = 0

    def rng(self) -> random.Random:
        """A deterministic RNG seeded from ``seed`` (backends must use this, not ``random``)."""
        return random.Random(self.seed)

    def spec_for(self, name: str) -> Optional[AgentToolSpec]:
        """The resolved spec for a tool name, or ``None`` if the model invented it."""
        return self.tool_specs.get(name)

    def is_forbidden(self, name: str) -> bool:
        spec = self.tool_specs.get(name)
        return bool(spec and spec.forbidden)

    def injection_for_tool(self, tool_name: str) -> Optional[InjectionPayload]:
        """The next unfired injection whose carrier is ``tool_name`` and whose turn is due."""
        for inj in self.injections:
            if inj.carrier_tool != tool_name or inj.fired:
                continue
            if inj.fire_on_turn is None or self.turn_index >= inj.fire_on_turn:
                return inj
        return None

    def record_planted_secret(self, secret: PlantedSecret) -> None:
        """Register a canary a SOURCE tool just embedded in its return (single-source: a
        given ``value`` may be recorded only once — the transcript validator enforces it)."""
        self.planted_secrets.append(secret)
