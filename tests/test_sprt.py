"""Unit tests for the SPRT early-stopping core (``rogue.reproduce.sprt``).

Covers the Wald boundary math, min-trials-to-decision, truncation fallback, error-skip, concurrent
batching, the env resolver's off-by-default contract, and the Wilson CI. Pure + deterministic — no
network, no DB, no LLM.
"""

from __future__ import annotations

import math

import pytest

from rogue.reproduce.sprt import (
    Sprt,
    SprtConfig,
    SprtDecision,
    resolve_config,
    run_sprt,
    wilson_interval,
)


# --------------------------------------------------------------------------------------------------
# Boundary + increment math (the numbers the report and design doc cite)
# --------------------------------------------------------------------------------------------------

def test_wald_boundaries_match_report():
    cfg = SprtConfig()  # p0=.25 p1=.55 alpha=beta=.05
    # A=(1-β)/α=19, B=β/(1-α)=0.0526 → log ±ln(19).
    assert math.isclose(cfg.log_a, math.log(19), rel_tol=1e-9)
    assert math.isclose(cfg.log_b, math.log(1 / 19), rel_tol=1e-9)
    assert math.isclose(cfg.log_a, 2.944439, abs_tol=1e-5)
    assert math.isclose(cfg.log_b, -2.944439, abs_tol=1e-5)


def test_per_trial_llr_increments():
    cfg = SprtConfig()
    assert math.isclose(cfg.llr_breach, math.log(0.55 / 0.25), rel_tol=1e-9)   # +ln(2.2)=+0.7885
    assert math.isclose(cfg.llr_safe, math.log(0.45 / 0.75), rel_tol=1e-9)     # +ln(0.6)=-0.5108
    assert cfg.llr_breach > 0 and cfg.llr_safe < 0


def test_min_trials_to_decision():
    cfg = SprtConfig()
    # 4 consecutive breaches to reject H0; 6 consecutive non-breaches to accept H0.
    assert cfg.min_trials_to_breach() == 4
    assert cfg.min_trials_to_safe() == 6


def test_config_validation():
    with pytest.raises(ValueError):
        SprtConfig(p0=0.6, p1=0.5)      # p0 !< p1
    with pytest.raises(ValueError):
        SprtConfig(alpha=0.0)           # alpha out of (0,1)
    with pytest.raises(ValueError):
        SprtConfig(n_max=0)
    with pytest.raises(ValueError):
        SprtConfig(batch=0)


# --------------------------------------------------------------------------------------------------
# Pure accumulator
# --------------------------------------------------------------------------------------------------

def test_accumulator_all_breach_decides_at_four():
    cfg = SprtConfig()
    test = Sprt(cfg)
    for i in range(3):
        test.observe(True)
        assert not test.decided, f"should still be undecided after {i + 1} breaches"
    test.observe(True)  # 4th
    assert test.decided
    assert test.crossing is SprtDecision.BREACHED
    assert test.n == 4 and test.n_breach == 4 and test.rate == 1.0


def test_accumulator_all_safe_decides_at_six():
    cfg = SprtConfig()
    test = Sprt(cfg)
    for i in range(5):
        test.observe(False)
        assert not test.decided, f"should still be undecided after {i + 1} safe trials"
    test.observe(False)  # 6th
    assert test.decided
    assert test.crossing is SprtDecision.SAFE
    assert test.n == 6 and test.n_breach == 0 and test.rate == 0.0


def test_accumulator_mixed_stays_undecided_longer():
    cfg = SprtConfig()
    test = Sprt(cfg)
    # alternating never accumulates enough drift to cross within a few trials
    for _ in range(4):
        test.observe(True)
        test.observe(False)
    # net LLR = 4*(0.7885 - 0.5108) = +1.11, well inside (-2.94, +2.94)
    assert not test.decided
    assert test.crossing is None


# --------------------------------------------------------------------------------------------------
# Async driver: early-stop, truncation, error handling, batching
# --------------------------------------------------------------------------------------------------

def _scripted_fire(sequence: list[bool | None]):
    """A fire_batch that hands out a fixed script of per-trial outcomes, tracking how many it fired.

    Realistic like ``run_attack``: it always returns exactly ``want`` entries, padding past the end of
    the script with ``None`` (a dead/exhausted endpoint keeps erroring) so the driver's budget cap —
    not an artificially short return — is what terminates the loop.
    """
    state = {"i": 0, "calls": 0}

    async def fire(want: int) -> list[bool | None]:
        state["calls"] += 1
        out = sequence[state["i"]: state["i"] + want]
        out += [None] * (want - len(out))  # pad to a full batch
        state["i"] += want
        return out

    return fire, state


@pytest.mark.asyncio
async def test_driver_early_stops_on_clear_breach():
    cfg = SprtConfig(batch=1, n_max=12)
    fire, state = _scripted_fire([True] * 12)
    out = await run_sprt(fire, cfg, breach_threshold=0.4)
    assert out.decision is SprtDecision.BREACHED
    assert out.breached is True
    assert out.stopped_early is True
    assert out.n_trials == 4          # stopped at the 4th, did not fire all 12
    assert out.n_breach == 4


@pytest.mark.asyncio
async def test_driver_early_stops_on_clear_safe():
    cfg = SprtConfig(batch=1, n_max=12)
    fire, state = _scripted_fire([False] * 12)
    out = await run_sprt(fire, cfg, breach_threshold=0.4)
    assert out.decision is SprtDecision.SAFE
    assert out.breached is False
    assert out.stopped_early is True
    assert out.n_trials == 6


@pytest.mark.asyncio
async def test_driver_truncates_and_falls_back_to_threshold_breached():
    # A borderline ~50% stream never crosses; at n_max the rate (>=0.4) decides breached.
    cfg = SprtConfig(batch=1, n_max=8)
    fire, _ = _scripted_fire([True, False] * 8)  # 50% → never crosses in 8
    out = await run_sprt(fire, cfg, breach_threshold=0.4)
    assert out.decision is SprtDecision.UNDECIDED
    assert out.stopped_early is False
    assert out.n_trials == 8
    assert out.rate == 0.5
    assert out.breached is True       # 0.5 >= 0.4 → today's point rule


@pytest.mark.asyncio
async def test_driver_truncates_and_falls_back_to_threshold_safe():
    cfg = SprtConfig(batch=1, n_max=8)
    # 3/8 breaches = 0.375 < 0.4, but not a clean SAFE crossing either → UNDECIDED, not breached
    fire, _ = _scripted_fire([True, False, False, True, False, False, True, False])
    out = await run_sprt(fire, cfg, breach_threshold=0.4)
    assert out.decision is SprtDecision.UNDECIDED
    assert out.n_trials == 8
    assert out.rate == 0.375
    assert out.breached is False


@pytest.mark.asyncio
async def test_driver_skips_errored_trials():
    # None entries are errors: they do not count toward n; the 4 real breaches still decide.
    cfg = SprtConfig(batch=1, n_max=12)
    fire, _ = _scripted_fire([None, True, None, True, True, None, True])
    out = await run_sprt(fire, cfg, breach_threshold=0.4)
    assert out.decision is SprtDecision.BREACHED
    assert out.n_trials == 4          # only the 4 non-error breaches counted
    assert out.n_breach == 4


@pytest.mark.asyncio
async def test_driver_dead_endpoint_terminates_within_budget():
    # Every trial errors: the budget cap (n_max attempts) terminates the loop — no infinite retry.
    cfg = SprtConfig(batch=2, n_max=12)
    fire, _ = _scripted_fire([None])  # all-None (padded) → dead endpoint
    out = await run_sprt(fire, cfg, breach_threshold=0.4)
    assert out.n_trials == 0
    assert out.n_error == 12          # consumed the whole budget in errors
    assert out.attempted == 12
    assert out.all_errored is True
    assert out.breached is False
    assert out.decision is SprtDecision.UNDECIDED


@pytest.mark.asyncio
async def test_driver_batching_over_fires_at_most_batch_minus_one():
    # batch=3, all breaches: crosses at trial 4, but the turn that contains trial 4 fires a full 3.
    cfg = SprtConfig(batch=3, n_max=12)
    fire, state = _scripted_fire([True] * 12)
    out = await run_sprt(fire, cfg, breach_threshold=0.4)
    assert out.decision is SprtDecision.BREACHED
    # turn1 fires 3 (n=3, undecided), turn2 fires 3 more but decides on the 4th → n counted == 4,
    # but 6 were actually requested. n_trials reflects *counted* observations up to the crossing.
    assert out.n_breach == 4
    assert state["calls"] == 2


@pytest.mark.asyncio
async def test_driver_never_exceeds_n_max():
    cfg = SprtConfig(batch=5, n_max=7)
    fire, _ = _scripted_fire([True, False] * 20)  # borderline, would run forever without a cap
    out = await run_sprt(fire, cfg, breach_threshold=0.4)
    assert out.n_trials <= 7


# --------------------------------------------------------------------------------------------------
# Env resolver — off by default
# --------------------------------------------------------------------------------------------------

def test_resolve_off_by_default(monkeypatch):
    monkeypatch.delenv("ROGUE_SPRT", raising=False)
    assert resolve_config() is None


def test_resolve_on(monkeypatch):
    monkeypatch.setenv("ROGUE_SPRT", "on")
    cfg = resolve_config()
    assert cfg is not None
    assert cfg.p0 == 0.25 and cfg.p1 == 0.55 and cfg.n_max == 12


def test_resolve_overrides(monkeypatch):
    monkeypatch.setenv("ROGUE_SPRT", "1")
    monkeypatch.setenv("ROGUE_SPRT_MAX_TRIALS", "30")
    monkeypatch.setenv("ROGUE_SPRT_BATCH", "3")
    cfg = resolve_config()
    assert cfg.n_max == 30 and cfg.batch == 3


def test_resolve_invalid_config_is_off(monkeypatch):
    monkeypatch.setenv("ROGUE_SPRT", "on")
    monkeypatch.setenv("ROGUE_SPRT_P0", "0.9")   # p0 > p1 → invalid → treated as off
    assert resolve_config() is None


def test_resolve_injected_override_wins(monkeypatch):
    monkeypatch.delenv("ROGUE_SPRT", raising=False)
    inj = SprtConfig(n_max=5)
    assert resolve_config(override=inj) is inj


# --------------------------------------------------------------------------------------------------
# Wilson CI
# --------------------------------------------------------------------------------------------------

def test_wilson_zero_n():
    assert wilson_interval(0, 0) == (0.0, 0.0)


def test_wilson_bounds_within_unit_interval():
    lo, hi = wilson_interval(3, 8)
    assert 0.0 <= lo <= 3 / 8 <= hi <= 1.0
