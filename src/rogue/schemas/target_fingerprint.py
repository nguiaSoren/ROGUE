"""TargetFingerprint — capability profile of one deployment target.

Used by the Technique Retrieval System to filter techniques to those that are
actually executable against a given target model (e.g. skip image-modality
techniques when ``supports_images=False``), and to warm-start retrieval ranking
via the ``known_successes`` evidence list.

``target_key`` is the canonical identifier — it matches the ``target_model``
string used throughout the reproduction layer, e.g.
``"anthropic/claude-haiku-4-5"``.

Spec: ROGUE_PLAN.md §10 (reproduction + escalation layer).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TargetFingerprint(BaseModel):
    """Capability profile of one deployment target used for technique filtering.

    ``target_key`` matches the ``target_model`` string in the reproduction layer,
    e.g. ``"anthropic/claude-haiku-4-5"``.
    """

    # ----- Identity -----
    target_key: str = Field(
        ...,
        description="the target_model string, e.g. 'anthropic/claude-haiku-4-5'",
    )
    vendor: str = Field(..., description="model vendor, e.g. 'anthropic', 'openai'")
    model_family: str = Field(
        ...,
        description="model family within the vendor, e.g. 'claude-haiku', 'gpt-4o'",
    )

    # ----- Capability flags -----
    supports_images: bool = Field(
        False,
        description="True iff the target accepts image inputs (enables image-modality techniques)",
    )
    supports_audio: bool = Field(
        False,
        description="True iff the target accepts audio inputs (enables audio-modality techniques)",
    )
    context_length: int | None = Field(
        None,
        description="maximum context length in tokens, or None if unknown",
    )
    reasoning_model: bool = Field(
        False,
        description="True iff the model is a chain-of-thought / reasoning model (e.g. o1, o3)",
    )

    # ----- Telemetry evidence -----
    known_successes: list[str] = Field(
        default_factory=list,
        description="technique labels (matching TechniqueProfile.label) known to breach this target",
    )
