"""Surface 1 OFFENSE — client policy → custom attack pack → per-rule breach report (build-04).

The offensive surface that turns a customer's plain-language policy into a per-rule
breach report: decompose the policy into typed rules, re-aim harvested attack families
at each rule, judge each with a per-rule (area-02) judge, score how hard the pack
exercises the rule, and roll it up into a CI-bearing, honestly-calibrated report with
attestation-ready rows.

Public surface (functions land per build wave):
  decompose_policy          §3  — policy text → ClientPolicy            (Wave 2)
  build_attack_pack         §3  — PolicyRule → RuleAttackPack           (Wave 2)
  instantiate_rule_judge    §4  — PolicyRule → a per-rule judge         (Wave 2)
  score_pack_coverage       §5  — RuleAttackPack → coverage score       (Wave 2)
  build_rule_breach_report  §6  — trials → RuleBreachReport             (Wave 3)
  run_policy_scan           §6  — orchestration over the existing scan  (Wave 3)

Wire schemas (built in Wave 1) live in ``rogue.schemas.governance`` and are
re-exported here for convenience.
"""

from rogue.schemas.governance import (
    BreachType,
    CalibrationStatus,
    ClientPolicy,
    CoverageStatus,
    PolicyRule,
    RuleAttackPack,
    RuleBreachReport,
    RuleVerdict,
)

__all__ = [
    "BreachType",
    "CalibrationStatus",
    "ClientPolicy",
    "CoverageStatus",
    "PolicyRule",
    "RuleAttackPack",
    "RuleBreachReport",
    "RuleVerdict",
]
