"""Render one shareable ROGUE breach card per leaderboard model.

Reads the REAL measured per-model breach rates from ``src/rogue/data/demo_stats.json`` (the same
numbers the live ``/leaderboard`` shows) and renders a brand-native breach card for each model via
``rogue.report_card.render_breach_card``. Each card's QR points at that model's all-time breach
detail cell on the live matrix (falling back to ``/leaderboard`` for any model we have no config id
for), and carries a muted ``measured <date>`` credibility line.

Outputs, per model (``<slug>`` = a filesystem-safe ``model_label``):
    * ``assets/card/models/<slug>/``   — the full set: svg, square svg, og png, square png, html.
    * ``frontend/public/cards/<slug>.png`` — JUST the 1200×630 OG png (for a "share card" button).

Pure + offline: no network, no API keys. ``--date`` is required-ish (defaults to a baked constant —
we deliberately never call ``datetime.now()``, which is blocked in some run contexts).

Run:
    uv run python scripts/cards/generate_model_cards.py --date 2026-06-19
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from rogue.report_card import render_breach_card

# Repo root = three levels up from this file (scripts/cards/generate_model_cards.py).
_ROOT = Path(__file__).resolve().parents[2]
_DEMO_STATS = _ROOT / "src" / "rogue" / "data" / "demo_stats.json"
_ASSETS_DIR = _ROOT / "assets" / "card" / "models"
_FRONTEND_DIR = _ROOT / "frontend" / "public" / "cards"
# The slug→{family,config} map the short-link redirect route (`/m/[slug]`) resolves. Emitted here so
# the card QR target and the route that serves it derive from one source — no drift.
_MODEL_MAP = _ROOT / "frontend" / "src" / "data" / "model-cards.json"

# Default "measured" date — a baked constant so the script never calls datetime.now() (blocked in
# some contexts). Override with --date YYYY-MM-DD.
_DEFAULT_DATE = "2026-06-19"

_BASE_URL = "https://rogue-eosin.vercel.app"

# target_model → live matrix CONFIG_ID. A model absent from this map falls back to /leaderboard for
# its QR (and we never crash). Kept in lockstep with the deployment configs behind /matrix/cell.
_CONFIG_IDS: dict[str, str] = {
    "anthropic/claude-opus-4-8": "acme-claudeopus-20260531",
    "anthropic/claude-haiku-4-5": "acme-claudehaiku-20260526",
    "google/gemini-3.1-flash-lite": "acme-geminiflashlite-20260526",
    "openai/gpt-5.4-nano": "acme-gpt54nano-20260526",
    "openai/gpt-audio-mini": "acme-gptaudiomini-20260604",
    "meta-llama/llama-3.1-8b-instruct": "acme-llama3-20260526",
    "mistralai/mistral-small-2603": "acme-mistralsm-20260526",
    "mistralai/voxtral-small-24b-2507": "acme-voxtral-20260604",
}


def _slug(model_label: str) -> str:
    """A filesystem-safe slug for a model label: lowercased, ``/`` → ``-``, whitespace → ``-``."""
    s = model_label.strip().lower().replace("/", "-")
    return "-".join(s.split())


def _cell_target_for(model: dict) -> dict | None:
    """The {family, config} this model's QR should deep-link to, or None when we have no config id
    for the target model (then the QR falls back to the public leaderboard)."""
    config_id = _CONFIG_IDS.get(model.get("target_model", ""))
    if not config_id:
        return None
    return {"family": model["worst_family"], "config": config_id}


def _qr_url_for(model: dict) -> str:
    """The per-model QR target — a SHORT redirect link (`/m/<slug>`) so the QR stays low-density and
    scannable at card size; the `/m/[slug]` route resolves it to that model's all-time breach cell.
    Falls back to the public leaderboard when we have no config id for the target model."""
    if _cell_target_for(model) is None:
        return f"{_BASE_URL}/leaderboard"
    return f"{_BASE_URL}/m/{_slug(model['model_label'])}"


def _card_for(model: dict, date: str) -> dict:
    """Build the loosely-typed ``card`` dict for one model from its REAL measured stats."""
    rate = float(model["mean_breach_rate"])
    trials = int(model["n_trials"])
    n_families = int(model["n_families"])
    return {
        "model_label": model["model_label"],
        "breach_rate": rate,
        "trials": trials,
        "breaches": round(rate * trials),
        "top_attack": model["worst_family"],
        # render_breach_card only needs the COUNT of distinct families; supply placeholder slugs.
        "families": [f"family_{i}" for i in range(n_families)],
        "tier": "calibrated",
        "generated_at": date,
        "qr_url": _qr_url_for(model),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Render one breach card per leaderboard model.")
    ap.add_argument(
        "--date",
        default=_DEFAULT_DATE,
        help=f"measurement date as YYYY-MM-DD (default {_DEFAULT_DATE}); shown as 'measured <date>'.",
    )
    args = ap.parse_args()

    stats = json.loads(_DEMO_STATS.read_text(encoding="utf-8"))
    models = stats["models"]

    _ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    _FRONTEND_DIR.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    model_map: dict[str, dict] = {}  # slug → {family, config} for the /m/[slug] redirect route
    for model in models:
        slug = _slug(model["model_label"])
        card = _card_for(model, args.date)

        target = _cell_target_for(model)
        if target is not None:
            model_map[slug] = target

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

        print(
            f"  ✓ {model['model_label']:<24} "
            f"({round(card['breach_rate'] * 100)}% breach) → {out_dir}/  +  {fe_png}"
        )

    # Emit the slug→{family,config} map the /m/[slug] short-link route resolves (sorted for a stable
    # diff). Single source: the same run that renders the cards writes the map their QRs point at.
    _MODEL_MAP.parent.mkdir(parents=True, exist_ok=True)
    _MODEL_MAP.write_text(
        json.dumps({k: model_map[k] for k in sorted(model_map)}, indent=2) + "\n", encoding="utf-8"
    )

    print(f"\nWrote {len(written)} files across {len(models)} models.")
    print(f"  assets:   {_ASSETS_DIR}/<slug>/")
    print(f"  frontend: {_FRONTEND_DIR}/<slug>.png")
    print(f"  map:      {_MODEL_MAP}  ({len(model_map)} models → /m/<slug>)")


if __name__ == "__main__":
    main()
