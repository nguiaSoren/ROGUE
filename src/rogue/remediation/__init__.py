"""Surface 1b — assurance-native measured remediation (build-05).

ROGUE *generates and verifies* a mitigation for a breach and NEVER enforces it at runtime
(ADR-0010): a breach (Surface 1) → a generated candidate → re-test vs the attack family
(breach rate ↓) → re-test vs an independent legitimate-traffic set (over-block ≈ 0, scored by
the same judge-v3 gate — no new model) → accept/iterate → the proven artifact rolls into the
attestation record; the client deploys it into their own runtime.

Thin orchestration over existing assets (scan engine + per-rule judge); composes them rather
than living inside them. Wire schemas live in ``rogue.schemas.remediation`` (the schema
convention) and are re-exported here. Function surfaces (generate §4 / retest §6 / loop §7) are
wired in as their modules land.
"""

from rogue.schemas.remediation import (
    CONFIG_APPLICABLE,
    MitigationCandidate,
    MitigationType,
    OverBlockCheck,
    RemediationResult,
)

__all__ = [
    "MitigationType",
    "MitigationCandidate",
    "OverBlockCheck",
    "RemediationResult",
    "CONFIG_APPLICABLE",
]
