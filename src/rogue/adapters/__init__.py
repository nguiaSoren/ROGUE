"""Adapter layer — the only place provider-specific code and SDK imports live.

Importing this module registers every built-in adapter into the process-wide
``rogue.core.registry``. Adding a provider is exactly this: write an adapter, add one
``registry.register(...)`` line here. Zero core changes. Provider SDK imports inside each adapter
module are lazy, so importing this package needs none of the provider SDKs installed.
"""

from ..core.registry import registry
from .anthropic import AnthropicAdapter
from .base import AdapterConfig, TargetAdapter
from .custom import CustomHTTPAdapter
from .gemini import GeminiAdapter
from .mock import MockAdapter
from .openai import GroqAdapter, OpenAIAdapter
from .openrouter import OpenRouterAdapter

# Built-in registrations — one line each.
registry.register("mock", MockAdapter, overwrite=True)
registry.register("openai", OpenAIAdapter, overwrite=True)
registry.register("groq", GroqAdapter, overwrite=True)
registry.register("openrouter", OpenRouterAdapter, overwrite=True)
registry.register("anthropic", AnthropicAdapter, overwrite=True)
registry.register("gemini", GeminiAdapter, overwrite=True)
registry.register("custom", CustomHTTPAdapter, overwrite=True)

__all__ = [
    "TargetAdapter",
    "AdapterConfig",
    "MockAdapter",
    "OpenAIAdapter",
    "GroqAdapter",
    "OpenRouterAdapter",
    "AnthropicAdapter",
    "GeminiAdapter",
    "CustomHTTPAdapter",
    "registry",
]
