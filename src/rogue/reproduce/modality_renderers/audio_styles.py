"""Audio "styles" — deterministic acoustic transforms of a spoken payload.

The audio analogue of ``ocr.py``: a thin styling layer over the base TTS renderer
(``render_speech_audio``) that varies *how* the payload is spoken — voice, speed,
and a fixed background hiss — so a speech-capable model that flags the plainly
spoken words may transcribe-and-comply when the same words arrive faster, in a
different voice, or buried in noise. These are **black-box** transforms (no model
gradients), the audio counterpart to the image renderers; the white-box acoustic
adversarial attack (#11) stays out of scope.

Every style is **deterministic** (same text + style → same WAV bytes): the speech
comes from ``say`` with a fixed voice/rate, and the "noisy" style mixes in
pseudo-random noise from a *fixed seed*. No third-party audio deps — stdlib
``wave``/``struct``/``random`` only.

Voices are restricted to ones present on a stock macOS install (Samantha en_US,
Daniel en_GB) — the novelty "Whisper" voice is NOT installed by default, so we
don't ship a style that depends on it. Only one panel config currently accepts
audio (Gemini via OpenRouter; see ``target_panel.supports_audio``), so this is a
thin-but-real escalation surface.
"""

from __future__ import annotations

import base64
import io
import random
import struct
import wave

from rogue.reproduce.modality_renderers.audio_tts import render_speech_audio

__all__ = ["AUDIO_STYLES", "render_styled_audio"]

# style -> (voice, rate-wpm | None, noise-amplitude 0..1). Fixed values keep every
# style byte-stable. `rate` None = the voice's natural pace; `noise` 0 = clean.
AUDIO_STYLES: dict[str, dict[str, object]] = {
    "plain": {"voice": "Samantha", "rate": None, "noise": 0.0},
    "fast": {"voice": "Samantha", "rate": 320, "noise": 0.0},
    "slow": {"voice": "Samantha", "rate": 90, "noise": 0.0},
    "accented": {"voice": "Daniel", "rate": None, "noise": 0.0},
    "noisy": {"voice": "Samantha", "rate": None, "noise": 0.15},
}

# Fixed seed ⇒ the "noisy" style's background hiss is identical every run, so the
# whole renderer stays deterministic (§10.3 reproducibility contract).
_NOISE_SEED = 0x40677565  # "@gue"


def _mix_white_noise(wav_b64: str, amplitude: float) -> str:
    """Mix deterministic low-amplitude white noise into a 16-bit PCM WAV.

    Decodes the base64 WAV, adds seeded noise to every 16-bit sample (clamped to
    the int16 range), re-encodes with the same WAV params. Stdlib only.
    """
    raw = base64.b64decode(wav_b64)
    with wave.open(io.BytesIO(raw), "rb") as w:
        params = w.getparams()
        frames = w.readframes(w.getnframes())

    count = len(frames) // 2  # 16-bit ⇒ 2 bytes/sample
    samples = struct.unpack(f"<{count}h", frames)
    rng = random.Random(_NOISE_SEED)
    peak = int(amplitude * 32767)
    mixed = bytearray()
    for s in samples:
        v = s + rng.randint(-peak, peak)
        v = -32768 if v < -32768 else 32767 if v > 32767 else v
        mixed += struct.pack("<h", v)

    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setparams(params)
        w.writeframes(bytes(mixed))
    return base64.b64encode(out.getvalue()).decode("ascii")


def render_styled_audio(text: str, style: str = "plain") -> str:
    """Speak ``text`` in the given ``style``; return base64 WAV.

    Args:
        text: the payload to speak.
        style: one of ``AUDIO_STYLES`` (plain / fast / slow / accented / noisy).

    Raises:
        ValueError: if ``style`` is unknown.
    """
    spec = AUDIO_STYLES.get(style)
    if spec is None:
        raise ValueError(
            f"unknown audio style {style!r}; expected one of {tuple(AUDIO_STYLES)}"
        )
    audio_b64 = render_speech_audio(text, voice=spec["voice"], rate=spec["rate"])
    noise = spec["noise"]
    if noise:
        audio_b64 = _mix_white_noise(audio_b64, float(noise))
    return audio_b64
