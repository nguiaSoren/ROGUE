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
from dataclasses import replace
from time import perf_counter
from typing import TYPE_CHECKING, Any

from ..core import (
    AudioBlock,
    CanonicalMessage,
    ContentBlock,
    ImageBlock,
    InvocationResult,
    MessageRole,
    StopReason,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    UsageMetrics,
)
from ..core.capabilities import TargetCapabilities
from ..core.errors import ValidationError
from ..core.prefill import split_trailing_prefill
from . import model_specs
from ._provider_errors import map_provider_exception, with_provider_retry
from .base import AdapterConfig, TargetAdapter

if TYPE_CHECKING:
    from ..schemas import AgentToolSpec

_DEFAULT_MAX_TOKENS = 4096  # Anthropic Messages API requires an explicit max_tokens
_MAX_TEMP = 1.0  # the SDK rejects higher temps on some Claude lines (panel clamps to 1.0)


class AnthropicAdapter(TargetAdapter):
    """Native Anthropic Messages-API adapter. ``provider`` is ``anthropic``."""

    # Anthropic honors a trailing assistant turn as a NATIVE response-prefill: the reply continues
    # from it. So a planted seed passes through as-is (no in-band fold); we stitch it back onto the
    # returned continuation below so the caller sees the full ``prefix + continuation`` answer.
    supports_native_prefill: bool = True

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
        per image. A :class:`ToolCallBlock` (assistant tool call) → an Anthropic ``tool_use`` part;
        a :class:`ToolResultBlock` (fed back on a ``tool``/``user`` turn) → a ``tool_result`` part
        (Anthropic has no ``tool`` role — see :meth:`_split_messages`). An :class:`AudioBlock` is a
        misroute (Anthropic takes no audio) → ValidationError.
        """
        if msg.blocks_of(AudioBlock):
            raise ValidationError(
                "anthropic dispatch: audio is not supported by Anthropic", provider="anthropic"
            )
        images = msg.blocks_of(ImageBlock)
        tool_calls = msg.blocks_of(ToolCallBlock)
        tool_results = msg.blocks_of(ToolResultBlock)
        if not (images or tool_calls or tool_results):
            return msg.text
        parts: list[dict[str, Any]] = []
        # Text leads the parts list. Preserve the image path's historical shape (a text part is
        # always present for an image turn, even when empty); a pure tool turn carries no text part.
        if msg.text or images:
            parts.append({"type": "text", "text": msg.text})
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
        for call in tool_calls:
            parts.append(
                {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
            )
        for res in tool_results:
            parts.append(
                {"type": "tool_result", "tool_use_id": res.tool_call_id, "content": res.result}
            )
        return parts

    @staticmethod
    def _to_anthropic_tool(spec: AgentToolSpec) -> dict[str, Any]:
        """Translate one provider-neutral tool spec to the Anthropic tool wire shape.

        Only :meth:`AgentToolSpec.provider_schema` (``{name, description, parameters}``) crosses the
        seam; Anthropic names the argument schema ``input_schema`` (OpenAI calls it ``parameters``).
        """
        schema = spec.provider_schema()
        return {
            "name": schema["name"],
            "description": schema["description"],
            "input_schema": schema["parameters"],
        }

    @staticmethod
    def _to_anthropic_tool_choice(tool_choice: str | None) -> dict[str, Any] | None:
        """Map the neutral ``tool_choice`` string to Anthropic's ``{"type": ...}`` object.

        ``None`` → omit (Anthropic defaults to ``auto`` when tools are present). ``"auto"``,
        ``"any"``/``"required"``, and ``"none"`` map to the matching ``type``; any other value is
        treated as a specific tool name → ``{"type": "tool", "name": <value>}``.
        """
        if tool_choice is None:
            return None
        choice = tool_choice.strip()
        if choice == "auto":
            return {"type": "auto"}
        if choice in ("any", "required"):
            return {"type": "any"}
        if choice == "none":
            return {"type": "none"}
        return {"type": "tool", "name": choice}

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
                # Anthropic has no `tool` role: a tool result rides a `user` turn as a
                # `tool_result` content block (H8). Every other role passes through verbatim.
                role = "user" if m.role == MessageRole.TOOL else m.role.value
                chat_messages.append(
                    {"role": role, "content": self._to_anthropic_content(m)}
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
        tools: list[AgentToolSpec] | None = None,
        tool_choice: str | None = None,
        **kwargs,
    ) -> InvocationResult:
        # Response-prefill: a trailing text-only assistant turn is passed NATIVELY (it flows through
        # _split_messages as the final assistant chat turn) — Anthropic continues from it. We capture
        # the seed text (detection only; the turn is NOT stripped) to stitch back onto the returned
        # continuation, so the caller/judge sees prefix+continuation as one answer. Skipped when tools
        # are offered (agent tool loop territory, not a prefill seed).
        prefill_seed: str | None = None
        if not tools:
            _, prefill_seed = split_trailing_prefill(messages)
        system_prompt, chat_messages = self._split_messages(messages)
        anthropic_temp = min(temperature, _MAX_TEMP)
        client = self._client()
        wire_model = self._wire_model
        max_tokens = max_output_tokens or _DEFAULT_MAX_TOKENS

        # Tool params are added ONLY when tools are offered, so a no-tools call builds a request
        # byte-identical to the pre-harness one (contract §1). ``tool_choice`` is omitted (None)
        # ⇒ Anthropic's default ``auto`` when a tool set is present.
        extra_params: dict[str, Any] = {}
        if tools is not None:
            extra_params["tools"] = [self._to_anthropic_tool(t) for t in tools]
            choice = self._to_anthropic_tool_choice(tool_choice)
            if choice is not None:
                extra_params["tool_choice"] = choice

        @with_provider_retry
        async def _do_call() -> Any:
            return await client.messages.create(
                model=wire_model,
                max_tokens=max_tokens,
                temperature=anthropic_temp,
                system=system_prompt or "",
                messages=chat_messages,
                **extra_params,
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

        # Preserve provider block order: each Anthropic ``text`` block → a TextBlock, each
        # ``tool_use`` block → a ToolCallBlock, interleaved exactly as returned (contract §3).
        content_blocks: list[ContentBlock] = []
        reasoning_parts: list[str] = []  # Anthropic extended-thinking blocks — the reasoning trace
        for block in getattr(response, "content", None) or []:
            btype = getattr(block, "type", None)
            if btype == "text":
                content_blocks.append(TextBlock(text=getattr(block, "text", "") or ""))
            elif btype in ("thinking", "redacted_thinking"):
                reasoning_parts.append(getattr(block, "thinking", "") or "")
            elif btype == "tool_use":
                content_blocks.append(
                    ToolCallBlock(
                        id=getattr(block, "id", "") or "",
                        name=getattr(block, "name", "") or "",
                        arguments=getattr(block, "input", None) or {},
                    )
                )
        stop_reason = StopReason.from_provider(getattr(response, "stop_reason", None))

        # Native prefill: Anthropic returns only the continuation, so prepend the seed onto the first
        # text block (or insert one) — the caller sees the full ``prefix + continuation`` reply.
        if prefill_seed:
            if content_blocks and isinstance(content_blocks[0], TextBlock):
                content_blocks[0] = TextBlock(text=prefill_seed + content_blocks[0].text)
            else:
                content_blocks.insert(0, TextBlock(text=prefill_seed))

        dump = getattr(response, "model_dump", None)
        raw_response = dump() if callable(dump) else {}

        return InvocationResult(
            content=content_blocks,
            reasoning="\n".join(p for p in reasoning_parts if p),
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
        # supports_tools is NOT hardcoded — it delegates to the model spec so a Claude line that
        # doesn't honor tool calling is never over-claimed (contract §4).
        tools_ok = model_specs.supports_tools(self._price_key)
        caps = model_specs.capabilities_for(
            self._price_key, supports_tools=tools_ok, supports_function_calling=tools_ok
        )
        return replace(caps, supports_native_prefill=self.supports_native_prefill)

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
