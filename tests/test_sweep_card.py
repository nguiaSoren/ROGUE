"""Sweep card — the robustness-threshold companion to the breach card. Pure SVG build, no browser."""

from __future__ import annotations

import xml.dom.minidom as minidom

import pytest

from rogue.reproduce.generator_sweep import SweepPoint, SweepResult
from rogue.sweep_card import render_sweep_card


def _result(threshold):
    pts = [
        SweepPoint(2000, 2047, 4, 0, 0.0, 0.0, 0.49),
        SweepPoint(8000, 8059, 4, 0, 0.0, 0.0, 0.49),
        SweepPoint(32000, 32160, 4, 2, 0.5, 0.15, 0.85),
        SweepPoint(128000, 128052, 4, 4, 1.0, 0.51, 1.0),
    ]
    return SweepResult(kind="many_shot", sweep_param="target_tokens", points=pts, cost_usd=0.04,
                       breach_threshold=0.5, threshold_value=threshold)


def test_renders_valid_svg_with_curve_and_threshold():
    svg = render_sweep_card(_result(32000), config_name="acme", target_model="qwen/qwen-2.5-7b")
    minidom.parseString(svg)  # well-formed XML or raises
    assert "<polyline" in svg  # the ASR curve
    assert "BREAKS AT" in svg and "stroke-dasharray" in svg  # threshold callout + marker line
    assert 'fill="#ff003c"' in svg and 'fill="#00ff88"' in svg  # breached (red) + held (green) points
    assert "128K" in svg  # token values are humanized on the x-axis


def test_held_sweep_says_so_and_has_no_threshold_line():
    svg = render_sweep_card(_result(None), config_name="acme")
    assert "HELD ACROSS THE SWEEP" in svg
    assert "BREAKS AT" not in svg


def test_square_variant_renders_1080():
    svg = render_sweep_card(_result(32000), config_name="acme", square=True)
    minidom.parseString(svg)
    assert 'width="1080" height="1080"' in svg  # feed-post aspect
    assert "BREAKS AT" in svg and "<polyline" in svg


def test_empty_points_raises():
    empty = SweepResult(kind="many_shot", sweep_param="target_tokens")
    with pytest.raises(ValueError):
        render_sweep_card(empty, config_name="acme")
