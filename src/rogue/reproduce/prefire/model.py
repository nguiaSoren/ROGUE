"""The pre-fire predictor: reuse Q11's logistic head, add Platt calibration → a real probability.

Two reasons this is a thin layer over ``survival.model.SurvivalPredictor`` and not a fresh learner:

* **Same learner, honestly comparable.** The base head is the *identical* L2-logistic IRLS solve Q11
  ships (numpy-only, deterministic, no new dependency). Q7's only additions to the model itself are the
  three affinity columns (see ``features.py``) and a calibration wrapper — so the ablation that decides
  whether the embedding earns its place is a genuine apples-to-apples comparison.

* **Calibration is Q7's job, not Q11's.** Q11 needs an *ordering*; Q7 needs an absolute probability it
  can threshold ("skip if P(breach) < τ") and hand to the Q18 acquisition score (uncertainty =
  |P−0.5|). A raw logistic sigmoid on a 16%-positive set is systematically over/under-confident, so we
  fit **Platt scaling** — ``P_cal = σ(a·logit(P_raw) + b)`` — on a held-out calibration slice. None of
  the three grounding papers calibrates its score to a probability, so this is genuinely beyond them.
  ``a,b`` are fit with the same IRLS routine (1-D), so still no new dependency.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from rogue.reproduce.prefire.embedding_affinity import EmbeddingAffinity
from rogue.reproduce.prefire.features import PREFIRE_FEATURE_DIM, PREFIRE_SCHEMA_VERSION
from rogue.reproduce.survival.model import SurvivalPredictor

_EPS = 1e-6


def _sigmoid(z: np.ndarray) -> np.ndarray:
    out = np.empty_like(z, dtype=np.float64)
    pos = z >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-z[pos]))
    ez = np.exp(z[~pos])
    out[~pos] = ez / (1.0 + ez)
    return out


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=np.float64), _EPS, 1.0 - _EPS)
    return np.log(p / (1.0 - p))


@dataclass
class PlattCalibrator:
    """1-D Platt recalibration of a base probability: ``σ(a·logit(p)+b)``. Identity until fit."""

    a: float = 1.0
    b: float = 0.0
    fitted: bool = False

    @classmethod
    def fit(cls, base_probs, labels, *, l2: float = 1e-6) -> "PlattCalibrator":
        z = _logit(np.asarray(base_probs, dtype=np.float64))
        y = np.asarray(labels, dtype=np.float64).ravel()
        if len(z) < 4 or y.min() == y.max():
            return cls()  # too little / one-class calibration data → leave the base score untouched
        # Reuse the survival IRLS solve on a single feature column; weights are [bias, slope].
        head = SurvivalPredictor.fit(z[:, None], y, l2=l2)
        return cls(a=float(head.weights[1]), b=float(head.weights[0]), fitted=True)

    def transform(self, base_probs) -> np.ndarray:
        z = _logit(np.asarray(base_probs, dtype=np.float64))
        return _sigmoid(self.a * z + self.b)

    def to_dict(self) -> dict:
        return {"a": self.a, "b": self.b, "fitted": self.fitted}

    @classmethod
    def from_dict(cls, d: dict) -> "PlattCalibrator":
        return cls(a=d.get("a", 1.0), b=d.get("b", 0.0), fitted=d.get("fitted", False))


@dataclass
class PrefirePredictor:
    """A trained pre-fire scorer: base logistic head + embedding affinity + Platt calibrator.

    ``family_support`` mirrors survival's — distinct primitives per family in training — and the gate
    fires-all for any family below ``min_support`` (Kirch's OOD collapse made operational). ``predict_proba``
    returns the **calibrated** probability by default; the raw head score is available for the ablation.
    """

    base: SurvivalPredictor
    affinity: EmbeddingAffinity
    calibrator: PlattCalibrator = field(default_factory=PlattCalibrator)
    family_support: dict[str, int] = field(default_factory=dict)
    class_prior: float = 0.5
    l2: float = 1.0
    n_train: int = 0
    schema_version: int = PREFIRE_SCHEMA_VERSION
    feature_dim: int = PREFIRE_FEATURE_DIM
    metrics: dict = field(default_factory=dict)

    # ---- inference -------------------------------------------------------------------------------
    def predict_proba(self, X, *, calibrated: bool = True) -> np.ndarray:
        raw = self.base.predict_proba(X)
        if calibrated and self.calibrator.fitted:
            return self.calibrator.transform(raw)
        return raw

    def score_one(self, features: list[float], *, calibrated: bool = True) -> float:
        return float(self.predict_proba(np.asarray([features], dtype=np.float64), calibrated=calibrated)[0])

    # ---- construction ----------------------------------------------------------------------------
    @classmethod
    def cold(cls, class_prior: float = 0.5) -> "PrefirePredictor":
        """An untrained scorer that returns ``class_prior`` for every row (no artifact yet). Ranking is
        then a no-op and — because the score equals the base rate — a sensible skip threshold never
        fires, so a missing model can never silently start dropping trials."""
        w = np.zeros(PREFIRE_FEATURE_DIM + 1)
        cp = min(max(class_prior, _EPS), 1 - _EPS)
        w[0] = float(np.log(cp / (1 - cp)))
        base = SurvivalPredictor(weights=w, n_train=0, class_prior=class_prior)
        return cls(
            base=base,
            affinity=EmbeddingAffinity(global_breach=None, global_safe=None),
            class_prior=class_prior,
        )

    # ---- persistence -----------------------------------------------------------------------------
    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.schema_version,
            "feature_dim": self.feature_dim,
            "weights": self.base.weights.tolist(),
            "affinity": self.affinity.to_dict(),
            "calibrator": self.calibrator.to_dict(),
            "class_prior": self.class_prior,
            "l2": self.l2,
            "n_train": self.n_train,
            "family_support": self.family_support,
            "metrics": self.metrics,
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "PrefirePredictor":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("schema_version") != PREFIRE_SCHEMA_VERSION:
            raise ValueError(
                f"prefire model schema {data.get('schema_version')} != current "
                f"{PREFIRE_SCHEMA_VERSION}; retrain"
            )
        if data.get("feature_dim") != PREFIRE_FEATURE_DIM:
            raise ValueError(
                f"prefire model feature_dim {data.get('feature_dim')} != current "
                f"{PREFIRE_FEATURE_DIM}; retrain"
            )
        base = SurvivalPredictor(
            weights=np.asarray(data["weights"], dtype=np.float64),
            class_prior=data.get("class_prior", 0.5),
            l2=data.get("l2", 1.0),
            n_train=data.get("n_train", 0),
        )
        m = cls(
            base=base,
            affinity=EmbeddingAffinity.from_dict(data.get("affinity", {})),
            calibrator=PlattCalibrator.from_dict(data.get("calibrator", {})),
            family_support=data.get("family_support", {}),
            class_prior=data.get("class_prior", 0.5),
            l2=data.get("l2", 1.0),
            n_train=data.get("n_train", 0),
        )
        m.metrics = data.get("metrics", {})
        return m


__all__ = ["PrefirePredictor", "PlattCalibrator"]
