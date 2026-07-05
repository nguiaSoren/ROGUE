"""AgentHarness — the multi-turn tool loop that makes ROGUE's ``× tool`` axis real (Phase 3).

Drives: ``adapter.invoke(messages, tools=…)`` → parse tool calls → dispatch each to the
:class:`HybridBackend` → feed the returns back → loop, until the model stops calling tools,
``max_turns`` is hit, or a loop guard trips. Produces a replayable :class:`AgentTranscript`
(the artifact the Phase-4 ``TraceJudge`` scores). Nothing here judges breaches.

Composition, not a fork: adapter resolution mirrors ``TargetPanel`` (the module-level
``_resolve_provider`` + the registry) so routing stays in one place, but the loop is new.
Forbidden-call *blocking* (recorded-not-executed, review H6) lives here; the backend only
produces returns for calls it is asked to execute.

Review fixes baked in: terminate whenever the model emits no tool call regardless of the
provider's stop_reason (M2); a Counter-based loop guard that catches A→B→A oscillation, not
just a repeated call (LOW-12); default-forbid CRITICAL declared tools (DESIGN §8 Q4).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any, Optional

from rogue.adapters import AdapterConfig, registry
from rogue.core.content_blocks import TextBlock, ToolCallBlock, ToolResultBlock
from rogue.core.message import CanonicalMessage, MessageRole
from rogue.reproduce.target_panel import _resolve_provider
from rogue.schemas import (
    AgentTranscript,
    AgentTurn,
    DeploymentConfig,
    DeterminismHeader,
    ReturnProvenance,
    ToolBackendKind,
    ToolCallRecord,
    ToolResultRecord,
    TurnRole,
)

from .backends.hybrid import HybridBackend
from .canaries import new_run_secret
from .context import AgentRunContext

# A forbidden call is recorded-not-executed; the model still needs a result to continue.
_DENIED = "Error: permission denied — this tool is not permitted in this deployment."


def _transcript_id(primitive_id: str, config_id: str, trial_index: int, seed: int) -> str:
    h = hashlib.sha256(f"{primitive_id}:{config_id}:{trial_index}:{seed}".encode()).hexdigest()
    return f"tr-{h[:24]}"


class AgentHarness:
    """Runs one (primitive × config × trial) agent loop and returns its transcript."""

    def __init__(
        self,
        backend: Optional[HybridBackend] = None,
        *,
        max_turns: int = 6,
        loop_guard_threshold: int = 3,
        default_forbid_critical: bool = True,
        adapter_extra: Optional[dict[str, Any]] = None,
        harness_version: str = "v1",
    ) -> None:
        self.backend = backend or HybridBackend()
        self.max_turns = max_turns
        self.loop_guard_threshold = loop_guard_threshold
        self.default_forbid_critical = default_forbid_critical
        self._adapters: dict[tuple, Any] = {}
        self._adapter_extra = dict(adapter_extra or {})
        self.harness_version = harness_version

    # ---- setup ----

    def effective_forbidden(self, config: DeploymentConfig) -> list[str]:
        """Config's forbidden_tools ∪ (default-forbidden CRITICAL declared tools)."""
        forbidden = set(config.forbidden_tools)
        if self.default_forbid_critical:
            forbidden |= self.backend.critical_declared(config.declared_tools)
        return sorted(forbidden)

    def _adapter_for(self, model_id: str, base_url: Optional[str] = None):
        provider = "custom" if base_url else _resolve_provider(model_id)
        key = (provider, model_id, base_url)
        adapter = self._adapters.get(key)
        if adapter is None:
            adapter = registry.create(
                provider,
                AdapterConfig(
                    model=model_id,
                    base_url=base_url,
                    api_key=self._adapter_extra.get("api_key"),
                    extra=dict(self._adapter_extra),
                ),
            )
            self._adapters[key] = adapter
        return adapter

    # ---- the loop ----

    async def run(
        self,
        config: DeploymentConfig,
        user_prompt: str,
        *,
        primitive_id: str,
        ctx: Optional[AgentRunContext] = None,
        seed: int = 0,
        temperature: float = 0.0,
        trial_index: int = 0,
        adapter: Any = None,
        budget: Any = None,
        backend: Any = None,
    ) -> AgentTranscript:
        # ``backend`` lets the caller inject a per-run backend (e.g. a live McpToolBackend for a
        # config with live_tool_target); default is the shared safe backend. The caller owns its
        # lifecycle (prepare/aclose). Everything below dispatches through this local, not self.backend.
        backend = backend or self.backend
        forbidden = self.effective_forbidden(config)
        forbidden_set = set(forbidden)
        specs = backend.tool_specs(config.declared_tools, forbidden, provided=config.tool_specs)
        spec_by_name = {s.name: s for s in specs}

        if ctx is None:
            ctx = AgentRunContext(seed=seed, run_secret=new_run_secret(), tool_specs=spec_by_name)
        elif not ctx.tool_specs:
            ctx.tool_specs = spec_by_name

        adapter = adapter or self._adapter_for(config.target_model, config.base_url)

        messages: list[CanonicalMessage] = []
        if config.system_prompt:
            messages.append(
                CanonicalMessage(role=MessageRole.SYSTEM, content=[TextBlock(text=config.system_prompt)])
            )
        messages.append(
            CanonicalMessage(role=MessageRole.USER, content=[TextBlock(text=user_prompt)])
        )

        turns: list[AgentTurn] = []
        call_counter: Counter = Counter()
        stop_reason = "final_text"
        final_text = ""
        truncated = False

        for turn_i in range(self.max_turns):
            ctx.turn_index = turn_i
            # Cost guard (duck-typed AgentExecBudget): stop before a turn we can't afford.
            if budget is not None and budget.run_exhausted():
                stop_reason = "budget"
                truncated = True
                break
            try:
                result = await adapter.invoke(
                    messages, temperature=temperature, tools=specs, tool_choice=None
                )
            except Exception as exc:  # provider/network failure — record, don't crash the run
                turns.append(AgentTurn(role=TurnRole.MODEL, text=f"[invoke error: {exc}]"))
                stop_reason = "error"
                truncated = True
                break

            if budget is not None:
                budget.add(getattr(result.usage, "estimated_cost_usd", None) or 0.0)
            text = result.text
            tool_calls: list[ToolCallBlock] = result.tool_calls

            # M2: a turn with no tool call is terminal, regardless of provider stop_reason.
            if not tool_calls:
                final_text = text
                turns.append(AgentTurn(role=TurnRole.MODEL, text=text))
                stop_reason = "final_text"
                break

            call_records: list[ToolCallRecord] = []
            result_records: list[ToolResultRecord] = []
            assistant_content: list[Any] = []
            if text:
                assistant_content.append(TextBlock(text=text))

            for tc in tool_calls:
                assistant_content.append(tc)
                call_counter[(tc.name, json.dumps(tc.arguments, sort_keys=True))] += 1

                canonical = backend.canonical_name(tc.name) or tc.name
                is_forbidden = canonical in forbidden_set or tc.name in forbidden_set

                rec = ToolCallRecord(call_id=tc.id, tool_name=tc.name, arguments=dict(tc.arguments))
                if is_forbidden:
                    # H6: recorded-not-executed. The judge reads is_forbidden/executed from here.
                    rec.executed = False
                    rec.blocked_reason = "forbidden"
                    rec.is_forbidden = True
                    rec.backend_kind = ToolBackendKind.HONEYTOKEN
                    res = ToolResultRecord(
                        call_id=tc.id,
                        result=_DENIED,
                        backend_kind=ToolBackendKind.HONEYTOKEN,
                        provenance=ReturnProvenance(),
                    )
                else:
                    res = await backend.execute(tc, ctx)
                    rec.executed = True
                    rec.backend_kind = res.backend_kind
                call_records.append(rec)
                result_records.append(res)

            turns.append(AgentTurn(role=TurnRole.MODEL, text=text, tool_calls=call_records))
            turns.append(AgentTurn(role=TurnRole.TOOL, tool_results=result_records))

            # feed back to the model: assistant turn (text + tool calls), then tool results
            messages.append(CanonicalMessage(role=MessageRole.ASSISTANT, content=assistant_content))
            messages.append(
                CanonicalMessage(
                    role=MessageRole.TOOL,
                    content=[ToolResultBlock(tool_call_id=r.call_id, result=r.result) for r in result_records],
                )
            )

            # loop guard: any (name,args) signature seen >= threshold times (catches oscillation)
            if call_counter and max(call_counter.values()) >= self.loop_guard_threshold:
                stop_reason = "loop_guard"
                truncated = True
                break
        else:
            stop_reason = "max_turns"
            truncated = True

        header = DeterminismHeader(
            seed=ctx.seed,
            target_model=config.target_model,
            temperature=temperature,
            max_turns=self.max_turns,
            emulator_model=getattr(getattr(backend, "emulator", None), "model_name", None),
            harness_version=self.harness_version,
        )
        return AgentTranscript(
            transcript_id=_transcript_id(primitive_id, config.config_id, trial_index, seed),
            primitive_id=primitive_id,
            config_id=config.config_id,
            trial_index=trial_index,
            header=header,
            turns=turns,
            planted_secrets=ctx.planted_secrets,
            final_text=final_text,
            stop_reason=stop_reason,
            truncated=truncated,
        )


__all__ = ["AgentHarness"]
