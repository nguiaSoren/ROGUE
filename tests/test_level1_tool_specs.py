"""Level 1 — bring-your-own tool schema. A config's ``tool_specs`` are presented to the model
verbatim (the real production surface), not synthesized from ``declared_tools`` names; returns stay
ROGUE-simulated. Forbidden is re-stamped by name."""

from __future__ import annotations

import pytest

from rogue.core.content_blocks import TextBlock
from rogue.core.invocation import InvocationResult, StopReason, UsageMetrics
from rogue.reproduce.agent.backends.hybrid import HybridBackend
from rogue.reproduce.agent.harness import AgentHarness
from rogue.schemas import AgentToolSpec, DeploymentConfig, ToolCategory


def _spec(name: str, cat: ToolCategory = ToolCategory.ACTION) -> AgentToolSpec:
    return AgentToolSpec(name=name, description=f"{name} tool", parameters={"type": "object"}, category=cat)


def test_hybrid_passthrough_uses_provided_specs_and_stamps_forbidden():
    provided = [_spec("send_corporate_email", ToolCategory.SINK), _spec("lookup_customer")]
    specs = HybridBackend().tool_specs(declared=[], forbidden=["send_corporate_email"], provided=provided)
    by_name = {s.name: s for s in specs}
    assert set(by_name) == {"send_corporate_email", "lookup_customer"}  # customer surface, verbatim
    assert by_name["send_corporate_email"].forbidden is True
    assert by_name["lookup_customer"].forbidden is False


def test_no_provided_specs_is_todays_synthesis_path():
    # A known honeytoken name still resolves from declared_tools when no provided specs are given.
    specs = HybridBackend().tool_specs(declared=["read_file"], forbidden=[], provided=None)
    assert any(s.name for s in specs)  # synthesized, non-empty


class _RecordingAdapter:
    """Captures the tool surface the harness offered the model, then ends the run (no tool call)."""

    def __init__(self) -> None:
        self.offered: list[str] = []

    async def invoke(self, messages, *, tools=None, **kwargs) -> InvocationResult:
        self.offered = [t.name for t in (tools or [])]
        return InvocationResult(content=[TextBlock(text="done")], usage=UsageMetrics(),
                                stop_reason=StopReason.COMPLETE)


@pytest.mark.asyncio
async def test_harness_offers_the_customers_real_surface():
    config = DeploymentConfig(
        config_id="cfg-byo-000001", customer_id="acme", name="byo", target_model="mock-model",
        system_prompt="agent", declared_tools=["ignored_name"],
        tool_specs=[_spec("send_corporate_email", ToolCategory.SINK), _spec("lookup_customer")],
    )
    rec = _RecordingAdapter()
    await AgentHarness().run(config, "task", primitive_id="prim-000001", adapter=rec)
    # the model was offered the customer's real tools, NOT the declared_tools name
    assert set(rec.offered) == {"send_corporate_email", "lookup_customer"}
    assert "ignored_name" not in rec.offered
