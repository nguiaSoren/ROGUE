"""Unit tests for :mod:`rogue.core.attachment` — Attachment + sniff_mime."""

from __future__ import annotations

import base64

import pytest

from rogue.core.attachment import Attachment, sniff_mime

PNG = b"\x89PNG\r\n\x1a\n" + b"the rest of the png"
JPEG = b"\xff\xd8\xff\xe0" + b"jfif"
GIF87 = b"GIF87a" + b"gifdata"
GIF89 = b"GIF89a" + b"gifdata"
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"vp8 "
WAV = b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"fmt "
OGG = b"OggS" + b"oggdata"
MP3_ID3 = b"ID3" + b"\x03\x00" + b"mp3"
MP3_SYNC = b"\xff\xfb" + b"mp3frames"
FLAC = b"fLaC" + b"\x00\x00"


# ---- sniff_mime --------------------------------------------------------------------------------


def test_sniff_png():
    assert sniff_mime(PNG) == "image/png"


def test_sniff_jpeg():
    assert sniff_mime(JPEG) == "image/jpeg"


def test_sniff_gif87():
    assert sniff_mime(GIF87) == "image/gif"


def test_sniff_gif89():
    assert sniff_mime(GIF89) == "image/gif"


def test_sniff_webp():
    assert sniff_mime(WEBP) == "image/webp"


def test_sniff_wav():
    assert sniff_mime(WAV) == "audio/wav"


def test_sniff_riff_webp_vs_wav_disambiguation():
    # Both start with RIFF; only the form-type at offset 8 distinguishes them.
    assert sniff_mime(WEBP) == "image/webp"
    assert sniff_mime(WAV) == "audio/wav"
    # An unknown RIFF form-type → None.
    unknown_riff = b"RIFF" + b"\x00\x00\x00\x00" + b"AVI " + b"rest"
    assert sniff_mime(unknown_riff) is None


def test_sniff_ogg():
    assert sniff_mime(OGG) == "audio/ogg"


def test_sniff_mp3_id3():
    assert sniff_mime(MP3_ID3) == "audio/mpeg"


def test_sniff_mp3_sync():
    assert sniff_mime(MP3_SYNC) == "audio/mpeg"


def test_sniff_flac():
    assert sniff_mime(FLAC) == "audio/flac"


def test_sniff_unknown_returns_none():
    assert sniff_mime(b"not a known magic header at all") is None


def test_sniff_empty_returns_none():
    assert sniff_mime(b"") is None


# ---- construction / validation ------------------------------------------------------------------


def test_inline_attachment():
    a = Attachment(mime_type="image/png", data=PNG)
    assert a.data == PNG
    assert a.url is None
    assert a.is_inline is True


def test_url_attachment():
    a = Attachment(mime_type="image/png", url="http://x/y.png")
    assert a.url == "http://x/y.png"
    assert a.data is None
    assert a.is_inline is False


def test_requires_exactly_one_neither():
    with pytest.raises(ValueError):
        Attachment(mime_type="image/png")


def test_requires_exactly_one_both():
    with pytest.raises(ValueError):
        Attachment(mime_type="image/png", data=PNG, url="http://x/y.png")


def test_requires_nonempty_mime():
    with pytest.raises(ValueError):
        Attachment(mime_type="", data=PNG)


# ---- constructors ------------------------------------------------------------------------------


def test_from_bytes_sniffs_when_no_mime():
    a = Attachment.from_bytes(PNG)
    assert a.mime_type == "image/png"
    assert a.data == PNG


def test_from_bytes_explicit_mime_overrides_sniff():
    a = Attachment.from_bytes(PNG, mime_type="application/octet-stream")
    assert a.mime_type == "application/octet-stream"


def test_from_bytes_unrecognized_raises():
    with pytest.raises(ValueError):
        Attachment.from_bytes(b"mystery bytes")


def test_from_bytes_name_kw():
    a = Attachment.from_bytes(PNG, name="logo.png")
    assert a.name == "logo.png"


def test_from_base64():
    b64 = base64.b64encode(PNG).decode("ascii")
    a = Attachment.from_base64(b64, "image/png")
    assert a.data == PNG
    assert a.mime_type == "image/png"


def test_from_path_sniffs(tmp_path):
    p = tmp_path / "img.bin"
    p.write_bytes(PNG)
    a = Attachment.from_path(p)
    assert a.mime_type == "image/png"
    assert a.data == PNG
    assert a.name == "img.bin"


def test_from_path_explicit_mime(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"opaque")
    a = Attachment.from_path(p, mime_type="application/pdf")
    assert a.mime_type == "application/pdf"


def test_from_path_unrecognized_raises(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"opaque mystery")
    with pytest.raises(ValueError):
        Attachment.from_path(p)


def test_from_url():
    a = Attachment.from_url("http://x/y.png", "image/png", name="y.png")
    assert a.url == "http://x/y.png"
    assert a.mime_type == "image/png"
    assert a.name == "y.png"
    assert a.is_inline is False


# ---- accessors ---------------------------------------------------------------------------------


def test_to_base64_round_trip():
    a = Attachment(mime_type="image/png", data=PNG)
    b64 = a.to_base64()
    assert b64 == base64.b64encode(PNG).decode("ascii")
    back = Attachment.from_base64(b64, "image/png")
    assert back.data == a.data


def test_from_bytes_to_base64_from_base64_round_trip():
    a = Attachment.from_bytes(PNG)
    restored = Attachment.from_base64(a.to_base64(), a.mime_type)
    assert restored.data == PNG
    assert restored.mime_type == "image/png"


def test_to_base64_url_only_raises():
    a = Attachment.from_url("http://x/y.png", "image/png")
    with pytest.raises(ValueError):
        a.to_base64()


def test_to_data_uri():
    a = Attachment(mime_type="image/png", data=PNG)
    uri = a.to_data_uri()
    assert uri.startswith("data:image/png;base64,")
    assert uri == f"data:image/png;base64,{a.to_base64()}"


def test_kind():
    assert Attachment(mime_type="image/png", data=PNG).kind == "image"
    assert Attachment(mime_type="audio/wav", data=WAV).kind == "audio"
    assert Attachment(mime_type="video/mp4", url="http://x/y.mp4").kind == "video"


def test_size_bytes_inline():
    a = Attachment(mime_type="image/png", data=PNG)
    assert a.size_bytes == len(PNG)


def test_size_bytes_url_none():
    a = Attachment.from_url("http://x/y.png", "image/png")
    assert a.size_bytes is None
