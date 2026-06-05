"""Anthropic provider adapter."""

from __future__ import annotations

from .base import Adapter


class AnthropicAdapter(Adapter):
    provider = "anthropic"
    required = ("api_key",)
    optional = ("base_url",)

    def normalize_model(self, model: str) -> str:
        return model.split("/", 1)[1] if model.startswith("anthropic/") else model


__all__ = ["AnthropicAdapter"]
