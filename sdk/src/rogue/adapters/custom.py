"""Custom / self-hosted OpenAI-compatible endpoint adapter.

For any provider behind a custom base URL (vLLM, Together, a private gateway, etc.). Requires the
endpoint; an api_key and extra headers are optional.
"""

from __future__ import annotations

from .base import Adapter


class CustomAdapter(Adapter):
    provider = "custom"
    required = ("base_url",)
    optional = ("api_key", "headers")


__all__ = ["CustomAdapter"]
