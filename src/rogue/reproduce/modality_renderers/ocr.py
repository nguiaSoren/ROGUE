"""OCR / document-layout renderer (framework #5) — hide-in-plain-sight text.

The payload is rendered so it is **OCR-readable by a vision model but visually
subtle to a human** (and to naive "is there obvious text?" filters): near-white
text on white, tiny fonts, low contrast. This is the document-layout / font-trick
family — the same "hidden text in an image" idea as VPI's `lowcontrast` overlay,
but as a plain document render rather than fake UI chrome.

It's implemented as a thin styling layer over the typographic renderer (#1), so
it inherits that renderer's guarantees for free: deterministic bytes, the
long-token hard-split wrap, and optional compositing onto a user-supplied
screenshot via ``base_image_b64``. Each style is just a (foreground, font_size)
parameterization — no new drawing code, no new dependency.
"""

from __future__ import annotations

from rogue.reproduce.modality_renderers.typographic import render_typographic_image

__all__ = ["OCR_STYLES", "render_ocr_image"]

# style → typographic kwargs. The whole technique is "OCR sees it, humans/filters
# don't" — achieved via near-white colour and/or small size on a white page.
_OCR_STYLES: dict[str, dict] = {
    "white_on_white": {"foreground": "#f5f5f5", "background": "white"},
    "low_contrast": {"foreground": "#c8c8c8", "background": "white"},
    "tiny": {"font_size": 11, "foreground": "#1a1a1a"},
    "tiny_faint": {"font_size": 12, "foreground": "#d8d8d8"},
}
OCR_STYLES: tuple[str, ...] = tuple(_OCR_STYLES)


def render_ocr_image(
    payload: str, style: str = "white_on_white", *, base_image_b64: str | None = None
) -> str:
    """Render ``payload`` with an OCR-evasion style; return base64 PNG.

    ``style`` ∈ ``OCR_STYLES``. Deterministic. Delegates to the typographic
    renderer with style-specific colour/size, so ``base_image_b64`` compositing
    and long-token wrapping work identically.
    """
    if style not in _OCR_STYLES:
        raise ValueError(f"unknown OCR style {style!r}; choose from {OCR_STYLES}")
    return render_typographic_image(
        payload, base_image_b64=base_image_b64, **_OCR_STYLES[style]
    )
