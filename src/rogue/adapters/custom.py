"""Custom OpenAI-compatible HTTP target adapter — the product hinge.

Any OpenAI chat-completions-compatible endpoint (a customer's inference gateway, a self-hosted
vLLM/TGI front, an internal proxy) is reachable through this adapter: the operator supplies the
``base_url`` (required), an optional ``api_key``, and the model id is sent as-is. Optional default
headers can be passed via ``config.extra['headers']`` (e.g. a gateway's auth header).
"""

from __future__ import annotations

from ..core.errors import ValidationError
from .base import AdapterConfig
from .openai_compat import OpenAICompatAdapter


class CustomHTTPAdapter(OpenAICompatAdapter):
    """An OpenAI-compatible endpoint at a caller-supplied ``base_url``.

    ``base_url`` is required — without it there is nowhere to send the request, so a missing/empty
    value is a configuration error (:class:`rogue.core.errors.ValidationError`), not a runtime
    provider failure.
    """

    def __init__(self, config: AdapterConfig):
        super().__init__(config)
        if not config.base_url:
            raise ValidationError(
                "CustomHTTPAdapter requires a base_url (the OpenAI-compatible endpoint).",
                provider="custom",
            )
        self._base_url = config.base_url
        self._api_key = config.api_key
        self._wire_model = config.model
        self._price_key = config.model

    @property
    def provider(self) -> str:
        return "custom"


__all__ = ["CustomHTTPAdapter"]
