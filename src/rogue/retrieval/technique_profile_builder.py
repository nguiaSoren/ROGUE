"""Technique profile builder — seeds the retrieval index with TechniqueProfile objects.

Produces one TechniqueProfile per technique label.  Labels match
``ladder_attempts.entity_id`` / ``ladder_rotation_membership.strategy_id`` exactly so
Recall@K is measurable against live telemetry.

Three sources are unified:
1. **ARMS strategies** (always available, no DB needed) — 17 hand-written strategies
   from ``arms_strategies.ARMS_STRATEGIES``.  label = strategy id (e.g. "crescendo").
2. **Tier labels** (always available, no DB needed) — the five renderer/operator tier
   label sets that the escalation ladder derives at runtime.  Labels are constructed
   with the same f-string the ladder uses (``image:{r}``, ``coj:{o}``,
   ``structured:{f}``, ``audio:{s}``).  origin="tier".
3. **Harvested strategies** (requires a live session) — ``attack_strategies`` rows
   (any status) loaded from the DB.  label = technique_id.  origin="harvested".
   image/audio harvested strategies appear here (unlike ``load_strategy_library`` which
   excludes non-auto-integrable ones for the planner).
4. **Telemetry coverage** (requires a live session) — every distinct winner label seen
   in ``ladder_attempts.entity_id`` where ``is_winner=True`` is guaranteed a profile,
   so Recall@K is well-defined for all observed winners.  historical_targets is
   populated for every profile from the same table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from rogue.reproduce.arms_strategies import ARMS_STRATEGIES
from rogue.reproduce.coj import COJ_OPERATIONS
from rogue.reproduce.escalation_ladder import (
    DEFAULT_AUDIO_STYLES,
    DEFAULT_IMAGE_RENDERERS,
    ESCALATION_LADDER,
)
from rogue.reproduce.structured_data import STRUCTURED_FORMATS
from rogue.schemas import TechniqueProfile

__all__ = ["build_technique_profiles"]

# ---------------------------------------------------------------------------
# Pattern → modality mapping for ARMS strategies
# ---------------------------------------------------------------------------
_PATTERN_MODALITY: dict[str, list[str]] = {
    "visual_context_cloaking": ["image", "text"],
    "typographic_transformation": ["image"],
    "visual_multi_turn_escalation": ["multi_turn"],
    "visual_reasoning_hijacking": ["text"],
    "visual_perturbation": ["image"],
}

# Multi-turn strategy ids (the planner drives these)
_MULTI_TURN_IDS = frozenset(ESCALATION_LADDER)

# Tier label format strings — mirrors escalation_ladder.py build_escalation_context
_TIER_IMAGE_RENDERERS: tuple[str, ...] = DEFAULT_IMAGE_RENDERERS
_TIER_COJ: tuple[str, ...] = COJ_OPERATIONS
_TIER_STRUCTURED: tuple[str, ...] = STRUCTURED_FORMATS
_TIER_AUDIO: tuple[str, ...] = DEFAULT_AUDIO_STYLES
_TIER_PLANNER: tuple[str, ...] = ESCALATION_LADDER


def _modalities_for_arms(strategy_id: str, pattern: str) -> list[str]:
    """Derive modalities for an ARMS strategy."""
    if strategy_id in _MULTI_TURN_IDS:
        return ["multi_turn"]
    return _PATTERN_MODALITY.get(pattern, ["text"])


def _arms_profiles() -> list[TechniqueProfile]:
    """Build TechniqueProfile objects for all 17 ARMS strategies."""
    profiles: list[TechniqueProfile] = []
    for strategy in ARMS_STRATEGIES.values():
        modalities = _modalities_for_arms(strategy.id, strategy.pattern)
        profiles.append(
            TechniqueProfile(
                label=strategy.id,
                technique_id=strategy.id,
                name=strategy.name,
                family=strategy.pattern,
                description=strategy.realized_by,
                principle=strategy.principle,
                steps=[strategy.directive] if strategy.directive else [],
                modalities=modalities,
                historical_targets=[],
                origin="arms",
                tier="",
            )
        )
    return profiles


def _tier_profiles() -> list[TechniqueProfile]:
    """Build TechniqueProfile objects for every tier label in the escalation ladder."""
    profiles: list[TechniqueProfile] = []

    # Tier 1 — image renderers
    for renderer in _TIER_IMAGE_RENDERERS:
        label = f"image:{renderer}"
        profiles.append(
            TechniqueProfile(
                label=label,
                technique_id=label,
                name=f"Image renderer: {renderer}",
                family="renderer_tier",
                description=(
                    f"Render the refused payload as an image using the '{renderer}' "
                    "modality renderer and present it to the target model."
                ),
                principle=(
                    "Visual encoding bypasses text-level safety filters by moving the "
                    "payload into the image modality."
                ),
                steps=[],
                modalities=["image"],
                historical_targets=[],
                origin="tier",
                tier="image",
            )
        )

    # Tier 2 — CoJ (Chain-of-Jailbreak) operations
    for operation in _TIER_COJ:
        label = f"coj:{operation}"
        profiles.append(
            TechniqueProfile(
                label=label,
                technique_id=label,
                name=f"CoJ operation: {operation}",
                family="coj_tier",
                description=(
                    f"Apply the '{operation}' chain-of-jailbreak syntactic mutation "
                    "to distract the model's safety filter with edit-sequence reasoning."
                ),
                principle=(
                    "Syntactic token-level perturbations via edit operations cause the "
                    "model to reason about edits rather than the payload's semantics."
                ),
                steps=[],
                modalities=["text"],
                historical_targets=[],
                origin="tier",
                tier="coj",
            )
        )

    # Tier 3 — structured data formats
    for fmt in _TIER_STRUCTURED:
        label = f"structured:{fmt}"
        profiles.append(
            TechniqueProfile(
                label=label,
                technique_id=label,
                name=f"Structured format: {fmt}",
                family="structured_tier",
                description=(
                    f"Re-cast the refused payload as a '{fmt}' structured-data "
                    "document; the format framing diffuses direct intent detection."
                ),
                principle=(
                    "Serialized data formats shift the perceived intent from 'request' "
                    "to 'data entry', softening refusal thresholds."
                ),
                steps=[],
                modalities=["text"],
                historical_targets=[],
                origin="tier",
                tier="structured",
            )
        )

    # Tier 4 — audio styles
    for style in _TIER_AUDIO:
        label = f"audio:{style}"
        profiles.append(
            TechniqueProfile(
                label=label,
                technique_id=label,
                name=f"Audio style: {style}",
                family="audio_tier",
                description=(
                    f"Speak the refused payload using the '{style}' acoustic rendering "
                    "and send it to audio-capable model configurations."
                ),
                principle=(
                    "Audio modality changes the surface representation of the payload, "
                    "potentially bypassing text-tuned safety classifiers."
                ),
                steps=[],
                modalities=["audio"],
                historical_targets=[],
                origin="tier",
                tier="audio",
            )
        )

    # Tier 5 — planner (ARMS escalation) strategies
    for strategy_id in _TIER_PLANNER:
        # These overlap with ARMS profiles — they will be deduped by label below.
        # We do NOT emit a duplicate here; the ARMS profile covers them.
        # (The planner tier labels are bare ids like "crescendo", same as ARMS.)
        pass

    return profiles


def _harvested_profiles(session: "Session") -> list[TechniqueProfile]:
    """Load harvested AttackStrategy rows as TechniqueProfile objects."""
    try:
        from rogue.db.models import AttackStrategy
        rows = session.query(AttackStrategy).all()
    except Exception:
        return []

    profiles: list[TechniqueProfile] = []
    for row in rows:
        modality = getattr(row, "modality", "") or ""
        modalities: list[str] = [modality] if modality else []

        principle = getattr(row, "principle", "") or ""
        steps_raw = getattr(row, "steps", None) or []
        steps: list[str] = list(steps_raw) if steps_raw else []
        directive = getattr(row, "directive", "") or ""
        name = getattr(row, "name", "") or row.technique_id

        profiles.append(
            TechniqueProfile(
                label=row.technique_id,
                technique_id=row.technique_id,
                name=name,
                family="harvested_method",
                description=directive,
                principle=principle,
                steps=steps,
                modalities=modalities,
                historical_targets=[],
                origin="harvested",
                tier="",
            )
        )
    return profiles


def _historical_targets(session: "Session") -> dict[str, list[str]]:
    """Return {label: [vendor/family, ...]} for all winning ladder attempts."""
    try:
        from sqlalchemy import select
        from rogue.db.models import LadderAttempt

        rows = (
            session.execute(
                select(
                    LadderAttempt.entity_id,
                    LadderAttempt.target_vendor,
                    LadderAttempt.target_family,
                ).where(LadderAttempt.is_winner.is_(True))
            ).all()
        )
    except Exception:
        return {}

    result: dict[str, set[str]] = {}
    for entity_id, vendor, family in rows:
        if not entity_id:
            continue
        if vendor and family:
            key = f"{vendor}/{family}"
        elif vendor:
            key = vendor
        elif family:
            key = family
        else:
            continue
        result.setdefault(entity_id, set()).add(key)

    return {label: sorted(targets) for label, targets in result.items()}


def _winner_labels(session: "Session") -> set[str]:
    """Return all distinct entity_id values for winning ladder attempts."""
    try:
        from sqlalchemy import select
        from rogue.db.models import LadderAttempt

        rows = (
            session.execute(
                select(LadderAttempt.entity_id).where(
                    LadderAttempt.is_winner.is_(True)
                ).distinct()
            ).all()
        )
        return {row[0] for row in rows if row[0]}
    except Exception:
        return set()


def build_technique_profiles(session: "Session | None" = None) -> list[TechniqueProfile]:
    """Build the full set of TechniqueProfile objects for the retrieval index.

    Always includes:
    - 17 ARMS strategy profiles (no DB required)
    - Tier-label profiles for all image/coj/structured/audio ladder slots (no DB
      required)

    With a ``session``:
    - Harvested AttackStrategy rows from the DB (origin="harvested")
    - Telemetry winner labels are ensured — any winner label not covered by the above
      gets a minimal stub profile so Recall@K is always well-defined
    - historical_targets populated from ladder_attempts (is_winner=True)

    Returns a deduped list — one profile per label (first definition wins, ARMS then
    tier then harvested).
    """
    profiles: list[TechniqueProfile] = []
    profiles.extend(_arms_profiles())
    profiles.extend(_tier_profiles())

    if session is not None:
        profiles.extend(_harvested_profiles(session))

    # Dedup by label — preserve first occurrence (ARMS > tier > harvested)
    seen: dict[str, TechniqueProfile] = {}
    for p in profiles:
        if p.label not in seen:
            seen[p.label] = p

    if session is not None:
        # Populate historical_targets
        hist = _historical_targets(session)
        for label, targets in hist.items():
            if label in seen:
                # Replace with updated profile (TechniqueProfile is immutable Pydantic)
                old = seen[label]
                seen[label] = old.model_copy(update={"historical_targets": targets})

        # Ensure coverage of every telemetry winner
        winners = _winner_labels(session)
        for label in winners:
            if label not in seen:
                # Stub — origin determined by label prefix
                if label.startswith("image:"):
                    tier, origin, modalities = "image", "tier", ["image"]
                    family = "renderer_tier"
                elif label.startswith("coj:"):
                    tier, origin, modalities = "coj", "tier", ["text"]
                    family = "coj_tier"
                elif label.startswith("structured:"):
                    tier, origin, modalities = "structured", "tier", ["text"]
                    family = "structured_tier"
                elif label.startswith("audio:"):
                    tier, origin, modalities = "audio", "tier", ["audio"]
                    family = "audio_tier"
                else:
                    tier, origin, modalities = "", "arms", ["text"]
                    family = "unknown"
                seen[label] = TechniqueProfile(
                    label=label,
                    technique_id=label,
                    name=label,
                    family=family,
                    modalities=modalities,
                    historical_targets=hist.get(label, []),
                    origin=origin,
                    tier=tier,
                )

    return list(seen.values())
