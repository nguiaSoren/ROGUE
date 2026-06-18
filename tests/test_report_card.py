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
    assert "quick scan" in svg
    assert "upgrade" not in svg  # the nag tail was dropped — chip is a clean confidence band


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


# --- QR code ------------------------------------------------------------------------------------
def test_qr_url_default_is_leaderboard() -> None:
    from rogue.report_card import _QR_URL

    assert _QR_URL == "https://rogue-eosin.vercel.app/leaderboard"


def test_styled_qr_image_builds_at_requested_size() -> None:
    """`_styled_qr_image` returns a square RGB PIL image of the requested side (qrcode is a declared
    dep). The modules are integer-pixel crisp and white-padded to the exact size."""
    from rogue.report_card import _styled_qr_image

    img = _styled_qr_image("https://rogue-eosin.vercel.app/leaderboard", 150)
    assert img is not None
    assert img.size == (150, 150)
    assert img.mode == "RGB"


def test_svg_embeds_qr_image(tmp_path: Path) -> None:
    """The styled QR is embedded as a base64 PNG ``<image>`` on a white rounded tile (green border),
    on both the OG and square SVG, with the honest scan label."""
    out = render_breach_card(_sample_card(), tmp_path)
    svg = out["svg"].read_text(encoding="utf-8")
    square = (tmp_path / "breach-card-square.svg").read_text(encoding="utf-8")
    for doc in (svg, square):
        assert 'fill="#ffffff"' in doc  # the white QR tile
        assert "<image" in doc and "data:image/png;base64," in doc  # the embedded styled QR
    assert "scan → leaderboard" in svg


def test_card_renders_without_qrcode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the QR can't be rendered (qrcode/Pillow absent), the card still renders fully — contract
    keys intact, PNG still the right size, no QR tile/label drawn (graceful degradation)."""
    monkeypatch.setattr("rogue.report_card._styled_qr_image", lambda *a, **k: None)
    out = render_breach_card(_sample_card(), tmp_path)
    assert set(out) == {"html", "png", "svg"}
    svg = out["svg"].read_text(encoding="utf-8")
    assert svg.lstrip().startswith("<svg") and "</svg>" in svg
    # No QR tile / embedded image / scan label when the QR is absent.
    assert "data:image/png;base64," not in svg
    assert "scan → leaderboard" not in svg
    # The breach facts and brand are still present.
    assert "6/10" in svg and GREEN in svg
    png = out["png"]
    if png is not None:
        data = png.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")) == (1200, 630)


def test_qr_url_override_changes_embedded_qr(tmp_path: Path) -> None:
    """A card-supplied `qr_url` overrides the default leaderboard target: the override URL is encoded
    into the QR, so the embedded base64 image differs from the default leaderboard card's."""
    override = "https://rogue-eosin.vercel.app/m/some-model"

    card = _sample_card()
    card["qr_url"] = override
    over_svg = render_breach_card(card, tmp_path)["svg"].read_text(encoding="utf-8")
    default_svg = render_breach_card(_sample_card(), tmp_path / "d")["svg"].read_text(encoding="utf-8")

    assert _qr_data_uri(over_svg) is not None
    assert _qr_data_uri(over_svg) != _qr_data_uri(default_svg)  # different target → different image


def _qr_data_uri(svg: str) -> str | None:
    """The embedded QR PNG data-URI in an SVG — a fingerprint of the encoded URL."""
    import re

    m = re.search(r'href="(data:image/png;base64,[^"]+)"', svg)
    return m.group(1) if m else None


def test_measured_date_line_appears(tmp_path: Path) -> None:
    """The muted `measured <date>` credibility line appears on both the OG and the square SVG, with
    only the date portion of `generated_at` (an ISO timestamp is trimmed to YYYY-MM-DD)."""
    card = _sample_card()  # generated_at = "2026-06-18T12:00:00Z"
    out = render_breach_card(card, tmp_path)
    svg = out["svg"].read_text(encoding="utf-8")
    square = (tmp_path / "breach-card-square.svg").read_text(encoding="utf-8")
    assert "measured 2026-06-18" in svg
    assert "measured 2026-06-18" in square
    # The full timestamp's time portion is not shown — just the date.
    assert "12:00:00" not in svg

    # A plain YYYY-MM-DD date passes through unchanged.
    card2 = _sample_card()
    card2["generated_at"] = "2026-06-19"
    svg2 = render_breach_card(card2, tmp_path / "d2")["svg"].read_text(encoding="utf-8")
    assert "measured 2026-06-19" in svg2


def test_og_coverage_shows_families_in_full(tmp_path: Path) -> None:
    """The OG card's COVERAGE column must show the family count in full — it used to be the last
    column and got truncated by the QR tile. A realistic large card ('N trials · M families') must
    appear un-clipped (no trailing ellipsis on the families word) on the 1200×630 OG svg."""
    card = _sample_card()
    card.update(trials=2288, breaches=350, breach_rate=0.15)
    card["families"] = [f"family_{i}" for i in range(15)]
    out = render_breach_card(card, tmp_path)
    svg = out["svg"].read_text(encoding="utf-8")
    assert "2288 trials · 15 families" in svg  # full coverage string, families not cut off


def test_qr_label_reflects_target(tmp_path: Path) -> None:
    """The scan label under the QR is honest about where the code goes: the generic card lands on the
    leaderboard ('scan → leaderboard'); a per-model card (qr_url override) deep-links to that model's
    breach cell ('scan → breaches')."""
    generic = render_breach_card(_sample_card(), tmp_path)["svg"].read_text(encoding="utf-8")
    assert "scan → leaderboard" in generic
    assert "scan → breaches" not in generic

    card = _sample_card()
    card["qr_url"] = "https://rogue-eosin.vercel.app/m/gpt-4o-mini"
    overridden = render_breach_card(card, tmp_path / "o")["svg"].read_text(encoding="utf-8")
    assert "scan → breaches" in overridden
    assert "scan → leaderboard" not in overridden


@pytest.mark.parametrize(
    "qr_url, expected",
    [
        (None, "https://rogue-eosin.vercel.app/leaderboard"),  # generic card → leaderboard
        (
            "https://rogue-eosin.vercel.app/m/voxtral-small-24b-2507",  # per-model → that model
            "https://rogue-eosin.vercel.app/m/voxtral-small-24b-2507",
        ),
    ],
)
def test_qr_decodes_to_target(tmp_path: Path, qr_url, expected) -> None:
    """The single most important QR guarantee: the code rendered onto BOTH the OG and square card
    actually scans, and decodes to the intended URL. Decoded off the final PNG with cv2's detector
    (skips if cv2 isn't installed). This is what keeps "clean QR" from silently meaning "dead QR"."""
    cv2 = pytest.importorskip("cv2")
    import numpy as np  # noqa: F401  (cv2 needs numpy present)

    card = _sample_card()
    card.update(trials=185, breaches=81, breach_rate=0.44, families=[f"f{i}" for i in range(9)])
    if qr_url:
        card["qr_url"] = qr_url
    render_breach_card(card, tmp_path)

    detector = cv2.QRCodeDetector()
    for name in ("breach-card.png", "breach-card-square.png"):
        img = cv2.imread(str(tmp_path / name))
        data, _, _ = detector.detectAndDecode(img)
        assert data == expected, f"{name} QR decoded to {data!r}, expected {expected!r}"
