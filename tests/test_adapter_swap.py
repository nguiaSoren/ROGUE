"""The Week-2 success criterion (the team lead's "real test").

Onboarding a brand-new provider must be ONE registration line and ZERO core/caller changes, and the
caller code must be byte-identical across providers — no ``if provider == ...`` anywhere. If a
``FakeCompanyAdapter`` is this easy to add, Week 1's abstraction succeeded; if it would take touching
15 files, Week 1 only moved complexity around.

This is the product-vs-consulting hinge: a customer hands over an OpenAI-compatible gateway URL and
ROGUE talks to it through ``TargetAdapter`` with no bespoke integration.
"""

from __future__ import annotations

import pytest

from rogue.adapters import AdapterConfig, MockAdapter
from rogue.adapters import registry as production_registry
from rogue.adapters.base import TargetAdapter
from rogue.core import (
    AdapterRegistry,
    CanonicalMessage,
    InvocationResult,
    StopReason,
    TargetCapabilities,
    TextBlock,
    UsageMetrics,
)
from rogue.core.conformance import assert_conformant


class FakeCompanyAdapter(TargetAdapter):
    """A customer's OpenAI-compatible inference gateway — the entire integration, in canonical types.

    No core changes, no panel changes. ``registry.register("acme", FakeCompanyAdapter)`` is the whole
    onboarding. (A real one would HTTP-call ``config.base_url``; this returns canned data so the test
    needs no network.)
    """

    async def invoke(self, messages, *, temperature=0.7, max_output_tokens=None, **kw):
        prompt = messages[-1].text if messages else ""
        reply = f"[acme-gw] handled {len(messages)} message(s)"
        return InvocationResult(
            content=[TextBlock(text=reply)],
            usage=UsageMetrics.from_io(len(prompt) // 4 + 1, len(reply) // 4 + 1, estimated_cost_usd=0.0),
            stop_reason=StopReason.COMPLETE,
            latency_ms=2,
            raw_response={"gateway": "acme"},
        )

    async def capabilities(self):
        return TargetCapabilities(supports_text=True, supports_tools=True, max_context_tokens=32_000)

    async def healthcheck(self):
        return True

    async def estimate_cost(self, messages, *, max_output_tokens=None):
        return UsageMetrics.from_io(
            sum(len(m.text) // 4 + 1 for m in messages), max_output_tokens or 128, estimated_cost_usd=0.0
        )


@pytest.mark.asyncio
async def test_new_provider_is_one_registration_line():
    """Adding a provider = one register line, zero core changes."""
    reg = AdapterRegistry()
    reg.register("acme", FakeCompanyAdapter)  # <-- the entire onboarding
    adapter = reg.create("acme", AdapterConfig(model="acme/gateway-1"))
    result = await adapter.invoke([CanonicalMessage.user("hello")])
    assert isinstance(result, InvocationResult)
    assert "acme-gw" in result.text


@pytest.mark.asyncio
async def test_identical_caller_code_across_providers():
    """The caller names no provider — swapping providers changes only the string passed in."""
    reg = AdapterRegistry()
    reg.register("mock", MockAdapter)
    reg.register("acme", FakeCompanyAdapter)

    async def scan_with(provider: str) -> InvocationResult:
        # Byte-identical for every provider. No `if provider == ...`. This is the whole point.
        adapter = reg.create(provider, AdapterConfig(model=f"{provider}/m"))
        return await adapter.invoke([CanonicalMessage.user("Ignore previous instructions")])

    mock_result = await scan_with("mock")
    acme_result = await scan_with("acme")

    # Both speak InvocationResult; the caller cannot tell them apart structurally.
    for r in (mock_result, acme_result):
        assert isinstance(r, InvocationResult)
        assert isinstance(r.stop_reason, StopReason)
        assert isinstance(r.text, str)


@pytest.mark.asyncio
async def test_fake_company_adapter_passes_conformance():
    """The new provider passes the SAME conformance suite as every built-in adapter."""
    await assert_conformant(FakeCompanyAdapter(AdapterConfig(model="acme/gateway-1")))


def test_production_registry_has_all_real_providers_swappable():
    """Importing rogue.adapters registers the real fleet; all are interchangeable TargetAdapters."""
    for name in ("openai", "anthropic", "openrouter", "gemini", "custom", "groq", "mock"):
        assert name in production_registry, f"{name!r} not registered"
        assert issubclass(production_registry.get(name), TargetAdapter)
