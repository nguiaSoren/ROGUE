"""Content blocks — the typed, provider-neutral pieces a :class:`CanonicalMessage` is made of.

The whole point of this layer: a message's content is a list of blocks ROGUE understands, and the
adapter (and only the adapter) translates them into provider wire format at the boundary. There must
be **no provider-specific fields here** — never ``openai_image_url`` / ``anthropic_source`` /
``gemini_part``. Extending the modality set (video, documents, web pages) = adding a block subclass.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from .attachment import Attachment


@dataclass
class ContentBlock:
    """Base content block. Subclasses carry the payload."""

    @property
    def modality(self) -> str:
        return "unknown"


@dataclass
class TextBlock(ContentBlock):
    text: str

    @property
    def modality(self) -> str:
        return "text"


@dataclass
class _MediaBlock(ContentBlock):
    """Shared base for inline-or-URL binary media (image/audio). Exactly one of data/url."""

    data: bytes | None = None
    url: str | None = None
    mime_type: str = ""

    def __post_init__(self) -> None:
        if (self.data is None) == (self.url is None):
            raise ValueError(f"{type(self).__name__} requires exactly one of `data` or `url`.")
        if not self.mime_type:
            raise ValueError(f"{type(self).__name__} requires a mime_type.")

    @classmethod
    def from_attachment(cls, att: Attachment):
        return cls(data=att.data, url=att.url, mime_type=att.mime_type)

    def to_attachment(self) -> Attachment:
        return Attachment(mime_type=self.mime_type, data=self.data, url=self.url)

    def to_base64(self) -> str:
        if self.data is None:
            raise ValueError("cannot base64-encode a URL-only block; fetch it first.")
        return base64.b64encode(self.data).decode("ascii")


@dataclass
class ImageBlock(_MediaBlock):
    mime_type: str = "image/png"

    @property
    def modality(self) -> str:
        return "image"


@dataclass
class AudioBlock(_MediaBlock):
    mime_type: str = "audio/wav"

    @property
    def modality(self) -> str:
        return "audio"


@dataclass
class ToolCallBlock(ContentBlock):
    """A tool/function call the model wants to make (assistant-emitted)."""

    id: str
    name: str
    arguments: dict

    @property
    def modality(self) -> str:
        return "tool_call"


@dataclass
class ToolResultBlock(ContentBlock):
    """The result of a tool call, fed back to the model."""

    tool_call_id: str
    result: str

    @property
    def modality(self) -> str:
        return "tool_result"


__all__ = [
    "ContentBlock",
    "TextBlock",
    "ImageBlock",
    "AudioBlock",
    "ToolCallBlock",
    "ToolResultBlock",
]
