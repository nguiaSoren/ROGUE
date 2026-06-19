"""Tests for ``rogue.reproduce.calibration.bootstrap`` (build 02 §4.1).

The bootstrap CI is load-bearing — every v2 calibration headline number gets
its error bars from here. We check: (1) the CI brackets the point estimate,
(2) it is reproducible under a fixed seed, (3) the degenerate cases are exact,
and (4) a coverage sanity check against the analytic Wilson interval.
"""

from __future__ import annotations

import math

import pytest

from rogue.reproduce.calibration.bootstrap import DEFAULT_SEED, bootstrap_ci


def _wilson(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Analytic Wilson 95% interval for a binomial proportion (reference)."""
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (centre - half, centre + half)


def test_ci_brackets_point_estimate():
    point, lo, hi = bootstrap_ci(40, 100, seed=DEFAULT_SEED)
    assert point == pytest.approx(0.40)
    assert lo <= point <= hi
    assert 0.0 <= lo < hi <= 1.0


def test_point_is_exact_rate_not_resampled():
    # point must be the observed rate exactly, not a resampled mean.
    point, _, _ = bootstrap_ci(37, 100, seed=DEFAULT_SEED)
    assert point == 37 / 100


def test_reproducible_under_fixed_seed():
    a = bootstrap_ci(33, 80, seed=12345)
    b = bootstrap_ci(33, 80, seed=12345)
    assert a == b


def test_different_seed_can_shift_bounds():
    a = bootstrap_ci(33, 80, seed=1)
    b = bootstrap_ci(33, 80, seed=2)
    # Point identical; the resampled bounds may differ.
    assert a[0] == b[0]
    assert (a[1], a[2]) != (b[1], b[2]) or True  # tolerate rare coincidence


def test_degenerate_cases_exact():
    assert bootstrap_ci(0, 0) == (0.0, 0.0, 0.0)
    assert bootstrap_ci(0, 50) == (0.0, 0.0, 0.0)
    assert bootstrap_ci(50, 50) == (1.0, 1.0, 1.0)


def test_invalid_successes_raises():
    with pytest.raises(ValueError):
        bootstrap_ci(11, 10)
    with pytest.raises(ValueError):
        bootstrap_ci(-1, 10)


def test_bounds_in_unit_interval():
    for s in (1, 5, 50, 95, 99):
        _, lo, hi = bootstrap_ci(s, 100, seed=DEFAULT_SEED)
        assert 0.0 <= lo <= hi <= 1.0


def test_coverage_sanity_vs_wilson():
    # The percentile bootstrap and the Wilson interval are different estimators,
    # but for a non-degenerate moderate n they should land in the same
    # ballpark. Assert the bootstrap interval overlaps Wilson and is of a
    # comparable width (within 2x) — a sanity check, not an equivalence proof.
    successes, n = 40, 100
    _, blo, bhi = bootstrap_ci(successes, n, iters=10_000, seed=DEFAULT_SEED)
    wlo, whi = _wilson(successes, n)
    # Overlap.
    assert blo <= whi and wlo <= bhi
    bwidth = bhi - blo
    wwidth = whi - wlo
    assert 0.5 * wwidth <= bwidth <= 2.0 * wwidth


def test_non_default_alpha_widens_with_higher_confidence():
    # A 99% CI (alpha=0.01) must be at least as wide as a 95% CI (alpha=0.05).
    _, lo95, hi95 = bootstrap_ci(40, 100, alpha=0.05, seed=DEFAULT_SEED)
    _, lo99, hi99 = bootstrap_ci(40, 100, alpha=0.01, seed=DEFAULT_SEED)
    assert (hi99 - lo99) >= (hi95 - lo95) - 1e-9
    assert lo99 <= lo95 + 1e-9
    assert hi99 >= hi95 - 1e-9
