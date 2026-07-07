"""Env-gated M2S consolidation surface — the one call each fire path makes.

Off by default (``ROGUE_M2S`` unset) → the primitive list is returned unchanged, so every
surface is byte-for-byte identical to today. When on (``ROGUE_M2S=on``), each primitive that
carries a ``multi_turn_sequence`` of ≥2 turns is replaced by its single-turn M2S-consolidated
form (``ROGUE_M2S_METHOD`` ∈ {hyphenize, numberize, pythonize}; default ``pythonize`` — the
strongest single method on the paper's GPT-4o row, +14.3 ASR). Single-turn primitives pass
through untouched, so a mixed corpus is handled uniformly.

Rationale for a single method (not the paper's best-of-3 Ensemble): the Ensemble fires all three
variants and takes any-breach — 3× trials — which is a per-cell fan-out that belongs to the paid
research A/B, not the default operational path. One method keeps the operational win at a true 1×
trial and the splice a pure list transform. See ``docs/research/m2s_consolidation.md``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from rogue.reproduce.m2s.consolidate import M2S_METHODS, M2SMethod, consolidate_primitive
from rogue.schemas import AttackPrimitive, DeploymentConfig

_log = logging.getLogger(__name__)

ENV_M2S = "ROGUE_M2S"          # off (default) | on
ENV_METHOD = "ROGUE_M2S_METHOD"  # hyphenize | numberize | pythonize (default)

DEFAULT_METHOD: M2SMethod = "pythonize"


@dataclass
class M2SConfig:
    method: M2SMethod = DEFAULT_METHOD


@dataclass
class M2SPlan:
    """The consolidation outcome for one fire batch: the (possibly rewritten) primitive list."""

    primitives: list[AttackPrimitive]
    n_consolidated: int = 0
    method: M2SMethod = DEFAULT_METHOD
    enabled: bool = True

    def summary(self) -> str:
        return (
            f"M2S consolidation ({self.method}): {self.n_consolidated} multi-turn "
            f"primitive(s) folded to single-turn (1× trial each)"
        )


def resolve_m2s(config: M2SConfig | None = None) -> M2SConfig | None:
    """Build an ``M2SConfig`` from the environment, or ``None`` when M2S is off.

    Off unless ``ROGUE_M2S`` ∈ {on,1,true,yes}. An unrecognised ``ROGUE_M2S_METHOD`` falls back to
    the default with a warning rather than failing the scan (the transform is an optimisation, never
    a hard dependency of a scan completing).
    """
    if config is not None:
        return config
    mode = os.environ.get(ENV_M2S, "off").strip().lower()
    if mode not in ("on", "1", "true", "yes"):
        return None
    method = os.environ.get(ENV_METHOD, DEFAULT_METHOD).strip().lower()
    if method not in M2S_METHODS:
        _log.warning("%s=%r not in %s — using %r", ENV_METHOD, method, M2S_METHODS, DEFAULT_METHOD)
        method = DEFAULT_METHOD
    return M2SConfig(method=method)  # type: ignore[arg-type]


def apply_m2s(
    primitives: list[AttackPrimitive],
    *,
    config: M2SConfig | None = None,
) -> M2SPlan:
    """The one call a scan makes before its fire loop. Resolves from env when not injected; returns a
    disabled plan (list unchanged) when M2S is off — a single uniform surface, byte-identical when off."""
    cfg = resolve_m2s(config)
    if cfg is None or not primitives:
        return M2SPlan(primitives=list(primitives), enabled=False)
    out: list[AttackPrimitive] = []
    n = 0
    for p in primitives:
        derived, done = consolidate_primitive(p, cfg.method)
        out.append(derived)
        n += 1 if done else 0
    plan = M2SPlan(primitives=out, n_consolidated=n, method=cfg.method, enabled=True)
    _log.info("%s", plan.summary())
    return plan


def apply_m2s_pairs(
    pairs: list[tuple[AttackPrimitive, DeploymentConfig]],
    *,
    config: M2SConfig | None = None,
) -> tuple[list[tuple[AttackPrimitive, DeploymentConfig]], int, bool]:
    """Sweep-side entry: consolidate the primitive of each (primitive × config) pair.

    Returns ``(pairs, n_consolidated, enabled)``. When off returns the input unchanged with
    ``enabled=False`` — byte-identical. Like the survival/prefire pair helpers this is called ONLY
    under an explicit opt-in on the research arm (``--m2s-consolidate``); consolidating replaces the
    multi-turn fire with its single-turn form, so the caller gates it rather than defaulting it on.
    Each distinct primitive is consolidated once and reused across its configs.
    """
    cfg = resolve_m2s(config)
    if cfg is None or not pairs:
        return pairs, 0, False
    cache: dict[str, tuple[AttackPrimitive, bool]] = {}
    out: list[tuple[AttackPrimitive, DeploymentConfig]] = []
    for p, c in pairs:
        if p.primitive_id not in cache:
            cache[p.primitive_id] = consolidate_primitive(p, cfg.method)
        derived, _ = cache[p.primitive_id]
        out.append((derived, c))
    n = sum(1 for _, (_, done) in cache.items() if done)
    _log.info(
        "M2S sweep (%s): %d/%d distinct primitive(s) consolidated to single-turn",
        cfg.method, n, len(cache),
    )
    return out, n, True


__all__ = [
    "M2SConfig",
    "M2SPlan",
    "resolve_m2s",
    "apply_m2s",
    "apply_m2s_pairs",
    "ENV_M2S",
    "ENV_METHOD",
    "DEFAULT_METHOD",
]
