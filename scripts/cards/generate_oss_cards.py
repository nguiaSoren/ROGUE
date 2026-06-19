"""Render one shareable ROGUE breach card per open-source (Featherless sweep) model.

Sibling of ``generate_model_cards.py`` (the demo-stats hosted-model cards). Reads the REAL measured
per-model breach rates from ``src/rogue/data/oss_leaderboard_stats.json`` — the same numbers the live
OSS ``/leaderboard`` shows — and renders a brand-native breach card for each of the 16 Featherless
open-weight models via ``rogue.report_card.render_breach_card``.

The displayed ``N/M BREACHED`` + percentage are pinned to the leaderboard's **primitive-level
any-breach** rate: ``breaches = breached_primitives`` over ``trials = n_primitives`` (e.g. the
abliterated Llama = 11/15 = 73%). The headline ``breach_rate`` ring uses ``mean_breach_rate``. Each
card's QR points at that model's all-time breach detail cell on the live matrix via the short
``/m/<slug>`` redirect, and carries a muted ``measured <date>`` credibility line.

Outputs, per model (``<slug>`` = a filesystem-safe ``model_label``):
    * ``assets/card/models/<slug>/``   — the full set: svg, square svg, og png, square png, html.
    * ``frontend/public/cards/<slug>.png`` — JUST the 1200×630 OG png (for a "share card" button).

And MERGES the 16 slug→{family,config} entries into ``frontend/src/data/model-cards.json`` (the map
the ``/m/[slug]`` redirect route resolves) WITHOUT dropping the existing hosted-model entries.

Pure + offline: no network, no API keys. ``--date`` defaults to the stats file's ``measured`` date.

Run:
    uv run python scripts/cards/generate_oss_cards.py
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from rogue.report_card import render_breach_card

# Repo root = three levels up from this file (scripts/cards/generate_oss_cards.py).
_ROOT = Path(__file__).resolve().parents[2]
_OSS_STATS = _ROOT / "src" / "rogue" / "data" / "oss_leaderboard_stats.json"
_ASSETS_DIR = _ROOT / "assets" / "card" / "models"
_FRONTEND_DIR = _ROOT / "frontend" / "public" / "cards"
# The slug→{family,config} map the short-link redirect route (`/m/[slug]`) resolves. MERGED here so
# the OSS card QR targets and the route that serves them derive from one source — no drift, and the
# hosted-model entries (written by generate_model_cards.py) are preserved.
_MODEL_MAP = _ROOT / "frontend" / "src" / "data" / "model-cards.json"

_BASE_URL = "https://rogue-eosin.vercel.app"


def _slug(model_label: str) -> str:
    """A filesystem-safe slug for a model label: lowercased, ``/`` → ``-``, whitespace → ``-``."""
    s = model_label.strip().lower().replace("/", "-")
    return "-".join(s.split())


def _card_for(model: dict, date: str) -> dict:
    """Build the loosely-typed ``card`` dict for one OSS model from its REAL measured stats.

    Counts are pinned to the leaderboard's primitive-level any-breach rate (breached_primitives over
    n_primitives) so the card's ``N/M BREACHED`` matches the leaderboard; the headline ring uses the
    mean per-trial breach rate."""
    n_families = int(model["n_families"])
    slug = _slug(model["model_label"])
    return {
        "model_label": model["model_label"],
        "breach_rate": float(model["mean_breach_rate"]),
        "trials": int(model["n_primitives"]),
        "breaches": int(model["breached_primitives"]),
        "top_attack": model["worst_family"],
        # render_breach_card only needs the COUNT of distinct families; supply placeholder slugs.
        "families": [f"family_{i}" for i in range(n_families)],
        # The JUDGE was the calibrated Anthropic judge; single-shot-ness is about attacks, not the judge.
        "tier": "calibrated",
        "generated_at": date,
        "qr_url": f"{_BASE_URL}/m/{slug}",
    }


def main() -> None:
    stats = json.loads(_OSS_STATS.read_text(encoding="utf-8"))
    default_date = str(stats.get("measured", "2026-06-20"))

    ap = argparse.ArgumentParser(description="Render one breach card per OSS (Featherless) model.")
    ap.add_argument(
        "--date",
        default=default_date,
        help=f"measurement date as YYYY-MM-DD (default {default_date}); shown as 'measured <date>'.",
    )
    args = ap.parse_args()

    models = stats["models"]

    _ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    _FRONTEND_DIR.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    oss_map: dict[str, dict] = {}  # slug → {family, config} for the /m/[slug] redirect route
    for model in models:
        slug = _slug(model["model_label"])
        card = _card_for(model, args.date)

        # Every OSS model has a prod DB deployment config_id, so each gets a deep-linked map entry.
        oss_map[slug] = {"family": model["worst_family"], "config": model["config_id"]}

        out_dir = _ASSETS_DIR / slug
        result = render_breach_card(card, out_dir)

        # Mirror JUST the OG png into frontend/public/cards/<slug>.png (the share-card button source).
        fe_png = _FRONTEND_DIR / f"{slug}.png"
        if result["png"] is not None:
            shutil.copyfile(result["png"], fe_png)
            written.append(str(fe_png))
        else:
            print(f"  ! {slug}: no PNG produced (Pillow unavailable); skipped frontend copy")

        for key in ("svg", "html"):
            written.append(str(result[key]))
        if result["png"] is not None:
            written.append(str(result["png"]))
        # The square svg/png are written alongside but not in the return contract — list them too.
        for extra in ("breach-card-square.svg", "breach-card-square.png"):
            p = out_dir / extra
            if p.exists():
                written.append(str(p))

        pct = round(card["breaches"] / card["trials"] * 100) if card["trials"] else 0
        print(
            f"  ✓ {model['model_label']:<40} "
            f"({card['breaches']}/{card['trials']} = {pct}% breached) → {out_dir}/  +  {fe_png}"
        )

    # MERGE the OSS slug→{family,config} entries into the existing map (hosted-model entries kept),
    # sorted for a stable diff. Single source: the same run that renders the cards writes the map.
    existing: dict[str, dict] = {}
    if _MODEL_MAP.exists():
        existing = json.loads(_MODEL_MAP.read_text(encoding="utf-8"))
    merged = {**existing, **oss_map}
    _MODEL_MAP.parent.mkdir(parents=True, exist_ok=True)
    _MODEL_MAP.write_text(
        json.dumps({k: merged[k] for k in sorted(merged)}, indent=2) + "\n", encoding="utf-8"
    )

    print(f"\nWrote {len(written)} files across {len(models)} OSS models.")
    print(f"  assets:   {_ASSETS_DIR}/<slug>/")
    print(f"  frontend: {_FRONTEND_DIR}/<slug>.png")
    print(f"  map:      {_MODEL_MAP}  (+{len(oss_map)} OSS → /m/<slug>, {len(merged)} total)")


if __name__ == "__main__":
    main()
