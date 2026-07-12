"""Fireworks AI adapter — OpenAI-compatible endpoint for open-weight models (funded, fast lane).

Fireworks serves open-weight models (Llama, Qwen, DeepSeek, GLM, Kimi, ...) behind an OpenAI
chat-completions surface at ``api.fireworks.ai/inference/v1`` on dedicated serving. This is a
:class:`~rogue.adapters.custom.CustomHTTPAdapter` with the Fireworks base_url + the ``FIREWORKS_API_KEY``
env key baked in, so a model id like ``accounts/fireworks/models/llama-v3p1-8b-instruct`` routes here via
``target_panel._PROVIDER_ROUTES`` with no per-config ``base_url`` (the DB configs have none).

It exists alongside the Featherless lane for one reason: **speed.** Featherless's flat-fee plan serves
these open models at ~45s/cell (unbounded generation on shared capacity), which makes a serial
open-weight reproduce impractical; Fireworks's dedicated serving is much faster, so it is the preferred
lane for a *powered* open-weight / permissive-target run (Featherless stays the free fallback).

The Fireworks key is preferred over any api_key handed in via the panel's ``adapter_extra`` — a mixed
OpenAI+Fireworks panel passes ONE key to every adapter, and this one must always use its own credential.

**Hang guard** (same as the Featherless lane): open-weight (esp. *reasoning*) models ramble to the client
timeout when the caller passes no output cap — and the panel's target call passes none. So this adapter
(1) caps output tokens by DEFAULT (``_DEFAULT_MAX_TOKENS``) when the caller omits one, and (2) trims SDK
retries to 1, so a genuinely-slow call fails fast instead of stacking timeout × retries.
"""

from __future__ import annotations

import os
from dataclasses import replace

from .base import AdapterConfig
from .custom import CustomHTTPAdapter

_FIREWORKS_BASE = "https://api.fireworks.ai/inference/v1"
# Bounded so a rambling/reasoning generation can't hang the sweep; generous enough for a
# reasoning trace + a substantive answer (the judge grades the answer).
_DEFAULT_MAX_TOKENS = 2048


class FireworksAdapter(CustomHTTPAdapter):
    """CustomHTTPAdapter pinned to the Fireworks endpoint + ``FIREWORKS_API_KEY``, with an
    output-token cap + trimmed retries so a slow open-weight generation can't hang a serial sweep."""

    def __init__(self, config: AdapterConfig):
        super().__init__(
            replace(
                config,
                base_url=config.base_url or _FIREWORKS_BASE,
                api_key=os.environ.get("FIREWORKS_API_KEY") or config.api_key,
                max_retries=min(config.max_retries, 1),
            )
        )

    async def invoke(self, messages, *, max_output_tokens: int | None = None, **kwargs):
        # Default-cap the generation length: the panel passes None, and an uncapped open-weight
        # (esp. reasoning) model runs to the client timeout and blocks the sweep.
        if max_output_tokens is None:
            max_output_tokens = _DEFAULT_MAX_TOKENS
        return await super().invoke(messages, max_output_tokens=max_output_tokens, **kwargs)

    @property
    def provider(self) -> str:
        return "fireworks"


__all__ = ["FireworksAdapter"]
