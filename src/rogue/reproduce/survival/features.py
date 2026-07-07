"""Survival-predictor feature extraction — the black-box, embedding-free descriptor.

Q11 asks: *given a harvested attack and a target deployment config, will the attack survive
the system-prompt / context change and still breach?* The three load-bearing papers all answer a
neighbouring question with **white-box** signals — Kirch (2411.03343) and Ball (2406.09289) probe a
model's hidden activations; Helm (2605.26409) embeds a model's *responses* into a behavioural
geometry. ROGUE's targets are closed API endpoints: no activations, and probing responses costs the
very budget we are trying to save. So we predict from features we already own for free at scan time —
the attack's **surface** (family, vector, requirements, provenance scores, payload shape) crossed with
a cheap **descriptor of the target config** (size/context/tools/multimodal + system-prompt class).

The feature vector is fixed-order and versioned (``SCHEMA_VERSION``): the model artifact records the
schema it was trained under, and serving rebuilds the identical layout, so train/serve can never drift
silently. One-hots range over the **frozen** ``AttackFamily`` / ``AttackVector`` enums (§4.2, frozen
Day 0) plus a trailing "unknown" slot, so a novel/emergent label lands in a stable bucket rather than
shifting every downstream index — and the drift-guard (see ``gate.py``) treats exactly that bucket as
fire-all, which is Kirch's out-of-distribution failure made operational.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from rogue.reproduce.config_features import ConfigFeatures, derive_config_features
from rogue.schemas import AttackPrimitive, DeploymentConfig
from rogue.schemas.attack_primitive import AttackFamily, AttackVector

# Bump when the feature layout changes — a model artifact trained under an older version is refused
# by SurvivalPredictor.load rather than silently mis-fed.
SCHEMA_VERSION = 1

# Frozen enum orders → stable one-hot indices. A trailing slot absorbs anything outside the enum.
_FAMILIES: tuple[str, ...] = tuple(f.value for f in AttackFamily)
_VECTORS: tuple[str, ...] = tuple(v.value for v in AttackVector)

_SIZE_CLASSES = ("small", "medium", "large")
_CONTEXT_BUCKETS = ("short", "medium", "long", "xlong", "unknown")

# Keyword heuristic: does this system prompt actively assert a safety boundary? Cheap, black-box, and
# only a weak feature — the reproduction still measures the truth. Lower-cased substring match.
_SAFETY_MARKERS = (
    "refuse", "must not", "do not", "cannot", "policy", "safety", "safe",
    "harmful", "illegal", "unethical", "not allowed", "decline", "guideline",
)


def _onehot(value: str, vocab: tuple[str, ...]) -> list[float]:
    """One-hot over ``vocab`` with a trailing 'unknown' slot (len == len(vocab)+1)."""
    vec = [0.0] * (len(vocab) + 1)
    try:
        vec[vocab.index(value)] = 1.0
    except ValueError:
        vec[-1] = 1.0
    return vec


def _len_bucket(n: int) -> float:
    """log1p(n) squashed to ~[0,1] — a smooth length feature that is robust to outliers."""
    return math.log1p(max(0, n)) / 12.0  # log1p(160k) ≈ 12 → payloads saturate near 1.0


@dataclass(frozen=True)
class SystemPromptDescriptor:
    """A tiny, comparable summary of a config's system prompt — the axis Q11 says survival hinges on.

    Derived purely from the config (no model call). ``sp_class`` is the coarse bucket the backtest
    groups on to prove *cross-system-prompt* generalization (an attack that breaches config A must be
    shown to still breach a config B whose ``sp_class`` differs)."""

    length: int
    has_prompt: bool
    has_safety_directive: bool
    n_forbidden_topics: int
    n_declared_tools: int

    @property
    def sp_class(self) -> str:
        """Coarse system-prompt class: none | permissive | guarded-short | guarded-long."""
        if not self.has_prompt:
            return "none"
        if not self.has_safety_directive:
            return "permissive"
        return "guarded-long" if self.length >= 600 else "guarded-short"

    def to_features(self) -> list[float]:
        return [
            1.0 if self.has_prompt else 0.0,
            1.0 if self.has_safety_directive else 0.0,
            _len_bucket(self.length),
            _len_bucket(self.n_forbidden_topics),
            _len_bucket(self.n_declared_tools),
        ]


def describe_system_prompt(config: DeploymentConfig) -> SystemPromptDescriptor:
    sp = config.system_prompt or ""
    low = sp.lower()
    return SystemPromptDescriptor(
        length=len(sp),
        has_prompt=bool(sp.strip()),
        has_safety_directive=any(m in low for m in _SAFETY_MARKERS),
        n_forbidden_topics=len(config.forbidden_topics or []),
        n_declared_tools=len(config.declared_tools or []),
    )


def is_novel_family(primitive: AttackPrimitive) -> bool:
    """A primitive the frozen taxonomy does not cleanly cover — the drift-guard fire-all trigger.

    True when the extractor flagged the technique as a novel taxonomy fit or attached a free-text
    ``emergent_label`` (an out-of-enum technique). These are exactly Kirch's held-out-attack regime:
    the predictor has no in-distribution evidence, so ``gate.py`` refuses to skip them."""
    return primitive.taxonomy_fit == "novel" or bool(primitive.emergent_label)


def primitive_features(primitive: AttackPrimitive) -> list[float]:
    """Surface features of the attack itself — all free at scan time, no embedding, no model call."""
    repro = max(0, min(10, primitive.reproducibility_score)) / 10.0
    authorship = primitive.authorship_score
    n_turns = len(primitive.multi_turn_sequence or []) or (
        len((primitive.payload_template or "").split("---")) if primitive.requires_multi_turn else 1
    )
    feats: list[float] = []
    feats += _onehot(primitive.family.value, _FAMILIES)
    feats += _onehot(primitive.vector.value, _VECTORS)
    feats += [
        1.0 if primitive.requires_multi_turn else 0.0,
        1.0 if primitive.requires_system_prompt_access else 0.0,
        1.0 if primitive.requires_tools else 0.0,
        1.0 if primitive.requires_multimodal else 0.0,
        1.0 if primitive.synthesized else 0.0,
        1.0 if primitive.generator is not None else 0.0,
        1.0 if primitive.multi_turn_sequence else 0.0,
        1.0 if is_novel_family(primitive) else 0.0,
        repro,
        authorship if authorship is not None else 0.5,
        1.0 if authorship is None else 0.0,  # missing-authorship flag
        _len_bucket(len(primitive.payload_template or "")),
        _len_bucket(n_turns),
    ]
    return feats


def config_features_vec(cf: ConfigFeatures, spd: SystemPromptDescriptor) -> list[float]:
    """Descriptor of the target the attack is being fired at — size/context/tools + system-prompt class."""
    feats: list[float] = []
    feats += _onehot(cf.size_class, _SIZE_CLASSES)
    feats += _onehot(cf.context_bucket, _CONTEXT_BUCKETS)
    feats += [
        1.0 if cf.supports_tools else 0.0,
        1.0 if cf.multimodal else 0.0,
    ]
    feats += spd.to_features()
    return feats


def build_features(
    primitive: AttackPrimitive,
    config: DeploymentConfig,
    *,
    config_features: ConfigFeatures | None = None,
) -> list[float]:
    """The full (primitive × target-config) feature row. Order is fixed and versioned.

    ``config_features`` may be passed pre-derived to avoid recomputing the ModelSpec lookup once per
    primitive in a scan of hundreds — the descriptor is identical for every primitive in one scan.

    ``config`` is duck-typed: a Pydantic ``DeploymentConfig`` (scan time) or an ORM row (training,
    which has no ephemeral ``base_url`` attribute) both work — hence ``getattr`` for ``base_url``."""
    cf = config_features or derive_config_features(
        config.target_model, base_url=getattr(config, "base_url", None)
    )
    spd = describe_system_prompt(config)
    return primitive_features(primitive) + config_features_vec(cf, spd)


# Number of dims the layout emits — asserted in tests so a silent layout change trips a red bar.
FEATURE_DIM = (
    (len(_FAMILIES) + 1) + (len(_VECTORS) + 1) + 13          # primitive block
    + (len(_SIZE_CLASSES) + 1) + (len(_CONTEXT_BUCKETS) + 1) + 2 + 5  # config block
)


def feature_names() -> list[str]:
    """Human-readable feature names, same order as ``build_features`` — for model introspection/docs."""
    names = [f"family={f}" for f in (*_FAMILIES, "unknown")]
    names += [f"vector={v}" for v in (*_VECTORS, "unknown")]
    names += [
        "requires_multi_turn", "requires_system_prompt_access", "requires_tools",
        "requires_multimodal", "synthesized", "has_generator", "has_multi_turn_seq",
        "is_novel_family", "reproducibility_score", "authorship_score", "authorship_missing",
        "payload_len", "n_turns",
    ]
    names += [f"cfg_size={s}" for s in (*_SIZE_CLASSES, "unknown")]
    names += [f"cfg_ctx={c}" for c in (*_CONTEXT_BUCKETS, "unknown")]
    names += ["cfg_supports_tools", "cfg_multimodal"]
    names += ["sp_has_prompt", "sp_has_safety", "sp_len", "sp_n_forbidden", "sp_n_tools"]
    return names


__all__ = [
    "SCHEMA_VERSION",
    "FEATURE_DIM",
    "SystemPromptDescriptor",
    "describe_system_prompt",
    "is_novel_family",
    "primitive_features",
    "config_features_vec",
    "build_features",
    "feature_names",
]
