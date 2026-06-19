"""Shared OpenAI chat-completions logic — the base every OpenAI-compatible adapter builds on.

This is the Week-2 port of ``target_panel._call_openai_compat`` / ``_do_openai_compat_call``
into the :class:`TargetAdapter` shape. One class, :class:`OpenAICompatAdapter`, encapsulates the
wire-format translation, the retried provider call, response parsing, and cost/capability lookups
that OpenAI proper, Groq, OpenRouter, and any customer's OpenAI-compatible gateway all share.

Subclasses change only four facts (endpoint, api-key source, the WIRE model id sent to the API, and
the PRICE key used for cost lookup), via the ``_base_url`` / ``_api_key`` / ``_wire_model`` /
``_price_key`` instance attributes set in ``__init__``. Everything below the seam — message
translation, retry, error mapping — is provider-neutral and lives here once.

Wire-format note: ``_to_openai_messages`` reproduces the panel's exact shape — a plain ``content``
STRING for text-only turns (the legacy ``{role, content:str}`` form the panel sent), and a content
LIST (text part first, then media parts) only when an image/audio/tool block is present. See
``target_panel._attach_image_to_last_user`` / ``_attach_audio_to_last_user`` for the original.
"""

from __future__ import annotations

import time
from typing import Any

from ..core import (
    AudioBlock,
    CanonicalMessage,
    ImageBlock,
    InvocationResult,
    StopReason,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    UsageMetrics,
)
from ..core.capabilities import TargetCapabilities
from . import model_specs
from ._provider_errors import map_provider_exception, with_provider_retry
from .base import AdapterConfig, TargetAdapter


class OpenAICompatAdapter(TargetAdapter):
    """Base adapter for any OpenAI chat-completions-compatible endpoint.

    Subclasses set ``self._base_url`` / ``self._api_key`` / ``self._wire_model`` / ``self._price_key``
    in ``__init__`` (after ``super().__init__``); the provider slug comes from the
    :attr:`TargetAdapter.provider` property unless a subclass overrides it.
    """

    # The chat-completions param for the output-token cap. OpenAI's own gpt-5.x rejects ``max_tokens``
    # and requires ``max_completion_tokens``; OpenRouter/Groq/most compat endpoints still take
    # ``max_tokens``. The OpenAI adapter overrides this; everyone else keeps the default.
    _max_tokens_param: str = "max_tokens"

    def __init__(self, config: AdapterConfig):
        super().__init__(config)
        # Sensible defaults; concrete subclasses override these in their own __init__.
        self._base_url: str | None = config.base_url
        self._api_key: str | None = config.api_key
        self._wire_model: str = config.model
        self._price_key: str = config.model
        self._owned_client: Any | None = None  # lazily-built client we are responsible for closing

    # ----- Client -----------------------------------------------------------------------------

    def _client(self) -> Any:
        """Return the injected fake client (``config.extra['client']``) or a cached real one.

        The real client is built lazily so importing this module never requires an API key or the
        ``openai`` package; tests inject a fake via ``AdapterConfig(extra={'client': fake})``.
        """
        injected = self.config.extra.get("client")
        if injected is not None:
            return injected
        if self._owned_client is None:
            from openai import AsyncOpenAI  # noqa: PLC0415 - lazy: keep import optional

            kwargs: dict[str, Any] = {
                "base_url": self._base_url,
                "api_key": self._api_key,
                "timeout": self.config.timeout_s,
                "max_retries": self.config.max_retries,
            }
            headers = self.config.extra.get("headers")
            if headers:
                kwargs["default_headers"] = headers
            self._owned_client = AsyncOpenAI(**kwargs)
        return self._owned_client

    async def aclose(self) -> None:
        """Close a self-built client. No-op for an injected (caller-owned) client."""
        client = self._owned_client
        if client is None:
            return
        close_fn = getattr(client, "close", None)
        if close_fn is not None:
            try:
                result = close_fn()
                if result is not None and hasattr(result, "__await__"):
                    await result
            except Exception:  # pragma: no cover - cleanup must never raise
                pass
        self._owned_client = None

    # ----- Message translation ----------------------------------------------------------------

    def _to_openai_messages(self, messages: list[CanonicalMessage]) -> list[dict[str, Any]]:
        """Translate canonical messages to OpenAI chat-completions wire dicts.

        Matches the panel's format exactly: a text-only message becomes ``{role, content: <str>}``
        (plain string), while a message carrying image/audio becomes ``{role, content: [parts...]}``
        with the text part first (only if there is text) and one media part per block.

        Tool blocks are translated best-effort (ROGUE does not send tools to targets): a
        :class:`ToolCallBlock` is emitted as an ``assistant`` ``tool_calls`` entry and a
        :class:`ToolResultBlock` as a separate ``{"role": "tool", ...}`` message.
        """
        out: list[dict[str, Any]] = []
        for m in messages:
            role = m.role.value
            text_parts = [b.text for b in m.content if isinstance(b, TextBlock)]
            joined_text = "\n".join(text_parts)
            images = [b for b in m.content if isinstance(b, ImageBlock)]
            audios = [b for b in m.content if isinstance(b, AudioBlock)]
            tool_calls = [b for b in m.content if isinstance(b, ToolCallBlock)]
            tool_results = [b for b in m.content if isinstance(b, ToolResultBlock)]

            # ToolResultBlocks become standalone {"role": "tool", ...} messages.
            for tr in tool_results:
                out.append(
                    {"role": "tool", "tool_call_id": tr.tool_call_id, "content": tr.result}
                )

            # ToolCallBlocks attach to an assistant message as `tool_calls`.
            if tool_calls:
                import json  # noqa: PLC0415 - only needed on the rare tool-call path

                entry: dict[str, Any] = {
                    "role": role,
                    "content": joined_text or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in tool_calls
                    ],
                }
                out.append(entry)
                continue

            if images or audios:
                content: list[dict[str, Any]] = []
                if joined_text:
                    content.append({"type": "text", "text": joined_text})
                for img in images:
                    url = img.url if img.url is not None else (
                        f"data:{img.mime_type};base64,{img.to_base64()}"
                    )
                    content.append({"type": "image_url", "image_url": {"url": url}})
                for aud in audios:
                    fmt = aud.mime_type.split("/", 1)[1] if "/" in aud.mime_type else aud.mime_type
                    if fmt == "mpeg":
                        fmt = "mp3"
                    content.append(
                        {
                            "type": "input_audio",
                            "input_audio": {"data": aud.to_base64(), "format": fmt},
                        }
                    )
                out.append({"role": role, "content": content})
            else:
                # Text-only: plain string content (legacy panel shape).
                out.append({"role": role, "content": joined_text})
        return out

    # ----- Public API -------------------------------------------------------------------------

    async def invoke(
        self,
        messages: list[CanonicalMessage],
        *,
        temperature: float = 0.7,
        max_output_tokens: int | None = None,
        **kwargs,
    ) -> InvocationResult:
        client = self._client()
        msgs = self._to_openai_messages(messages)
        wire_model = self._wire_model

        @with_provider_retry
        async def _do_call() -> Any:
            create_kwargs: dict[str, Any] = {
                "model": wire_model,
                "messages": msgs,
                "temperature": temperature,
            }
            # The panel omits the cap entirely when None — do NOT pass it. The param name is
            # provider-specific (OpenAI gpt-5.x wants max_completion_tokens; see _max_tokens_param).
            if max_output_tokens:
                create_kwargs[self._max_tokens_param] = max_output_tokens
            return await client.chat.completions.create(**create_kwargs)

        t0 = time.perf_counter()
        try:
            response = await _do_call()
        except Exception as e:  # noqa: BLE001 - translate then re-raise
            mapped = map_provider_exception(e, provider=self.provider)
            if mapped is not None:
                raise mapped from e
            raise
        latency_ms = int((time.perf_counter() - t0) * 1000)

        usage = getattr(response, "usage", None)
        tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
        tokens_out = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0

        content_text = ""
        finish_reason: str | None = None
        choices = getattr(response, "choices", None)
        if choices:
            message = choices[0].message
            content_text = getattr(message, "content", None) or ""
            finish_reason = getattr(choices[0], "finish_reason", None)

        try:
            raw = response.model_dump()
        except Exception:  # noqa: BLE001 - fake/old clients may not implement model_dump
            raw = {}

        return InvocationResult(
            content=[TextBlock(text=content_text)],
            usage=UsageMetrics.from_io(
                tokens_in,
                tokens_out,
                estimated_cost_usd=model_specs.estimate_cost(
                    self._price_key, tokens_in, tokens_out
                ),
            ),
            stop_reason=StopReason.from_provider(finish_reason),
            latency_ms=latency_ms,
            raw_response=raw if isinstance(raw, dict) else {},
        )

    async def capabilities(self) -> TargetCapabilities:
        return model_specs.capabilities_for(
            self._price_key,
            supports_tools=True,
            supports_json_mode=True,
            supports_function_calling=True,
        )

    async def healthcheck(self) -> bool:
        try:
            await self._client().models.list()
            return True
        except Exception:  # noqa: BLE001 - a clean "down" must not raise
            return False

    async def estimate_cost(
        self, messages: list[CanonicalMessage], *, max_output_tokens: int | None = None
    ) -> UsageMetrics:
        tokens_in = sum(max(1, len(m.text) // 4) for m in messages)
        tokens_out = max_output_tokens or 256
        cost = model_specs.estimate_cost(self._price_key, tokens_in, tokens_out)
        return UsageMetrics.from_io(tokens_in, tokens_out, estimated_cost_usd=cost)


__all__ = ["OpenAICompatAdapter"]
