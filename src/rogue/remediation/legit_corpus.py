"""Legitimate-traffic corpus loader for the over-block check (ADR-0011).

The over-block side of the remediation loop needs an **independent** set of
legitimate requests the agent *should* answer for each rule. These are
authored, designed should-answer labels — requests that sit near a rule's
boundary but do NOT cross it (refusing them is the over-block trap). They are
deliberately **not** derived from any agent's behavior (never "whatever the
patched agent now allows"), so that a later "over-block ≈ 0" is a real,
independent measurement rather than a tautology (ADR-0011 source #1; build 05
§5; unified-spec §5).

This module is a thin loader — the fixtures under
``tests/fixtures/legit_traffic/<rule_id>.json`` are the data. The over-block
*rate* (and its bootstrap CI) is computed downstream when the corpus is scored
against the post-mitigation config in build 05 §6; nothing is measured here.
"""

from __future__ import annotations

import json
from pathlib import Path

_FIXTURE_DIR = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "legit_traffic"
)


def _fixture_path(rule_id: str) -> Path:
    return _FIXTURE_DIR / f"{rule_id}.json"


def available_rule_ids() -> list[str]:
    """Return the rule ids that have an authored legitimate-traffic set."""
    return sorted(p.stem for p in _FIXTURE_DIR.glob("*.json"))


def load_legit_set(rule_id: str) -> list[str]:
    """Load the authored should-answer requests for ``rule_id``.

    Raises:
        ValueError: if no legitimate-traffic set exists for ``rule_id``.
    """
    path = _fixture_path(rule_id)
    if not path.is_file():
        known = ", ".join(available_rule_ids()) or "(none)"
        raise ValueError(
            f"No legitimate-traffic set for rule_id {rule_id!r}; "
            f"known rules: {known}."
        )
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)
