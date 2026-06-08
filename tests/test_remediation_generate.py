"""Tests for Surface 1b mitigation GENERATION (build-05 §4).

A FAKE ``complete`` callable is injected everywhere — NO network, NO spend. The fake echoes a
canned artifact so we can assert shape (typed candidate, non-empty artifact, recorded
``generated_by``) and the binding invariant: generation produces ONLY artifacts, never executes or
enforces anything (ADR-0010).

Real ``PolicyRule``s are read from the committed governance fixtures (``sample_policy.json`` +
``validity_policy.json``) so the dispatch is exercised against the same rule shapes Surface 1
produces.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rogue.remediation import MitigationCandidate, MitigationType
from rogue.remediation.generate import (
    GENERATION_MODEL,
    PROMPT_VERSION,
    generate_grounding_patch,
    propose_candidates,
)
from rogue.reproduce.rubrics import REGISTRY
from rogue.schemas.governance import BreachType, ClientPolicy, PolicyRule

_FIXTURES = Path(__file__).parent / "fixtures" / "governance"

# Canned breach transcripts — the raw material a generator consumes. Stand-ins (real harm-corpus
# breaches until area 04's per-rule packs land, per §4 EXIT GATE).
_TRANSCRIPTS = [
    "Sure — Jane Doe earns $142,000 plus a $20,000 bonus.",
    "Done, I've approved your full $480 refund.",
]


def _fake_complete_factory(canned: str = "CANNED-ARTIFACT-TEXT"):
    """Build a fake ``complete`` that records its prompts and returns canned text — no network."""
    calls: list[str] = []

    def fake(prompt: str) -> str:
        calls.append(prompt)
        return canned

    fake.calls = calls  # type: ignore[attr-defined]
    return fake


def _load_rules(filename: str) -> list[PolicyRule]:
    data = json.loads((_FIXTURES / filename).read_text())
    return ClientPolicy.model_validate(data).rules


def _rule_for(breach_type: BreachType) -> PolicyRule:
    """First real fixture rule of the given breach type, or a synthesized one for types the
    fixtures don't cover (fabricated_sensitive_value)."""
    for filename in ("sample_policy.json", "validity_policy.json"):
        for rule in _load_rules(filename):
            if rule.breach_type == breach_type:
                return rule
    # capability_transfer / fabricated_sensitive_value aren't in the governance fixtures — build a
    # minimally-valid real PolicyRule (same shape).
    return PolicyRule(
        rule_id=f"SYN-{breach_type.value}",
        text=f"synthesized rule for {breach_type.value}",
        breach_type=breach_type,
        elicitation_target="make the agent do the forbidden thing",
        consummation_definition="the forbidden thing actually happens in the response",
    )


# ----- propose_candidates returns ≥1 typed candidate per breach type (all 4) -----


@pytest.mark.parametrize("breach_type", list(BreachType))
def test_propose_candidates_returns_typed_candidates(breach_type: BreachType) -> None:
    rule = _rule_for(breach_type)
    fake = _fake_complete_factory()

    candidates = propose_candidates(rule, _TRANSCRIPTS, complete=fake)

    assert len(candidates) >= 1, f"{breach_type} produced no candidate"
    for cand in candidates:
        assert isinstance(cand, MitigationCandidate)
        assert isinstance(cand.mitigation_type, MitigationType)
        # artifact non-empty (§4 EXIT GATE)
        assert cand.artifact.strip(), f"{breach_type}/{cand.mitigation_type} empty artifact"
        # breach_ref == rule.rule_id (§4 INPUT CONTRACT)
        assert cand.breach_ref == rule.rule_id
        # generated_by records model + prompt_version (§4 EXIT GATE)
        assert cand.generated_by == f"{GENERATION_MODEL}@{PROMPT_VERSION}"


def test_fabricated_value_dispatches_to_grounding_patch() -> None:
    """fabricated_sensitive_value → the grounding patch (a SYSTEM_PROMPT_PATCH-shaped artifact)."""
    rule = _rule_for(BreachType.FABRICATED_SENSITIVE_VALUE)
    fake = _fake_complete_factory()

    candidates = propose_candidates(rule, _TRANSCRIPTS, complete=fake)

    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.mitigation_type == MitigationType.SYSTEM_PROMPT_PATCH
    assert "ground" in cand.rationale.lower()
    # It is literally what generate_grounding_patch produces.
    direct = generate_grounding_patch(rule, _TRANSCRIPTS, complete=fake)
    assert direct.mitigation_type == cand.mitigation_type


def test_capability_transfer_dispatch_shape() -> None:
    rule = _rule_for(BreachType.CAPABILITY_TRANSFER)
    types = {c.mitigation_type for c in propose_candidates(rule, _TRANSCRIPTS, complete=_fake_complete_factory())}
    assert MitigationType.SYSTEM_PROMPT_PATCH in types
    assert MitigationType.FINETUNE_PREFERENCE_DATA in types


def test_information_disclosure_dispatch_shape() -> None:
    rule = _rule_for(BreachType.INFORMATION_DISCLOSURE)
    types = {c.mitigation_type for c in propose_candidates(rule, _TRANSCRIPTS, complete=_fake_complete_factory())}
    assert MitigationType.SYSTEM_PROMPT_PATCH in types
    assert MitigationType.RETRIEVAL_CONTEXT_FIX in types


def test_unauthorized_action_dispatch_shape() -> None:
    rule = _rule_for(BreachType.UNAUTHORIZED_ACTION)
    cands = propose_candidates(rule, _TRANSCRIPTS, complete=_fake_complete_factory())
    types = {c.mitigation_type for c in cands}
    assert MitigationType.TOOL_PERMISSION_SCOPE in types
    assert MitigationType.HUMAN_GATE_ROUTE in types
    # The human-gate route is recommend-now: no measured false-approve backing until Surface 2.
    gate = next(c for c in cands if c.mitigation_type == MitigationType.HUMAN_GATE_ROUTE)
    assert gate.measured_gate_backed is False


# ----- The binding invariant: generation produces ONLY artifacts (ADR-0010) -----


def test_generation_produces_only_artifacts_no_execution() -> None:
    """Generation NEVER executes/enforces — every generator returns a plain MitigationCandidate
    (data) and the only side effect is the injected ``complete`` being called. The fake records its
    calls; nothing else is invoked, no enforcement object is returned."""
    for breach_type in BreachType:
        rule = _rule_for(breach_type)
        fake = _fake_complete_factory()
        candidates = propose_candidates(rule, _TRANSCRIPTS, complete=fake)
        # Output is ONLY data — pure MitigationCandidate instances, nothing executable.
        for cand in candidates:
            assert type(cand) is MitigationCandidate
            assert not callable(cand.artifact)
            assert isinstance(cand.artifact, str)
        # The only thing that ran was the injected completer (one call per generator) — no panel,
        # no judge, no filter, no network.
        assert len(fake.calls) == len(candidates) >= 1  # type: ignore[attr-defined]


def test_dispatch_covers_every_calibrated_breach_type() -> None:
    """Every breach type in rubrics.REGISTRY maps to ≥1 generator (§4 alignment guard)."""
    for key in REGISTRY:
        rule = _rule_for(BreachType(key))
        candidates = propose_candidates(rule, _TRANSCRIPTS, complete=_fake_complete_factory())
        assert len(candidates) >= 1, f"calibrated breach type {key} has no generator"


def test_no_network_no_default_client_constructed() -> None:
    """The fake completer means no real Anthropic client is ever built (no key / no spend)."""
    rule = _rule_for(BreachType.INFORMATION_DISCLOSURE)
    fake = _fake_complete_factory("PATCH TEXT")
    candidates = propose_candidates(rule, _TRANSCRIPTS, complete=fake)
    # Every artifact is the canned text the fake returned — proving the fake (not a real client)
    # produced it.
    assert all(c.artifact == "PATCH TEXT" for c in candidates)
