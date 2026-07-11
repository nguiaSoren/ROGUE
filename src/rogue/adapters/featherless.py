"""Featherless.ai adapter — flat-fee OpenAI-compatible endpoint for open-weight models.

Featherless serves open-weight models (Qwen, DeepSeek, GLM, MiniMax, ...) behind an OpenAI
chat-completions surface at ``api.featherless.ai/v1`` on a flat monthly plan. This is a
:class:`~rogue.adapters.custom.CustomHTTPAdapter` with the Featherless base_url + the
``FEATHERLESS_API_KEY`` env key baked in, so a bare model id like ``Qwen/Qwen3-32B`` routes here
via ``target_panel._PROVIDER_ROUTES`` with no per-config ``base_url`` (the DB configs have none).

The Featherless key is preferred over any api_key handed in via the panel's ``adapter_extra`` — a
mixed OpenAI+Featherless panel passes ONE key to every adapter, and this one must always use its
own credential, never a sibling provider's.
"""

from __future__ import annotations

import os
from dataclasses import replace

from .base import AdapterConfig
from .custom import CustomHTTPAdapter

_FEATHERLESS_BASE = "https://api.featherless.ai/v1"


class FeatherlessAdapter(CustomHTTPAdapter):
    """CustomHTTPAdapter pinned to the Featherless endpoint + ``FEATHERLESS_API_KEY``."""

    def __init__(self, config: AdapterConfig):
        super().__init__(
            replace(
                config,
                base_url=config.base_url or _FEATHERLESS_BASE,
                api_key=os.environ.get("FEATHERLESS_API_KEY") or config.api_key,
            )
        )

    @property
    def provider(self) -> str:
        return "featherless"


__all__ = ["FeatherlessAdapter"]
