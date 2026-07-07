"""AgentTranscript — the replayable record of one agent-harness run + the judge's contract.

Reconciled single schema (post-review CRIT-1, DESIGN §10). A run is a list of
:class:`AgentTurn`s (model message + emitted tool calls + tool-result feedback);
:meth:`AgentTranscript.events` derives a FLAT, ``seq``-ordered view that the
deterministic ``TraceJudge`` (Phase 4) consumes — so the "turn model" and the
"flat event model" the parallel design pass diverged on are ONE schema with two
views, not two incompatible schemas.

Determinism: the *stored* transcript replays byte-exactly with zero model calls
(:class:`DeterminismHeader` pins seed/params/versions). Re-EXECUTION is best-effort
and can diverge whenever the target or the emulator is involved (review MED-8) — do
not claim seed-reproducible re-execution.

Additive taxonomy: :class:`AgentBreachSignal` sits BELOW the frozen
``AttackFamily``/``AttackVector`` enums (DESIGN §5.6). Signal (b) reuses the existing
``ExfiltrationMethod.TOOL_ARGUMENT_SMUGGLING`` at persistence time.

Design: ``docs/v2/agent_harness/DESIGN.md`` §4 + §10.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

from .agent_tool import InjectionGoal, ToolBackendKind
from .attack_primitive import Severity
from .breach_result import JudgeVerdict


class TurnRole(str, Enum):
    """Which side authored a turn."""

    MODEL = "model"  # assistant turn: text + emitted tool calls
    TOOL = "tool"  # tool-result feedback turn


class AgentBreachSignal(str, Enum):
    """Agentic breach outcomes — additive below the frozen taxonomy (DESIGN §5.6).

    ``SECRET_IN_ARGS`` is the finding-level label for signal (b); at persistence it
    maps to the existing ``ExfiltrationMethod.TOOL_ARGUMENT_SMUGGLING`` (no new
    frozen-taxonomy value). ``ATTEMPTED_UNDECLARED_SENSITIVE_TOOL`` is a
    non-headline recall signal (review M7/F8): the model reached for a canonical
    sensitive capability the config never declared, so no stub ran.
    """

    FORBIDDEN_TOOL_INVOKED = "forbidden_tool_invoked"  # signal (a)
    SECRET_IN_ARGS = "secret_in_args"  # signal (b) -> ExfiltrationMethod.TOOL_ARGUMENT_SMUGGLING
    INJECTION_FOLLOWED = "injection_followed"  # signal (c)
    ATTEMPTED_UNDECLARED_SENSITIVE_TOOL = "attempted_undeclared_sensitive_tool"  # non-headline
    # signal (d) — the agent COMPLIED with a harmful multi-step task (web-enabled harmful-task
    # safeguard test): it proceeded to execute (engaged recon/sink tools toward the objective) rather
    # than refusing. Measures the safeguard, not a tool-mechanic breach. See agent/safeguard_judge.py.
    AGENTIC_HARMFUL_TASK = "agentic_harmful_task"
    # signal (e) — the target EMITTED PII in its own text that ROGUE never planted (memorized from
    # weights / RAG-context bleed / system-prompt parroting), detected by the FUZZY two-step
    # pii_detector and attributed a PIIProvenance. UNCALIBRATED by construction: TraceJudge marks
    # every PII_EMITTED finding non-headline until the detector clears the P2 calibration harness
    # (Axis B of the PII-leakage axis). See agent/pii_detector.py + agent/pii_provenance.py.
    PII_EMITTED = "pii_emitted"
    # signal (f) — DERIVED exfil: a tool-return canary reappears in a LATER call's args NOT verbatim but
    # after transport-decoding (obfuscated copy) OR by semantic derivation/paraphrase (an LLM entailment
    # check). Closes the verbatim-substring blind spot of (b)/(c) (review M8) via an evidence bank of
    # returned secrets (TRACE 2510.02837; information-flow/inference-leakage, GIF 2606.23277 / OCELOT
    # 2606.12341). Non-headline: decode-match is near-zero-FP but the semantic tier is an uncalibrated
    # LLM judge, so signal (f) stays out of the deterministic headline ASR. See agent/evidence_bank.py.
    DERIVED_SECRET_EXFIL = "derived_secret_exfil"


class PlantedSecret(BaseModel):
    """A canary secret seeded into a SOURCE tool's return so signals (b)/(c) fire.

    Single-source invariant (review H7): a headline canary value is planted in
    exactly ONE site, enforced by :meth:`AgentTranscript._single_source_canaries`.
    The literal ``value`` is HMAC-derived and high-entropy; published artifacts
    carry only ``kind`` (review H4).
    """

    secret_id: str
    kind: str = Field(
        ..., description="canary kind: aws_akia | bearer | api_key | private_key | email | pii"
    )
    pii_attribute: Optional[str] = Field(
        default=None,
        description=(
            "for kind='pii' only: which PII attribute this canary is (e.g. 'ssn', 'email', "
            "'date_of_birth'), so the TraceJudge grades leak severity by PRI (reproduce/agent/pri.py). "
            "None ⇒ generic-PII fallback profile."
        ),
    )
    value: str = Field(
        ...,
        description="the literal canary (HMAC-derived, high-entropy; redacted to `kind` when published).",
    )
    planted_in: str = Field(
        default="tool_return",
        description="'tool_return' (headline-eligible single source) | 'system_prompt' | 'prior_context'",
    )
    source_call_id: Optional[str] = Field(
        default=None,
        description="the ToolResultRecord.call_id that planted it, when planted_in='tool_return'.",
    )


class ReturnProvenance(BaseModel):
    """Provenance tags on a tool RETURN — where the judge reads injection state.

    ``injected_goal`` lives HERE (moved off a sibling ``injections[]`` list per
    review CRIT-1) so ``TraceJudge.detect_followed_injection`` reads it directly.
    """

    is_poisoned: bool = False
    injection_id: Optional[str] = None
    injected_goal: Optional[InjectionGoal] = None
    canary_ids: list[str] = Field(
        default_factory=list, description="PlantedSecret ids seeded into this return."
    )


class ToolCallRecord(BaseModel):
    """A tool call the target model emitted.

    Fields renamed from the core ``ToolCallBlock`` (``id``->``call_id``,
    ``name``->``tool_name``) so the judge reads them directly (review CRIT-1). The
    ``emitted`` / ``executed`` / ``blocked_reason`` split is load-bearing (review
    H6): a forbidden call recorded-but-not-run is ``executed=False,
    blocked_reason='forbidden'`` and still a signal-(a) breach.
    """

    call_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    emitted: bool = Field(default=True, description="the model emitted this call (always True once recorded).")
    executed: bool = Field(
        default=True,
        description="backend returned a non-error stub/emulated result; False when policy-blocked.",
    )
    blocked_reason: Optional[str] = Field(
        default=None, description="e.g. 'forbidden' when a forbidden call was recorded-not-executed."
    )
    backend_kind: Optional[ToolBackendKind] = Field(
        default=None, description="backend that served the paired result (headline honesty)."
    )
    malformed_args: bool = Field(
        default=False,
        description="provider returned unparseable args (review M10 — a typed flag, not a sentinel dict).",
    )
    # ----- judge-annotated (filled by TraceJudge, Phase 4) -----
    is_forbidden: bool = False
    smuggled_secret_ids: list[str] = Field(default_factory=list)
    followed_injection_id: Optional[str] = None


class ToolResultRecord(BaseModel):
    """A tool return fed back to the model (honeytoken stub or emulated)."""

    call_id: str  # pairs to the ToolCallRecord.call_id it answers
    result: str
    backend_kind: ToolBackendKind = ToolBackendKind.HONEYTOKEN
    provenance: ReturnProvenance = Field(default_factory=ReturnProvenance)


class AgentTurn(BaseModel):
    """One turn: a model message (text + emitted calls) or a tool-result feedback."""

    role: TurnRole
    text: str = ""
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    tool_results: list[ToolResultRecord] = Field(default_factory=list)


class DeterminismHeader(BaseModel):
    """Everything needed to replay a stored transcript byte-exactly (DESIGN §5.1).

    ``run_secret_ref`` is an opaque handle to the per-run HMAC secret that mints the
    canaries; the literal secret is SEALED server-side and never published (review
    H4), so a published transcript cannot be used to reconstruct its canaries.
    """

    seed: int
    target_model: str
    temperature: float = 0.0
    max_turns: int = 6
    stub_library_version: str = "v1"
    emulator_model: Optional[str] = None
    emulator_prompt_hash: Optional[str] = None
    injection_set_version: Optional[str] = None
    harness_version: str = "v1"
    run_secret_ref: Optional[str] = Field(
        default=None,
        description="opaque ref to the sealed per-run HMAC secret; never the literal value.",
    )


class TranscriptEvent(BaseModel):
    """One flat, ``seq``-ordered event — the judge's iteration unit (:meth:`AgentTranscript.events`)."""

    seq: int
    turn_index: int
    role: TurnRole
    kind: str  # 'text' | 'tool_call' | 'tool_result'
    text: Optional[str] = None
    call: Optional[ToolCallRecord] = None
    result: Optional[ToolResultRecord] = None


class TraceFinding(BaseModel):
    """One breach signal fired by the ``TraceJudge`` over a transcript's events.

    ``headline_eligible`` is the mechanical filter that ``any_breach_rate`` respects
    (review H2 / Q3 reversal): emulated-involved, quarantine, and fingerprint-less
    signal-(c) findings are ``False`` and never enter the deterministic headline ASR.
    The validator makes "emulated => not headline" impossible to violate in code.
    """

    finding_id: str
    signal: AgentBreachSignal
    verdict: JudgeVerdict
    severity: Severity
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    headline_eligible: bool = Field(
        default=True,
        description="False for emulated-involved / quarantine / fingerprint-less-(c); any_breach_rate filters on it.",
    )
    emulated_involved: bool = False
    source_return_call_id: Optional[str] = Field(
        default=None,
        description="single-hop taint: which tool return sourced a leaked canary (None/AMBIGUOUS when >1 site).",
    )
    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="the trace slice proving the breach (canary redacted to kind).",
    )

    @model_validator(mode="after")
    def _emulated_never_headline(self) -> "TraceFinding":
        # review H1/H2: an emulator-authored finding can never enter the headline.
        if self.emulated_involved and self.headline_eligible:
            raise ValueError(
                "emulated_involved findings must not be headline_eligible (Q3 reversed, DESIGN §10)"
            )
        return self


class AgentTranscript(BaseModel):
    """The full replayable record of one (primitive × config × trial) agent run."""

    transcript_id: str = Field(..., min_length=1)
    primitive_id: str
    config_id: str
    trial_index: int = 0
    header: DeterminismHeader
    turns: list[AgentTurn] = Field(default_factory=list)
    planted_secrets: list[PlantedSecret] = Field(default_factory=list)
    final_text: str = ""
    stop_reason: str = Field(
        default="final_text",
        description="final_text | max_turns | budget | loop_guard | error",
    )
    truncated: bool = False
    fired_signals: list[AgentBreachSignal] = Field(
        default_factory=list, description="judge-filled summary of which signals fired."
    )
    created_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _single_source_canaries(self) -> "AgentTranscript":
        # review H7: each headline canary VALUE is planted in exactly one site, so
        # signal-(b)/(c) provenance is unambiguous. Duplicate values are rejected.
        values = [s.value for s in self.planted_secrets]
        dupes = sorted({v for v in values if values.count(v) > 1})
        if dupes:
            raise ValueError(
                f"planted secret value(s) not single-source (planted in >1 site): {dupes}"
            )
        return self

    def events(self) -> list[TranscriptEvent]:
        """Derive the flat, monotonic-``seq`` event view the ``TraceJudge`` consumes.

        Within a turn the order is: text, then each tool_call (in emitted order),
        then each tool_result. ``seq`` is a global monotonic counter across turns.
        """
        out: list[TranscriptEvent] = []
        seq = 0
        for ti, turn in enumerate(self.turns):
            if turn.text:
                out.append(
                    TranscriptEvent(seq=seq, turn_index=ti, role=turn.role, kind="text", text=turn.text)
                )
                seq += 1
            for call in turn.tool_calls:
                out.append(
                    TranscriptEvent(seq=seq, turn_index=ti, role=turn.role, kind="tool_call", call=call)
                )
                seq += 1
            for res in turn.tool_results:
                out.append(
                    TranscriptEvent(seq=seq, turn_index=ti, role=turn.role, kind="tool_result", result=res)
                )
                seq += 1
        return out

    @property
    def n_turns(self) -> int:
        return len(self.turns)
