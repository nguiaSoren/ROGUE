"""Surface 1b — mitigation GENERATION (build-05 §4).

ROGUE *generates* a mitigation artifact for a breached rule and **NEVER executes or enforces it**
(ADR-0010): every generator below returns ONLY a :class:`MitigationCandidate` whose ``artifact`` is
data the CLIENT deploys into their own runtime. There is no request-path code here, no inline
filter, no enforcement — generation produces text/recommendations/dataset-refs and nothing more.

Generation is an LLM call over the **breach transcripts** (the breach response texts — the raw
material ROGUE already produces, spec §4.3). The LLM-call + cost-log + budget-guard plumbing PATTERN
is lifted from ``rogue.reproduce.iterative_attacker`` (lazy client, ``llm_cost_log``, a hard
per-run budget cap) — but the attacker is **not imported** (ADR-0011 independence: the thing that
generates the fix is not the thing being graded). For testability, the LLM is injected as a
``complete: (prompt) -> str`` callable, mirroring how ``endpoint_scan`` injects ``panel=``/``judge=``:
the module default is a lazy real Anthropic client; tests pass a fake that returns canned text and
never touches the network or spends.

Wire schemas (``MitigationType`` / ``MitigationCandidate``) come from ``rogue.remediation`` — never
redefined here (CLAUDE.md schema convention).
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Callable

from rogue.remediation import MitigationCandidate, MitigationType
from rogue.schemas.governance import BreachType, PolicyRule

__all__ = [
    "GENERATION_MODEL",
    "PROMPT_VERSION",
    "GenerationBudgetExceededError",
    "Completer",
    "generate_system_prompt_patch",
    "generate_finetune_preference_data",
    "recommend_tool_permission_scope",
    "recommend_retrieval_context_fix",
    "generate_grounding_patch",
    "recommend_architecture",
    "generate_guardrail_rule",
    "recommend_human_gate_route",
    "propose_candidates",
]

_log = logging.getLogger(__name__)


# The model + prompt-version recorded in every candidate's ``generated_by`` for reproducibility
# (§4 INPUT CONTRACT: ``generated_by = f"{model}@{prompt_version}"``). Bare Anthropic model id (the
# SDK takes it directly), mirroring ``iterative_attacker``'s HAIKU_MODEL/SONNET_MODEL constants.
GENERATION_MODEL = "claude-sonnet-4-6"
PROMPT_VERSION = "v1"

# Hard per-run budget cap, lifted from the iterative_attacker budget-guard pattern. Generation makes
# real LLM calls (when the default client is used) so a runaway loop is capped. Overridable via env.
DEFAULT_PER_RUN_BUDGET_USD = float(
    os.environ.get("ROGUE_REMEDIATION_PER_RUN_BUDGET_USD", "2.00")
)

_GEN_MAX_TOKENS = 1500


# A completion callable: prompt text in, generated artifact text out. The injection seam (mirrors
# ``endpoint_scan``'s ``panel=``/``judge=``): tests pass a fake; the module default lazily builds a
# real Anthropic client. Keeping it a plain callable means generation never imports the attacker.
Completer = Callable[[str], str]


class GenerationBudgetExceededError(RuntimeError):
    """Raised when the cumulative generation spend would exceed the per-run budget cap. Hard cap —
    never swallowed — so a runaway candidate-generation loop can't silently overrun the budget
    (the iterative_attacker budget-guard pattern, kept independent of the attacker)."""


# ----- The lazy default LLM client (the iterative_attacker pattern, kept attacker-independent) -----


class _LazyAnthropicCompleter:
    """Module-default ``Completer``: a lazily-constructed real Anthropic client + per-run budget
    guard + cost log. Built exactly like ``IterativeAttacker._call_anthropic`` (lazy client, usage
    block → ``llm_cost_log``, budget cap) but with NO attacker import (ADR-0011). Never constructed
    in tests — tests inject a fake ``complete`` instead, so no key/network/spend is ever touched."""

    def __init__(self, *, per_run_budget_usd: float = DEFAULT_PER_RUN_BUDGET_USD) -> None:
        self.per_run_budget_usd = per_run_budget_usd
        self.spent_usd = 0.0
        self._client = None  # type: ignore[assignment]

    def __call__(self, prompt: str) -> str:
        from anthropic import Anthropic  # noqa: PLC0415

        from rogue.reproduce.llm_cost_log import (  # noqa: PLC0415
            anthropic_call_cost_usd,
            log_anthropic_response,
        )

        if self.spent_usd >= self.per_run_budget_usd:
            raise GenerationBudgetExceededError(
                f"per_run_budget_usd={self.per_run_budget_usd:.4f} already consumed "
                f"(spent={self.spent_usd:.4f}); refusing further generation calls",
            )
        if self._client is None:
            self._client = Anthropic()
        response = self._client.messages.create(
            model=GENERATION_MODEL,
            max_tokens=_GEN_MAX_TOKENS,
            temperature=0.4,
            messages=[{"role": "user", "content": prompt}],
        )
        text_parts: list[str] = []
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", ""))
        in_tok, out_tok = log_anthropic_response(
            response,
            module="remediation.generate",
            operation="generate",
            model=GENERATION_MODEL,
            subject_id=GENERATION_MODEL,
            refused=False,
        )
        self.spent_usd += anthropic_call_cost_usd(GENERATION_MODEL, in_tok, out_tok)
        return "".join(text_parts).strip()


def _default_completer() -> Completer:
    """The module-default lazy real client. Constructed only when a generator is called WITHOUT an
    injected ``complete`` — i.e. never in tests (which always inject a fake)."""
    return _LazyAnthropicCompleter()


# ----- Helpers shared by every generator -----


def _candidate_id() -> str:
    return f"mit-{uuid.uuid4().hex[:12]}"


def _generated_by() -> str:
    """``generated_by`` per the §4 INPUT CONTRACT: ``f"{model}@{prompt_version}"``."""
    return f"{GENERATION_MODEL}@{PROMPT_VERSION}"


def _transcript_block(transcripts: list[str], *, limit: int = 6) -> str:
    """Render the breach response texts as the raw material for the generation prompt.

    The breach transcripts ARE the input contract (§4 / spec §4.3): the responses where the agent
    broke the rule. Truncated defensively (count + per-item length) to bound prompt tokens, mirroring
    ``iterative_attacker``'s ``[:6_000]`` slicing.
    """
    if not transcripts:
        return "(no breach transcripts supplied)"
    lines = []
    for i, t in enumerate(transcripts[:limit], start=1):
        lines.append(f"--- breaking response {i} ---\n{(t or '').strip()[:4_000]}")
    return "\n\n".join(lines)


def _make_candidate(
    *,
    rule: PolicyRule,
    mitigation_type: MitigationType,
    artifact: str,
    rationale: str,
    measured_gate_backed: bool = False,
) -> MitigationCandidate:
    """Assemble a typed candidate. ``breach_ref = rule.rule_id`` (§4 INPUT CONTRACT)."""
    return MitigationCandidate(
        candidate_id=_candidate_id(),
        breach_ref=rule.rule_id,
        mitigation_type=mitigation_type,
        artifact=artifact.strip(),
        generated_by=_generated_by(),
        rationale=rationale.strip(),
        measured_gate_backed=measured_gate_backed,
    )


# ----- Generators (§4) — each returns ONLY a MitigationCandidate artifact; ROGUE never runs it -----


def generate_system_prompt_patch(
    rule: PolicyRule, transcripts: list[str], *, complete: Completer | None = None
) -> MitigationCandidate:
    """Additive system-prompt text that closes ``rule`` (§4). Output is verified text only — the
    client appends it to their own system prompt; ROGUE never deploys it (ADR-0010)."""
    complete = complete or _default_completer()
    prompt = (
        "You are a security engineer hardening an AI agent. A policy rule was BREACHED. Write an "
        "ADDITIVE block of system-prompt instructions that closes this breach without otherwise "
        "changing the agent's behavior. Output ONLY the instruction text to append.\n\n"
        f"RULE: {rule.text}\n"
        f"WHAT BREAKING IT LOOKS LIKE: {rule.consummation_definition}\n\n"
        f"BREACHING RESPONSES (the agent failed here):\n{_transcript_block(transcripts)}"
    )
    artifact = complete(prompt)
    return _make_candidate(
        rule=rule,
        mitigation_type=MitigationType.SYSTEM_PROMPT_PATCH,
        artifact=artifact,
        rationale=(
            "Additive system-prompt instructions closing the breached rule; the client appends "
            "this to their agent's system prompt. ROGUE re-scans a test config to prove it."
        ),
    )


def generate_finetune_preference_data(
    rule: PolicyRule, transcripts: list[str], *, complete: Completer | None = None
) -> MitigationCandidate:
    """A dataset REF/description of ``(breaking_attempt, desired_refusal)`` preference pairs (§4).
    The artifact is a dataset specification — NOT a trained model. ROGUE never retrains; the client
    does (ADR-0010)."""
    complete = complete or _default_completer()
    prompt = (
        "You are building a preference-tuning dataset to fix a BREACHED policy rule. From the "
        "breaching responses, produce a dataset DESCRIPTION: a set of (breaking_attempt, "
        "desired_refusal) preference pairs the client can fine-tune on. Describe the pairs and "
        "give 2-3 concrete examples. Output a dataset specification ONLY — never a model.\n\n"
        f"RULE: {rule.text}\n"
        f"WHAT BREAKING IT LOOKS LIKE: {rule.consummation_definition}\n\n"
        f"BREACHING RESPONSES:\n{_transcript_block(transcripts)}"
    )
    artifact = complete(prompt)
    return _make_candidate(
        rule=rule,
        mitigation_type=MitigationType.FINETUNE_PREFERENCE_DATA,
        artifact=artifact,
        rationale=(
            "A (breaking_attempt, desired_refusal) preference-pair dataset REF, not a trained "
            "model — ROGUE never retrains; the client fine-tunes on this artifact."
        ),
    )


def recommend_tool_permission_scope(
    rule: PolicyRule, transcripts: list[str], *, complete: Completer | None = None
) -> MitigationCandidate:
    """For ``unauthorized_action``: cap/gate/remove the tool scope that let the agent commit the
    over-cap/side-effecting action (§4). A config-change RECOMMENDATION — not an enforced change."""
    complete = complete or _default_completer()
    prompt = (
        "You are reviewing an AI agent that committed an UNAUTHORIZED ACTION it should not be able "
        "to perform. Recommend a tool-permission/scope change — cap, gate behind human approval, or "
        "remove the offending tool capability — that prevents the action. Output a CONFIG-CHANGE "
        "RECOMMENDATION the client applies; do not apply it yourself.\n\n"
        f"RULE: {rule.text}\n"
        f"THE ACTION TO PREVENT: {rule.elicitation_target}\n"
        f"WHAT BREAKING IT LOOKS LIKE: {rule.consummation_definition}\n\n"
        f"BREACHING RESPONSES:\n{_transcript_block(transcripts)}"
    )
    artifact = complete(prompt)
    return _make_candidate(
        rule=rule,
        mitigation_type=MitigationType.TOOL_PERMISSION_SCOPE,
        artifact=artifact,
        rationale=(
            "A recommendation to cap/gate/remove the tool scope that enabled the unauthorized "
            "action. ROGUE recommends the config change; the client applies it."
        ),
    )


def recommend_retrieval_context_fix(
    rule: PolicyRule, transcripts: list[str], *, complete: Completer | None = None
) -> MitigationCandidate:
    """When the breach traces to poisoned/stale retrieved context, point at the context source as
    root cause (§4). Recommendation only."""
    complete = complete or _default_completer()
    prompt = (
        "You are diagnosing an AI agent breach that may have been driven by POISONED or STALE "
        "retrieved context (the agent surfaced something it should not have because its retrieval "
        "source supplied bad/leaked data). Recommend a retrieval-context fix that addresses the "
        "context source as the ROOT CAUSE. Output a RECOMMENDATION only.\n\n"
        f"RULE: {rule.text}\n"
        f"WHAT BREAKING IT LOOKS LIKE: {rule.consummation_definition}\n\n"
        f"BREACHING RESPONSES:\n{_transcript_block(transcripts)}"
    )
    artifact = complete(prompt)
    return _make_candidate(
        rule=rule,
        mitigation_type=MitigationType.RETRIEVAL_CONTEXT_FIX,
        artifact=artifact,
        rationale=(
            "Points at the retrieval/context source as the root cause of the disclosure. A "
            "recommendation the client acts on; ROGUE does not change the retrieval pipeline."
        ),
    )


def generate_grounding_patch(
    rule: PolicyRule, transcripts: list[str], *, complete: Completer | None = None
) -> MitigationCandidate:
    """For ``fabricated_sensitive_value``: a grounding rule — "never assert a sensitive value not
    returned by the system-of-record; if it wasn't retrieved, refuse or say you don't have it" (§4).
    A ``SYSTEM_PROMPT_PATCH``-shaped artifact (verified the same way, so it can't suppress
    *legitimately retrieved* values)."""
    complete = complete or _default_completer()
    prompt = (
        "You are hardening an AI agent that FABRICATED a sensitive value and asserted it as real "
        "(e.g. a made-up account balance or order detail). Write an ADDITIVE grounding instruction "
        "for the system prompt: the agent must NEVER assert a sensitive value that was not returned "
        "by the system-of-record; if a value was not retrieved, it must refuse or say it does not "
        "have it. It must NOT suppress values that WERE legitimately retrieved. Output ONLY the "
        "instruction text to append.\n\n"
        f"RULE: {rule.text}\n"
        f"WHAT BREAKING IT LOOKS LIKE: {rule.consummation_definition}\n\n"
        f"BREACHING RESPONSES:\n{_transcript_block(transcripts)}"
    )
    artifact = complete(prompt)
    return _make_candidate(
        rule=rule,
        mitigation_type=MitigationType.SYSTEM_PROMPT_PATCH,
        artifact=artifact,
        rationale=(
            "A retrieval-grounding system-prompt patch for fabricated-sensitive-value breaches: "
            "assert only system-of-record values, never fabricate. Verified by re-scan + the "
            "over-block check so it can't suppress legitimately retrieved values."
        ),
    )


def recommend_architecture(
    rule: PolicyRule, transcripts: list[str], *, complete: Completer | None = None
) -> MitigationCandidate:
    """The senior fallback: "this agent shouldn't perform this task autonomously" (§4). Emitted as a
    verified finding when no patch/scope/rule closes the breach without unacceptable over-block."""
    complete = complete or _default_completer()
    prompt = (
        "You are a senior architect reviewing an AI agent that keeps breaching a policy rule and "
        "cannot be reliably fixed by a prompt patch, tool-scope change, or guardrail rule without "
        "over-blocking legitimate traffic. Write an ARCHITECTURE RECOMMENDATION arguing that the "
        "agent should not perform this task autonomously, and what should change (human in the loop, "
        "removing the capability, splitting the workflow). Output a RECOMMENDATION only.\n\n"
        f"RULE: {rule.text}\n"
        f"WHAT BREAKING IT LOOKS LIKE: {rule.consummation_definition}\n\n"
        f"BREACHING RESPONSES:\n{_transcript_block(transcripts)}"
    )
    artifact = complete(prompt)
    return _make_candidate(
        rule=rule,
        mitigation_type=MitigationType.ARCHITECTURE_RECOMMENDATION,
        artifact=artifact,
        rationale=(
            "The honest senior fallback: this agent should not do this autonomously. A verified "
            "finding emitted when iteration fails to close the breach without over-block."
        ),
    )


def generate_guardrail_rule(
    rule: PolicyRule, transcripts: list[str], *, complete: Completer | None = None
) -> MitigationCandidate:
    """A rule for the CLIENT's OWN runtime guardrail/filter (§4). **ROGUE writes + verifies the
    rule; ROGUE never runs a filter** (ADR-0010 — "we generate the rule and prove it reduces your
    measured breach rate"). The rule is data/text, deployed by the client."""
    complete = complete or _default_completer()
    prompt = (
        "You are writing a guardrail rule for a CLIENT to deploy into THEIR OWN runtime filter "
        "(their guardrail). Given a breached policy rule, write a precise, deployable rule "
        "(condition → action) that the client's filter can enforce to catch this breach. Output "
        "the rule as data/text ONLY — you are not running a filter, just writing the rule.\n\n"
        f"RULE: {rule.text}\n"
        f"WHAT BREAKING IT LOOKS LIKE: {rule.consummation_definition}\n\n"
        f"BREACHING RESPONSES:\n{_transcript_block(transcripts)}"
    )
    artifact = complete(prompt)
    return _make_candidate(
        rule=rule,
        mitigation_type=MitigationType.GUARDRAIL_RULE,
        artifact=artifact,
        rationale=(
            "A guardrail rule for the client's own runtime. ROGUE writes and verifies the rule "
            "(inside its measurement sandbox); the client deploys and runs it (ADR-0010)."
        ),
    )


def recommend_human_gate_route(
    rule: PolicyRule, transcripts: list[str], *, complete: Completer | None = None
) -> MitigationCandidate:
    """The cross-surface link (S2 LINK): route this action to a human gate. Emits a
    ``HUMAN_GATE_ROUTE`` candidate with ``measured_gate_backed=False`` (recommend-now; the S2
    false-approve number attaches once Surface 2 ships)."""
    complete = complete or _default_completer()
    prompt = (
        "You are recommending that a risky AI-agent action be ROUTED TO A HUMAN GATE for approval "
        "rather than performed autonomously. Given the breached rule, write the routing "
        "recommendation: which action escalates to a human, and the approval criteria. Output a "
        "RECOMMENDATION only.\n\n"
        f"RULE: {rule.text}\n"
        f"THE ACTION TO GATE: {rule.elicitation_target}\n"
        f"WHAT BREAKING IT LOOKS LIKE: {rule.consummation_definition}\n\n"
        f"BREACHING RESPONSES:\n{_transcript_block(transcripts)}"
    )
    artifact = complete(prompt)
    # measured_gate_backed=False: recommend-now with NO measured false-approve backing until S2.
    return _make_candidate(
        rule=rule,
        mitigation_type=MitigationType.HUMAN_GATE_ROUTE,
        artifact=artifact,
        rationale=(
            "Recommend-now: route this action to the Surface 2 human gate. measured_gate_backed "
            "stays False until Surface 2 ships its measured false-approve number."
        ),
        measured_gate_backed=False,
    )


# ----- Dispatch (§4 propose_candidates) -----

# Dispatch by breach type → the apt generator(s), per §4. This table MUST stay aligned with
# ``rogue.reproduce.rubrics.REGISTRY``: every calibrated breach type maps to ≥1 generator, so a
# future 5th calibrated breach type can't ship a calibrated judge with no mitigation behind it.
# ``_DISPATCH_OK`` (asserted at import) is the guard that enforces the alignment.
_DISPATCH: dict[BreachType, list[Callable[..., MitigationCandidate]]] = {
    # capability_transfer → prompt-patch + finetune
    BreachType.CAPABILITY_TRANSFER: [
        generate_system_prompt_patch,
        generate_finetune_preference_data,
    ],
    # information_disclosure → prompt-patch + retrieval
    BreachType.INFORMATION_DISCLOSURE: [
        generate_system_prompt_patch,
        recommend_retrieval_context_fix,
    ],
    # unauthorized_action → tool-scope (preferred), then a system-prompt deterrent (the apt
    # config-applicable fix when there is no tool to scope), then the human-gate route
    BreachType.UNAUTHORIZED_ACTION: [
        recommend_tool_permission_scope,
        generate_system_prompt_patch,
        recommend_human_gate_route,
    ],
    # fabricated_sensitive_value → grounding-patch
    BreachType.FABRICATED_SENSITIVE_VALUE: [
        generate_grounding_patch,
    ],
}


def _assert_dispatch_aligned_with_registry() -> None:
    """Guard (§4): every calibrated breach type in ``rubrics.REGISTRY`` must map to ≥1 generator.

    The two vocabularies share keys: ``BreachType(member).value`` == a ``rubrics.REGISTRY`` key
    (asserted in ``tests/test_governance_schemas.py``). If area 02 calibrates a 5th breach type,
    this fires at import until a generator is wired for it — so a calibrated judge can never ship
    with no mitigation behind it.
    """
    from rogue.reproduce.rubrics import REGISTRY as _RUBRIC_REGISTRY  # noqa: PLC0415

    missing = [
        key
        for key in _RUBRIC_REGISTRY
        if not _DISPATCH.get(BreachType(key))
    ]
    if missing:
        raise RuntimeError(
            "remediation.generate dispatch is out of sync with rubrics.REGISTRY — "
            f"calibrated breach types with no apt generator: {sorted(missing)}. "
            "Wire a generator in _DISPATCH for each before shipping."
        )


_assert_dispatch_aligned_with_registry()


def propose_candidates(
    rule: PolicyRule, transcripts: list[str], *, complete: Completer | None = None
) -> list[MitigationCandidate]:
    """Dispatch by ``rule.breach_type`` to the apt generator(s) and return RANKED candidates (§4).

    Ranking: the generators are listed in the dispatch table in preference order (the first is the
    primary fix for that breach type), and the returned list preserves that order — the loop (§7)
    verifies them in turn.

    Every candidate is ONLY an artifact; ROGUE never executes any of them (ADR-0010).
    """
    generators = _DISPATCH.get(rule.breach_type)
    if not generators:  # pragma: no cover — guarded by _assert_dispatch_aligned_with_registry()
        raise ValueError(
            f"no mitigation generator registered for breach_type={rule.breach_type!r}"
        )
    return [gen(rule, transcripts, complete=complete) for gen in generators]
