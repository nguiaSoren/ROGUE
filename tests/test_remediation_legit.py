"""Tests for the legitimate-traffic corpus loader (build 05 §5, ADR-0011).

Pure authoring/loading — no network, no model calls.
"""

from __future__ import annotations

import pytest

from rogue.remediation.legit_corpus import available_rule_ids, load_legit_set

CORE_RULES = {"R1", "R2", "R3", "R4"}  # the canonical sample_policy rules (always present)
# Demo/live-run sets (RA06, RD04, …) are added as needed and are NOT asserted here, so adding one
# never breaks this test — we only require the core rules to be present.


def test_available_rule_ids_covers_at_least_the_core_rules():
    assert CORE_RULES <= set(available_rule_ids())


@pytest.mark.parametrize("rule_id", sorted(CORE_RULES))
def test_load_legit_set_non_empty_string_list(rule_id):
    entries = load_legit_set(rule_id)
    assert isinstance(entries, list)
    assert entries, f"legit set for {rule_id} must be non-empty"
    for entry in entries:
        assert isinstance(entry, str)
        assert entry.strip(), f"empty entry in {rule_id}"


def test_unknown_rule_id_raises():
    with pytest.raises(ValueError, match="No legitimate-traffic set"):
        load_legit_set("R999")
