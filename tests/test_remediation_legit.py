"""Tests for the legitimate-traffic corpus loader (build 05 §5, ADR-0011).

Pure authoring/loading — no network, no model calls.
"""

from __future__ import annotations

import pytest

from rogue.remediation.legit_corpus import available_rule_ids, load_legit_set

EXPECTED_RULES = {"R1", "R2", "R3", "R4", "RA06"}  # RA06 added for the remediation live-run demo


def test_available_rule_ids_covers_the_authored_rules():
    assert set(available_rule_ids()) == EXPECTED_RULES


@pytest.mark.parametrize("rule_id", sorted(EXPECTED_RULES))
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
