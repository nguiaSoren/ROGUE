"""Build a TargetFingerprint for one target model.

This module assembles the capability profile used by the Technique Retrieval
System to filter and rank techniques against a specific deployment target.

Spec: ROGUE_PLAN.md §10 (reproduction + escalation layer).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rogue.schemas import TargetFingerprint

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reasoning-model heuristic
# ---------------------------------------------------------------------------
# Models in these families use chain-of-thought / extended-thinking and expose
# different refusal surfaces from standard instruction-tuned models, so they
# warrant a separate technique-selection axis.
#
# Detection strategy (in priority order):
#   1. ModelSpec.reasoning_model field — if the spec table has an explicit flag,
#      trust it (reserved for a future spec-table extension).
#   2. Name-fragment heuristic — patterns in the model string that reliably
#      indicate a reasoning / thinking lineage.  Current patterns (June 2026):
#        "o1", "o3"             — OpenAI o-series
#        "o4"                   — OpenAI o4-mini etc.
#        "reasoning"            — generic/open-weight reasoning tags
#        "thinking"             — Anthropic extended-thinking suffix
#      Matched against lowercased model-name tokens split on "/" and "-".
#      False by default; unknown models default False safely.
_REASONING_NAME_FRAGMENTS: frozenset[str] = frozenset({"o1", "o3", "o4", "reasoning", "thinking"})


def _is_reasoning_model(target_model: str) -> bool:
    """Best-effort heuristic: True iff the model is a reasoning / thinking model.

    Checks the model_specs table for an explicit flag first (future-proof), then
    falls back to name-fragment matching against ``_REASONING_NAME_FRAGMENTS``.
    Never raises; defaults False for unknown inputs.
    """
    # Guard import: model_specs is an optional internal dep; missing it must not
    # crash the whole retrieval module at import time.
    try:
        from rogue.adapters.model_specs import get_spec  # type: ignore[import]

        spec = get_spec(target_model)
        # If ModelSpec grows a ``reasoning_model`` field in the future, use it.
        if spec is not None and getattr(spec, "reasoning_model", None) is not None:
            return bool(spec.reasoning_model)  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover
        _log.debug("model_specs unavailable; falling back to name heuristic", exc_info=True)

    # Name-fragment heuristic: check tokens in the full model string.
    # Split on "/" and "-" so "o1" does not match "foo1" or "tool".
    lower = target_model.lower()
    # Also check the raw model string for substrings that can't be split off
    # (e.g. "claude-3-7-sonnet-thinking").
    parts = lower.replace("/", "-").split("-")
    for fragment in _REASONING_NAME_FRAGMENTS:
        if fragment in parts:
            return True
    return False


def _query_known_successes(target_model: str, session: "Session") -> list[str]:
    """Return distinct winning technique labels for *target_model* from the ladder log.

    Pulls distinct ``entity_id`` values from ``ladder_attempts`` where:
      - ``is_winner`` is True
      - ``breached`` is True
      - ``config_id`` == *target_model*  (note: MISNOMER in schema — holds target_model string)

    Falls back to an empty list on any DB error rather than propagating (defensive:
    fingerprint building must not crash the caller if telemetry is unavailable).
    """
    try:
        from sqlalchemy import select, true

        from rogue.db.models import LadderAttempt  # type: ignore[import]

        stmt = (
            select(LadderAttempt.entity_id)
            .where(LadderAttempt.is_winner == true())
            .where(LadderAttempt.breached == true())
            .where(LadderAttempt.config_id == target_model)
            .distinct()
        )
        rows = session.execute(stmt).scalars().all()
        return list(rows)
    except Exception as exc:  # pragma: no cover
        _log.warning(
            "known_successes query failed for %r (%s: %s); defaulting to []",
            target_model,
            type(exc).__name__,
            exc,
        )
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_target_fingerprint(
    target_model: str,
    *,
    session: "Session | None" = None,
    deployment_config: object | None = None,
) -> TargetFingerprint:
    """Build a :class:`~rogue.schemas.TargetFingerprint` for *target_model*.

    Parameters
    ----------
    target_model:
        The canonical ``"vendor/model-name"`` identifier used throughout ROGUE,
        e.g. ``"anthropic/claude-haiku-4-5"``.  This becomes ``target_key``.
    session:
        Optional SQLAlchemy :class:`~sqlalchemy.orm.Session`.  When provided,
        ``known_successes`` is populated from the ``ladder_attempts`` table;
        otherwise it is left as ``[]``.
    deployment_config:
        Optional :class:`~rogue.schemas.DeploymentConfig` (or ORM equivalent).
        Reserved for future enrichment (e.g. declared tools, system-prompt hints).
        Not required; ``target_key``/``vendor``/``model_family`` always derive
        from *target_model* alone.

    Returns
    -------
    TargetFingerprint
        Fully populated capability profile, safe to use even for unknown models
        (all capabilities default to False/None rather than raising).
    """
    # --- Identity (always from model_specs; graceful on unknown) ---
    try:
        from rogue.adapters.model_specs import (  # type: ignore[import]
            extract_model_family,
            extract_vendor,
            get_spec,
            supports_audio as _supports_audio,
            supports_image as _supports_image,
        )

        vendor = extract_vendor(target_model)
        model_family = extract_model_family(target_model)
        spec = get_spec(target_model)
        _img = _supports_image(target_model)
        _aud = _supports_audio(target_model)
        _ctx = spec.max_context_tokens if spec is not None else None
    except Exception as exc:  # pragma: no cover
        _log.warning(
            "model_specs unavailable while building fingerprint for %r (%s: %s); "
            "defaulting vendor/family to 'unknown', caps to False",
            target_model,
            type(exc).__name__,
            exc,
        )
        vendor = "unknown"
        model_family = "unknown"
        _img = False
        _aud = False
        _ctx = None

    # --- Reasoning heuristic ---
    reasoning = _is_reasoning_model(target_model)

    # --- Telemetry: known successes (requires session) ---
    successes: list[str] = []
    if session is not None:
        successes = _query_known_successes(target_model, session)

    return TargetFingerprint(
        target_key=target_model,
        vendor=vendor,
        model_family=model_family,
        supports_images=_img,
        supports_audio=_aud,
        context_length=_ctx,
        reasoning_model=reasoning,
        known_successes=successes,
    )
