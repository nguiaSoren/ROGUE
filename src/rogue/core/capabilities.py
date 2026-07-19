""":class:`TargetCapabilities` — the single source of truth for what a target can do.

Today ROGUE scatters capability checks: ``_IMAGE_CAPABLE_MODELS`` / ``supports_image()``,
``_AUDIO_CAPABLE_MODELS`` / ``supports_audio()`` frozensets, an Anthropic temperature clamp, a
hardcoded ``max_tokens=4096``. This object subsumes all of it so routing keys on *capabilities*,
not provider names (architecture Rule 4: ``if caps.supports_audio`` — never ``if provider == ...``).
"""

from __future__ import annotations

from dataclasses import dataclass

from .content_blocks import (
    AudioBlock,
    ContentBlock,
    ImageBlock,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from .message import CanonicalMessage, MessageRole


@dataclass(frozen=True)
class TargetCapabilities:
    """What a target deployment supports. Frozen — capabilities are a fixed description, not state."""

    supports_text: bool = True
    supports_image: bool = False
    supports_audio: bool = False
    supports_video: bool = False
    supports_tools: bool = False
    supports_system_prompt: bool = True
    supports_json_mode: bool = False
    supports_streaming: bool = False
    supports_function_calling: bool = False
    # Whether a trailing ``assistant`` turn is honored as a NATIVE response-prefill (the model
    # continues from it). True on Anthropic-protocol targets; False on OpenAI-style ones, which need
    # the seed folded in-band ("Begin your reply with…"). Drives adapter prefill routing — see
    # ``rogue.core.prefill`` and each adapter's ``supports_native_prefill`` attribute.
    supports_native_prefill: bool = False
    max_context_tokens: int | None = None
    # Extensions beyond the base ten — real ROGUE constraints that drive dispatch today:
    max_output_tokens: int | None = None
    max_temperature: float | None = None

    # --- capability-driven routing helpers ----------------------------------------------------

    def supports_block(self, block: ContentBlock) -> bool:
        """Whether a single content block is sendable to this target."""
        if isinstance(block, TextBlock):
            return self.supports_text
        if isinstance(block, ImageBlock):
            return self.supports_image
        if isinstance(block, AudioBlock):
            return self.supports_audio
        if isinstance(block, (ToolCallBlock, ToolResultBlock)):
            return self.supports_tools
        return False

    def supports_message(self, message: CanonicalMessage) -> bool:
        if message.role == MessageRole.SYSTEM and not self.supports_system_prompt:
            return False
        return all(self.supports_block(b) for b in message.content)

    def unsupported_blocks(self, messages: list[CanonicalMessage]) -> list[ContentBlock]:
        """Every block in ``messages`` this target cannot accept (empty ⇒ fully routable)."""
        return [b for m in messages for b in m.content if not self.supports_block(b)]

    def can_handle(self, messages: list[CanonicalMessage]) -> bool:
        """True iff every message (and the system prompt, if any) is supported."""
        return all(self.supports_message(m) for m in messages)

    def clamp_temperature(self, temperature: float) -> float:
        """Clamp a requested temperature to this target's ceiling, if any."""
        if self.max_temperature is not None:
            return min(temperature, self.max_temperature)
        return temperature


__all__ = ["TargetCapabilities"]
