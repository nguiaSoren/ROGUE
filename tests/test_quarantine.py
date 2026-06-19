"""Tests for ``rogue.dedupe.quarantine`` — the §3.5 budget-conditional gate.

Three canonical cases per §3.5: under-budget primitives stay canonical;
over-budget high-score stay canonical; over-budget low-score get
quarantined. Plus boundary tests on each threshold.
"""

from __future__ import annotations

from decimal import Decimal

from rogue.dedupe.quarantine import (
    QUARANTINE_BUDGET_THRESHOLD_USD,
    QUARANTINE_SCORE_FLOOR,
    should_quarantine,
)


# --------------------------------------------------------------------------- #
# A. The three canonical cases enumerated in §3.5
# --------------------------------------------------------------------------- #


def test_under_budget_low_score_stays_canonical() -> None:
    """Below the budget threshold, EVERY primitive is canonical regardless
    of reproducibility_score."""
    assert not should_quarantine(
        primitive_reproducibility_score=3,
        daily_bd_spend_usd=Decimal("10.00"),
    )


def test_over_budget_high_score_stays_canonical() -> None:
    """Above the budget threshold, score >= 5 primitives stay canonical."""
    assert not should_quarantine(
        primitive_reproducibility_score=8,
        daily_bd_spend_usd=Decimal("30.00"),
    )


def test_over_budget_low_score_gets_quarantined() -> None:
    """Above the budget threshold, score < 5 primitives are quarantined."""
    assert should_quarantine(
        primitive_reproducibility_score=4,
        daily_bd_spend_usd=Decimal("30.00"),
    )


# --------------------------------------------------------------------------- #
# B. Boundary behavior on each threshold
# --------------------------------------------------------------------------- #


def test_exact_budget_threshold_triggers_gate() -> None:
    """The budget check uses ``>=`` so exact threshold spend trips the gate."""
    assert should_quarantine(
        primitive_reproducibility_score=2,
        daily_bd_spend_usd=QUARANTINE_BUDGET_THRESHOLD_USD,
    )


def test_one_cent_under_budget_does_not_trigger_gate() -> None:
    """One cent below threshold leaves every primitive canonical."""
    just_under = QUARANTINE_BUDGET_THRESHOLD_USD - Decimal("0.01")
    assert not should_quarantine(
        primitive_reproducibility_score=1,
        daily_bd_spend_usd=just_under,
    )


def test_score_floor_boundary_at_five() -> None:
    """Score == 5 stays canonical; score == 4 gets quarantined."""
    spend = Decimal("50.00")
    assert not should_quarantine(
        primitive_reproducibility_score=QUARANTINE_SCORE_FLOOR,
        daily_bd_spend_usd=spend,
    )
    assert should_quarantine(
        primitive_reproducibility_score=QUARANTINE_SCORE_FLOOR - 1,
        daily_bd_spend_usd=spend,
    )


# --------------------------------------------------------------------------- #
# C. Locked-constant smoke tests (catch accidental edits to §3.5 defaults)
# --------------------------------------------------------------------------- #


def test_budget_threshold_locked_at_twenty_five_dollars() -> None:
    """§3.5 locks $25/day. Catches a typo or unit change.

    Note: $25/day is intentionally 1/8 of the $200 total budget per §7;
    changing this value requires a §3.5 rationale update."""
    assert QUARANTINE_BUDGET_THRESHOLD_USD == Decimal("25.00")
    # Decimal, not float — exact comparison against cost-log sums.
    assert isinstance(QUARANTINE_BUDGET_THRESHOLD_USD, Decimal)


def test_score_floor_locked_at_five() -> None:
    """§3.5 locks score floor at 5 (the midpoint of the 1-10
    reproducibility_score range)."""
    assert QUARANTINE_SCORE_FLOOR == 5
