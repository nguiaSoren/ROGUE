"""Render the PII-leakage card from the Axis-B run data (context-leak + emission + calibration).

Builds a PiiProfile for one target from data/research/pii/*.json and writes the landscape + square
SVG (canonical). Rasterizes to PNG if a CLI rasterizer (rsvg-convert / resvg / inkscape) is present.

Usage:  uv run python scripts/cards/generate_pii_card.py [--model openai/gpt-5.4]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from rogue.pii_card import PiiProfile, render_pii_card
from rogue.reproduce.agent import pri
from rogue.schemas.attack_primitive import severity_from_score

DATA = Path(__file__).resolve().parents[2] / "data" / "research" / "pii"


def _load(name):
    p = DATA / name
    return json.load(open(p)) if p.exists() else {}


def _rasterize(svg_path: Path, png_path: Path, w: int, h: int) -> bool:
    for tool, cmd in (
        ("rsvg-convert", ["rsvg-convert", "-w", str(w), "-h", str(h), "-o", str(png_path), str(svg_path)]),
        ("resvg", ["resvg", "-w", str(w), str(svg_path), str(png_path)]),
        ("inkscape", ["inkscape", str(svg_path), "--export-type=png", f"--export-filename={png_path}", "-w", str(w)]),
    ):
        if shutil.which(tool):
            try:
                subprocess.run(cmd, check=True, capture_output=True)
                return png_path.exists()
            except subprocess.CalledProcessError:
                continue
    return False


def build_profile(model: str) -> PiiProfile:
    ctx = _load("context_leak_result.json").get("per_model", {}).get(model, {})
    emi = _load("emission_result.json").get("per_model", {}).get(model, {})
    cal = _load("calibration_result.json")
    precision = 0.0
    for s in cal.get("slices", []):
        if s.get("slice") == "calibration":
            precision = s.get("regex+semantic", {}).get("precision", 0.0)

    if not ctx:
        fl = _load("featherless_context_leak_result.json").get("per_model", {})
        ctx = fl.get(model) or fl.get(f"featherless:{model}") or {}

    # attributes: emission (fabrication) run, else the context-leak (Featherless) run's leaked set
    attrs = emi.get("attributes") or ctx.get("attributes_leaked", {})
    top = sorted(attrs.items(), key=lambda kv: -kv[1])
    top_attributes = [(a, severity_from_score(pri.score_for(a)).value) for a, _ in top]

    return PiiProfile(
        config_name="demo-support-agent",
        target_model=model,
        context_leak_rate=ctx.get("context_leak_rate", ctx.get("leak_rate", 0.0)),
        emission_rate=emi.get("emission_rate", 0.0),
        detector_precision=precision,
        # emission run carries a provenance split; a context-leak (planted) run is 100% PLANTED
        provenance=emi.get("provenance") or ({"planted": ctx.get("n_leaked", 0)} if ctx.get("n_leaked") else {}),
        param_split={},  # emission_result predates the subtype wiring; left empty
        top_attributes=top_attributes,
        n_probes=emi.get("n_cells", 0) or ctx.get("n_cells", 0),
    )


# marketing cards live alongside the breach/sweep/oss cards
OUT = Path(__file__).resolve().parents[2] / "assets" / "card" / "marketing"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="openai/gpt-5.4")
    ap.add_argument("--slug", default="pii-card")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    profile = build_profile(args.model)
    written = []
    for square, suffix in ((False, ""), (True, "-square")):
        name = f"{args.slug}{suffix}"
        svg = render_pii_card(profile, square=square)
        svg_path = OUT / f"{name}.svg"
        svg_path.write_text(svg)
        written.append(str(svg_path))
        w, h = (1080, 1080) if square else (1200, 630)
        png_path = OUT / f"{name}.png"
        if _rasterize(svg_path, png_path, w, h):
            written.append(str(png_path))

    print("PII card profile:", args.model)
    print(f"  context-leak={profile.context_leak_rate:.0%}  emission={profile.emission_rate:.0%}  "
          f"precision={profile.detector_precision:.2f}  attrs={[a for a, _ in profile.top_attributes]}")
    print("wrote:")
    for w_ in written:
        print("  " + w_)
    if not any(p.endswith(".png") for p in written):
        print("  (no PNG — install rsvg-convert/resvg/inkscape to rasterize; SVG is canonical)")


if __name__ == "__main__":
    main()
