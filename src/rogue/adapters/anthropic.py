"""The :class:`AnthropicAdapter` — ROGUE's native Anthropic Messages-API target adapter (Week-2).

A faithful migration of ``target_panel._call_anthropic`` behind the provider-neutral
:class:`TargetAdapter` boundary: it speaks :class:`CanonicalMessage` in and :class:`InvocationResult`
out, and is the *only* place Anthropic-specific request/response shapes live (architecture Rule 1).

Behavior preserved verbatim from the panel:
  - **System/chat split** — Anthropic takes the system prompt as a top-level ``system=`` kwarg, not as
    an inline ``{"role": "system"}`` turn. Leading/any SYSTEM messages are concatenated (double-newline)
    into ``system_prompt``; the rest become the ``messages`` payload. No non-system turn → ValidationError.
  - **Image block shape** — an :class:`ImageBlock` on a user turn becomes the Anthropic
    ``{"type": "image", "source": {"type": "base64", "media_type": ..., "data": ...}}`` block.
  - **Temperature clamp** — ``min(temperature, 1.0)`` (the SDK rejects higher temps on some Claude lines).
  - **max_tokens** — Anthropic *requires* it; default 4096 as the panel does.
  - **Retry + error mapping** — the inner call is wrapped with :data:`with_provider_retry`; a post-retry
    exception is translated via :func:`map_provider_exception` (RateLimitError → core RateLimitError,
    BadRequestError → ContentPolicyError, APIStatusError(5xx) → ProviderError).

Audio is a misroute (Anthropic takes no audio input): an :class:`AudioBlock` raises ValidationError.
"""

from __future__ import annotations

import os
from time import perf_counter
from typing import Any

from ..core import (
    AudioBlock,
    CanonicalMessage,
    ImageBlock,
    InvocationResult,
    MessageRole,
    StopReason,
    TextBlock,
    UsageMetrics,
)
from ..core.capabilities import TargetCapabilities
from ..core.errors import ValidationError
from . import model_specs
from ._provider_errors import map_provider_exception, with_provider_retry
from .base import AdapterConfig, TargetAdapter

_DEFAULT_MAX_TOKENS = 4096  # Anthropic Messages API requires an explicit max_tokens
_MAX_TEMP = 1.0  # the SDK rejects higher temps on some Claude lines (panel clamps to 1.0)


class AnthropicAdapter(TargetAdapter):
    """Native Anthropic Messages-API adapter. ``provider`` is ``anthropic``."""

    def __init__(self, config: AdapterConfig):
        super().__init__(config)
        self._owned_client: Any = None  # lazily-built real SDK client (None when injected)

    # --- wire identity --------------------------------------------------------------------------

    @property
    def _wire_model(self) -> str:
        """The bare model id Anthropic expects (strip a leading ``anthropic/`` provider prefix)."""
        return self.config.model.removeprefix("anthropic/")

    @property
    def _price_key(self) -> str:
        """The full provider-prefixed id used to look up pricing/capabilities in ``model_specs``."""
        return self.config.model

    # --- client lifecycle -----------------------------------------------------------------------

    def _client(self) -> Any:
        """Return the injected fake client (``config.extra["client"]``) or lazily build a real one."""
        injected = self.config.extra.get("client")
        if injected is not None:
            return injected
        if self._owned_client is None:
            from anthropic import AsyncAnthropic  # noqa: PLC0415

            self._owned_client = AsyncAnthropic(
                timeout=self.config.timeout_s, max_retries=self.config.max_retries
            )
        return self._owned_client

    async def aclose(self) -> None:
        # Only close a client we built ourselves; never close an injected (test) client.
        if self._owned_client is not None:
            close = getattr(self._owned_client, "close", None)
            if close is not None:
                await close()
            self._owned_client = None

    # --- translation ----------------------------------------------------------------------------

    @staticmethod
    def _to_anthropic_content(msg: CanonicalMessage) -> str | list[dict[str, Any]]:
        """Translate one non-system canonical message's content to the Anthropic content shape.

        Text-only → the plain joined string (the panel's text path). With an :class:`ImageBlock` →
        a list of parts: a ``{"type": "text", ...}`` part followed by one Anthropic ``image`` block
        per image. An :class:`AudioBlock` is a misroute (Anthropic takes no audio) → ValidationError.
        """
        images = msg.blocks_of(ImageBlock)
        if msg.blocks_of(AudioBlock):
            raise ValidationError(
                "anthropic dispatch: audio is not supported by Anthropic", provider="anthropic"
            )
        if not images:
            return msg.text
        parts: list[dict[str, Any]] = [{"type": "text", "text": msg.text}]
        for img in images:
            parts.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img.mime_type,
                        "data": img.to_base64(),
                    },
                }
            )
        return parts

    def _split_messages(
        self, messages: list[CanonicalMessage]
    ) -> tuple[str, list[dict[str, Any]]]:
        """Split canonical messages into ``(system_prompt, chat_messages)`` per the panel."""
        system_parts: list[str] = []
        chat_messages: list[dict[str, Any]] = []
        for m in messages:
            if m.role == MessageRole.SYSTEM:
                if m.text:
                    system_parts.append(m.text)
            else:
                chat_messages.append(
                    {"role": m.role.value, "content": self._to_anthropic_content(m)}
                )
        if not chat_messages:
            raise ValidationError(
                "anthropic dispatch: no non-system messages", provider="anthropic"
            )
        return "\n\n".join(system_parts), chat_messages

    # --- the four required methods --------------------------------------------------------------

    async def invoke(
        self,
        messages: list[CanonicalMessage],
        *,
        temperature: float = 0.7,
        max_output_tokens: int | None = None,
        **kwargs,
    ) -> InvocationResult:
        system_prompt, chat_messages = self._split_messages(messages)
        anthropic_temp = min(temperature, _MAX_TEMP)
        client = self._client()
        wire_model = self._wire_model
        max_tokens = max_output_tokens or _DEFAULT_MAX_TOKENS

        @with_provider_retry
        async def _do_call() -> Any:
            return await client.messages.create(
                model=wire_model,
                max_tokens=max_tokens,
                temperature=anthropic_temp,
                system=system_prompt or "",
                messages=chat_messages,
            )

        t0 = perf_counter()
        try:
            response = await _do_call()
        except Exception as e:  # noqa: BLE001 - translate or re-raise the post-retry exception
            mapped = map_provider_exception(e, provider="anthropic")
            if mapped is not None:
                raise mapped from e
            raise
        latency_ms = int((perf_counter() - t0) * 1000)

        usage = getattr(response, "usage", None)
        tokens_in = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
        tokens_out = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0

        content = "".join(
            getattr(block, "text", "")
            for block in (getattr(response, "content", None) or [])
            if getattr(block, "type", None) == "text"
        )
        stop_reason = StopReason.from_provider(getattr(response, "stop_reason", None))

        dump = getattr(response, "model_dump", None)
        raw_response = dump() if callable(dump) else {}

        return InvocationResult(
            content=[TextBlock(text=content)],
            usage=UsageMetrics.from_io(
                tokens_in,
                tokens_out,
                estimated_cost_usd=model_specs.estimate_cost(self._price_key, tokens_in, tokens_out),
            ),
            stop_reason=stop_reason,
            latency_ms=latency_ms,
            raw_response=raw_response if isinstance(raw_response, dict) else {},
        )

    async def capabilities(self) -> TargetCapabilities:
        return model_specs.capabilities_for(
            self._price_key, supports_tools=True, supports_function_calling=True
        )

    async def healthcheck(self) -> bool:
        """Best-effort: True iff an API key is resolvable. Anthropic has no cheap list endpoint."""
        return bool(self.config.api_key or os.environ.get("ANTHROPIC_API_KEY"))

    async def estimate_cost(
        self, messages: list[CanonicalMessage], *, max_output_tokens: int | None = None
    ) -> UsageMetrics:
        input_tokens = sum(len(m.text) // 4 for m in messages)  # incl. system turns
        output_tokens = max_output_tokens or 512
        cost = model_specs.estimate_cost(self._price_key, input_tokens, output_tokens)
        return UsageMetrics.from_io(input_tokens, output_tokens, estimated_cost_usd=cost)


__all__ = ["AnthropicAdapter"]
