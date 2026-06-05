"""OpenAI provider adapter."""

from __future__ import annotations

from .base import Adapter


class OpenAIAdapter(Adapter):
    provider = "openai"
    required = ("api_key",)
    optional = ("organization", "base_url")

    def normalize_model(self, model: str) -> str:
        # Accept "openai/gpt-5" or "gpt-5"; the OpenAI API wants the bare id.
        return model.split("/", 1)[1] if model.startswith("openai/") else model


__all__ = ["OpenAIAdapter"]
