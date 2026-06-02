"""Renderer registry — governed lifecycle for executable renderer capabilities (§10.9 Phase 3b).

Renderers are *executable capabilities*, not transforms (memory
project_phase3b_renderer_registry). This module is the governance layer: it
registers renderer manifests, moves them through the lifecycle with **strict
forward-only transitions**, and exposes the active set to the reproduce ladder.

The load-bearing safety invariant: a ``synthesized`` (LLM-generated) renderer can
NEVER reach ``active`` without passing ``sandbox_verified → deterministic →
human_approved`` — i.e. ``synthesized`` and ``human_approved`` never collapse.
Enforced structurally by adjacency: a transition is legal only to the *immediate*
successor state for the renderer's ``origin``. There is no path that skips human
approval.

  - ``origin=human``      → harvested → spec_validated → deterministic →
                            human_approved → active  (skips the synthesis-only
                            sandbox states — there's no untrusted codegen to box).
  - ``origin=synthesized`` → the FULL chain incl. synthesized → sandbox_verified
                            (3b-v2; the synthesis pipeline plugs in at these states).

``active`` is the only state the ladder will run (``active_renderers``). Phase 3b-v1
ships human-written renderers; 3b-v2 (LLM synthesis + sandbox) is built on top of
this same lifecycle later.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from rogue.schemas import (
    LIFECYCLE_ORDER,
    SYNTHESIS_ONLY_STATES,
    RendererManifest,
    RendererOrigin,
    RendererStatus,
    StrategyStatus,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from rogue.db.models import AttackStrategy, RendererCapability

__all__ = [
    "InvalidTransition",
    "effective_order",
    "can_transition",
    "transition",
    "approve",
    "activate",
    "reject",
    "register_renderer",
    "active_renderers",
    "backlog",
    "seed_static_renderers",
    "STATIC_RENDERERS",
]


class InvalidTransition(ValueError):
    """Raised when a renderer lifecycle transition would violate the state machine."""


def effective_order(origin: RendererOrigin) -> tuple[RendererStatus, ...]:
    """The legal lifecycle sequence for a renderer of this origin.

    Human-written renderers skip the synthesis-only states (there is no untrusted
    generated code to sandbox); synthesized renderers traverse the full chain.
    """
    if origin is RendererOrigin.HUMAN:
        return tuple(s for s in LIFECYCLE_ORDER if s not in SYNTHESIS_ONLY_STATES)
    return LIFECYCLE_ORDER


def can_transition(
    origin: RendererOrigin, frm: RendererStatus, to: RendererStatus
) -> bool:
    """True iff ``frm → to`` is a legal one-step-forward move (or a reject).

    Forward-only, no skipping: ``to`` must be the *immediate* successor of ``frm``
    in this origin's ``effective_order``. ``rejected`` is reachable from any
    non-active, non-rejected state (a capability can be killed at any review gate).
    This is what makes ``synthesized → active`` structurally impossible.
    """
    if to is RendererStatus.REJECTED:
        return frm not in (RendererStatus.ACTIVE, RendererStatus.REJECTED)
    order = effective_order(origin)
    if frm not in order or to not in order:
        return False
    return order.index(to) == order.index(frm) + 1


def transition(
    row: "RendererCapability",
    to: RendererStatus,
    *,
    approved_by: Optional[str] = None,
    now: Optional[datetime] = None,
) -> None:
    """Apply a lifecycle transition in place, or raise ``InvalidTransition``.

    Promoting to ``human_approved`` records ``approved_by`` + ``approved_at``;
    promoting to ``active`` requires the predecessor ``human_approved`` (enforced
    by adjacency), so activation can never bypass review.
    """
    if not can_transition(row.origin, row.status, to):
        raise InvalidTransition(
            f"illegal renderer transition {row.status.value} → {to.value} "
            f"for origin={row.origin.value} (renderer_id={row.renderer_id})"
        )
    if to is RendererStatus.HUMAN_APPROVED:
        if not approved_by:
            raise InvalidTransition("human_approved requires approved_by")
        row.approved_by = approved_by
        row.approved_at = now
    row.status = to


def approve(
    row: "RendererCapability", approved_by: str, *, now: Optional[datetime] = None
) -> None:
    """Promote a verified renderer to ``human_approved``."""
    transition(row, RendererStatus.HUMAN_APPROVED, approved_by=approved_by, now=now)


def activate(row: "RendererCapability") -> None:
    """Promote a ``human_approved`` renderer to ``active`` (ladder-eligible)."""
    transition(row, RendererStatus.ACTIVE)


def reject(row: "RendererCapability") -> None:
    """Terminally reject a renderer (failed validation/review). Kept for provenance."""
    transition(row, RendererStatus.REJECTED)


def register_renderer(
    session: "Session", manifest: RendererManifest
) -> "RendererCapability":
    """Insert a new renderer capability from its manifest. Returns the ORM row."""
    from rogue.db.models import RendererCapability

    row = RendererCapability(
        renderer_id=manifest.renderer_id,
        name=manifest.name,
        technique_id=manifest.technique_id,
        modality=manifest.modality,
        origin=manifest.origin,
        entrypoint=manifest.entrypoint,
        artifact_types=list(manifest.artifact_types),
        network_allowed=manifest.network_allowed,
        deterministic=manifest.deterministic,
        sandbox_policy=manifest.sandbox_policy,
        provenance_hash=manifest.provenance_hash,
        resource_limits=dict(manifest.resource_limits),
        status=manifest.status,
        approved_by=manifest.approved_by,
        approved_at=manifest.approved_at,
    )
    session.add(row)
    return row


def active_renderers(
    session: "Session", modality: Optional[str] = None
) -> list["RendererCapability"]:
    """Renderers that are ``active`` (the only ones the ladder will run)."""
    from rogue.db.models import RendererCapability

    q = session.query(RendererCapability).filter(
        RendererCapability.status == RendererStatus.ACTIVE
    )
    if modality is not None:
        q = q.filter(RendererCapability.modality == modality)
    return q.order_by(RendererCapability.renderer_id.asc()).all()


def backlog(session: "Session") -> list["AttackStrategy"]:
    """Image/audio techniques parked as ``needs_implementation`` with NO active
    renderer yet — the structured "renderers to build" backlog."""
    from rogue.db.models import AttackStrategy, RendererCapability

    implemented = {
        tid
        for (tid,) in session.query(RendererCapability.technique_id)
        .filter(
            RendererCapability.status == RendererStatus.ACTIVE,
            RendererCapability.technique_id.isnot(None),
        )
        .all()
    }
    rows = (
        session.query(AttackStrategy)
        .filter(AttackStrategy.status == StrategyStatus.NEEDS_IMPLEMENTATION)
        .order_by(AttackStrategy.created_at.asc())
        .all()
    )
    return [r for r in rows if r.technique_id not in implemented]


# --------------------------------------------------------------------------- #
# Static renderers — the hand-written renderers ROGUE already ships, seeded as
# pre-approved `active` (origin=human, trusted in-process, deterministic). They
# predate the technique pipeline, so they link to no harvested technique.
# --------------------------------------------------------------------------- #

_R = "rogue.reproduce.modality_renderers"

STATIC_RENDERERS: tuple[RendererManifest, ...] = (
    RendererManifest(
        renderer_id="typographic_png_v1",
        name="Typographic text→PNG",
        modality="image",
        origin=RendererOrigin.HUMAN,
        entrypoint=f"{_R}.typographic:render_typographic_image",
        artifact_types=["png"],
        deterministic=True,
        sandbox_policy="none",
        status=RendererStatus.ACTIVE,
        approved_by="seed",
    ),
    RendererManifest(
        renderer_id="mml_v1",
        name="MML multi-modal layout",
        modality="image",
        origin=RendererOrigin.HUMAN,
        entrypoint=f"{_R}.mml:render_mml",
        artifact_types=["png"],
        deterministic=True,
        sandbox_policy="none",
        status=RendererStatus.ACTIVE,
        approved_by="seed",
    ),
    RendererManifest(
        renderer_id="vpi_overlay_v1",
        name="VPI overlay",
        modality="image",
        origin=RendererOrigin.HUMAN,
        entrypoint=f"{_R}.vpi:render_vpi_overlay",
        artifact_types=["png"],
        deterministic=True,
        sandbox_policy="none",
        status=RendererStatus.ACTIVE,
        approved_by="seed",
    ),
    RendererManifest(
        renderer_id="ocr_image_v1",
        name="OCR-layout image",
        modality="image",
        origin=RendererOrigin.HUMAN,
        entrypoint=f"{_R}.ocr:render_ocr_image",
        artifact_types=["png"],
        deterministic=True,
        sandbox_policy="none",
        status=RendererStatus.ACTIVE,
        approved_by="seed",
    ),
    RendererManifest(
        renderer_id="exif_injection_v1",
        name="EXIF metadata injection",
        modality="image",
        origin=RendererOrigin.HUMAN,
        entrypoint=f"{_R}.exif:render_exif_injection",
        artifact_types=["png", "jpg"],
        deterministic=True,
        sandbox_policy="none",
        status=RendererStatus.ACTIVE,
        approved_by="seed",
    ),
    RendererManifest(
        renderer_id="styled_audio_v1",
        name="Styled audio render",
        modality="audio",
        origin=RendererOrigin.HUMAN,
        entrypoint=f"{_R}.audio_styles:render_styled_audio",
        artifact_types=["wav"],
        deterministic=True,
        sandbox_policy="none",
        status=RendererStatus.ACTIVE,
        approved_by="seed",
    ),
    RendererManifest(
        renderer_id="speech_audio_v1",
        name="TTS speech render",
        modality="audio",
        origin=RendererOrigin.HUMAN,
        entrypoint=f"{_R}.audio_tts:render_speech_audio",
        artifact_types=["wav"],
        deterministic=True,
        sandbox_policy="none",
        status=RendererStatus.ACTIVE,
        approved_by="seed",
    ),
)


def seed_static_renderers(session: "Session") -> int:
    """Idempotently register the shipped static renderers as ``active``.

    Returns the number newly inserted. Safe to call repeatedly (skips existing ids).
    """
    from rogue.db.models import RendererCapability

    existing = {
        rid for (rid,) in session.query(RendererCapability.renderer_id).all()
    }
    inserted = 0
    for manifest in STATIC_RENDERERS:
        if manifest.renderer_id in existing:
            continue
        register_renderer(session, manifest)
        inserted += 1
    return inserted
