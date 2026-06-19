"""Shared pytest configuration.

Keeps the unit suite hermetic: §10.9 Step 3 slot-fill is **default-on in
production** (the planner calls the model to fill template slots), but a unit test
must never depend on network/credentials or risk spend. This autouse fixture sets
``ROGUE_ESCALATION_SLOT_FILL=0`` so every ``EscalationPlanner()`` built without an
explicit ``slot_fill`` argument resolves to OFF in tests — deterministic, no I/O.
Tests that specifically exercise slot-fill (``test_slot_fill.py``) pass
``slot_fill=True`` explicitly, and an explicit argument wins over the env.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _slot_fill_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROGUE_ESCALATION_SLOT_FILL", "0")
