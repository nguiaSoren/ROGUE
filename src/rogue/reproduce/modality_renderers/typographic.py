"""Typographic image renderer — render attack text onto a plain PNG.

This is Promptfoo's "image" red-team strategy (framework #1 in
``papers/MULTIMODAL_CONTEXT.md``), reimplemented in Pillow. Promptfoo's
``simpleImage.ts`` renders the text to an SVG (Arial, black-on-white, ~800px
wide, word-wrapped with long-token hard-splitting) then rasterises to PNG via
``sharp``; we produce the same black-on-white text image directly with Pillow,
including Promptfoo's load-bearing detail — **hard-splitting a token too long
to fit on one line** so an unbroken string (e.g. an MML base64 payload) wraps
instead of overflowing the canvas. The attack premise: a vision model that
would refuse the typed words may read-and-comply when they arrive as pixels. No
weights, no diffusion, no per-image cost.

Determinism contract: ``render_typographic_image`` is a pure function of its
inputs. We use Pillow's built-in scalable font (no system-font dependency) and
write a PNG with no timestamp chunk, so the same text always produces the same
bytes — required for reproducible breach records (§10.3).
"""

from __future__ import annotations

import base64
import io

from PIL import Image, ImageDraw, ImageFont

__all__ = ["render_typographic_image"]


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    """Greedy word-wrap ``text`` to ``max_width`` px, preserving blank lines.

    Mirrors Promptfoo's ``wrapTextToLines``: per-paragraph wrapping plus
    **hard-splitting any single token wider than a full line** (measured by font
    pixel width), so an unbroken string like a base64 payload wraps across lines
    instead of overflowing/truncating off the right edge.
    """
    lines: list[str] = []
    for paragraph in text.replace("\r\n", "\n").split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        current = ""
        for word in paragraph.split():
            if draw.textlength(word, font=font) > max_width:
                # Token wider than a whole line — flush, then hard-split it,
                # measuring char-by-char. The trailing partial chunk stays as
                # `current` so the next word can continue that line.
                if current:
                    lines.append(current)
                    current = ""
                chunk = ""
                for ch in word:
                    if chunk and draw.textlength(chunk + ch, font=font) > max_width:
                        lines.append(chunk)
                        chunk = ch
                    else:
                        chunk += ch
                current = chunk
                continue
            candidate = f"{current} {word}".strip()
            if not current or draw.textlength(candidate, font=font) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines or [""]


def render_typographic_image(
    text: str,
    *,
    width: int = 800,
    padding: int = 40,
    font_size: int = 20,
    line_spacing: int = 6,
    background: str = "white",
    foreground: str = "black",
    base_image_b64: str | None = None,
) -> str:
    """Render ``text`` as a PNG image of typed words; return base64 (no data: prefix).

    Args:
        text: the payload to render into the image.
        width: canvas width in pixels (height is derived from wrapped lines).
        padding: margin in pixels around the text block.
        font_size: point size for Pillow's built-in font.
        line_spacing: extra pixels between baselines.
        background / foreground: Pillow color names or hex strings.
        base_image_b64: optional base64 image (a screenshot you supply). When
            given, the text is composited onto that image (scaled to ``width``)
            inside a backing strip for readability, instead of a blank canvas.

    Returns:
        Base64-encoded PNG bytes (ASCII str), ready for ``RenderedAttack.image_b64``.
    """
    # When compositing onto a supplied screenshot, keep the image near its own
    # resolution (clamped) and scale the font/padding proportionally so the text
    # is legible relative to the picture rather than tiny on a tall canvas.
    base: Image.Image | None = None
    if base_image_b64 is not None:
        base = Image.open(io.BytesIO(base64.b64decode(base_image_b64))).convert("RGB")
        target_w = max(800, min(base.width, 1400))
        if base.width != target_w:
            base = base.resize((target_w, max(1, round(base.height * target_w / base.width))))
        scale = target_w / width
        width = target_w
        # Font as a fraction of canvas width so the injected text reads
        # prominently on a real screenshot (not at the tiny synthetic ratio).
        font_size = max(font_size, round(target_w * 0.032))
        padding = round(padding * scale)
        line_spacing = round(line_spacing * scale)

    # Built-in font keeps the renderer deterministic + dependency-free (no
    # reliance on a system TTF that may differ across machines).
    font = ImageFont.load_default(size=font_size)

    # A scratch 1x1 image just to measure text before we know the final height.
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    max_text_width = width - 2 * padding
    lines = _wrap(scratch, text, font, max_text_width)

    ascent, descent = font.getmetrics()
    line_height = ascent + descent + line_spacing
    block_height = 2 * padding + max(line_height * len(lines), line_height)

    if base is not None:
        # Backing strip at the top keeps the text legible over any image.
        image = base
        draw = ImageDraw.Draw(image)
        draw.rectangle([0, 0, width, min(block_height, image.height)], fill=background)
    else:
        image = Image.new("RGB", (width, block_height), color=background)
        draw = ImageDraw.Draw(image)

    y = padding
    for line in lines:
        draw.text((padding, y), line, fill=foreground, font=font)
        y += line_height

    buffer = io.BytesIO()
    # optimize=True is deterministic; Pillow omits the tIME chunk by default, so
    # output bytes depend only on the pixels → reproducible.
    image.save(buffer, format="PNG", optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")
