"""Google Vertex AI provider adapter.

Vertex authenticates by GCP project + region (and optionally a service-account credentials JSON),
not a bare API key — so its required fields differ from the OpenAI/Anthropic shape.
"""

from __future__ import annotations

from .base import Adapter


class VertexAdapter(Adapter):
    provider = "vertex"
    required = ("project", "location")
    optional = ("credentials_json",)

    def normalize_model(self, model: str) -> str:
        return model.split("/", 1)[1] if model.startswith("vertex/") else model


__all__ = ["VertexAdapter"]
