"""§10.10 — the Growth Scheduler: decide *when* to pay for repertoire growth.

The experiments proved `allocation → growth`: a growth-mode sweep (K=quota,
starvation ordering) converts starved candidates into graduated capabilities at
~$7/graduation, but it costs ~10× a canonical sweep, so it must run *deliberately*,
not on every reproduce. `scripts/reproduce/growth_sweep.sh` made growth mode explicit; this
makes the *decision to run it* explicit too — turning growth from a human call into
system behaviour.

The policy is intentionally a deterministic rule over inventory we already track,
NOT a bandit and NOT new telemetry: run growth mode when there is enough unevaluated
candidate inventory to justify the fixed full-rotation cost, otherwise stay canonical.

    growth   ⟺   candidate_pool ≥ MIN_POOL  (and avg candidate age ≥ MIN_AGE_DAYS)
    canonical ⟺   otherwise

This self-regulates: a growth sweep graduates candidates, draining the pool below
MIN_POOL, so the scheduler reverts to canonical until harvesting refills it. K is held
at the evidence-backed growth default (5) rather than scaled — the saturation point
is not yet mapped (see the stopping rule in `growth_sweep.sh`).

Thresholds via env (GROWTH_MIN_POOL=5, GROWTH_MIN_AGE_DAYS=0, GROWTH_K=5). The age
gate is off by default (MIN_AGE_DAYS=0) for the simplest pool-only rule; set it to 7
for the "let candidates age before a growth sweep" variant.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

__all__ = [
    "GrowthDecision",
    "candidate_pool_stats",
    "decide_sweep_mode",
    "GROWTH_MIN_POOL",
    "GROWTH_MIN_AGE_DAYS",
    "GROWTH_K",
]

GROWTH_MIN_POOL = int(os.environ.get("GROWTH_MIN_POOL", "5"))
GROWTH_MIN_AGE_DAYS = float(os.environ.get("GROWTH_MIN_AGE_DAYS", "0"))
GROWTH_K = int(os.environ.get("GROWTH_K", "5"))


@dataclass(frozen=True)
class GrowthDecision:
    """The scheduler's verdict for the next escalation sweep + the mode bundle.

    ``mode`` is ``growth`` or ``canonical``; the remaining fields are the parameter
    bundle that mode implies, so callers don't re-derive (and can't drift) them."""

    mode: str  # "growth" | "canonical"
    reason: str
    candidate_pool: int
    avg_age_days: float
    K: int
    quota: int
    order: str

    @property
    def is_growth(self) -> bool:
        return self.mode == "growth"


def candidate_pool_stats(session: "Session", *, now: datetime) -> tuple[int, float]:
    """Return ``(candidate_count, avg_age_days)`` for the current candidate pool.

    No new telemetry — reads ``attack_strategies`` (status + created_at). Average age
    is 0.0 when the pool is empty."""
    from sqlalchemy import func

    from rogue.db.models import AttackStrategy
    from rogue.schemas import StrategyStatus

    row = (
        session.query(
            func.count().label("n"),
            func.avg(
                func.extract("epoch", now - AttackStrategy.created_at)
            ).label("avg_age_s"),
        )
        .filter(AttackStrategy.status == StrategyStatus.CANDIDATE)
        .one()
    )
    n = int(row.n or 0)
    avg_age_days = float(row.avg_age_s or 0.0) / 86_400.0
    return n, avg_age_days


def _decide(
    candidate_pool: int,
    avg_age_days: float,
    *,
    min_pool: int,
    min_age_days: float,
    growth_K: int,
) -> GrowthDecision:
    """Pure policy (no DB) — the deterministic rule, isolated for testing."""
    if candidate_pool >= min_pool and avg_age_days >= min_age_days:
        return GrowthDecision(
            mode="growth",
            reason=(f"candidate_pool {candidate_pool} ≥ {min_pool}"
                    + (f" and avg_age {avg_age_days:.1f}d ≥ {min_age_days}d"
                       if min_age_days > 0 else "")),
            candidate_pool=candidate_pool,
            avg_age_days=avg_age_days,
            K=growth_K,
            quota=growth_K,  # quota locked equal to K — evaluate every selected slot
            order="starvation",
        )
    if candidate_pool < min_pool:
        reason = f"candidate_pool {candidate_pool} < {min_pool} — too little inventory"
    else:
        reason = f"avg_age {avg_age_days:.1f}d < {min_age_days}d — pool too fresh"
    return GrowthDecision(
        mode="canonical",
        reason=reason,
        candidate_pool=candidate_pool,
        avg_age_days=avg_age_days,
        K=3,
        quota=0,
        order="canonical",
    )


def decide_sweep_mode(
    session: "Session",
    *,
    now: datetime,
    min_pool: int = GROWTH_MIN_POOL,
    min_age_days: float = GROWTH_MIN_AGE_DAYS,
    growth_K: int = GROWTH_K,
) -> GrowthDecision:
    """Query the candidate pool and return the growth-vs-canonical decision."""
    pool, avg_age = candidate_pool_stats(session, now=now)
    return _decide(
        pool, avg_age,
        min_pool=min_pool, min_age_days=min_age_days, growth_K=growth_K,
    )
