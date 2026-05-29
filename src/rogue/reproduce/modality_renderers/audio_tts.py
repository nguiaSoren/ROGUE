"""Text-to-speech renderer — speak an attack's text into a WAV (Step 0b).

The audio analogue of the typographic image renderer: take the harmful text
payload and *say it out loud*, so a speech-capable model that would refuse the
typed words may instead transcribe-and-comply when they arrive as audio. This is
the true-multimodal audio path (framework #6 in ``papers/MULTIMODAL_CONTEXT.md``).

Implementation: macOS ``say`` (offline, no API key, no per-call cost, and
deterministic for a fixed voice/format — same text in, same WAV bytes out, which
the §10.3 reproducibility contract requires). On non-macOS hosts wire a pip TTS
(e.g. gTTS / piper) here; the rest of the pipeline is platform-agnostic.

Only ``google/gemini-3.1-flash-lite`` (via the OpenRouter OpenAI-compat route)
accepts audio in the current panel — see ``target_panel.supports_audio``.
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import tempfile

__all__ = ["render_speech_audio"]


def render_speech_audio(
    text: str,
    *,
    voice: str = "Samantha",
    sample_rate: int = 16000,
    rate: int | None = None,
) -> str:
    """Render ``text`` to a spoken WAV; return base64 (no data: prefix).

    Args:
        text: the payload to speak.
        voice: macOS ``say`` voice name (default "Samantha", a clear en_US voice).
        sample_rate: WAV sample rate in Hz (16 kHz is the speech-model standard).
        rate: speaking rate in words-per-minute (``say -r``); None = the voice's
            natural rate. Faster/slower speech is one of the deterministic audio
            "styles" (see ``audio_styles.py``) — same text+voice+rate → same bytes.

    Returns:
        Base64-encoded 16-bit PCM WAV bytes (ASCII str), ready for
        ``RenderedAttack.audio_b64``.

    Raises:
        RuntimeError: if macOS ``say`` is unavailable (non-macOS host).
    """
    if shutil.which("say") is None:
        raise RuntimeError(
            "macOS `say` not found — the Step 0b TTS renderer requires macOS. "
            "On another platform, wire a pip TTS (gTTS / piper) into "
            "render_speech_audio()."
        )

    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        cmd = ["say", "-v", voice]
        if rate is not None:
            cmd += ["-r", str(rate)]
        cmd += [
            "-o",
            path,
            "--file-format=WAVE",
            f"--data-format=LEI16@{sample_rate}",
            text,
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        with open(path, "rb") as fh:
            data = fh.read()
    finally:
        try:
            os.unlink(path)
        except OSError:  # pragma: no cover — temp cleanup must never raise
            pass

    return base64.b64encode(data).decode("ascii")
