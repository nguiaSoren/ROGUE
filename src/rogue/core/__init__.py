"""ROGUE core — the provider-neutral substrate every adapter, scan, and benchmark depends on.

No provider-specific types live above this layer. ROGUE talks only to :class:`CanonicalMessage` and
:class:`InvocationResult`; capabilities (not provider names) drive routing. See ``ARCHITECTURE.md``.
"""

from .attachment import Attachment, sniff_mime
from .capabilities import TargetCapabilities
from .content_blocks import (
    AudioBlock,
    ContentBlock,
    ImageBlock,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from .errors import (
    AdapterError,
    AuthenticationError,
    ContentPolicyError,
    ProviderError,
    RateLimitError,
    TimeoutError,
    ValidationError,
    from_http_status,
    is_retryable,
)
from .invocation import InvocationResult, StopReason, UsageMetrics
from .message import (
    CanonicalMessage,
    MessageRole,
    from_legacy_messages,
    to_legacy_messages,
)
from .registry import AdapterRegistry, registry

__all__ = [
    # message
    "CanonicalMessage",
    "MessageRole",
    "from_legacy_messages",
    "to_legacy_messages",
    # content blocks
    "ContentBlock",
    "TextBlock",
    "ImageBlock",
    "AudioBlock",
    "ToolCallBlock",
    "ToolResultBlock",
    "Attachment",
    "sniff_mime",
    # invocation
    "InvocationResult",
    "UsageMetrics",
    "StopReason",
    # capabilities
    "TargetCapabilities",
    # registry
    "AdapterRegistry",
    "registry",
    # errors
    "AdapterError",
    "AuthenticationError",
    "RateLimitError",
    "TimeoutError",
    "ProviderError",
    "ValidationError",
    "ContentPolicyError",
    "from_http_status",
    "is_retryable",
]
