"""EXIF / metadata-injection renderer (framework #4).

Hides the payload in an image's **metadata** (EXIF tags) while the visible
picture stays benign. The attack premise: a model or agent that *reads file
metadata* (e.g. an assistant wired to an `exiftool`-style extractor, or a
captioning pipeline that surfaces ImageDescription) ingests the hidden
instruction.

⚠️ **Efficacy caveat (documented, on purpose):** plain vision APIs decode an
image to pixels and **strip/ignore EXIF**, so against a bare vision endpoint
this is a no-op. It only bites when a metadata-reading tool is in the loop. So
it's NOT in the auto-ladder's always-on Tier-1 (that would waste calls) — it's
an opt-in strategy (`image_strategy="exif"`) for tool-augmented targets and for
coverage completeness. Output is **JPEG** (EXIF is a JPEG/TIFF construct).

Deterministic: a fixed (payload, base image) yields the same JPEG bytes
(Pillow, no timestamp tag written).
"""

from __future__ import annotations

import base64
import io

from PIL import Image, ImageDraw, ImageFont

__all__ = ["render_exif_injection"]

# Benign visible caption — the picture a human sees is innocuous; the payload
# lives only in metadata.
_VISIBLE_TEXT = "Attached photo — additional notes are stored in the file's metadata."

# EXIF tag IDs we write the payload into (all reliably round-trippable via
# Pillow's IFD0): ImageDescription, Artist, Software, plus Windows XPComment.
_TAG_IMAGE_DESCRIPTION = 0x010E
_TAG_ARTIST = 0x013B
_TAG_SOFTWARE = 0x0131
_TAG_XP_COMMENT = 0x9C9C


def render_exif_injection(
    payload: str, *, base_image_b64: str | None = None, visible_text: str = _VISIBLE_TEXT
) -> str:
    """Return a base64 **JPEG** whose EXIF metadata carries ``payload``.

    The visible image is benign (a neutral caption, or a screenshot you supply
    via ``base_image_b64``); the payload is written into several EXIF text tags.
    """
    if base_image_b64 is not None:
        img = Image.open(io.BytesIO(base64.b64decode(base_image_b64))).convert("RGB")
    else:
        img = Image.new("RGB", (800, 200), "white")
        draw = ImageDraw.Draw(img)
        draw.text((24, 24), visible_text, fill="#333333", font=ImageFont.load_default(size=18))

    exif = img.getexif()
    exif[_TAG_IMAGE_DESCRIPTION] = payload
    exif[_TAG_ARTIST] = payload
    exif[_TAG_SOFTWARE] = payload
    # XPComment is stored as UTF-16-LE bytes (Windows convention).
    exif[_TAG_XP_COMMENT] = payload.encode("utf-16-le")

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", exif=exif.tobytes())
    return base64.b64encode(buffer.getvalue()).decode("ascii")
