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

from .generate import propose_candidates
from .legit_corpus import available_rule_ids, load_legit_set
from .loop import RemediationLoop, RemediationTask
from .report import remediation_attestation_rows, render_remediation_markdown
from .retest import apply_offline_mitigation, retest_vs_family, retest_vs_legitimate

__all__ = [
    # schemas
    "MitigationType",
    "MitigationCandidate",
    "OverBlockCheck",
    "RemediationResult",
    "CONFIG_APPLICABLE",
    # §4 generation
    "propose_candidates",
    # §5 legitimate-traffic corpus
    "load_legit_set",
    "available_rule_ids",
    # §6 re-test
    "apply_offline_mitigation",
    "retest_vs_family",
    "retest_vs_legitimate",
    # §7 loop
    "RemediationLoop",
    "RemediationTask",
    # §8 render + attestation rows (data level)
    "render_remediation_markdown",
    "remediation_attestation_rows",
]
