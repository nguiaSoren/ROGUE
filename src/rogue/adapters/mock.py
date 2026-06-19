"""Reference :class:`MockAdapter` — a fully-conformant adapter that calls no provider.

It exists to (a) prove the abstraction is implementable end-to-end, (b) be the conformance-suite
fixture, and (c) back offline tests/demos. Deterministic: no network, no randomness, no clock. Its
behavior is steerable via ``AdapterConfig.extra`` so tests can exercise capabilities variation and
every error path without a real provider.

``extra`` knobs:
  - ``capabilities``: a :class:`TargetCapabilities` to return (else a sensible text+image+tools default)
  - ``fail``: one of ``rate_limit|auth|timeout|provider|content_policy|validation`` → ``invoke`` raises
  - ``unhealthy``: truthy → ``healthcheck`` returns False
  - ``emit_tool_call``: truthy → response includes a :class:`ToolCallBlock`
  - ``reply``: override the canned reply text
"""

from __future__ import annotations

from ..core.capabilities import TargetCapabilities
from ..core.content_blocks import TextBlock, ToolCallBlock
from ..core.errors import (
    AuthenticationError,
    ContentPolicyError,
    ProviderError,
    RateLimitError,
    TimeoutError,
    ValidationError,
)
from ..core.invocation import InvocationResult, StopReason, UsageMetrics
from ..core.message import CanonicalMessage
from .base import AdapterConfig, TargetAdapter

# Refusal triggers — let tests deterministically drive a SAFETY stop reason via message content.
_REFUSAL_TRIGGERS = ("i can't help", "i cannot help", "<refuse>")

_FAIL_MAP = {
    "rate_limit": lambda: RateLimitError("mock rate limit", provider="mock", status_code=429, retry_after=1.0),
    "auth": lambda: AuthenticationError("mock auth failure", provider="mock", status_code=401),
    "timeout": lambda: TimeoutError("mock timeout", provider="mock"),
    "provider": lambda: ProviderError("mock upstream error", provider="mock", status_code=503),
    "content_policy": lambda: ContentPolicyError("mock content-policy block", provider="mock", status_code=400),
    "validation": lambda: ValidationError("mock bad request", provider="mock", status_code=400),
}

_DEFAULT_CAPABILITIES = TargetCapabilities(
    supports_text=True,
    supports_image=True,
    supports_audio=False,
    supports_tools=True,
    supports_system_prompt=True,
    supports_json_mode=True,
    supports_function_calling=True,
    max_context_tokens=128_000,
    max_output_tokens=4096,
    max_temperature=2.0,
)

# Mock price: $/million tokens (input, output). Arbitrary but stable.
_PRICE_IN, _PRICE_OUT = 1.0, 3.0


def _estimate_tokens(text: str) -> int:
    # ~4 chars/token, a deterministic rough estimate (good enough for a mock).
    return max(1, len(text) // 4)


class MockAdapter(TargetAdapter):
    """A conformant, deterministic, network-free adapter."""

    def __init__(self, config: AdapterConfig | None = None):
        super().__init__(config or AdapterConfig(model="mock/mock-1"))

    async def invoke(
        self,
        messages: list[CanonicalMessage],
        *,
        temperature: float = 0.7,
        max_output_tokens: int | None = None,
        **kwargs,
    ) -> InvocationResult:
        fail = self.config.extra.get("fail")
        if fail:
            if fail not in _FAIL_MAP:
                raise ValidationError(f"unknown mock fail mode: {fail!r}")
            raise _FAIL_MAP[fail]()

        if not messages:
            raise ValidationError("invoke requires at least one message", provider="mock")

        last_user_text = next(
            (m.text for m in reversed(messages) if m.text), ""
        )
        caps = await self.capabilities()
        clamped = caps.clamp_temperature(temperature)

        if any(t in last_user_text.lower() for t in _REFUSAL_TRIGGERS):
            reply = "I can't help with that."
            stop = StopReason.SAFETY
        else:
            reply = self.config.extra.get("reply") or f"[mock:{self.model}] ack: {last_user_text[:200]}"
            stop = StopReason.COMPLETE

        content: list = [TextBlock(text=reply)]
        if self.config.extra.get("emit_tool_call"):
            content.append(ToolCallBlock(id="call_mock_1", name="noop", arguments={}))
            stop = StopReason.TOOL_CALL

        input_tokens = sum(_estimate_tokens(m.text) for m in messages)
        output_tokens = _estimate_tokens(reply)
        if max_output_tokens is not None and output_tokens >= max_output_tokens:
            output_tokens = max_output_tokens
            stop = StopReason.LENGTH
        cost = (input_tokens * _PRICE_IN + output_tokens * _PRICE_OUT) / 1_000_000

        return InvocationResult(
            content=content,
            usage=UsageMetrics.from_io(input_tokens, output_tokens, estimated_cost_usd=cost),
            stop_reason=stop,
            latency_ms=1,
            raw_response={
                "mock": True,
                "model": self.model,
                "n_messages": len(messages),
                "temperature": clamped,
            },
        )

    async def capabilities(self) -> TargetCapabilities:
        caps = self.config.extra.get("capabilities")
        return caps if isinstance(caps, TargetCapabilities) else _DEFAULT_CAPABILITIES

    async def healthcheck(self) -> bool:
        return not self.config.extra.get("unhealthy", False)

    async def estimate_cost(
        self, messages: list[CanonicalMessage], *, max_output_tokens: int | None = None
    ) -> UsageMetrics:
        input_tokens = sum(_estimate_tokens(m.text) for m in messages)
        output_tokens = max_output_tokens or 256  # assume a typical completion when none specified
        cost = (input_tokens * _PRICE_IN + output_tokens * _PRICE_OUT) / 1_000_000
        return UsageMetrics.from_io(input_tokens, output_tokens, estimated_cost_usd=cost)


__all__ = ["MockAdapter"]
