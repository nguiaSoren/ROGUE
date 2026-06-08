"""Tests for the BreachType abstraction (v2 build-02 §1.1–§1.2).

Pure-unit: no network, no DB, no LLM. Verifies the registry resolves the three
breach types, the harm type points at the existing v3 rubric, unknown keys fail
loudly, and an empty BreachContext is the all-None harm case.
"""

from __future__ import annotations

import pytest

from rogue.reproduce.rubrics import REGISTRY, BreachType, get_breach_type
from rogue.reproduce.rubrics.context import BreachContext

EXPECTED_KEYS = {
    "capability_transfer",
    "information_disclosure",
    "unauthorized_action",
    "fabricated_sensitive_value",
}

EXPECTED_FILENAMES = {
    "capability_transfer": "judge_v3.md",
    "information_disclosure": "infodisc_v2.md",
    "unauthorized_action": "unauthorized_action_v3.md",
    "fabricated_sensitive_value": "fabricated_sensitive_value_v2.md",
}


def test_capability_transfer_resolves_to_v3_rubric() -> None:
    """The harm type is the reference instance — it must point at judge_v3.md."""
    bt = get_breach_type("capability_transfer")
    assert isinstance(bt, BreachType)
    assert bt.key == "capability_transfer"
    assert bt.rubric_filename == "judge_v3.md"


def test_registry_has_exactly_four_keys() -> None:
    assert set(REGISTRY) == EXPECTED_KEYS


@pytest.mark.parametrize("key", sorted(EXPECTED_KEYS))
def test_all_keys_round_trip(key: str) -> None:
    """Every key resolves, returns its own key back, and the expected rubric."""
    bt = get_breach_type(key)
    assert bt.key == key
    assert bt.rubric_filename == EXPECTED_FILENAMES[key]
    # The human-facing labels are populated (they feed reports + attestation).
    assert bt.consummation_label
    assert bt.fp_mode_label


def test_breach_type_is_frozen() -> None:
    bt = get_breach_type("capability_transfer")
    with pytest.raises((AttributeError, TypeError)):
        bt.rubric_filename = "other.md"  # type: ignore[misc]


def test_unknown_key_raises() -> None:
    with pytest.raises(KeyError) as exc:
        get_breach_type("does_not_exist")
    # Error names the offending key + lists the valid options.
    assert "does_not_exist" in str(exc.value)
    for key in EXPECTED_KEYS:
        assert key in str(exc.value)


def test_breach_context_defaults_all_none() -> None:
    """An empty BreachContext is the harm case — no extra context injected."""
    ctx = BreachContext()
    assert ctx.rule_text is None
    assert ctx.protected_target is None


def test_breach_context_carries_non_harm_fields() -> None:
    ctx = BreachContext(
        rule_text="never reveal another employee's compensation",
        protected_target="another employee's compensation",
    )
    assert ctx.rule_text == "never reveal another employee's compensation"
    assert ctx.protected_target == "another employee's compensation"
