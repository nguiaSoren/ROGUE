"""System-prompt-transfer survival prediction (Q11).

Rank harvested attacks by predicted survival across a config change, so ROGUE fires the ~few percent
that will still breach first and defers the rest — instead of spending most of the reproduce budget on
attacks that won't transfer. Black-box (no model internals), embedding-free at serve time, trained on
``breach_results`` ROGUE has already paid for.

* ``features`` — the (attack surface × target-config) descriptor.
* ``model``    — a numpy L2-logistic head with versioned save/load.
* ``train``    — fit + offline back-test (precision@k, budget-saved) from historical breach data.
* ``gate``     — the live serving surface: ``apply_survival_order`` reorders a scan's primitives.

Design notes and the paper grounding (Kirch 2411.03343, Helm 2605.26409, Ball 2406.09289) live in
``docs/research/survival_predictor.md``.
"""

from rogue.reproduce.survival.gate import (
    SurvivalGate,
    SurvivalPlan,
    apply_survival_order,
    resolve_gate,
)
from rogue.reproduce.survival.model import SurvivalPredictor

__all__ = [
    "SurvivalPredictor",
    "SurvivalGate",
    "SurvivalPlan",
    "apply_survival_order",
    "resolve_gate",
]
