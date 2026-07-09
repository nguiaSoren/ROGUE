"""Q18 — hybrid acquisition ordering for the paid reproduction budget.

A serve-time ordering gate (sibling of ``survival`` / ``prefire``) that ranks the attacks about to be
fired by a **hybrid acquisition score** — exploitation *and* learning — instead of the static
``reproducibility_score`` order that ships today:

    score(p) = w·value + α·uncertainty + β·diversity + γ·info_gain

Off by default (``ROGUE_ACQUISITION_ORDER`` unset) → byte-identical to today. See ``gate.py`` for the
term definitions and their paper grounding (Kossen active-testing, Ma test-selection, Chung info-gain).
"""

from rogue.reproduce.acquisition.gate import (
    ENV_ORDER,
    AcquisitionGate,
    AcquisitionPlan,
    AcquisitionScore,
    apply_acquisition_order,
    apply_acquisition_order_pairs,
    build_cell_evidence,
    resolve_acquisition_gate,
)

__all__ = [
    "AcquisitionGate",
    "AcquisitionPlan",
    "AcquisitionScore",
    "apply_acquisition_order",
    "apply_acquisition_order_pairs",
    "resolve_acquisition_gate",
    "build_cell_evidence",
    "ENV_ORDER",
]
