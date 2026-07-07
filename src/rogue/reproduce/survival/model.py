"""The survival predictor — an L2-regularized logistic head, numpy-only, black-box, deterministic.

Why logistic regression and not a gradient-boosted forest (as the Elicit brief loosely suggested)?
Three reasons that fit ROGUE's context: (1) the training set is small — historical ``breach_results``
is thousands of rows, not millions — where a linear model with strong L2 out-generalizes a boosted
forest and will not memorize a handful of prolific primitives; (2) it adds **no new dependency**
(ROGUE ships numpy for pgvector work; sklearn/torch are deliberately absent, per the stack
discipline); (3) the coefficients are directly inspectable, so a "why did this rank high" answer is a
dot product, which matters for a security product whose users need to trust the ordering. Kirch's own
probes were logistic; their finding was that the *features* (white-box activations) don't transfer
out-of-distribution — not that the classifier was too weak. We inherit that lesson as the drift-guard,
not as a call for a heavier model.

Fit is L2-penalised iteratively-reweighted least squares (Newton's method). The penalty makes the
Hessian strictly positive-definite, so the solve is stable even when a one-hot column is degenerate in
a small sample, and convergence is deterministic (no random init, no SGD shuffle) — the same data
yields byte-identical weights across processes, which the tests rely on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from rogue.reproduce.survival.features import FEATURE_DIM, SCHEMA_VERSION


def _sigmoid(z: np.ndarray) -> np.ndarray:
    # Numerically stable logistic.
    out = np.empty_like(z, dtype=np.float64)
    pos = z >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-z[pos]))
    ez = np.exp(z[~pos])
    out[~pos] = ez / (1.0 + ez)
    return out


@dataclass
class SurvivalPredictor:
    """A trained (or empty) survival model. ``weights`` includes a leading bias term.

    ``family_support`` records, per attack family, how many distinct primitives contributed a labeled
    training row. The gate reads it: a family below ``min_support`` has too little in-distribution
    evidence to trust a skip, so it is fired regardless of score (Kirch OOD guard).
    """

    weights: np.ndarray                    # shape (FEATURE_DIM + 1,), index 0 is bias
    schema_version: int = SCHEMA_VERSION
    class_prior: float = 0.5               # base survival rate — cold-start fallback score
    l2: float = 1.0
    n_train: int = 0
    family_support: dict[str, int] = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)  # backtest numbers, stamped by train.py

    # ---- inference -------------------------------------------------------------------------------
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """P(survive) for each row of ``X`` (shape (n, FEATURE_DIM))."""
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X[None, :]
        Xb = np.hstack([np.ones((X.shape[0], 1)), X])
        return _sigmoid(Xb @ self.weights)

    def score_one(self, features: list[float]) -> float:
        return float(self.predict_proba(np.asarray(features, dtype=np.float64))[0])

    # ---- training --------------------------------------------------------------------------------
    @classmethod
    def fit(
        cls,
        X: np.ndarray,
        y: np.ndarray,
        *,
        l2: float = 1.0,
        max_iter: int = 50,
        tol: float = 1e-6,
        family_support: dict[str, int] | None = None,
    ) -> "SurvivalPredictor":
        """L2-penalised logistic regression via Newton/IRLS. Deterministic; no random state.

        The bias term (column 0) is left unpenalised so the model can still express the base rate."""
        X = np.asarray(X, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64).ravel()
        n, d = X.shape
        Xb = np.hstack([np.ones((n, 1)), X])
        w = np.zeros(d + 1)
        # Penalty matrix: penalise every weight except the bias (index 0).
        reg = np.eye(d + 1) * l2
        reg[0, 0] = 0.0
        for _ in range(max_iter):
            p = _sigmoid(Xb @ w)
            grad = Xb.T @ (p - y) + reg @ w
            wmat = p * (1.0 - p)
            # Hessian = Xᵀ W X + reg; W diagonal. Add a tiny ridge for the degenerate all-same-p case.
            H = (Xb.T * wmat) @ Xb + reg + np.eye(d + 1) * 1e-8
            step = np.linalg.solve(H, grad)
            w = w - step
            if np.max(np.abs(step)) < tol:
                break
        prior = float(y.mean()) if n else 0.5
        return cls(
            weights=w, l2=l2, n_train=n, class_prior=prior,
            family_support=dict(family_support or {}),
        )

    @classmethod
    def cold(cls, class_prior: float = 0.5) -> "SurvivalPredictor":
        """An untrained predictor that scores every row at ``class_prior`` — used when no artifact
        exists yet. Ranking is then a no-op (stable order preserved), which is the safe default."""
        w = np.zeros(FEATURE_DIM + 1)
        # Set bias so sigmoid(bias) == class_prior.
        cp = min(max(class_prior, 1e-6), 1 - 1e-6)
        w[0] = float(np.log(cp / (1 - cp)))
        return cls(weights=w, n_train=0, class_prior=class_prior)

    # ---- persistence -----------------------------------------------------------------------------
    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.schema_version,
            "feature_dim": FEATURE_DIM,
            "weights": self.weights.tolist(),
            "class_prior": self.class_prior,
            "l2": self.l2,
            "n_train": self.n_train,
            "family_support": self.family_support,
            "metrics": self.metrics,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "SurvivalPredictor":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"survival model schema {data.get('schema_version')} != current {SCHEMA_VERSION}; retrain"
            )
        if data.get("feature_dim") != FEATURE_DIM:
            raise ValueError(
                f"survival model feature_dim {data.get('feature_dim')} != current {FEATURE_DIM}; retrain"
            )
        m = cls(
            weights=np.asarray(data["weights"], dtype=np.float64),
            schema_version=data["schema_version"],
            class_prior=data.get("class_prior", 0.5),
            l2=data.get("l2", 1.0),
            n_train=data.get("n_train", 0),
            family_support=data.get("family_support", {}),
        )
        m.metrics = data.get("metrics", {})
        return m


__all__ = ["SurvivalPredictor"]
