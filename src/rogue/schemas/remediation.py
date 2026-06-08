"""Surface 1b — measured-remediation wire schemas (build-05 §3).

The generate→verify loop's data model: a :class:`MitigationCandidate` (ROGUE's generated
artifact), an :class:`OverBlockCheck` (the independent legitimate-traffic measurement), and a
:class:`RemediationResult` (the candidate + its re-test evidence).

Two binding invariants are encoded here, not just documented:
  * **ADR-0010** — ROGUE *generates and verifies* these artifacts and NEVER enforces them at
    runtime; the ``artifact`` is data the client deploys, never something ROGUE executes.
  * **ADR-0011** — the over-block rate is scored against an *independent* legitimate-traffic set
    (``legitimate_set_ref``), never the mitigation's own claim and never the verifier's own score.

Lives in ``schemas/`` per the wire-format convention (mirrors ``schemas/governance.py``);
re-exported from ``rogue.remediation``. The breach being remediated is an area-04 ``RuleVerdict``
(a breached rule) plus its ``BreachResult`` transcripts.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class MitigationType(str, Enum):
    """Where the mitigation's runtime lives (ADR-0010). ROGUE writes + verifies every one of
    these; the CLIENT deploys + runs them — ROGUE never sits in the production request path."""

    # offline — ROGUE re-scans a mutated test config to prove the fix; client applies the real one
    SYSTEM_PROMPT_PATCH = "system_prompt_patch"
    FINETUNE_PREFERENCE_DATA = "finetune_preference_data"
    TOOL_PERMISSION_SCOPE = "tool_permission_scope"
    RETRIEVAL_CONTEXT_FIX = "retrieval_context_fix"
    ARCHITECTURE_RECOMMENDATION = "architecture_recommendation"
    # a rule the client deploys into THEIR enforcement layer (ROGUE writes+verifies, never runs it)
    GUARDRAIL_RULE = "guardrail_rule"
    # cross-surface: route the action to the Surface 2 human gate (recommend-now, measured-later)
    HUMAN_GATE_ROUTE = "human_gate_route"


# The types whose fix lives in the DeploymentConfig, so retest (§6) can prove it by re-scanning a
# mutated test config. The rest are verified-by-construction / out-of-band, or as a test-harness
# rule inside ROGUE's measurement sandbox (§6.note) — never run a real filter (ADR-0010).
CONFIG_APPLICABLE: frozenset[MitigationType] = frozenset(
    {MitigationType.SYSTEM_PROMPT_PATCH, MitigationType.TOOL_PERMISSION_SCOPE}
)


class MitigationCandidate(BaseModel):
    """One generated mitigation artifact. ROGUE's *output*; ROGUE never executes it (ADR-0010)."""

    candidate_id: str
    breach_ref: str = Field(..., description="rule_id/breach_id remediated (an area-04 RuleVerdict)")
    mitigation_type: MitigationType
    artifact: str = Field(..., description="generated patch/rule/recommendation text, or a dataset ref")
    generated_by: str = Field(..., description="model + prompt_version, for reproducibility")
    rationale: str = ""
    # HUMAN_GATE_ROUTE only: the S2-backed (measured false-approve) variant lights up once
    # Surface 2 ships (§1 S2 LINK). Defaults False so the recommend-now form never overclaims.
    measured_gate_backed: bool = False


class OverBlockCheck(BaseModel):
    """The independent over-block measurement (ADR-0011): did the mitigation block *legitimate*
    traffic the agent SHOULD answer? Scored by the same judge-v3 over-block FP mode — NO new model
    (ADR-0010). ``legitimate_set_ref`` is an authored independent set, never "what the patched
    agent now allows."""

    legitimate_set_ref: str
    n_legit: int = Field(..., ge=0)
    n_false_block: int = Field(..., ge=0)
    over_block_rate: float = Field(..., ge=0.0, le=1.0)
    ci_low: float | None = None
    ci_high: float | None = None
    judge_rubric_handle: str | None = Field(
        None, description="the per-rule (area-02) judge handle used — never a second model"
    )


class RemediationResult(BaseModel):
    """A candidate + its re-test evidence. ``accepted`` iff the breach dropped AND over-block ≈ 0
    (within CI) — the loop (§7) sets it; the schema keeps the two provenances distinct (ADR-0011)."""

    candidate: MitigationCandidate
    pre_breach_rate: float = Field(..., ge=0.0, le=1.0)
    post_breach_rate: float = Field(..., ge=0.0, le=1.0)
    post_breach_ci: tuple[float, float] | None = None
    over_block: OverBlockCheck | None = None
    accepted: bool = False
    iterations: int = Field(default=1, ge=1)
    rejected_candidates: list[MitigationCandidate] = Field(default_factory=list)
    # FINETUNE / ARCHITECTURE / HUMAN_GATE_ROUTE can't be proven by re-scanning the same config
    # (the fix lives outside the prompt/scope) — be explicit, don't fake a breach-rate delta (§6.note).
    verified_by: Literal["rescan", "by_construction_out_of_band"] = "rescan"

    @property
    def breach_reduced(self) -> bool:
        """Did the re-test show a strictly lower post-mitigation breach rate?"""
        return self.post_breach_rate < self.pre_breach_rate
