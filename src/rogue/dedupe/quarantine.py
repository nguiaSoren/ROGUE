"""Budget-conditional quarantine gate for low-reproducibility primitives.

Position in the dedup pipeline (ROGUE_PLAN.md §3.5, called from
``dedupe/embeddings.py`` after cluster assignment):

    Deduplicator.assign_cluster(primitive)
            │
            ▼
    should_quarantine(primitive.reproducibility_score, daily_bd_spend)
            │
            ▼ True ──►  primitive.canonical = False  (quarantined; NOT reproduced)
            ▼ False ──►  preserve clustering decision

Two-condition gate, both required to fire:
  1. Today's Bright Data spend has crossed the daily threshold ($25), AND
  2. The primitive's LLM-self-assessed ``reproducibility_score`` is below 5.

Under-budget: every primitive is canonical and gets reproduced (Layer 4).
Over-budget: only score >= 5 primitives stay canonical; the rest are
quarantined (preserved in DB + dataset export, but skipped by reproduction
to save trial budget). Quarantine is the cheapest cut — low-score primitives
produce the lowest-information breach signal anyway (the model's response
to a vague technique description with no concrete payload is uninterpretable).

See §3.5 for the full rationale (late-arriving payload promotion, backfill
recoverability, HuggingFace dataset coverage).
"""

from __future__ import annotations

from decimal import Decimal

__all__ = [
    "QUARANTINE_BUDGET_THRESHOLD_USD",
    "QUARANTINE_SCORE_FLOOR",
    "should_quarantine",
]


# Per-UTC-day Bright Data spend threshold above which the gate engages.
# At the $200 total Day-1-through-Day-4 budget (§7), $25/day is 1/8 of total
# spend; hitting that means we're on track to exceed budget. Decimal (not
# float) so the comparison against cost-log sums is exact.
QUARANTINE_BUDGET_THRESHOLD_USD: Decimal = Decimal("25.00")

# Below this self-assessed reproducibility_score, primitives get quarantined
# IF the budget threshold has tripped. AttackPrimitive.reproducibility_score
# is an integer in [1, 10] per the §4.1 schema.
QUARANTINE_SCORE_FLOOR: int = 5


def should_quarantine(
    primitive_reproducibility_score: int,
    daily_bd_spend_usd: Decimal,
) -> bool:
    """Return True iff this primitive should be marked ``canonical=False``.

    Both conditions must hold:
      1. ``daily_bd_spend_usd >= QUARANTINE_BUDGET_THRESHOLD_USD``
      2. ``primitive_reproducibility_score < QUARANTINE_SCORE_FLOOR``
    """
    return (
        daily_bd_spend_usd >= QUARANTINE_BUDGET_THRESHOLD_USD
        and primitive_reproducibility_score < QUARANTINE_SCORE_FLOOR
    )
