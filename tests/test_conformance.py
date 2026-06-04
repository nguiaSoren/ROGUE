"""Tests for the provider-agnostic adapter conformance suite (``rogue.core.conformance``).

The suite proves the four-method I/O contract every :class:`TargetAdapter` must honor. These tests
prove (a) the reference :class:`MockAdapter` passes across config variations, (b) each method's types
and invariants hold when tested directly, and (c) the suite has *teeth* — deliberately non-conformant
adapters defined here are caught.
"""

from __future__ import annotations

import pytest

from rogue.adapters import AdapterConfig, MockAdapter, TargetAdapter
from rogue.core import (
    CanonicalMessage,
    InvocationResult,
    MessageRole,
    StopReason,
    TargetCapabilities,
    UsageMetrics,
)
from rogue.core.conformance import (
    ConformanceReport,
    assert_adapter_conformance,
    assert_conformant,
    run_conformance,
)


# --- MockAdapter passes conformance across config variations -----------------------------------


@pytest.mark.asyncio
async def test_mock_default_passes_conformance():
    report = await assert_adapter_conformance(MockAdapter())
    assert report.passed, str(report)
    # assert_conformant must not raise on a conformant adapter.
    returned = await assert_conformant(MockAdapter())
    assert returned.passed


@pytest.mark.asyncio
async def test_mock_text_only_capabilities_passes():
    text_only = TargetCapabilities(
        supports_text=True,
        supports_image=False,
        supports_audio=False,
        supports_tools=False,
        supports_system_prompt=True,
    )
    adapter = MockAdapter(AdapterConfig(model="mock/text-only", extra={"capabilities": text_only}))
    report = await assert_adapter_conformance(adapter)
    assert report.passed, str(report)


@pytest.mark.asyncio
async def test_mock_emit_tool_call_passes_and_has_tool_call():
    adapter = MockAdapter(AdapterConfig(model="mock/tools", extra={"emit_tool_call": True}))
    report = await assert_adapter_conformance(adapter)
    assert report.passed, str(report)

    result = await adapter.invoke([CanonicalMessage.user("call a tool please")])
    assert result.stop_reason is StopReason.TOOL_CALL
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "noop"


@pytest.mark.asyncio
async def test_mock_unhealthy_still_conformant():
    # healthcheck() returning False is valid — the contract is "returns a bool", not "is healthy".
    adapter = MockAdapter(AdapterConfig(model="mock/down", extra={"unhealthy": True}))
    assert await adapter.healthcheck() is False
    report = await assert_adapter_conformance(adapter)
    assert report.passed, str(report)


@pytest.mark.asyncio
async def test_run_conformance_factory():
    report = await run_conformance(lambda: MockAdapter())
    assert report.passed, str(report)


# --- each method tested directly: types + invariants -------------------------------------------


@pytest.mark.asyncio
async def test_capabilities_is_frozen_target_capabilities():
    caps = await MockAdapter().capabilities()
    assert isinstance(caps, TargetCapabilities)
    import dataclasses

    with pytest.raises(dataclasses.FrozenInstanceError):
        caps.supports_text = False  # type: ignore[misc]


@pytest.mark.asyncio
async def test_healthcheck_returns_bool():
    assert (await MockAdapter().healthcheck()) is True


@pytest.mark.asyncio
async def test_estimate_cost_usage_invariant():
    est = await MockAdapter().estimate_cost([CanonicalMessage.user("how much does this cost?")])
    assert isinstance(est, UsageMetrics)
    assert est.total_tokens == est.input_tokens + est.output_tokens
    assert est.input_tokens >= 0 and est.output_tokens >= 0
    assert est.estimated_cost_usd is None or (
        isinstance(est.estimated_cost_usd, float) and est.estimated_cost_usd >= 0
    )


@pytest.mark.asyncio
async def test_invoke_result_contract():
    result = await MockAdapter().invoke(
        [CanonicalMessage.system("be brief"), CanonicalMessage.user("hello")]
    )
    assert isinstance(result, InvocationResult)
    assert isinstance(result.content, list)
    assert isinstance(result.stop_reason, StopReason)
    assert isinstance(result.usage, UsageMetrics)
    assert result.usage.total_tokens == result.usage.input_tokens + result.usage.output_tokens
    assert isinstance(result.latency_ms, int) and result.latency_ms >= 0
    assert isinstance(result.raw_response, dict)
    assert isinstance(result.text, str)
    msg = result.to_message()
    assert isinstance(msg, CanonicalMessage)
    assert msg.role is MessageRole.ASSISTANT


# --- the suite has teeth: non-conformant adapters FAIL -----------------------------------------


class _BadInvokeAdapter(TargetAdapter):
    """invoke() returns a plain str instead of an InvocationResult — a contract violation."""

    async def invoke(self, messages, *, temperature=0.7, max_output_tokens=None, **kwargs):
        return "not an InvocationResult"  # type: ignore[return-value]

    async def capabilities(self) -> TargetCapabilities:
        return TargetCapabilities()

    async def healthcheck(self) -> bool:
        return True

    async def estimate_cost(self, messages, *, max_output_tokens=None) -> UsageMetrics:
        return UsageMetrics.from_io(1, 1)


class _BadCapabilitiesAdapter(TargetAdapter):
    """capabilities() returns a dict instead of a TargetCapabilities — a contract violation."""

    async def invoke(self, messages, *, temperature=0.7, max_output_tokens=None, **kwargs):
        return InvocationResult()

    async def capabilities(self):  # type: ignore[override]
        return {"supports_text": True}

    async def healthcheck(self) -> bool:
        return True

    async def estimate_cost(self, messages, *, max_output_tokens=None) -> UsageMetrics:
        return UsageMetrics.from_io(1, 1)


@pytest.mark.asyncio
async def test_bad_invoke_fails_conformance():
    adapter = _BadInvokeAdapter(AdapterConfig(model="bad/invoke"))
    report = await assert_adapter_conformance(adapter)
    assert not report.passed
    assert any(name == "invoke.type" for name, ok, _ in report.failures)
    with pytest.raises(AssertionError):
        await assert_conformant(adapter)


@pytest.mark.asyncio
async def test_bad_capabilities_fails_conformance():
    adapter = _BadCapabilitiesAdapter(AdapterConfig(model="bad/caps"))
    report = await assert_adapter_conformance(adapter)
    assert not report.passed
    assert any(name == "capabilities.type" for name, ok, _ in report.failures)
    with pytest.raises(AssertionError):
        await assert_conformant(adapter)


# --- report shape ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_records_all_checks():
    report = await assert_adapter_conformance(MockAdapter())
    assert isinstance(report, ConformanceReport)
    names = {name for name, _, _ in report.checks}
    # The four-method contract is represented.
    assert {
        "capabilities.type",
        "capabilities.frozen",
        "healthcheck.bool",
        "estimate_cost.type",
        "estimate_cost.usage_invariant",
        "invoke.type",
        "invoke.usage_invariant",
        "invoke.to_message",
        "invoke.max_output_tokens",
    } <= names
