"""Tests for ``rogue.reproduce.calibration.noise_corrected`` (Feng/Lee).

Covers the de-biased point estimate + CI (Lee, Rogan–Gladen + delta method),
the variance-corrected certification test (Feng Eq. 6), the refusal guards
(uninformative judge / empty cells), and the env-config resolver (off by
default, byte-identical when off is the runner's job — here we test the flag).

Golden values are hand-computed in the docstring of each case so a reviewer can
recompute them without the module.
"""

from __future__ import annotations

import math

import pytest

from rogue.reproduce.calibration.noise_corrected import (
    ENV_ALPHA,
    ENV_ENABLED,
    ENV_ZETA,
    noise_corrected_from_agreement,
    noise_corrected_rate,
    resolve_noise_config,
)
from rogue.reproduce.wildguard_eval import AxisAgreement


def test_perfect_judge_is_identity():
    """TPR̂=1, FPR̂=0 ⇒ corrected == raw exactly (no bias to remove).

    raw = 30/1000 = 0.03, margin = 1 ⇒ corrected = 0.03.
    """
    r = noise_corrected_rate(
        tpr=1.0, fpr=0.0, n_m1=100, n_m0=100,
        judge_positive=30, n_judge=1000, alpha=0.20, zeta=0.05,
    )
    assert r.informative is True
    assert r.corrected_rate == pytest.approx(0.03, abs=1e-12)
    # CI brackets the point and is inside [0,1].
    assert 0.0 <= r.ci_lo <= r.corrected_rate <= r.ci_hi <= 1.0
    # α̂′ = 0 + 1·0.2 = 0.2; c′_J = 0.2 + Φ⁻¹(0.05)·sqrt(0.2·0.8/1000).
    assert r.alpha_prime == pytest.approx(0.20, abs=1e-12)
    assert r.critical_value == pytest.approx(0.179194, abs=1e-4)
    assert r.certified is True  # raw 0.03 < c′_J 0.179


def test_upward_bias_removed_at_low_true_rate():
    """An FP-heavy judge inflates a low rate; correction pulls it down.

    TPR̂=0.9, FPR̂=0.1, raw=0.15 ⇒ corrected = (0.15−0.1)/0.8 = 0.0625 < raw.
    """
    r = noise_corrected_rate(
        tpr=0.9, fpr=0.1, n_m1=200, n_m0=200,
        judge_positive=150, n_judge=1000, alpha=0.20, zeta=0.05,
    )
    assert r.informative
    assert r.corrected_rate == pytest.approx(0.0625, abs=1e-9)
    assert r.corrected_rate < r.raw_rate  # the whole point: de-inflate


def test_corrected_rate_clamped_to_zero():
    """When raw < FPR̂, the de-biased rate is negative → clamped to 0.

    raw = 0.10, FPR̂ = 0.13 ⇒ (0.10−0.13)/D < 0 ⇒ 0.0.
    """
    r = noise_corrected_rate(
        tpr=0.97, fpr=0.13, n_m1=110, n_m0=190,
        judge_positive=100, n_judge=1000, alpha=0.20, zeta=0.05,
    )
    assert r.corrected_rate == 0.0
    assert r.ci_lo == 0.0
    assert r.ci_hi > 0.0  # CI still has width from calibration uncertainty


def test_refuses_uninformative_judge():
    """TPR̂ ≤ FPR̂ ⇒ de-biasing undefined ⇒ refuse (no fabricated number)."""
    r = noise_corrected_rate(
        tpr=0.4, fpr=0.4, n_m1=100, n_m0=100,
        judge_positive=50, n_judge=1000,
    )
    assert r.informative is False
    assert r.corrected_rate is None
    assert r.certified is None
    assert "informative" in (r.reason or "")


def test_refuses_empty_calibration_cell():
    r = noise_corrected_rate(
        tpr=1.0, fpr=0.0, n_m1=0, n_m0=100,
        judge_positive=30, n_judge=1000,
    )
    assert r.informative is False
    assert "cell empty" in (r.reason or "")


def test_refuses_empty_judge_run():
    r = noise_corrected_rate(
        tpr=0.9, fpr=0.1, n_m1=100, n_m0=100,
        judge_positive=0, n_judge=0,
    )
    assert r.informative is False
    assert "empty judge run" in (r.reason or "")


def test_from_agreement_derives_tpr_fpr():
    """2x2 (breach polarity) ⇒ TPR̂=tp/(tp+fn), FPR̂=fp/(fp+tn)."""
    agr = AxisAgreement(axis="breach", tp=90, fp=10, fn=10, tn=90)
    r = noise_corrected_from_agreement(
        agr, judge_positive=150, n_judge=1000, alpha=0.20, zeta=0.05,
    )
    assert r.tpr == pytest.approx(0.9)  # 90/(90+10)
    assert r.fpr == pytest.approx(0.1)  # 10/(10+90)
    assert r.n_m1 == 100 and r.n_m0 == 100
    assert r.corrected_rate == pytest.approx(0.0625, abs=1e-9)


def test_ci_widens_with_smaller_calibration_set():
    """Feng's point: scarcer calibration ⇒ wider CI (the variance terms grow)."""
    big = noise_corrected_rate(
        tpr=0.9, fpr=0.1, n_m1=1000, n_m0=1000,
        judge_positive=150, n_judge=5000,
    )
    small = noise_corrected_rate(
        tpr=0.9, fpr=0.1, n_m1=20, n_m0=20,
        judge_positive=150, n_judge=5000,
    )
    big_w = big.ci_hi - big.ci_lo
    small_w = small.ci_hi - small.ci_lo
    assert small_w > big_w


def test_to_dict_and_summary_shapes():
    r = noise_corrected_rate(
        tpr=0.9, fpr=0.1, n_m1=100, n_m0=100,
        judge_positive=150, n_judge=1000,
    )
    d = r.to_dict()
    assert d["corrected_ci"] == [r.corrected_rate, r.ci_lo, r.ci_hi]
    assert set(["tpr", "fpr", "raw_rate", "certified", "critical_value"]).issubset(d)
    assert "corrected=" in r.summary_line()
    # refused case renders a REFUSED line and a None ci in the dict.
    ref = noise_corrected_rate(tpr=0.3, fpr=0.3, n_m1=10, n_m0=10,
                               judge_positive=1, n_judge=10)
    assert "REFUSED" in ref.summary_line()
    assert ref.to_dict()["corrected_ci"] is None


# --------------------------------------------------------------------------- #
# Config resolver — OFF by default; flag + params parse from env.
# --------------------------------------------------------------------------- #


def test_config_off_by_default():
    assert resolve_noise_config(env={}).enabled is False


@pytest.mark.parametrize("tok", ["1", "true", "TRUE", "yes", "on"])
def test_config_truthy_tokens_enable(tok):
    assert resolve_noise_config(env={ENV_ENABLED: tok}).enabled is True


@pytest.mark.parametrize("tok", ["0", "false", "off", "", "nope"])
def test_config_falsy_tokens_stay_off(tok):
    assert resolve_noise_config(env={ENV_ENABLED: tok}).enabled is False


def test_config_alpha_zeta_parse_and_default():
    c = resolve_noise_config(env={ENV_ENABLED: "on", ENV_ALPHA: "0.1", ENV_ZETA: "0.01"})
    assert c.alpha == pytest.approx(0.1)
    assert c.zeta == pytest.approx(0.01)
    assert c.ci_level == pytest.approx(0.99)
    # bad float → fall back to default, no raise.
    d = resolve_noise_config(env={ENV_ENABLED: "on", ENV_ALPHA: "banana"})
    assert d.alpha == pytest.approx(0.20)


def test_config_clamps_degenerate_params():
    c = resolve_noise_config(env={ENV_ENABLED: "on", ENV_ALPHA: "1.5", ENV_ZETA: "0.9"})
    assert 0.0 < c.alpha < 1.0
    assert 0.0 < c.zeta < 0.5


def test_certification_variance_terms_present():
    """c′_J must sit below α̂′ (Φ⁻¹(ζ)<0) and shrink toward α̂′ as n grows."""
    small_n = noise_corrected_rate(
        tpr=0.9, fpr=0.1, n_m1=30, n_m0=30, judge_positive=100, n_judge=300,
    )
    large_n = noise_corrected_rate(
        tpr=0.9, fpr=0.1, n_m1=3000, n_m0=3000, judge_positive=100000, n_judge=300000,
    )
    # More data ⇒ smaller safety margin (c′_J closer to α̂′).
    assert small_n.alpha_prime == pytest.approx(large_n.alpha_prime, abs=1e-9)
    margin_small = small_n.alpha_prime - small_n.critical_value
    margin_large = large_n.alpha_prime - large_n.critical_value
    assert margin_small > margin_large > 0
    assert not math.isnan(small_n.critical_value)
