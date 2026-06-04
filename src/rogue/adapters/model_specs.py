"""Single source of per-model facts: pricing + modality capability + limits.

Consolidates what was scattered across ``target_panel.py`` — ``_PRICE_PER_MILLION``,
``_IMAGE_CAPABLE_MODELS``, ``_AUDIO_CAPABLE_MODELS`` — into one table keyed by the full
provider-prefixed model id. Adapters read pricing/capabilities from here; the panel's
``supports_image``/``supports_audio`` delegate here too, so the data can never drift between the
dispatch gate and the adapters. Data values are copied verbatim from the panel (verified 2026-05/06).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..core.capabilities import TargetCapabilities

_log = logging.getLogger(__name__)

_ANTHROPIC_MAX_OUTPUT = 4096  # Anthropic Messages API requires an explicit max_tokens
_ANTHROPIC_MAX_TEMP = 1.0  # the SDK rejects higher temps on some Claude lines (panel clamps to 1.0)


@dataclass(frozen=True)
class ModelSpec:
    """Everything ROGUE knows about one target model, independent of which adapter calls it."""

    model: str
    input_price_per_m: float | None
    output_price_per_m: float | None
    supports_image: bool = False
    supports_audio: bool = False
    max_context_tokens: int | None = None
    max_output_tokens: int | None = None
    max_temperature: float | None = None


# Keyed by full "provider/model" id. Pricing tuple = (input $/M, output $/M).
_SPECS: dict[str, ModelSpec] = {
    "openai/gpt-5.4-nano": ModelSpec("openai/gpt-5.4-nano", 0.20, 1.25, supports_image=True),
    "openai/gpt-5.4": ModelSpec("openai/gpt-5.4", 2.50, 15.00, supports_image=True),
    "openai/gpt-audio-mini": ModelSpec("openai/gpt-audio-mini", 0.60, 2.40, supports_audio=True),
    "anthropic/claude-haiku-4-5": ModelSpec(
        "anthropic/claude-haiku-4-5", 1.00, 5.00, supports_image=True,
        max_output_tokens=_ANTHROPIC_MAX_OUTPUT, max_temperature=_ANTHROPIC_MAX_TEMP,
    ),
    "anthropic/claude-sonnet-4-6": ModelSpec(
        "anthropic/claude-sonnet-4-6", 3.00, 15.00, supports_image=True,
        max_output_tokens=_ANTHROPIC_MAX_OUTPUT, max_temperature=_ANTHROPIC_MAX_TEMP,
    ),
    "anthropic/claude-opus-4-8": ModelSpec(
        "anthropic/claude-opus-4-8", 15.00, 75.00,
        max_output_tokens=_ANTHROPIC_MAX_OUTPUT, max_temperature=_ANTHROPIC_MAX_TEMP,
    ),
    "groq/llama-3.1-8b-instant": ModelSpec("groq/llama-3.1-8b-instant", 0.05, 0.08),
    "meta-llama/llama-3.1-8b-instruct": ModelSpec("meta-llama/llama-3.1-8b-instruct", 0.02, 0.05),
    "mistralai/mistral-small-2603": ModelSpec(
        "mistralai/mistral-small-2603", 0.15, 0.60, supports_image=True
    ),
    "mistralai/voxtral-small-24b-2507": ModelSpec(
        "mistralai/voxtral-small-24b-2507", 0.10, 0.30, supports_audio=True
    ),
    "google/gemini-3.1-flash-lite": ModelSpec(
        "google/gemini-3.1-flash-lite", 0.25, 1.50, supports_image=True, supports_audio=True
    ),
}


def get_spec(model: str) -> ModelSpec | None:
    return _SPECS.get(model)


def supports_image(model: str) -> bool:
    """True iff ``model`` accepts image input (unknown models → False, fail-safe)."""
    spec = _SPECS.get(model)
    return bool(spec and spec.supports_image)


def supports_audio(model: str) -> bool:
    """True iff ``model`` accepts audio input (unknown models → False, fail-safe)."""
    spec = _SPECS.get(model)
    return bool(spec and spec.supports_audio)


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """USD cost for one call; 0.0 + warn on an unknown model (preserves panel behavior).

    We log-and-return-zero rather than raise so a model added without a pricing entry shows as $0
    in the matrix (with a warning) instead of crashing a reproduction sweep.
    """
    spec = _SPECS.get(model)
    if spec is None or spec.input_price_per_m is None or spec.output_price_per_m is None:
        _log.warning("no price entry for model %r; cost reported as 0.0", model)
        return 0.0
    return (tokens_in * spec.input_price_per_m + tokens_out * spec.output_price_per_m) / 1_000_000


def capabilities_for(
    model: str,
    *,
    supports_tools: bool = False,
    supports_json_mode: bool = False,
    supports_function_calling: bool = False,
    supports_streaming: bool = False,
    supports_system_prompt: bool = True,
) -> TargetCapabilities:
    """Build a :class:`TargetCapabilities` for ``model`` from its spec + provider-level flags.

    Modality (image/audio) and limits come from the spec; the provider-level flags
    (tools/json/streaming) are supplied by the calling adapter, which knows its own surface.
    Unknown models → text-only capabilities (fail-safe).
    """
    spec = _SPECS.get(model)
    return TargetCapabilities(
        supports_text=True,
        supports_image=bool(spec and spec.supports_image),
        supports_audio=bool(spec and spec.supports_audio),
        supports_video=False,
        supports_tools=supports_tools,
        supports_system_prompt=supports_system_prompt,
        supports_json_mode=supports_json_mode,
        supports_streaming=supports_streaming,
        supports_function_calling=supports_function_calling,
        max_context_tokens=spec.max_context_tokens if spec else None,
        max_output_tokens=spec.max_output_tokens if spec else None,
        max_temperature=spec.max_temperature if spec else None,
    )


__all__ = [
    "ModelSpec",
    "get_spec",
    "supports_image",
    "supports_audio",
    "estimate_cost",
    "capabilities_for",
]
