"""Percentile-bootstrap CI for a rate — the one genuinely new piece of math in
the v2 calibration harness (build 02 §4.1).

Why a second entry point, and why it delegates
----------------------------------------------
``rogue.diff.bootstrap.bootstrap_ci`` already implements the percentile
bootstrap of a Bernoulli rate, deterministically seeded, stdlib-only. The v2
harness needs the *same statistic* but a different call shape:

  * input is the **(successes, n)** count pair the agreement cells produce
    (tp/fp/fn/tn counts), not a pre-materialized success vector;
  * the return is **(point, lo, hi)** — the headline numbers all want the point
    estimate alongside its interval;
  * ``alpha`` and ``iters`` are caller-tunable (the v2 spec asks for a 95% CI at
    ``iters=10_000`` by default, where the brief renderer used a fixed 1000).

Rather than fork the resampling loop (CLAUDE.md "ONE bootstrap helper, not
three"; build 02 cross-cutting decision), this module **reuses the diff
helper's resampler** for the symmetric-95% common case and only implements the
percentile math directly when a non-default ``alpha`` is requested (the diff
helper hard-codes 2.5/97.5 percentiles). The resampling itself — the part that
must be statistically right and reproducible — is never duplicated.

Pure, stdlib ``random`` only (no numpy/scipy — ADR-0001-style minimalism).
"""

from __future__ import annotations

import random

from rogue.diff.bootstrap import bootstrap_ci as _diff_bootstrap_ci

__all__ = ["bootstrap_ci", "DEFAULT_ITERS", "DEFAULT_ALPHA", "DEFAULT_SEED"]


DEFAULT_ITERS = 10_000
DEFAULT_ALPHA = 0.05
# Locked to the project epoch (matches rogue.diff.bootstrap.DEFAULT_SEED) so a
# report re-rendered twice is bit-identical.
DEFAULT_SEED = 20260524


def bootstrap_ci(
    successes: int,
    n: int,
    *,
    iters: int = DEFAULT_ITERS,
    alpha: float = DEFAULT_ALPHA,
    seed: int = DEFAULT_SEED,
) -> tuple[float, float, float]:
    """Percentile-bootstrap CI for the rate ``successes / n``.

    Args:
        successes: number of positive outcomes (``0 <= successes <= n``).
        n: sample size.
        iters: bootstrap resamples (default 10_000).
        alpha: two-sided miscoverage; the CI is the ``alpha/2`` / ``1-alpha/2``
            percentiles of the resampled rates (default 0.05 → a 95% CI).
        seed: RNG seed for reproducibility.

    Returns:
        ``(point, lo, hi)`` — the observed rate and its CI bounds, each in
        ``[0.0, 1.0]``. ``point`` is ``successes / n`` exactly (not a resampled
        mean), so the interval always brackets the reported estimate.

    Degenerate cases (no raising — every headline number needs a defined CI):
        * ``n == 0`` → ``(0.0, 0.0, 0.0)`` (no information).
        * ``successes == 0`` or ``successes == n`` → width-zero CI at the point.
    """
    if not (0 <= successes <= n):
        raise ValueError(
            f"successes ({successes}) must satisfy 0 <= successes <= n ({n})"
        )
    if n == 0:
        return (0.0, 0.0, 0.0)

    point = successes / n

    # Degenerate uniformity → exact width-zero CI (mirrors the diff helper's
    # short-circuit; avoids resampling noise on a determinate rate).
    if successes == 0:
        return (0.0, 0.0, 0.0)
    if successes == n:
        return (1.0, 1.0, 1.0)

    # Materialize the Bernoulli success vector the resampler consumes.
    trials = [True] * successes + [False] * (n - successes)

    if abs(alpha - DEFAULT_ALPHA) < 1e-12:
        # Symmetric 95% — reuse the audited diff resampler verbatim (one helper).
        lo, hi = _diff_bootstrap_ci(trials, B=iters, seed=seed)
        return (point, lo, hi)

    # Non-default alpha: the diff helper hard-codes 2.5/97.5 percentiles, so we
    # run the same resampling locally and take the requested percentiles. The
    # resampling procedure is identical (rng.choices with replacement, seeded).
    rng = random.Random(seed)
    bools = [1 if t else 0 for t in trials]
    resampled = sorted(sum(rng.choices(bools, k=n)) / n for _ in range(iters))
    lo_idx = max(0, min(iters - 1, int((alpha / 2) * iters)))
    hi_idx = max(0, min(iters - 1, int((1 - alpha / 2) * iters) - 1))
    lo = max(0.0, min(1.0, resampled[lo_idx]))
    hi = max(0.0, min(1.0, resampled[hi_idx]))
    return (point, lo, hi)
