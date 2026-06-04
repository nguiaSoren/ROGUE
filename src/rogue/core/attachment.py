"""Normalized binary media (:class:`Attachment`) for image/audio content.

ROGUE today carries multimodal payloads out-of-band as base64 strings + a media-type/format string
(``RenderedAttack.image_b64`` / ``image_media_type`` / ``audio_b64`` / ``audio_format``), with magic-byte
sniffing in the instantiator. ``Attachment`` consolidates that: load media from bytes / a file / a URL /
base64, sniff the MIME type, and hand it to an :class:`~rogue.core.content_blocks.ImageBlock` or
``AudioBlock``. Provider-specific wire encoding (data-URI vs base64 source block) stays in ``adapters/``.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

# Magic-byte signatures → IANA MIME type (mirrors the instantiator's sniffing, consolidated here).
_MAGIC: list[tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),  # disambiguated below (RIFF is also WAV)
    (b"OggS", "audio/ogg"),
    (b"ID3", "audio/mpeg"),
    (b"\xff\xfb", "audio/mpeg"),
    (b"fLaC", "audio/flac"),
]


def sniff_mime(data: bytes) -> str | None:
    """Best-effort MIME from magic bytes; ``None`` if unrecognized."""
    if data[:4] == b"RIFF":
        # RIFF container: WEBP vs WAV disambiguated by the form-type at offset 8.
        form = data[8:12]
        if form == b"WEBP":
            return "image/webp"
        if form == b"WAVE":
            return "audio/wav"
        return None
    for sig, mime in _MAGIC:
        if sig != b"RIFF" and data.startswith(sig):
            return mime
    return None


@dataclass
class Attachment:
    """A piece of binary media identified by MIME type, carried inline (bytes) or by URL.

    Exactly one of ``data`` / ``url`` must be set.
    """

    mime_type: str
    data: bytes | None = None
    url: str | None = None
    name: str | None = None

    def __post_init__(self) -> None:
        if (self.data is None) == (self.url is None):
            raise ValueError("Attachment requires exactly one of `data` or `url`.")
        if not self.mime_type:
            raise ValueError("Attachment requires a mime_type.")

    # --- constructors -------------------------------------------------------------------------

    @classmethod
    def from_bytes(cls, data: bytes, mime_type: str | None = None, *, name: str | None = None) -> Attachment:
        mt = mime_type or sniff_mime(data)
        if not mt:
            raise ValueError("could not determine mime_type from bytes; pass mime_type explicitly.")
        return cls(mime_type=mt, data=data, name=name)

    @classmethod
    def from_base64(cls, b64: str, mime_type: str, *, name: str | None = None) -> Attachment:
        return cls(mime_type=mime_type, data=base64.b64decode(b64), name=name)

    @classmethod
    def from_path(cls, path: str | Path, mime_type: str | None = None) -> Attachment:
        p = Path(path)
        data = p.read_bytes()
        mt = mime_type or sniff_mime(data)
        if not mt:
            raise ValueError(f"could not determine mime_type for {p}; pass mime_type explicitly.")
        return cls(mime_type=mt, data=data, name=p.name)

    @classmethod
    def from_url(cls, url: str, mime_type: str, *, name: str | None = None) -> Attachment:
        return cls(mime_type=mime_type, url=url, name=name)

    # --- accessors ----------------------------------------------------------------------------

    @property
    def is_inline(self) -> bool:
        return self.data is not None

    @property
    def kind(self) -> str:
        """Top-level media kind: ``image`` / ``audio`` / ``video`` / the MIME's primary type."""
        return self.mime_type.split("/", 1)[0]

    def to_base64(self) -> str:
        """Base64 of the inline bytes. Raises if this attachment is URL-only."""
        if self.data is None:
            raise ValueError("cannot base64-encode a URL-only attachment; fetch it first.")
        return base64.b64encode(self.data).decode("ascii")

    def to_data_uri(self) -> str:
        """``data:<mime>;base64,<...>`` form (the OpenAI image_url style)."""
        return f"data:{self.mime_type};base64,{self.to_base64()}"

    @property
    def size_bytes(self) -> int | None:
        return len(self.data) if self.data is not None else None


__all__ = ["Attachment", "sniff_mime"]
