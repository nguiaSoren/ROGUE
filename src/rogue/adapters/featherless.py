"""Featherless.ai adapter — flat-fee OpenAI-compatible endpoint for open-weight models.

Featherless serves open-weight models (Qwen, DeepSeek, GLM, MiniMax, ...) behind an OpenAI
chat-completions surface at ``api.featherless.ai/v1`` on a flat monthly plan. This is a
:class:`~rogue.adapters.custom.CustomHTTPAdapter` with the Featherless base_url + the
``FEATHERLESS_API_KEY`` env key baked in, so a bare model id like ``Qwen/Qwen3-32B`` routes here
via ``target_panel._PROVIDER_ROUTES`` with no per-config ``base_url`` (the DB configs have none).

The Featherless key is preferred over any api_key handed in via the panel's ``adapter_extra`` — a
mixed OpenAI+Featherless panel passes ONE key to every adapter, and this one must always use its
own credential, never a sibling provider's.

**Hang guard.** Open-weight (especially *reasoning*) models on Featherless will ramble to the client
timeout when the caller passes no output cap — and the panel's target call passes none. At the
flat-fee plan's low concurrency a single unbounded/slow generation blocks a serial sweep. So this
adapter (1) caps output tokens by DEFAULT (``_DEFAULT_MAX_TOKENS``) when the caller omits one, and
(2) trims SDK retries to 1, so a genuinely-slow call fails fast instead of stacking 90s × retries.
"""

from __future__ import annotations

import os
from dataclasses import replace

from .base import AdapterConfig
from .custom import CustomHTTPAdapter

_FEATHERLESS_BASE = "https://api.featherless.ai/v1"
# Bounded so a rambling/reasoning generation can't hang the sweep; generous enough for a
# reasoning trace + a substantive answer (the judge grades the answer).
_DEFAULT_MAX_TOKENS = 2048


class FeatherlessAdapter(CustomHTTPAdapter):
    """CustomHTTPAdapter pinned to the Featherless endpoint + ``FEATHERLESS_API_KEY``, with an
    output-token cap + trimmed retries so a slow open-weight generation can't hang a serial sweep."""

    def __init__(self, config: AdapterConfig):
        super().__init__(
            replace(
                config,
                base_url=config.base_url or _FEATHERLESS_BASE,
                api_key=os.environ.get("FEATHERLESS_API_KEY") or config.api_key,
                max_retries=min(config.max_retries, 1),
            )
        )

    async def invoke(self, messages, *, max_output_tokens: int | None = None, **kwargs):
        # Default-cap the generation length: the panel passes None, and an uncapped open-weight
        # (esp. reasoning) model runs to the client timeout and blocks the concurrency-1 sweep.
        if max_output_tokens is None:
            max_output_tokens = _DEFAULT_MAX_TOKENS
        return await super().invoke(messages, max_output_tokens=max_output_tokens, **kwargs)

    @property
    def provider(self) -> str:
        return "featherless"


__all__ = ["FeatherlessAdapter"]
