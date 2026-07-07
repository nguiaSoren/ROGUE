"""Q7 pre-fire success scorer — skip low-P(breach) (attack × target) trials before spending on them.

A calibrated, black-box predictor that scores each harvested attack against the specific target config
it is about to be fired at and defers the ones it predicts won't breach — the expensive target + judge
calls are never spent on them. Off by default (``ROGUE_PREFIRE_SKIP``); a pure, visible skip when on.

It is the content-aware sibling of the Q11 survival predictor: same self-labeled join, same numpy
logistic head, same drift-guard — but Q7 adds the payload **embedding** affinity that Q11 omits, a
**Platt-calibrated** probability (which Q11 doesn't need and none of the grounding papers produce), and
a per-trial **skip** rather than a reorder. ``train.py`` reports an explicit structural-only-vs-embedding
ablation so the embedding's contribution is measured, not assumed.

Layers:
* ``embedding_affinity`` — the breach/safe centroid content feature (the axis Q11 leaves out).
* ``features`` — Q11's structural row ⊕ the affinity block (versioned).
* ``model`` — the reused logistic head + a numpy Platt calibrator.
* ``train`` — fit + group-aware back-test + ablation + calibration + recall-vs-skip curve ($0).
* ``gate`` — the live serve-time skip surface + env resolver.
"""

from rogue.reproduce.prefire.gate import (
    PrefireGate,
    PrefirePlan,
    apply_prefire_skip,
    resolve_prefire_gate,
)
from rogue.reproduce.prefire.model import PrefirePredictor

__all__ = [
    "PrefirePredictor",
    "PrefireGate",
    "PrefirePlan",
    "apply_prefire_skip",
    "resolve_prefire_gate",
]
