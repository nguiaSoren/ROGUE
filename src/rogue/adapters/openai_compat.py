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

Tool-calling: the agent execution harness (docs/v2/agent_harness/DESIGN.md) offers targets a REAL
function-calling surface. When ``invoke`` is given ``tools``, each :class:`AgentToolSpec` is translated
via :meth:`AgentToolSpec.provider_schema` into the OpenAI ``{"type":"function","function":{...}}`` wire
shape; the response's ``message.tool_calls`` are parsed back into :class:`ToolCallBlock`s. When
``tools`` is ``None``/empty the request body is byte-identical to a no-tools call.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from ..core import (
    AudioBlock,
    CanonicalMessage,
    ContentBlock,
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

if TYPE_CHECKING:
    from ..schemas import AgentToolSpec

# Marker key stashed in ``ToolCallBlock.arguments`` when the provider returned tool-call arguments
# that were not a valid JSON object. We keep ``arguments`` a plain dict (no OpenAI-specific sentinel
# type crossing the seam) and record the raw payload under this key, so the harness can DETECT the
# malformed call (``MALFORMED_ARGS_KEY in block.arguments``) and inspect the raw string, rather than
# silently treating it as an empty-args call.
MALFORMED_ARGS_KEY = "_malformed"


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

        Tool blocks close the multi-turn agent loop: a :class:`ToolCallBlock` is emitted as an
        ``assistant`` ``tool_calls`` entry, and a :class:`ToolResultBlock` as a separate
        ``{"role": "tool", "tool_call_id", ...}`` message. A message carrying ONLY tool results is
        fully emitted by the tool-result loop and MUST NOT fall through to the text branch (which
        would append a spurious ``{"role": "tool", "content": ""}`` with no ``tool_call_id`` — an
        OpenAI 400 on every feedback turn).
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

            # A message carrying only tool results is fully emitted above; don't fall through to the
            # text branch (mirrors the tool_calls `continue`) — it would append an empty, id-less
            # {"role": "tool", "content": ""} that OpenAI rejects with a 400 (M1).
            if tool_results and not (joined_text or images or audios or tool_calls):
                continue

            # ToolCallBlocks attach to an assistant message as `tool_calls`.
            if tool_calls:
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

    @staticmethod
    def _tools_to_openai(tools: list[AgentToolSpec]) -> list[dict[str, Any]]:
        """Translate provider-neutral :class:`AgentToolSpec`s to OpenAI ``tools`` wire dicts.

        Only :meth:`AgentToolSpec.provider_schema` (``{name, description, parameters}``) crosses the
        seam — harness-internal fields (``forbidden``/``backend_kind``) never reach the provider.
        """
        wire: list[dict[str, Any]] = []
        for spec in tools:
            fn = spec.provider_schema()
            wire.append(
                {
                    "type": "function",
                    "function": {
                        "name": fn["name"],
                        "description": fn["description"],
                        "parameters": fn["parameters"],
                    },
                }
            )
        return wire

    @staticmethod
    def _parse_tool_calls(message: Any) -> list[ToolCallBlock]:
        """Parse an OpenAI response message's ``tool_calls`` into :class:`ToolCallBlock`s.

        Each entry's ``function.arguments`` is a JSON *string*; we decode it to a dict. If it is not
        valid JSON (or not a JSON object), we record it under :data:`MALFORMED_ARGS_KEY` instead of
        leaking an OpenAI-specific sentinel up the stack (M10).
        """
        raw_calls = getattr(message, "tool_calls", None) or []
        blocks: list[ToolCallBlock] = []
        for tc in raw_calls:
            fn = getattr(tc, "function", None)
            name = getattr(fn, "name", None) or ""
            raw_args = getattr(fn, "arguments", None) or ""
            try:
                parsed = json.loads(raw_args) if raw_args else {}
            except (ValueError, TypeError):
                parsed = None
            arguments = parsed if isinstance(parsed, dict) else {MALFORMED_ARGS_KEY: raw_args}
            blocks.append(
                ToolCallBlock(id=getattr(tc, "id", None) or "", name=name, arguments=arguments)
            )
        return blocks

    # ----- Public API -------------------------------------------------------------------------

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
        client = self._client()
        msgs = self._to_openai_messages(messages)
        wire_model = self._wire_model
        # Only build the tools payload when tools are actually offered — an empty/None list must
        # leave the request body byte-identical to a no-tools call (shared contract §1).
        wire_tools = self._tools_to_openai(tools) if tools else None

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
            if wire_tools:
                create_kwargs["tools"] = wire_tools
                # OpenAI accepts "auto"/"none"/"required" (or a specific function); pass through
                # only when the caller set it AND we are actually sending tools.
                if tool_choice is not None:
                    create_kwargs["tool_choice"] = tool_choice
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
        tool_call_blocks: list[ToolCallBlock] = []
        choices = getattr(response, "choices", None)
        if choices:
            message = choices[0].message
            content_text = getattr(message, "content", None) or ""
            finish_reason = getattr(choices[0], "finish_reason", None)
            tool_call_blocks = self._parse_tool_calls(message)

        # Text first, then tool calls, in order. Preserve the legacy no-tools shape exactly: a
        # response with no tool calls always yields a single (possibly empty) TextBlock; a response
        # with tool calls omits the empty TextBlock and carries only the tool-call blocks.
        blocks: list[ContentBlock] = []
        if content_text or not tool_call_blocks:
            blocks.append(TextBlock(text=content_text))
        blocks.extend(tool_call_blocks)

        try:
            raw = response.model_dump()
        except Exception:  # noqa: BLE001 - fake/old clients may not implement model_dump
            raw = {}

        return InvocationResult(
            content=blocks,
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
        # Tool support is a per-model fact, not a blanket provider claim — delegate to the spec
        # table so unknown models correctly report False (fixes the old hardcoded over-claim).
        tools_ok = model_specs.supports_tools(self.model)
        return model_specs.capabilities_for(
            self._price_key,
            supports_tools=tools_ok,
            supports_json_mode=True,
            supports_function_calling=tools_ok,
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


__all__ = ["OpenAICompatAdapter", "MALFORMED_ARGS_KEY"]
