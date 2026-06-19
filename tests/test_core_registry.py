"""Unit tests for :mod:`rogue.core.registry` — AdapterRegistry.

The headline test is the Week-1 exit criterion: registering a brand-new provider
adapter takes ONE ``.register`` line and ZERO core changes, after which the registry
can ``create`` it and the generic engine can ``invoke`` it through the canonical interface.

All tests use a FRESH ``AdapterRegistry()`` — they never touch the global ``registry``.
"""

from __future__ import annotations

import pytest

from rogue.adapters import AdapterConfig, MockAdapter, TargetAdapter
from rogue.core.capabilities import TargetCapabilities
from rogue.core.errors import ValidationError
from rogue.core.invocation import InvocationResult, StopReason, UsageMetrics
from rogue.core.message import CanonicalMessage
from rogue.core.registry import AdapterRegistry, registry as global_registry
from rogue.core.content_blocks import TextBlock


# A throwaway adapter standing in for a future provider (xAI / Grok). It lives only in this
# test module — proving "add adapter = 1 register line, 0 core changes".
class FakeXAIAdapter(TargetAdapter):
    async def invoke(self, messages, *, temperature=0.7, max_output_tokens=None, **kwargs):
        last = next((m.text for m in reversed(messages) if m.text), "")
        return InvocationResult(
            content=[TextBlock(text=f"[xai] {last}")],
            usage=UsageMetrics.from_io(1, 1),
            stop_reason=StopReason.COMPLETE,
        )

    async def capabilities(self):
        return TargetCapabilities(supports_text=True)

    async def healthcheck(self):
        return True

    async def estimate_cost(self, messages, *, max_output_tokens=None):
        return UsageMetrics.from_io(1, 1)


@pytest.fixture
def reg():
    return AdapterRegistry()


# ---- the headline extensibility test -----------------------------------------------------------


@pytest.mark.asyncio
async def test_register_one_line_then_create_and_invoke(reg):
    # ONE line registers a brand-new provider.
    reg.register("xai", FakeXAIAdapter)

    adapter = reg.create("xai", AdapterConfig(model="xai/grok"))
    assert isinstance(adapter, FakeXAIAdapter)
    assert isinstance(adapter, TargetAdapter)

    result = await adapter.invoke([CanonicalMessage.user("hi")])
    assert isinstance(result, InvocationResult)
    assert result.text == "[xai] hi"
    assert result.stop_reason is StopReason.COMPLETE


# ---- register validation -----------------------------------------------------------------------


def test_register_returns_class(reg):
    assert reg.register("xai", FakeXAIAdapter) is FakeXAIAdapter


def test_register_empty_name_raises(reg):
    with pytest.raises(ValidationError):
        reg.register("", FakeXAIAdapter)


def test_register_non_subclass_raises(reg):
    with pytest.raises(ValidationError):
        reg.register("bad", str)


def test_register_non_class_raises(reg):
    instance = FakeXAIAdapter(AdapterConfig(model="xai/grok"))
    with pytest.raises(ValidationError):
        reg.register("bad", instance)  # an instance, not a class


def test_register_duplicate_raises(reg):
    reg.register("xai", FakeXAIAdapter)
    with pytest.raises(ValidationError):
        reg.register("xai", FakeXAIAdapter)


def test_register_duplicate_overwrite_succeeds(reg):
    reg.register("xai", FakeXAIAdapter)
    assert reg.register("xai", MockAdapter, overwrite=True) is MockAdapter
    assert reg.get("xai") is MockAdapter


# ---- get / create ------------------------------------------------------------------------------


def test_get_returns_class(reg):
    reg.register("xai", FakeXAIAdapter)
    assert reg.get("xai") is FakeXAIAdapter


def test_get_unknown_raises(reg):
    with pytest.raises(ValidationError):
        reg.get("nope")


def test_create_unknown_raises(reg):
    with pytest.raises(ValidationError):
        reg.create("nope", AdapterConfig(model="x/y"))


def test_create_instantiates_with_config(reg):
    reg.register("xai", FakeXAIAdapter)
    cfg = AdapterConfig(model="xai/grok")
    adapter = reg.create("xai", cfg)
    assert adapter.config is cfg
    assert adapter.model == "xai/grok"


# ---- decorator ---------------------------------------------------------------------------------


def test_decorator_registers(reg):
    @reg.decorator("dec")
    class _DecAdapter(FakeXAIAdapter):
        pass

    assert "dec" in reg
    assert reg.get("dec") is _DecAdapter


def test_decorator_returns_class(reg):
    decorate = reg.decorator("dec")
    out = decorate(FakeXAIAdapter)
    assert out is FakeXAIAdapter


def test_decorator_overwrite(reg):
    reg.register("dec", FakeXAIAdapter)

    @reg.decorator("dec", overwrite=True)
    class _Other(FakeXAIAdapter):
        pass

    assert reg.get("dec") is _Other


# ---- list / contains / len / unregister --------------------------------------------------------


def test_list_sorted(reg):
    reg.register("zeta", FakeXAIAdapter)
    reg.register("alpha", FakeXAIAdapter)
    reg.register("mid", FakeXAIAdapter)
    assert reg.list() == ["alpha", "mid", "zeta"]


def test_contains(reg):
    reg.register("xai", FakeXAIAdapter)
    assert "xai" in reg
    assert "nope" not in reg


def test_len(reg):
    assert len(reg) == 0
    reg.register("a", FakeXAIAdapter)
    reg.register("b", FakeXAIAdapter)
    assert len(reg) == 2


def test_unregister(reg):
    reg.register("xai", FakeXAIAdapter)
    reg.unregister("xai")
    assert "xai" not in reg
    assert len(reg) == 0


def test_unregister_unknown_is_noop(reg):
    reg.unregister("never-was-there")  # must not raise
    assert len(reg) == 0


# ---- the global default registry ---------------------------------------------------------------


def test_global_registry_has_mock():
    # importing rogue.adapters registers the built-in "mock" into the process-wide registry.
    assert "mock" in global_registry
    assert global_registry.get("mock") is MockAdapter
