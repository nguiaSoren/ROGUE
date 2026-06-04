"""OpenRouter target adapter — fronts Mistral / Google / Llama for ROGUE.

Ports the panel's OpenRouter branch (the ``mistralai/`` / ``google/`` / ``meta-llama/`` prefixes).
Critically, OpenRouter routes by the FULL ``provider/model`` string, so — unlike the OpenAI and Groq
adapters — the prefix is NOT stripped: the wire model id equals ``config.model``. The provider slug
is the model's own prefix (``mistralai`` / ``google`` / ``meta-llama``), falling back to
``openrouter`` when there is no prefix.
"""

from __future__ import annotations

import os

from .base import AdapterConfig
from .openai_compat import OpenAICompatAdapter


class OpenRouterAdapter(OpenAICompatAdapter):
    """OpenRouter — ``https://openrouter.ai/api/v1``, full ``provider/model`` sent as the wire id."""

    def __init__(self, config: AdapterConfig):
        super().__init__(config)
        self._base_url = "https://openrouter.ai/api/v1"
        self._api_key = config.api_key or os.environ.get("OPENROUTER_API_KEY")
        self._wire_model = config.model  # do NOT strip — OpenRouter routes by the full id
        self._price_key = config.model

    @property
    def provider(self) -> str:
        model = self.config.model
        return model.split("/", 1)[0] if "/" in model else "openrouter"


__all__ = ["OpenRouterAdapter"]
