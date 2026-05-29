"""Bootstrap confidence interval for per-(primitive, config) breach rates.

Why this exists (§10.6): 5 trials per cell is a tiny sample. Reporting a
breach rate of 0.40 without a confidence interval is rhetorically weak — a
CISO reads "40%" and assumes the model is meaningfully more vulnerable
than 20%, when in reality both estimates have overlapping ~70% CIs. The
bootstrap gives the brief honest error bars without requiring a
parametric assumption about the underlying distribution.

Single public surface:

    bootstrap_ci(trials: Sequence[bool], B: int = 1000, seed: int = 20260524)
        → tuple[float, float]    # (lo_95, hi_95)

The trials list is the per-attempt success vector (e.g. ``[True, True,
False, True, False]`` for 3/5 breaches). Returns the symmetric 95%
percentile bootstrap interval — i.e. the 2.5th and 97.5th percentiles of
the resampled means.

Deterministic seed (locked to ``20260524``, the project's epoch date) so
brief renders are reproducible across reruns. If you re-render today's
brief twice in a row the CIs are bit-identical.

Performance: B=1000 × N=5 = 5000 resamples per cell. ~0.2 ms on commodity
hardware. For a 820-cell breach_matrix that's ~160 ms total. Negligible
vs the threat-brief LLM rendering cost.
"""

from __future__ import annotations

import random
from typing import Sequence


__all__ = ["bootstrap_ci", "format_ci", "DEFAULT_SEED", "DEFAULT_B"]


DEFAULT_SEED = 20260524
DEFAULT_B = 1000


def bootstrap_ci(
    trials: Sequence[bool],
    B: int = DEFAULT_B,
    seed: int = DEFAULT_SEED,
) -> tuple[float, float]:
    """Return the 95% percentile-bootstrap CI for the mean of ``trials``.

    Args:
        trials: per-attempt success vector. Bools or 0/1 ints accepted.
        B: number of bootstrap resamples (default 1000 per §10.6).
        seed: RNG seed for reproducibility (default ``DEFAULT_SEED`` = 20260524).

    Returns:
        ``(lo_95, hi_95)`` — the 2.5th and 97.5th percentiles of the
        resampled means, each clamped to [0.0, 1.0].

    Degenerate cases:
        * Empty trials → ``(0.0, 0.0)`` (no information, neutral interval).
        * All-True trials (rate = 1.0) → ``(1.0, 1.0)`` (width-zero CI).
        * All-False trials (rate = 0.0) → ``(0.0, 0.0)`` (width-zero CI).
        These are handled without raising — the brief renderer needs a
        well-defined CI for every cell.
    """
    if not trials:
        return (0.0, 0.0)

    n = len(trials)
    bools = [1 if t else 0 for t in trials]

    # Degenerate uniformity → width-zero CI. Short-circuit so we don't
    # waste cycles + so the result is exact (no rounding from B resamples).
    s = sum(bools)
    if s == 0:
        return (0.0, 0.0)
    if s == n:
        return (1.0, 1.0)

    rng = random.Random(seed)
    resampled_means: list[float] = [0.0] * B
    for i in range(B):
        sample = rng.choices(bools, k=n)
        resampled_means[i] = sum(sample) / n

    resampled_means.sort()
    lo_idx = max(0, min(B - 1, int(0.025 * B)))
    hi_idx = max(0, min(B - 1, int(0.975 * B) - 1))

    lo = max(0.0, min(1.0, resampled_means[lo_idx]))
    hi = max(0.0, min(1.0, resampled_means[hi_idx]))
    return (lo, hi)


def format_ci(rate: float, lo: float, hi: float) -> str:
    """Render a rate + CI as the locked brief-line shape.

    Example: ``"78% [62%, 89%]"``. Used by the threat brief template per
    §10.6 acceptance criterion.
    """
    return (
        f"{int(round(rate * 100))}% "
        f"[{int(round(lo * 100))}%, {int(round(hi * 100))}%]"
    )
