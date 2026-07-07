"""Serve-time pre-fire skip gate — score each attack, skip the ones predicted not to breach.

The live surface. Given the attacks about to be fired at one target config, the gate scores each with
the calibrated predictor and, when its P(breach) is below the skip threshold, defers it *before any
target or judge call is spent*. It is **off by default** (``ROGUE_PREFIRE_SKIP`` unset) so today's
behaviour is byte-for-byte unchanged; when on it only ever *removes* low-probability trials from the
fire set (the caller records each as a visible skipped finding — never a silent drop) and leaves the
firing order untouched (ordering is Q11's job; Q7 only skips).

Two rails, both from the papers and both identical in spirit to the survival gate:

* **Drift-guard fire-all.** Kirch (2411.03343) shows a predictor trained on known attack families
  degrades to near-or-below random on held-out families. So a novel/emergent family, or one with too
  little in-distribution evidence (``family_support < min_support``), is **never skipped** — a confident
  skip there would be uncalibrated by construction.

* **Deterministic canary.** A fixed fraction of otherwise-skippable attacks is force-fired anyway (by a
  stable hash of the primitive id, no RNG), so the gate keeps collecting ground truth on exactly the
  rows it wanted to skip — the continuous validation that keeps the skip policy honest.

Serve-time embedding: the scan-time primitive is a Pydantic object with no stored embedding, so the
gate embeds each payload once (``text-embedding-3-small``, a fraction of a cent — trivially repaid by
skipping even one expensive target+judge trial). If no embedding function is available (no key /
opted out) it degrades to the structural signal alone (the affinity block is zeroed) and logs the
fallback, so a scan never fails because embeddings are unreachable.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field

from rogue.reproduce.config_features import derive_config_features
from rogue.reproduce.prefire.features import build_prefire_features
from rogue.reproduce.prefire.model import PrefirePredictor
from rogue.reproduce.survival.features import is_novel_family
from rogue.reproduce.survival.train import DEFAULT_MIN_SUPPORT
from rogue.retrieval.embed import EmbedFn
from rogue.schemas import AttackPrimitive, DeploymentConfig

_log = logging.getLogger(__name__)

ENV_SKIP = "ROGUE_PREFIRE_SKIP"            # off (default) | on
ENV_MODEL = "ROGUE_PREFIRE_MODEL"          # path to a saved PrefirePredictor json
ENV_THRESHOLD = "ROGUE_PREFIRE_THRESHOLD"  # skip below this calibrated P(breach); default from model
ENV_MIN_SUPPORT = "ROGUE_PREFIRE_MIN_SUPPORT"
ENV_CANARY = "ROGUE_PREFIRE_FIRE_ALL_FRAC"  # deterministic fraction of skips force-fired (default .15)
ENV_EMBED = "ROGUE_PREFIRE_EMBED"          # on (default) | off — compute serve-time embeddings

DEFAULT_MODEL_PATH = "data/models/prefire_scorer.json"
DEFAULT_CANARY_FRAC = 0.15
DEFAULT_SKIP_THRESHOLD = 0.15  # fallback when neither the env nor the model recommends one


@dataclass
class PrefireDecision:
    primitive: AttackPrimitive
    score: float
    fire: bool
    reason: str  # "" (fired normally) | "novel_family" | "low_support" | "canary" | "low_score"


@dataclass
class PrefirePlan:
    """The gate's decision for one (corpus × config): which attacks to fire, which to skip."""

    fired: list[AttackPrimitive]
    skipped: list[PrefireDecision] = field(default_factory=list)
    decisions: list[PrefireDecision] = field(default_factory=list)
    enabled: bool = True

    def summary(self) -> str:
        forced = sum(1 for d in self.decisions if d.reason in ("novel_family", "low_support", "canary"))
        return (
            f"pre-fire gate: {len(self.fired)} fired, {len(self.skipped)} skipped "
            f"(predicted non-breach), {forced} force-fired by drift-guard/canary"
        )


@dataclass
class PrefireGate:
    """Holds a predictor + policy + embed fn and turns (primitives, config) into a fire/skip plan."""

    predictor: PrefirePredictor
    embed_fn: EmbedFn | None = None
    enabled: bool = True
    min_support: int = DEFAULT_MIN_SUPPORT
    skip_threshold: float | None = None
    canary_frac: float = DEFAULT_CANARY_FRAC
    _embed_warned: bool = False

    def _canary(self, primitive_id: str) -> bool:
        if self.canary_frac <= 0:
            return False
        h = hashlib.sha256(f"prefire-canary:{primitive_id}".encode()).digest()
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

    def _embed(self, p: AttackPrimitive) -> list[float] | None:
        if self.embed_fn is None:
            return None
        try:
            return self.embed_fn(p.payload_template or " ")
        except Exception as e:  # noqa: BLE001 — embeddings unreachable must degrade, never abort
            if not self._embed_warned:
                _log.warning("pre-fire: embedding unavailable (%s) — scoring on structure alone", e)
                self._embed_warned = True
            return None

    def plan(self, primitives: list[AttackPrimitive], config: DeploymentConfig) -> PrefirePlan:
        cf = derive_config_features(config.target_model, base_url=getattr(config, "base_url", None))
        fired: list[AttackPrimitive] = []
        skipped: list[PrefireDecision] = []
        decisions: list[PrefireDecision] = []
        for p in primitives:
            emb = self._embed(p)
            feats = build_prefire_features(p, config, emb, self.predictor.affinity, config_features=cf)
            score = self.predictor.score_one(feats)
            forced, reason = self._forced(p)
            if not forced and self.skip_threshold is not None and score < self.skip_threshold:
                d = PrefireDecision(p, score, fire=False, reason="low_score")
                skipped.append(d)
            else:
                d = PrefireDecision(p, score, fire=True, reason=reason)
                fired.append(p)  # input order preserved — Q7 skips, it does not reorder
            decisions.append(d)
        return PrefirePlan(fired=fired, skipped=skipped, decisions=decisions, enabled=True)


def _disabled_plan(primitives: list[AttackPrimitive]) -> PrefirePlan:
    return PrefirePlan(fired=list(primitives), enabled=False)


def resolve_prefire_gate(
    *, predictor: PrefirePredictor | None = None, embed_fn: EmbedFn | None = None
) -> PrefireGate | None:
    """Build a gate from the environment, or ``None`` when pre-fire skipping is off / no model exists.

    Off unless ``ROGUE_PREFIRE_SKIP`` ∈ {on,1,true}. When on, loads ``ROGUE_PREFIRE_MODEL`` (default
    ``data/models/prefire_scorer.json``); a missing/stale artifact yields ``None`` (the scan then fires
    everything, today's behaviour) rather than a hard failure — the gate is an optimisation, never a
    dependency of a scan completing. The skip threshold defaults to the model's held-out
    ``recommended_threshold`` (the P that still recovers 95% of breaches) when the env doesn't set one.
    """
    mode = os.environ.get(ENV_SKIP, "off").strip().lower()
    if mode not in ("on", "1", "true", "yes"):
        return None
    if predictor is None:
        path = os.environ.get(ENV_MODEL, DEFAULT_MODEL_PATH)
        if not os.path.exists(path):
            _log.warning("pre-fire gate on but no model at %r — firing all (today's order)", path)
            return None
        try:
            predictor = PrefirePredictor.load(path)
        except Exception as e:  # noqa: BLE001 — a bad artifact must not break the scan
            _log.warning("pre-fire gate: failed to load %r (%s) — firing all", path, e)
            return None

    thr_raw = os.environ.get(ENV_THRESHOLD)
    if thr_raw not in (None, ""):
        skip_threshold: float | None = float(thr_raw)
    else:
        rec = predictor.metrics.get("recommended_threshold")
        skip_threshold = float(rec) if rec is not None else DEFAULT_SKIP_THRESHOLD

    min_support = int(os.environ.get(ENV_MIN_SUPPORT, DEFAULT_MIN_SUPPORT))
    canary = float(os.environ.get(ENV_CANARY, DEFAULT_CANARY_FRAC))

    if embed_fn is None and os.environ.get(ENV_EMBED, "on").strip().lower() in ("on", "1", "true", "yes"):
        from rogue.retrieval.embed import default_embed_fn  # noqa: PLC0415

        embed_fn = default_embed_fn()

    return PrefireGate(
        predictor=predictor, embed_fn=embed_fn, enabled=True,
        min_support=min_support, skip_threshold=skip_threshold, canary_frac=canary,
    )


def apply_prefire_skip_pairs(
    pairs: list[tuple[AttackPrimitive, DeploymentConfig]],
    *,
    gate: PrefireGate | None = None,
) -> tuple[
    list[tuple[AttackPrimitive, DeploymentConfig]],
    list[tuple[AttackPrimitive, DeploymentConfig, float]],
    bool,
]:
    """Sweep-side entry: score a flat (primitive × config) list and skip the predicted-non-breach pairs.

    Returns ``(fired_pairs, skipped, enabled)``. When the gate is off (env unset / no model) returns the
    input unchanged with ``enabled=False`` — byte-identical. Unlike the per-config ``apply_prefire_skip``,
    this is ONLY ever called under an explicit opt-in on the research sweep (dropping cells there would
    corrupt the breach matrix and the predictor's own future training labels), so the caller gates it.
    Embeddings are computed once per distinct primitive and cached across its configs.
    """
    gate = gate if gate is not None else resolve_prefire_gate()
    if gate is None or not pairs:
        return pairs, [], False
    emb_cache: dict[str, list[float] | None] = {}
    cf_cache: dict[str, object] = {}
    fired: list[tuple[AttackPrimitive, DeploymentConfig]] = []
    skipped: list[tuple[AttackPrimitive, DeploymentConfig, float]] = []
    for p, c in pairs:
        if p.primitive_id not in emb_cache:
            emb_cache[p.primitive_id] = gate._embed(p)
        key = getattr(c, "config_id", None) or c.target_model
        cf = cf_cache.get(key)
        if cf is None:
            cf = derive_config_features(c.target_model, base_url=getattr(c, "base_url", None))
            cf_cache[key] = cf
        feats = build_prefire_features(
            p, c, emb_cache[p.primitive_id], gate.predictor.affinity, config_features=cf
        )
        score = gate.predictor.score_one(feats)
        forced, _ = gate._forced(p)
        if not forced and gate.skip_threshold is not None and score < gate.skip_threshold:
            skipped.append((p, c, score))
        else:
            fired.append((p, c))
    _log.info("pre-fire sweep: %d pairs, %d skipped (predicted non-breach)", len(pairs), len(skipped))
    return fired, skipped, True


def apply_prefire_skip(
    primitives: list[AttackPrimitive],
    config: DeploymentConfig,
    *,
    gate: PrefireGate | None = None,
) -> PrefirePlan:
    """The one call a scan makes. Resolves the gate from env when not injected; returns a disabled plan
    (everything fired, input order) when pre-fire skipping is off — a single uniform surface."""
    gate = gate if gate is not None else resolve_prefire_gate()
    if gate is None or not primitives:
        return _disabled_plan(primitives)
    plan = gate.plan(primitives, config)
    _log.info("%s", plan.summary())
    return plan


__all__ = [
    "PrefireGate",
    "PrefirePlan",
    "PrefireDecision",
    "resolve_prefire_gate",
    "apply_prefire_skip",
    "apply_prefire_skip_pairs",
    "DEFAULT_MODEL_PATH",
    "ENV_SKIP",
    "ENV_MODEL",
    "ENV_THRESHOLD",
]
