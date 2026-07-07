"""Serve-time survival gate — ranks harvested attacks by predicted cross-config survival.

This is the live wiring surface. Given the attacks about to be fired and the target config, the gate
scores each with the trained predictor and reorders so the likely survivors go first — and, when a
budget cap is set, defers the predicted-dead tail. It is **off by default** (``ROGUE_SURVIVAL_ORDER``
unset) so today's behaviour is byte-for-byte unchanged until a model artifact exists and the flag is
set; then it becomes a pure reprioritization plus an optional cap.

Two safety rails are load-bearing, both from the papers:

* **Drift-guard fire-all.** Kirch (2411.03343) shows probes trained on known attack families transfer
  *below random* to held-out families. So a family the model has too little evidence for
  (``family_support < min_support``) or a technique the frozen taxonomy doesn't cover
  (``is_novel_family``) is **never skipped** — it is force-kept regardless of score. This is that OOD
  failure made operational: we only ever defer attacks we have in-distribution evidence about.

* **Deterministic canary sampling.** Even among skippable low-score attacks, a fixed fraction is
  force-kept so the gate keeps collecting ground truth on the exact rows it wanted to skip — the
  honest, continuous validation the report insists on. Sampling is by a stable hash of the primitive
  id (no RNG state), so a scan is reproducible and the canary set is consistent across runs.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field

from rogue.reproduce.config_features import derive_config_features
from rogue.reproduce.survival.features import build_features, is_novel_family
from rogue.reproduce.survival.model import SurvivalPredictor
from rogue.reproduce.survival.train import DEFAULT_MIN_SUPPORT
from rogue.schemas import AttackPrimitive, DeploymentConfig

_log = logging.getLogger(__name__)

ENV_ORDER = "ROGUE_SURVIVAL_ORDER"          # off (default) | on
ENV_MODEL = "ROGUE_SURVIVAL_MODEL"          # path to a saved SurvivalPredictor json
ENV_MIN_SUPPORT = "ROGUE_SURVIVAL_MIN_SUPPORT"
ENV_SKIP = "ROGUE_SURVIVAL_SKIP_THRESHOLD"  # if set, primitives below this score are skippable
ENV_CANARY = "ROGUE_SURVIVAL_FIRE_ALL_FRAC"  # deterministic fraction of skips force-kept (default .15)

DEFAULT_MODEL_PATH = "data/models/survival_predictor.json"
DEFAULT_CANARY_FRAC = 0.15


@dataclass
class RankedPrimitive:
    primitive: AttackPrimitive
    score: float
    forced: bool          # must-keep: novel/low-support family or canary sample
    forced_reason: str    # "" | "novel_family" | "low_support" | "canary"
    orig_index: int


@dataclass
class SurvivalPlan:
    """The gate's decision for one scan: a full reorder plus an optional budget selection."""

    ordered: list[AttackPrimitive]                 # every input, survival-ranked
    selected: list[AttackPrimitive]                # the subset to actually fire (== ordered if no cap)
    ranked: list[RankedPrimitive] = field(default_factory=list)
    deferred: list[AttackPrimitive] = field(default_factory=list)  # skipped by the budget cap
    enabled: bool = True

    def summary(self) -> str:
        forced = sum(1 for r in self.ranked if r.forced)
        return (
            f"survival gate: ranked {len(self.ordered)} attacks, firing {len(self.selected)} "
            f"({forced} force-kept by drift-guard/canary, {len(self.deferred)} deferred)"
        )


@dataclass
class SurvivalGate:
    """Holds a predictor + policy and turns (primitives, config) into a firing plan."""

    predictor: SurvivalPredictor
    enabled: bool = True
    min_support: int = DEFAULT_MIN_SUPPORT
    skip_threshold: float | None = None
    canary_frac: float = DEFAULT_CANARY_FRAC

    def _canary(self, primitive_id: str) -> bool:
        if self.canary_frac <= 0:
            return False
        h = hashlib.sha256(f"survival-canary:{primitive_id}".encode()).digest()
        return (int.from_bytes(h[:8], "big") / 2**64) < self.canary_frac

    def _forced(self, p: AttackPrimitive) -> tuple[bool, str]:
        if is_novel_family(p):
            return True, "novel_family"
        support = self.predictor.family_support.get(p.family.value, 0)
        if support < self.min_support:
            return True, "low_support"
        if self._canary(p.primitive_id):
            return True, "canary"
        return False, ""

    def rank_pairs(
        self,
        pairs: list[tuple[AttackPrimitive, DeploymentConfig]],
        *,
        skip: bool = False,
    ) -> tuple[list[tuple[AttackPrimitive, DeploymentConfig]], list[tuple[AttackPrimitive, DeploymentConfig]]]:
        """Rank a flat list of (primitive × config) pairs by predicted survival — for the research
        reproduce sweep, whose fan-out is a cartesian product, not a per-config scan.

        Returns ``(ordered, deferred)``. **Ordering-only by default** (``skip=False``): every pair is
        returned, highest predicted survival first — so an early budget / ``primitive_limit`` cutoff (or
        an interrupted run) has already measured the survivors; **no cell is dropped**. Only when
        ``skip=True`` AND ``skip_threshold`` is set are non-forced pairs below the floor moved to
        ``deferred`` (and even then the drift-guard force-keeps novel/low-support families) — this is the
        explicit opt-in for an Arm-13-style A/B, never the sweep's default, so the breach matrix and the
        predictor's own training labels stay complete."""
        cf_cache: dict[str, object] = {}
        scored = []
        for i, (p, c) in enumerate(pairs):
            key = getattr(c, "config_id", None) or c.target_model
            cf = cf_cache.get(key)
            if cf is None:
                cf = derive_config_features(c.target_model, base_url=getattr(c, "base_url", None))
                cf_cache[key] = cf
            score = self.predictor.score_one(build_features(p, c, config_features=cf))
            forced, _ = self._forced(p)
            scored.append((score, forced, i, p, c))
        scored.sort(key=lambda t: (-t[0], t[2]))  # survival desc, stable on original index

        ordered = [(p, c) for _, _, _, p, c in scored]
        deferred: list[tuple[AttackPrimitive, DeploymentConfig]] = []
        if skip and self.skip_threshold is not None:
            kept = []
            for score, forced, _, p, c in scored:
                if not forced and score < self.skip_threshold:
                    deferred.append((p, c))
                else:
                    kept.append((p, c))
            ordered = kept
        return ordered, deferred

    def rank(
        self,
        primitives: list[AttackPrimitive],
        config: DeploymentConfig,
        *,
        max_primitives: int | None = None,
    ) -> SurvivalPlan:
        """Score, reorder, and (optionally) defer the predicted-dead tail. Deferral fires under either
        policy — a top-``max_primitives`` cap, or a score floor (``skip_threshold``) — and the
        drift-guard/canary force-kept set is *never* deferred by either. Sort is stable: equal scores
        preserve the caller's order."""
        cf = derive_config_features(config.target_model, base_url=getattr(config, "base_url", None))
        ranked: list[RankedPrimitive] = []
        for i, p in enumerate(primitives):
            score = self.predictor.score_one(build_features(p, config, config_features=cf))
            forced, reason = self._forced(p)
            ranked.append(RankedPrimitive(p, score, forced, reason, i))

        # Fire order is pure survival-rank (highest predicted survival first), stable on the caller's
        # order for ties. The drift-guard/canary flag does NOT reorder — it only guarantees an item is
        # never *deferred* (handled in the selection below), so genuine high-survival attacks are never
        # buried beneath forced ones.
        ordered_ranked = sorted(ranked, key=lambda r: (-r.score, r.orig_index))
        ordered = [r.primitive for r in ordered_ranked]

        # A rank is deferrable only if it is (a) not force-kept AND (b) below the score floor and/or
        # beyond the top-k cap. Force-kept ranks are always selected.
        cap = max_primitives if max_primitives is not None else len(ordered_ranked)
        selected: list[AttackPrimitive] = []
        deferred: list[AttackPrimitive] = []
        for pos, r in enumerate(ordered_ranked):
            below_floor = self.skip_threshold is not None and r.score < self.skip_threshold
            beyond_cap = pos >= cap
            if r.forced or not (below_floor or beyond_cap):
                selected.append(r.primitive)
            else:
                deferred.append(r.primitive)

        return SurvivalPlan(
            ordered=ordered, selected=selected, ranked=ordered_ranked,
            deferred=deferred, enabled=True,
        )


def _disabled_plan(primitives: list[AttackPrimitive]) -> SurvivalPlan:
    return SurvivalPlan(ordered=list(primitives), selected=list(primitives), enabled=False)


def resolve_gate(*, predictor: SurvivalPredictor | None = None) -> SurvivalGate | None:
    """Build a gate from the environment, or ``None`` if survival ordering is off / no model is present.

    Off unless ``ROGUE_SURVIVAL_ORDER`` ∈ {on,1,true}. When on, loads the artifact at
    ``ROGUE_SURVIVAL_MODEL`` (default ``data/models/survival_predictor.json``); a missing/stale model
    yields ``None`` (the caller then keeps today's order) rather than a hard failure — the gate is an
    optimization, never a dependency of a scan completing."""
    mode = os.environ.get(ENV_ORDER, "off").strip().lower()
    if mode not in ("on", "1", "true", "yes"):
        return None
    if predictor is None:
        path = os.environ.get(ENV_MODEL, DEFAULT_MODEL_PATH)
        if not os.path.exists(path):
            _log.warning("survival gate on but no model at %r — keeping default order", path)
            return None
        try:
            predictor = SurvivalPredictor.load(path)
        except Exception as e:  # noqa: BLE001 — a bad artifact must not break the scan
            _log.warning("survival gate: failed to load %r (%s) — keeping default order", path, e)
            return None
    min_support = int(os.environ.get(ENV_MIN_SUPPORT, DEFAULT_MIN_SUPPORT))
    skip_raw = os.environ.get(ENV_SKIP)
    skip_threshold = float(skip_raw) if skip_raw not in (None, "") else None
    canary = float(os.environ.get(ENV_CANARY, DEFAULT_CANARY_FRAC))
    return SurvivalGate(
        predictor=predictor, enabled=True, min_support=min_support,
        skip_threshold=skip_threshold, canary_frac=canary,
    )


def apply_survival_order(
    primitives: list[AttackPrimitive],
    config: DeploymentConfig,
    *,
    gate: SurvivalGate | None = None,
    max_primitives: int | None = None,
) -> SurvivalPlan:
    """The one call the scan makes. Resolves the gate from env when not injected; returns a disabled
    plan (identity order) when survival ordering is off — so the caller has a single, uniform surface."""
    gate = gate if gate is not None else resolve_gate()
    if gate is None or not primitives:
        return _disabled_plan(primitives)
    plan = gate.rank(primitives, config, max_primitives=max_primitives)
    _log.info("%s", plan.summary())
    return plan


def apply_survival_order_pairs(
    pairs: list[tuple[AttackPrimitive, DeploymentConfig]],
    *,
    gate: SurvivalGate | None = None,
    skip: bool = False,
) -> tuple[list[tuple[AttackPrimitive, DeploymentConfig]], list[tuple[AttackPrimitive, DeploymentConfig]], bool]:
    """Sweep-side entry: order a flat (primitive × config) list by predicted survival.

    Returns ``(ordered, deferred, enabled)``. When the gate is off (env unset / no model) returns the
    input unchanged with ``enabled=False`` — so the research sweep is byte-identical by default.
    ``skip`` is the explicit opt-in that actually drops the deferred tail (below ``skip_threshold``);
    left False, this only reorders and never drops a cell."""
    gate = gate if gate is not None else resolve_gate()
    if gate is None or not pairs:
        return pairs, [], False
    ordered, deferred = gate.rank_pairs(pairs, skip=skip)
    _log.info(
        "survival sweep-order: %d pairs ranked, %d deferred%s",
        len(pairs), len(deferred), " (skip on)" if skip else " (ordering-only)",
    )
    return ordered, deferred, True


__all__ = [
    "SurvivalGate",
    "SurvivalPlan",
    "RankedPrimitive",
    "resolve_gate",
    "apply_survival_order",
    "apply_survival_order_pairs",
    "DEFAULT_MODEL_PATH",
    "ENV_ORDER",
    "ENV_MODEL",
]
