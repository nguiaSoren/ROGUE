"""The :class:`GeminiAdapter` — ROGUE's native google-genai target adapter (Week-2, forward-looking).

Unlike :class:`AnthropicAdapter`, this adapter is **not** used by the current reproduction panel —
the panel routes ``google/`` models through OpenRouter's OpenAI-compatible surface. This is the native
path for when ROGUE talks to Gemini directly via the ``google-genai`` SDK, kept behind the same
provider-neutral :class:`TargetAdapter` boundary (architecture Rule 1): :class:`CanonicalMessage` in,
:class:`InvocationResult` out, with all Gemini-specific shapes confined here.

Design decisions (documented per the brief):
  - **Message mapping** — canonical messages → Gemini ``contents``: a list of
    ``{"role": "user"|"model", "parts": [...]}``. ASSISTANT → ``"model"``; USER → ``"user"``.
    An :class:`ImageBlock` becomes an ``{"inline_data": {"mime_type": ..., "data": <base64>}}`` part.
  - **System prompt** — modeled via the SDK's ``system_instruction`` config field (the idiomatic
    google-genai surface) rather than folded into a user turn, so the chat history stays clean.
    Multiple SYSTEM messages are concatenated double-newline. (We pass it through the ``config`` dict
    handed to ``generate_content``; a fake client in tests can capture it.)
  - **Async surface** — ``client.aio.models.generate_content(model=, contents=, config=)``.
  - **Error mapping** — :func:`map_provider_exception` only recognizes OpenAI/Anthropic/httpx
    exceptions (returns None for a Gemini-native error). So for Gemini we try the canonical mapping
    first, and for any *unrecognized* provider exception we wrap it in a core
    :class:`~rogue.core.errors.ProviderError` rather than leaking the raw SDK type above the boundary.
  - **Capabilities** — ``model_specs.capabilities_for(price_key)``. A ``gemini/<id>`` price_key has no
    spec entry, so capabilities default to text-only (fail-safe); ``google/gemini-3.1-flash-lite`` (the
    spec'd id) reports image+audio. This is acceptable and documented.
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
from ..core.errors import AdapterError, ProviderError
from . import model_specs
from ._provider_errors import map_provider_exception, with_provider_retry
from .base import AdapterConfig, TargetAdapter

_DEFAULT_MAX_TOKENS = 512  # estimate-only default; Gemini does not require an explicit cap


class GeminiAdapter(TargetAdapter):
    """Native google-genai adapter. ``provider`` is ``gemini``."""

    def __init__(self, config: AdapterConfig):
        super().__init__(config)
        self._owned_client: Any = None

    # --- wire identity --------------------------------------------------------------------------

    @property
    def _wire_model(self) -> str:
        """Bare model id (strip a leading ``gemini/`` or ``google/`` prefix if present)."""
        model = self.config.model
        for prefix in ("gemini/", "google/"):
            if model.startswith(prefix):
                return model[len(prefix):]
        return model

    @property
    def _price_key(self) -> str:
        return self.config.model

    # --- client lifecycle -----------------------------------------------------------------------

    def _client(self) -> Any:
        """Injected fake client (``config.extra["client"]``) or a lazily-built real one.

        The ``from google import genai`` import is intentionally lazy (inside this builder) so the
        module — and the test file — import cleanly without the ``google-genai`` SDK installed.
        """
        injected = self.config.extra.get("client")
        if injected is not None:
            return injected
        if self._owned_client is None:
            from google import genai  # noqa: PLC0415

            api_key = (
                self.config.api_key
                or os.environ.get("GEMINI_API_KEY")
                or os.environ.get("GOOGLE_API_KEY")
            )
            self._owned_client = genai.Client(api_key=api_key)
        return self._owned_client

    async def aclose(self) -> None:
        # google-genai's Client has no documented async close; drop our reference if we built it.
        self._owned_client = None

    # --- translation ----------------------------------------------------------------------------

    @staticmethod
    def _to_parts(msg: CanonicalMessage) -> list[dict[str, Any]]:
        """Translate a message's content blocks to Gemini ``parts`` (text + inline_data)."""
        parts: list[dict[str, Any]] = []
        text = msg.text
        if text:
            parts.append({"text": text})
        for block in msg.content:
            if isinstance(block, (ImageBlock, AudioBlock)):
                parts.append(
                    {
                        "inline_data": {
                            "mime_type": block.mime_type,
                            "data": block.to_base64(),
                        }
                    }
                )
        if not parts:
            parts.append({"text": ""})
        return parts

    def _build_contents(
        self, messages: list[CanonicalMessage]
    ) -> tuple[list[dict[str, Any]], str]:
        """Return ``(contents, system_instruction)``.

        SYSTEM messages are collected into ``system_instruction``; everything else maps to a
        ``contents`` turn with role ``"model"`` (ASSISTANT) or ``"user"`` (USER).
        """
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []
        for m in messages:
            if m.role == MessageRole.SYSTEM:
                if m.text:
                    system_parts.append(m.text)
                continue
            role = "model" if m.role == MessageRole.ASSISTANT else "user"
            contents.append({"role": role, "parts": self._to_parts(m)})
        return contents, "\n\n".join(system_parts)

    # --- the four required methods --------------------------------------------------------------

    async def invoke(
        self,
        messages: list[CanonicalMessage],
        *,
        temperature: float = 0.7,
        max_output_tokens: int | None = None,
        tools: list[Any] | None = None,
        tool_choice: str | None = None,
        **kwargs,
    ) -> InvocationResult:
        # Phase 1: `tools`/`tool_choice` are accepted for a uniform adapter signature but NOT wired
        # into the Gemini request yet (Gemini tool-calling lands in a later phase). Passing tools= here
        # is a silent no-op, not an error.
        contents, system_instruction = self._build_contents(messages)
        client = self._client()
        wire_model = self._wire_model

        gen_config: dict[str, Any] = {"temperature": temperature}
        if system_instruction:
            gen_config["system_instruction"] = system_instruction
        if max_output_tokens is not None:
            gen_config["max_output_tokens"] = max_output_tokens

        @with_provider_retry
        async def _do_call() -> Any:
            return await client.aio.models.generate_content(
                model=wire_model, contents=contents, config=gen_config
            )

        t0 = perf_counter()
        try:
            response = await _do_call()
        except AdapterError:
            raise  # already canonical (e.g. raised inside the call) — never re-wrap
        except Exception as e:  # noqa: BLE001
            mapped = map_provider_exception(e, provider="gemini")
            if mapped is not None:
                raise mapped from e
            # google-genai-native errors aren't recognized by map_provider_exception (it handles only
            # OpenAI/Anthropic/httpx) — wrap broadly so nothing provider-specific leaks past the boundary.
            raise ProviderError(str(e), provider="gemini", raw=e) from e
        latency_ms = int((perf_counter() - t0) * 1000)

        content = self._extract_text(response)
        tokens_in, tokens_out = self._extract_usage(response)
        stop_reason = StopReason.from_provider(self._extract_finish_reason(response))

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

    @staticmethod
    def _extract_text(response: Any) -> str:
        """``response.text`` if present, else concatenate the first candidate's text parts."""
        text = getattr(response, "text", None)
        if text:
            return text
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return ""
        content = getattr(candidates[0], "content", None)
        parts = getattr(content, "parts", None) or []
        return "".join(getattr(p, "text", "") or "" for p in parts)

    @staticmethod
    def _extract_usage(response: Any) -> tuple[int, int]:
        usage = getattr(response, "usage_metadata", None)
        if not usage:
            return 0, 0
        tokens_in = int(getattr(usage, "prompt_token_count", 0) or 0)
        tokens_out = int(getattr(usage, "candidates_token_count", 0) or 0)
        return tokens_in, tokens_out

    @staticmethod
    def _extract_finish_reason(response: Any) -> str | None:
        """Raw ``finish_reason`` of the first candidate (StopReason.from_provider lowercases it)."""
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return None
        reason = getattr(candidates[0], "finish_reason", None)
        if reason is None:
            return None
        # google-genai exposes finish_reason as an enum with a `.name`; tolerate a plain string too.
        return getattr(reason, "name", None) or str(reason)

    async def capabilities(self) -> TargetCapabilities:
        return model_specs.capabilities_for(self._price_key)

    async def healthcheck(self) -> bool:
        """Best-effort: True iff an API key is resolvable (no token-spending probe)."""
        return bool(
            self.config.api_key
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        )

    async def estimate_cost(
        self, messages: list[CanonicalMessage], *, max_output_tokens: int | None = None
    ) -> UsageMetrics:
        input_tokens = sum(len(m.text) // 4 for m in messages)
        output_tokens = max_output_tokens or _DEFAULT_MAX_TOKENS
        cost = model_specs.estimate_cost(self._price_key, input_tokens, output_tokens)
        return UsageMetrics.from_io(input_tokens, output_tokens, estimated_cost_usd=cost)


__all__ = ["GeminiAdapter"]
