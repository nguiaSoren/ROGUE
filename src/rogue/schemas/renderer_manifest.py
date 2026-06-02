"""RendererManifest — the governed capability record for a modality renderer (§10.9 Phase 3b).

A *technique* (`TechniqueSpec`) is a described method; a *renderer* is the
**executable artifact** that operationalizes an image/audio technique (turns its
text payload into real PNG/WAV bytes). Phase 3a handles text/multi_turn techniques
(they become planner directives — no new code). Phase 3b handles the hard half:
image/audio techniques park as `needs_implementation` until a renderer exists.

This module models renderers as **executable capabilities, not transforms** — every
renderer carries a manifest (sandbox policy, network stance, determinism contract,
artifact schema, provenance hash, approval state) and moves through a strict
lifecycle. The load-bearing invariant: **a synthesized renderer can NEVER reach
`active` without passing sandbox + determinism + human approval** — `synthesized`
and `human_approved` must never collapse into the same state.

Lifecycle (`RendererStatus`), ordered:

    harvested → spec_validated → synthesized → sandbox_verified
              → deterministic → human_approved → active

  - **3b-v1 (human-written renderer):** ``origin=human`` — a person writes + reviews
    the renderer plugin; it skips ``synthesized``/``sandbox_verified`` (no untrusted
    codegen) and is promoted via ``human_approved → active``.
  - **3b-v2 (assisted synthesis, future):** ``origin=synthesized`` — an LLM generates
    candidate code that MUST traverse the full chain (sandbox → determinism → human
    approval) before activation. Never ``LLM → auto-run``.

Spec: ROGUE_PLAN.md §10.9 Phase 3b + memory project_phase3b_renderer_registry.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RendererStatus(str, Enum):
    """The renderer capability lifecycle. Order is load-bearing (see _ORDER)."""

    HARVESTED = "harvested"  # technique extracted; no renderer yet (the backlog entry)
    SPEC_VALIDATED = "spec_validated"  # manifest normalized + accepted
    SYNTHESIZED = "synthesized"  # v2: code generated — UNTRUSTED, must be verified
    SANDBOX_VERIFIED = "sandbox_verified"  # ran safely in a restricted sandbox
    DETERMINISTIC = "deterministic"  # same input → byte-identical artifact
    HUMAN_APPROVED = "human_approved"  # a person reviewed + approved it
    ACTIVE = "active"  # allowed into the reproduce ladder's renderer tiers
    REJECTED = "rejected"  # failed validation/review — kept for provenance, never run


#: Canonical lifecycle order for the non-terminal states (REJECTED is terminal,
#: off-path). A transition is legal only if it moves strictly forward through this
#: sequence (no skipping past sandbox/determinism/approval for a synthesized
#: renderer — that's the core safety invariant). ``origin=human`` renderers are
#: allowed to skip the synthesis-only states (see renderer_registry.can_transition).
LIFECYCLE_ORDER: tuple[RendererStatus, ...] = (
    RendererStatus.HARVESTED,
    RendererStatus.SPEC_VALIDATED,
    RendererStatus.SYNTHESIZED,
    RendererStatus.SANDBOX_VERIFIED,
    RendererStatus.DETERMINISTIC,
    RendererStatus.HUMAN_APPROVED,
    RendererStatus.ACTIVE,
)

#: States only meaningful for synthesized (LLM-generated) renderers — a human-written
#: renderer never passes through these (there is no untrusted codegen to sandbox).
SYNTHESIS_ONLY_STATES: frozenset[RendererStatus] = frozenset(
    {RendererStatus.SYNTHESIZED, RendererStatus.SANDBOX_VERIFIED}
)


class RendererOrigin(str, Enum):
    """Where the renderer's code came from — gates which lifecycle path it takes."""

    HUMAN = "human"  # hand-written plugin (3b-v1) — trusted authoring
    SYNTHESIZED = "synthesized"  # LLM-generated (3b-v2) — must be fully verified


class RendererManifest(BaseModel):
    """One renderer's capability manifest — what it is, what it may do, and its state.

    The wire/identity twin of an ``renderer_capabilities`` row. The safety-relevant
    fields (``network_allowed``, ``deterministic``, ``sandbox_policy``,
    ``provenance_hash``) are the governance contract; the lifecycle ``status`` plus
    ``origin`` decide whether it may enter the reproduce ladder.
    """

    # ----- Identity -----
    renderer_id: str = Field(
        ..., min_length=3, description="stable id, e.g. 'typographic_png_v1'"
    )
    name: str = Field(..., max_length=200)
    # The harvested technique this renderer implements; None for pre-§10.9 static
    # renderers (hand-authored before the technique pipeline existed).
    technique_id: Optional[str] = Field(
        None, description="FK → attack_strategies.technique_id (the parked technique)"
    )
    modality: str = Field(..., description="'image' | 'audio'")
    origin: RendererOrigin = Field(...)

    # ----- Capability contract (the manifest) -----
    entrypoint: str = Field(
        ...,
        description="callable ref, e.g. 'rogue.reproduce.modality_renderers.typographic:render_typographic_image' (human) or a stored code ref (synthesized)",
    )
    artifact_types: list[str] = Field(
        default_factory=list, description="e.g. ['png'] or ['wav']"
    )
    # The ladder identifier(s) this renderer contributes — the image_strategy /
    # audio-style string(s) instantiator.render() dispatches on (e.g. ['typographic'],
    # ['mml:wr','mml:base64']). When the renderer is `active`, these are merged into
    # the reproduce ladder's renderer tier (§10.9 Phase 3b-v1).
    ladder_strategies: list[str] = Field(default_factory=list)
    network_allowed: bool = Field(
        False, description="renderers MUST NOT need network; True requires justification"
    )
    deterministic: bool = Field(
        False, description="same input → byte-identical artifact (required for active)"
    )
    sandbox_policy: Optional[str] = Field(
        None, description="e.g. 'firejail', 'subprocess-restricted', 'none' (human-trusted)"
    )
    provenance_hash: Optional[str] = Field(
        None, description="hash of the renderer code (synthesized renderers)"
    )
    resource_limits: dict[str, str] = Field(
        default_factory=dict, description="e.g. {'cpu_s': '5', 'mem_mb': '256'}"
    )

    # ----- Lifecycle -----
    status: RendererStatus = Field(RendererStatus.HARVESTED)
    approved_by: Optional[str] = Field(None)
    approved_at: Optional[datetime] = Field(None)

    @property
    def is_active(self) -> bool:
        return self.status is RendererStatus.ACTIVE
