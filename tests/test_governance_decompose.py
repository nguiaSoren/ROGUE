"""build-04 §3.1 — decompose_policy with a MOCK agent (no live model calls).

EXIT-GATE §3 (decompose half): with a mock agent returning the four canonical
rules' structured output, ``decompose_policy`` yields four correctly-typed
:class:`PolicyRule`s matching ``tests/fixtures/governance/sample_policy.json``
(breach_type + elicitation_target correct). No network, no API key.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rogue.governance.decompose import (
    DecomposeAgent,
    PolicyDecomposer,
    decompose_policy,
    load_policy,
)
from rogue.schemas.governance import BreachType, ClientPolicy, PolicyRule

FIXTURE = Path(__file__).parent / "fixtures" / "governance" / "sample_policy.json"


@pytest.fixture
def golden_policy() -> ClientPolicy:
    return ClientPolicy.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


class _MockDecomposeAgent:
    """A mock that returns the golden fixture's rules — stands in for the LLM.

    Satisfies the ``DecomposeAgent`` protocol so it drops into ``decompose_policy``
    exactly where the live ``PolicyDecomposer`` would, proving the wiring with
    zero model calls.
    """

    def __init__(self, golden: ClientPolicy) -> None:
        self._golden = golden
        self.calls: list[str] = []

    def decompose(self, source_text: str) -> ClientPolicy:
        self.calls.append(source_text)
        # Return only the rules (as the LLM would); deliberately omit source_text
        # to exercise decompose_policy's re-attachment of it.
        return ClientPolicy(
            policy_id="POL-from-llm",
            customer_id="acme-corp",
            rules=[r.model_copy(deep=True) for r in self._golden.rules],
            source_text="",
        )


def test_mock_agent_satisfies_protocol(golden_policy: ClientPolicy) -> None:
    assert isinstance(_MockDecomposeAgent(golden_policy), DecomposeAgent)


def test_decompose_yields_four_typed_rules(golden_policy: ClientPolicy) -> None:
    agent = _MockDecomposeAgent(golden_policy)
    result = decompose_policy(golden_policy.source_text, agent=agent)

    assert isinstance(result, ClientPolicy)
    assert len(result.rules) == 4
    assert all(isinstance(r, PolicyRule) for r in result.rules)
    assert agent.calls == [golden_policy.source_text]


def test_decompose_breach_types_and_targets_match_golden(golden_policy: ClientPolicy) -> None:
    agent = _MockDecomposeAgent(golden_policy)
    result = decompose_policy(golden_policy.source_text, agent=agent)

    by_id = {r.rule_id: r for r in result.rules}
    golden_by_id = {r.rule_id: r for r in golden_policy.rules}

    assert set(by_id) == set(golden_by_id) == {"R1", "R2", "R3", "R4"}
    for rule_id, rule in by_id.items():
        golden = golden_by_id[rule_id]
        assert rule.breach_type == golden.breach_type, rule_id
        assert rule.elicitation_target == golden.elicitation_target, rule_id


def test_decompose_breach_type_vocabulary_is_canonical(golden_policy: ClientPolicy) -> None:
    """Each rule's breach_type is a real BreachType (the shared vocabulary)."""
    result = decompose_policy(
        golden_policy.source_text, agent=_MockDecomposeAgent(golden_policy)
    )
    expected = {
        "R1": BreachType.INFORMATION_DISCLOSURE,
        "R2": BreachType.UNAUTHORIZED_ACTION,
        "R3": BreachType.UNAUTHORIZED_ACTION,
        "R4": BreachType.INFORMATION_DISCLOSURE,
    }
    for r in result.rules:
        assert isinstance(r.breach_type, BreachType)
        assert r.breach_type == expected[r.rule_id]


def test_decompose_reattaches_source_text(golden_policy: ClientPolicy) -> None:
    """The agent may drop source_text; decompose_policy restores the canonical record."""
    result = decompose_policy(
        golden_policy.source_text, agent=_MockDecomposeAgent(golden_policy)
    )
    assert result.source_text == golden_policy.source_text


def test_decompose_rejects_empty_source_text(golden_policy: ClientPolicy) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        decompose_policy("   ", agent=_MockDecomposeAgent(golden_policy))


def test_load_policy_round_trips_the_fixture(golden_policy: ClientPolicy) -> None:
    """The offline (reviewed-rows) entry point loads the same typed policy."""
    loaded = load_policy(FIXTURE)
    assert loaded == golden_policy


def test_live_decomposer_constructs_without_api_key() -> None:
    """Importing/constructing the live agent must not require an API key
    (clients are lazy) — mirrors ExtractionAgent's import-safety contract."""
    agent = PolicyDecomposer(model="anthropic/claude-sonnet-4-5")
    assert agent.model == "anthropic/claude-sonnet-4-5"
    schema = agent._tool_schema()
    assert "rules" in schema["properties"]
