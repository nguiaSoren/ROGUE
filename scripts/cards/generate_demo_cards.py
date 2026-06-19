"""Render the two canonical demo breach cards: the keyless `sample` card and the `marketing` card.

These are the hero cards shown in the README and the launch assets — distinct from the per-model
leaderboard cards (`generate_model_cards.py`). They were previously one-off renders, which let them
go stale when `report_card.py` changed; committing this generator keeps them in lockstep.

  * ``assets/card/sample/``    — the keyless `rogue try` demo (gpt-4o-mini, a QUICK SCAN).
  * ``assets/card/marketing/`` — the hero card with REAL measured numbers (mistral-small-2603,
    a CALIBRATED JUDGE run).

Both carry the generic QR (→ the public ``/leaderboard``); only per-model cards deep-link to a cell.
Pure + offline: no network, no keys. ``--date`` defaults to a baked constant (we never call
``datetime.now()`` — blocked in some run contexts).

Run:
    uv run python scripts/cards/generate_demo_cards.py --date 2026-06-19
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rogue.report_card import render_breach_card

_ROOT = Path(__file__).resolve().parents[2]
_CARD_DIR = _ROOT / "assets" / "card"

_DEFAULT_DATE = "2026-06-19"

# The two canonical demo cards, keyed by their output subdirectory under assets/card/. Numbers are
# fixed: `sample` is the illustrative keyless demo; `marketing` carries the real mistral-small-2603
# calibrated run (668/2189 ≈ 31%). No qr_url → the generic QR points at the public leaderboard.
_CARDS: dict[str, dict] = {
    "sample": {
        "model_label": "gpt-4o-mini",
        "breaches": 6,
        "trials": 10,
        "breach_rate": 0.6,
        "top_attack": "dan_persona",
        "families": [f"family_{i}" for i in range(3)],
        "tier": "quick",
    },
    "marketing": {
        "model_label": "mistral-small-2603",
        "breaches": 668,
        "trials": 2189,
        "breach_rate": 668 / 2189,
        "top_attack": "training_data_extraction",
        "families": [f"family_{i}" for i in range(15)],
        "tier": "calibrated",
        # The marketing card shows REAL mistral numbers, so its QR deep-links to mistral's breach
        # cell (via the short /m/<slug> redirect), not the generic leaderboard. The sample card stays
        # generic (gpt-4o-mini is illustrative, not a measured leaderboard model).
        "qr_url": "https://rogue-eosin.vercel.app/m/mistral-small-2603",
    },
}


def main() -> None:
    ap = argparse.ArgumentParser(description="Render the sample + marketing demo breach cards.")
    ap.add_argument(
        "--date",
        default=_DEFAULT_DATE,
        help=f"measurement date as YYYY-MM-DD (default {_DEFAULT_DATE}); shown as 'measured <date>'.",
    )
    args = ap.parse_args()

    for name, card in _CARDS.items():
        out_dir = _CARD_DIR / name
        render_breach_card({**card, "generated_at": args.date}, out_dir)
        rate = round(card["breach_rate"] * 100)
        print(f"  ✓ {name:<10} {card['model_label']:<22} ({rate}% breach) → {out_dir}/")

    print(f"\nWrote the sample + marketing cards under {_CARD_DIR}/<name>/.")


if __name__ == "__main__":
    main()
