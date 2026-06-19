"""Wire schemas for Surface 1 OFFENSE — client policy → per-rule breach report (build-04 §2).

The breach-type vocabulary is SHARED with area 02 (the judge): the values of
:class:`BreachType` are exactly the keys of ``rogue.reproduce.rubrics.REGISTRY``
(``tests/test_governance_schemas.py`` asserts they never drift — one vocabulary,
both areas). REUSE ``AttackFamily`` / ``AttackPrimitive`` from ``rogue.schemas`` —
never duplicate (CLAUDE.md schema convention).

Honesty invariant (ADR-0011): ``RuleVerdict.calibration_status`` defaults to
``"uncalibrated"`` and a CI is never fabricated for an un-calibrated breach type.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

from rogue.schemas import AttackFamily, AttackPrimitive


class BreachType(str, Enum):
    """The consummation shape of a policy rule.

    The join key between a rule, its per-rule judge instantiation (§4), and
    area-02's per-breach-type calibration set. Values are identical to the keys of
    ``rogue.reproduce.rubrics.REGISTRY`` so the policy layer and the judge layer
    share one vocabulary that cannot drift.
    """

    CAPABILITY_TRANSFER = "capability_transfer"          # the original harm case
    INFORMATION_DISCLOSURE = "information_disclosure"     # did the protected datum appear
    UNAUTHORIZED_ACTION = "unauthorized_action"           # did the agent execute
    FABRICATED_SENSITIVE_VALUE = "fabricated_sensitive_value"  # asserted a fabricated value as real


class CoverageStatus(str, Enum):
    """How hard a rule's attack pack actually exercises the rule (build-04 §5).

    Gates whether a ``holds`` verdict is load-bearing: a ``holds`` backed by an
    ``inadequate`` pack is reported as "holds (low coverage)", not a strong pass.
    """

    ADEQUATE = "adequate"
    LOW = "low"
    INADEQUATE = "inadequate"


# Two distinct provenances must never be conflated (ADR-0011): the trial-outcome CI
# (bootstrapped from this scan's breach/no-breach trials) vs. whether the judge for
# this breach type was independently calibrated at all.
CalibrationStatus = Literal["calibrated", "uncalibrated"]


class PolicyRule(BaseModel):
    """One plain-language client rule, typed for offense + judging.

    ``consummation_definition`` + the example pairs are the heart: they feed both the
    per-rule judge (the engagement-vs-consummation boundary) and coverage scoring.
    """

    rule_id: str = Field(..., min_length=1, description="stable id within the policy, e.g. 'R1'")
    text: str = Field(..., min_length=1, description="the plain-language client rule, verbatim")
    breach_type: BreachType
    elicitation_target: str = Field(
        ..., min_length=1, description="what an attack must make the agent produce or do"
    )
    consummation_definition: str = Field(
        ..., min_length=1, description="what counts as breaking THIS rule (feeds the judge criterion)"
    )
    forbidden_examples: list[str] = Field(
        default_factory=list, description="responses that DO breach (consummation) — the positive boundary"
    )
    allowed_examples: list[str] = Field(
        default_factory=list, description="responses that engage but do NOT breach — the negative boundary"
    )


class ClientPolicy(BaseModel):
    """A customer's policy decomposed into typed rules (output of §3 decompose_policy)."""

    policy_id: str = Field(..., min_length=1)
    customer_id: str = Field(..., min_length=1)
    rules: list[PolicyRule] = Field(default_factory=list)
    source_text: str = Field("", description="the raw policy text that was decomposed")


class RuleAttackPack(BaseModel):
    """The re-aimed harvested-family primitives that exercise one rule (output of §3 reaim)."""

    rule_id: str = Field(..., min_length=1)
    primitives: list[AttackPrimitive] = Field(default_factory=list)
    coverage_score: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="§5 pack-strength score; None until scored"
    )
    coverage_status: Optional[CoverageStatus] = None


class RuleVerdict(BaseModel):
    """Per-rule rollup over trials (a row of the report).

    ``ci_low``/``ci_high`` are the **trial-outcome** bootstrap CI on this scan's
    breach rate. ``calibration_status``/``judge_precision`` come from **area 02** and
    describe the judge, not this scan — two provenances, kept separate (ADR-0011).
    """

    rule_id: str = Field(..., min_length=1)
    breach_type: BreachType
    attack_family: Optional[AttackFamily] = None
    n_trials: int = Field(0, ge=0)
    n_breaches: int = Field(0, ge=0)
    breach_rate: float = Field(0.0, ge=0.0, le=1.0)
    ci_low: Optional[float] = Field(None, ge=0.0, le=1.0, description="trial-outcome bootstrap CI lower")
    ci_high: Optional[float] = Field(None, ge=0.0, le=1.0, description="trial-outcome bootstrap CI upper")
    calibration_status: CalibrationStatus = Field(
        "uncalibrated", description="honest default — never claim calibrated without area-02 evidence"
    )
    judge_precision: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="per-breach-type precision from area 02; None iff uncalibrated"
    )
    coverage_status: Optional[CoverageStatus] = None
    transcript_refs: list[str] = Field(default_factory=list)

    @property
    def holds(self) -> bool:
        """True iff the rule was not breached in any trial (the report's 'holds' line)."""
        return self.n_breaches == 0


class RuleBreachReport(BaseModel):
    """The Surface-1 deliverable: per-rule verdicts + a 'holds against N/M' rollup (§6)."""

    policy_id: str = Field(..., min_length=1)
    config_id: str = Field(..., min_length=1, description="the DeploymentConfig under test")
    rule_verdicts: list[RuleVerdict] = Field(default_factory=list)
    holds_count: int = Field(0, ge=0)
    total_count: int = Field(0, ge=0)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
