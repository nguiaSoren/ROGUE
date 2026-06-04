"""OpenAI + Groq target adapters — both speak OpenAI chat-completions natively.

Ports the panel's ``openai/`` and ``groq/`` dispatch branches. Each strips its own provider prefix
to get the WIRE model id (the bare id the endpoint exposes) while keeping the full
provider-prefixed ``config.model`` as the PRICE key for cost lookup. The Groq adapter is dead in
production (the Llama slot moved to OpenRouter — cheaper) but is kept to mirror the panel's retained
``groq/`` branch.
"""

from __future__ import annotations

import os

from .base import AdapterConfig
from .openai_compat import OpenAICompatAdapter


class OpenAIAdapter(OpenAICompatAdapter):
    """OpenAI proper — ``https://api.openai.com/v1``, model id with the ``openai/`` prefix stripped."""

    def __init__(self, config: AdapterConfig):
        super().__init__(config)
        self._base_url = "https://api.openai.com/v1"
        self._api_key = config.api_key or os.environ.get("OPENAI_API_KEY")
        self._wire_model = config.model.removeprefix("openai/")
        self._price_key = config.model

    @property
    def provider(self) -> str:
        return "openai"


class GroqAdapter(OpenAICompatAdapter):
    """Groq's OpenAI-compatible endpoint — ``https://api.groq.com/openai/v1``, ``groq/`` stripped.

    Dead in production (no ``DeploymentConfig`` uses a ``groq/`` model today) but retained so a
    future task can opt back in with a one-line registration, exactly as the panel kept its branch.
    """

    def __init__(self, config: AdapterConfig):
        super().__init__(config)
        self._base_url = "https://api.groq.com/openai/v1"
        self._api_key = config.api_key or os.environ.get("GROQ_API_KEY")
        self._wire_model = config.model.removeprefix("groq/")
        self._price_key = config.model

    @property
    def provider(self) -> str:
        return "groq"


__all__ = ["OpenAIAdapter", "GroqAdapter"]
