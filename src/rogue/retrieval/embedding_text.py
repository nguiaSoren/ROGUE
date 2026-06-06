"""Embedding text builders for technique and target fingerprint objects.

Produces stable, human-readable multi-line text that captures the salient fields
of a TechniqueProfile or TargetFingerprint. This text is fed directly into the
embedding function; determinism is required so repeated calls yield identical
vectors for the same logical profile.

Public API
----------
build_technique_embedding_text(profile: TechniqueProfile) -> str
build_target_embedding_text(fp: TargetFingerprint) -> str
"""

from __future__ import annotations

from rogue.schemas import TargetFingerprint, TechniqueProfile


def build_technique_embedding_text(profile: TechniqueProfile) -> str:
    """Build a stable, readable embedding document for a TechniqueProfile.

    Fields included (in fixed order to guarantee determinism):
    - label, name, family, origin, tier
    - principle
    - description
    - steps (numbered)
    - modalities
    - historical_targets

    Returns a non-empty string. All optional fields that are empty/absent are
    omitted from the output (no blank lines that vary per call).
    """
    parts: list[str] = []

    # Identity block
    parts.append(f"Technique: {profile.name}")
    parts.append(f"Label: {profile.label}")
    parts.append(f"Family: {profile.family}")

    if profile.origin:
        parts.append(f"Origin: {profile.origin}")
    if profile.tier:
        parts.append(f"Tier: {profile.tier}")
    if profile.technique_id and profile.technique_id != profile.label:
        parts.append(f"Technique ID: {profile.technique_id}")

    # Conceptual content
    if profile.principle:
        parts.append(f"Principle: {profile.principle}")
    if profile.description:
        parts.append(f"Description: {profile.description}")

    # Steps (numbered for readability / retrieval signal)
    if profile.steps:
        step_lines = "\n".join(
            f"  {i + 1}. {step}" for i, step in enumerate(profile.steps)
        )
        parts.append(f"Steps:\n{step_lines}")

    # Modality / scope
    if profile.modalities:
        parts.append(f"Modalities: {', '.join(profile.modalities)}")

    # Telemetry evidence
    if profile.historical_targets:
        parts.append(f"Historical targets: {', '.join(profile.historical_targets)}")

    return "\n".join(parts)


def build_target_embedding_text(fp: TargetFingerprint) -> str:
    """Build a stable, readable embedding document for a TargetFingerprint.

    Fields included (in fixed order to guarantee determinism):
    - target_key, vendor, model_family
    - modality capabilities (images, audio)
    - context_length (when known)
    - reasoning_model flag
    - known_successes

    Returns a non-empty string.
    """
    parts: list[str] = []

    # Identity block
    parts.append(f"Target: {fp.target_key}")
    parts.append(f"Vendor: {fp.vendor}")
    parts.append(f"Model family: {fp.model_family}")

    # Capability flags — always emit so the embedding captures negatives too
    modality_caps: list[str] = ["text"]
    if fp.supports_images:
        modality_caps.append("image")
    if fp.supports_audio:
        modality_caps.append("audio")
    parts.append(f"Supported modalities: {', '.join(modality_caps)}")

    if fp.context_length is not None:
        parts.append(f"Context length: {fp.context_length} tokens")

    if fp.reasoning_model:
        parts.append("Reasoning model: yes")
    else:
        parts.append("Reasoning model: no")

    # Telemetry evidence
    if fp.known_successes:
        parts.append(f"Known successful techniques: {', '.join(fp.known_successes)}")

    return "\n".join(parts)
