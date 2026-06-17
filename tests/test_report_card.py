"""Tests for the shareable breach report card (`rogue.report_card`).

Verifies the public contract: `render_breach_card(card, out_dir) -> {"html","png","svg"}` writes
non-empty, locked-brand-colored, self-contained artifacts from a plain dict — zero network, zero
keys. Assertions cover the spec's must-haves: the locked palette, the breach rate, the model label,
the tier chip, the breach grid, and the dependency-light PNG decision.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rogue.report_card import BG, FOOTER_URL, GREEN, RED, TAGLINE, render_breach_card


def _sample_card() -> dict:
    return {
        "model_label": "gpt-4o-mini",
        "breach_rate": 0.6,
        "trials": 10,
        "breaches": 6,
        "top_attack": "dan_persona",
        "families": ["dan_persona", "role_hijack", "refusal_suppression", "obfuscation_encoding"],
        "verdict_counts": {"FULL_BREACH": 4, "PARTIAL_BREACH": 2, "REFUSED": 4},
        "tier": "quick",
        "generated_at": "2026-06-18T12:00:00Z",
    }


def test_render_returns_contract_keys(tmp_path: Path) -> None:
    out = render_breach_card(_sample_card(), tmp_path)
    assert set(out) == {"html", "png", "svg"}
    assert isinstance(out["html"], Path)
    assert isinstance(out["svg"], Path)
    # png is Path | None — Pillow is a project dep so it should be a Path here.
    assert out["png"] is None or isinstance(out["png"], Path)


def test_files_exist_and_nonempty(tmp_path: Path) -> None:
    out = render_breach_card(_sample_card(), tmp_path)
    for key in ("html", "svg", "png"):
        path = out[key]
        assert path is not None, f"{key} should have been produced"
        assert path.exists(), f"{key} file missing: {path}"
        assert path.stat().st_size > 0, f"{key} file is empty"


def test_svg_carries_locked_brand_and_facts(tmp_path: Path) -> None:
    out = render_breach_card(_sample_card(), tmp_path)
    svg = out["svg"].read_text(encoding="utf-8")
    # Locked palette — every one must appear.
    assert GREEN in svg
    assert RED in svg
    assert BG in svg
    # Breach rate, in both the count and the percentage forms.
    assert "6/10" in svg
    assert "60% BREACH RATE" in svg
    # Model label, top-attack DISPLAY label (matches report.py vocabulary), brand strings.
    assert "gpt-4o-mini" in svg
    assert "DAN / Persona Jailbreak" in svg
    assert TAGLINE in svg
    assert FOOTER_URL in svg
    # Self-contained vector card.
    assert svg.lstrip().startswith("<svg")
    assert "</svg>" in svg


def test_html_is_self_contained(tmp_path: Path) -> None:
    out = render_breach_card(_sample_card(), tmp_path)
    html = out["html"].read_text(encoding="utf-8")
    assert html.lstrip().lower().startswith("<!doctype html>")
    # Locked colors, the rate, the model, and the embedded (not externally fetched) SVG card.
    assert GREEN in html and RED in html and BG in html
    assert "6/10" in html
    assert "gpt-4o-mini" in html
    assert "<svg" in html
    # No external font fetch at render — no Google Fonts / remote stylesheet links.
    assert "fonts.googleapis.com" not in html
    assert "<link" not in html.lower()


def test_png_is_a_real_raster(tmp_path: Path) -> None:
    out = render_breach_card(_sample_card(), tmp_path)
    png = out["png"]
    if png is None:  # pragma: no cover - only when Pillow is unavailable
        pytest.skip("Pillow unavailable; SVG/HTML are the canonical artifacts")
    data = png.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG file"
    # The OG card is 1200×630 — check the IHDR width/height (bytes 16-24).
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    assert (width, height) == (1200, 630)


def test_square_svg_variant_written(tmp_path: Path) -> None:
    render_breach_card(_sample_card(), tmp_path)
    square = tmp_path / "breach-card-square.svg"
    assert square.exists() and square.stat().st_size > 0
    svg = square.read_text(encoding="utf-8")
    assert 'width="1080" height="1080"' in svg


def test_calibrated_tier_chip(tmp_path: Path) -> None:
    card = _sample_card()
    card["tier"] = "calibrated"
    out = render_breach_card(card, tmp_path)
    svg = out["svg"].read_text(encoding="utf-8")
    assert "calibrated judge ✓" in svg
    assert "quick scan" not in svg


def test_quick_tier_chip(tmp_path: Path) -> None:
    out = render_breach_card(_sample_card(), tmp_path)
    svg = out["svg"].read_text(encoding="utf-8")
    assert "quick scan — upgrade for calibrated judge" in svg


def test_breach_rate_derived_when_missing(tmp_path: Path) -> None:
    card = _sample_card()
    del card["breach_rate"]  # force derivation from trials/breaches
    out = render_breach_card(card, tmp_path)
    svg = out["svg"].read_text(encoding="utf-8")
    assert "60% BREACH RATE" in svg


def test_zero_breach_card_lights_no_red_grid(tmp_path: Path) -> None:
    card = _sample_card()
    card.update(breach_rate=0.0, breaches=0, top_attack=None)
    out = render_breach_card(card, tmp_path)
    svg = out["svg"].read_text(encoding="utf-8")
    assert "0/10" in svg
    assert "0% BREACH RATE" in svg
    # Defended-only card still renders the brand red somewhere (orb/defs) but reads as 0 breached.
    assert "— none breached" in svg


def test_humane_top_attack_label_passthrough(tmp_path: Path) -> None:
    card = _sample_card()
    card["top_attack"] = "Crescendo"  # already-humane label must not be re-slugified
    out = render_breach_card(card, tmp_path)
    assert "Crescendo" in out["svg"].read_text(encoding="utf-8")


def test_no_network_import_surface() -> None:
    """The module must be importable with no network/keys — a plain import + render is the contract.
    (Implicitly covered by every test above; this asserts the entry point is a plain callable.)"""
    assert callable(render_breach_card)
