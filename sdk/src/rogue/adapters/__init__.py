"""Provider adapters + registry. Importing this module registers the built-in adapters."""

from .anthropic import AnthropicAdapter
from .base import Adapter, get_adapter, register_adapter, registered_providers
from .custom import CustomAdapter
from .openai import OpenAIAdapter
from .vertex import VertexAdapter

for _adapter in (OpenAIAdapter(), AnthropicAdapter(), VertexAdapter(), CustomAdapter()):
    register_adapter(_adapter)

__all__ = [
    "Adapter",
    "OpenAIAdapter",
    "AnthropicAdapter",
    "VertexAdapter",
    "CustomAdapter",
    "get_adapter",
    "register_adapter",
    "registered_providers",
]
