"""Adapter layer — the *only* place provider-specific code and SDK imports may live.

Week 1 ships the base interface + the reference MockAdapter and registers it into the process-wide
``rogue.core.registry``. Real provider adapters (OpenAI/Anthropic/Gemini/...) arrive in Week 2 and
register the same way — one line each, zero core changes.
"""

from ..core.registry import registry
from .base import AdapterConfig, TargetAdapter
from .mock import MockAdapter

# Built-in registrations (the "add an adapter = 1 line" pattern).
registry.register("mock", MockAdapter, overwrite=True)

__all__ = ["TargetAdapter", "AdapterConfig", "MockAdapter", "registry"]
