"""Modality renderers — turn an attack's text payload into a *real* image/audio.

Each renderer is a small, **deterministic** function (same text in → same bytes
out) so a reproduced multimodal breach is byte-for-byte repeatable. Renderers
return a base64 payload that ``instantiator.render()`` attaches to the
``RenderedAttack`` (out-of-band; see ``papers/MULTIMODAL_CONTEXT.md`` Step 0a),
which ``target_panel`` then dispatches as a provider-specific content block.

Phase 1 adds more renderers here (MML, VPI overlay, EXIF, OCR-layout). Step 0a
ships only the typographic text→PNG renderer (#1 Promptfoo concept).
"""

from __future__ import annotations

from rogue.reproduce.modality_renderers.audio_styles import AUDIO_STYLES, render_styled_audio
from rogue.reproduce.modality_renderers.audio_tts import render_speech_audio
from rogue.reproduce.modality_renderers.exif import render_exif_injection
from rogue.reproduce.modality_renderers.mml import MML_METHODS, MMLRendered, render_mml
from rogue.reproduce.modality_renderers.ocr import OCR_STYLES, render_ocr_image
from rogue.reproduce.modality_renderers.polyjailbreak import (
    ASP_TAXONOMY,
    compose_messages,
    render_semantic_conflict_image,
)
from rogue.reproduce.modality_renderers.typographic import render_typographic_image
from rogue.reproduce.modality_renderers.vpi import VPI_STYLES, render_vpi_overlay

__all__ = [
    "ASP_TAXONOMY",
    "AUDIO_STYLES",
    "MML_METHODS",
    "OCR_STYLES",
    "VPI_STYLES",
    "MMLRendered",
    "compose_messages",
    "render_exif_injection",
    "render_mml",
    "render_ocr_image",
    "render_semantic_conflict_image",
    "render_speech_audio",
    "render_styled_audio",
    "render_typographic_image",
    "render_vpi_overlay",
]
