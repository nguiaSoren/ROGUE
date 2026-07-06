"""The PII-leakage card renders valid SVG for both aspect ratios and both leak states."""

from __future__ import annotations

import xml.dom.minidom as minidom

from rogue.pii_card import PiiProfile, render_pii_card

_HELD = PiiProfile(
    config_name="demo", target_model="openai/gpt-5.4",
    context_leak_rate=0.0, emission_rate=0.167, detector_precision=0.95,
    provenance={"parametric": 24}, top_attributes=[("ssn", "critical"), ("email", "high")], n_probes=18,
)
_LEAKY = PiiProfile(
    config_name="weak", target_model="some/model",
    context_leak_rate=0.42, emission_rate=0.6, detector_precision=0.9,
    provenance={"planted": 5, "retrieval": 3, "parametric": 2}, top_attributes=[("ssn", "critical")], n_probes=36,
)


def test_renders_valid_svg_both_ratios():
    for square in (False, True):
        svg = render_pii_card(_HELD, square=square)
        minidom.parseString(svg)  # raises on malformed
        assert svg.startswith("<svg") and svg.endswith("</svg>")


def test_held_shows_zero_and_green():
    svg = render_pii_card(_HELD)
    assert "0% CONTEXT LEAK" in svg
    assert "HELD" in svg


def test_leaky_shows_rate():
    svg = render_pii_card(_LEAKY)
    assert "42% CONTEXT LEAK" in svg
    # provenance bar renders all three sources
    for k in ("planted", "retrieval", "parametric"):
        assert k in svg


def test_emission_labeled_non_headline():
    assert "non-headline" in render_pii_card(_HELD)
