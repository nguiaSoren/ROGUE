"""The :class:`CanonicalMessage` — ROGUE's one internal message language.

Every provider speaks a different dialect (OpenAI/Anthropic ``{role, content:[...]}``, Gemini
``{parts:[...]}``, custom ``{prompt}``). ROGUE speaks only this. Adapters translate at the boundary.

Bridges to/from the legacy ``{"role": ..., "content": <str>}`` dicts ROGUE uses today
(``RenderedAttack.messages``) are provided so Week-2 migration is mechanical.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .content_blocks import ContentBlock, TextBlock


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class CanonicalMessage:
    role: MessageRole
    content: list[ContentBlock] = field(default_factory=list)

    # --- ergonomic constructors ---------------------------------------------------------------

    @classmethod
    def of(cls, role: MessageRole | str, text: str) -> CanonicalMessage:
        return cls(role=MessageRole(role), content=[TextBlock(text=text)])

    @classmethod
    def system(cls, text: str) -> CanonicalMessage:
        return cls.of(MessageRole.SYSTEM, text)

    @classmethod
    def user(cls, text: str) -> CanonicalMessage:
        return cls.of(MessageRole.USER, text)

    @classmethod
    def assistant(cls, text: str) -> CanonicalMessage:
        return cls.of(MessageRole.ASSISTANT, text)

    # --- accessors ----------------------------------------------------------------------------

    @property
    def text(self) -> str:
        """Concatenated text of all :class:`TextBlock`s (newline-joined)."""
        return "\n".join(b.text for b in self.content if isinstance(b, TextBlock))

    def blocks_of(self, block_type: type) -> list[ContentBlock]:
        return [b for b in self.content if isinstance(b, block_type)]

    @property
    def modalities(self) -> set[str]:
        return {b.modality for b in self.content}

    # --- legacy bridge (RenderedAttack.messages) ----------------------------------------------

    @classmethod
    def from_legacy_dict(cls, d: dict) -> CanonicalMessage:
        """Build from a ``{"role": ..., "content": <str>}`` dict (text-only legacy form)."""
        return cls.of(d["role"], d.get("content", "") or "")

    def to_legacy_dict(self) -> dict:
        """Flatten back to ``{"role": ..., "content": <text>}`` (drops non-text blocks)."""
        return {"role": self.role.value, "content": self.text}


def from_legacy_messages(messages: list[dict]) -> list[CanonicalMessage]:
    """Convert a list of legacy ``{role, content:str}`` dicts to canonical messages."""
    return [CanonicalMessage.from_legacy_dict(m) for m in messages]


def to_legacy_messages(messages: list[CanonicalMessage]) -> list[dict]:
    return [m.to_legacy_dict() for m in messages]


__all__ = [
    "MessageRole",
    "CanonicalMessage",
    "from_legacy_messages",
    "to_legacy_messages",
]
