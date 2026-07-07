"""Train the Q11 system-prompt-transfer survival predictor from historical ``breach_results``.

Ranks harvested attacks by predicted cross-config survival so a scan fires the likely survivors first
and defers the rest. This trainer is **FREE** — it reads only breach data ROGUE has already paid for,
featurizes it black-box (no embedding, no model call), fits a numpy logistic head, and back-tests it
group-aware by primitive. No live LLM/Bright-Data spend. (A prospective A/B to publish a live
budget-saved headline is a separate, deliberately-gated ~$35 reproduce run — not this.)

    uv run python scripts/reproduce/train_survival_model.py \
        --out data/models/survival_predictor.json

Then turn the gate on for scans:

    export ROGUE_SURVIVAL_ORDER=on
    export ROGUE_SURVIVAL_MODEL=data/models/survival_predictor.json
    # scans now reorder the corpus so predicted survivors fire first;
    # add survival_max_primitives (or the SDK/API cap) to defer the predicted-dead tail.

``--database-url`` defaults to ``$DATABASE_URL`` or the local dev Postgres; point it at Neon/prod to
train on live breach history. The saved artifact carries its back-test metrics inline (``.metrics``).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from dotenv import load_dotenv

from rogue.reproduce.endpoint_scan import DEFAULT_BREACH_THRESHOLD
from rogue.reproduce.survival.train import fetch_pair_rows, train_and_backtest

_DEFAULT_DB = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="data/models/survival_predictor.json", help="artifact output path")
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL", _DEFAULT_DB))
    ap.add_argument("--breach-threshold", type=float, default=DEFAULT_BREACH_THRESHOLD)
    ap.add_argument("--l2", type=float, default=1.0, help="L2 penalty (higher = smoother)")
    ap.add_argument("--recover", type=float, default=0.80, help="survivor-recall target for budget-saved")
    ap.add_argument("--min-rows", type=int, default=20, help="refuse to ship a model below this many pairs")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    print(f"Fetching breach pairs from {args.database_url.split('@')[-1]} …", file=sys.stderr)
    rows = fetch_pair_rows(args.database_url, breach_threshold=args.breach_threshold)
    print(f"  {len(rows)} (primitive × config) pairs; "
          f"{sum(r.breached for r in rows)} survived", file=sys.stderr)
    if len(rows) < args.min_rows:
        print(f"ERROR: only {len(rows)} pairs (< --min-rows {args.min_rows}); "
              "run more reproduce cycles first — refusing to ship a model on too little data.",
              file=sys.stderr)
        return 1

    model = train_and_backtest(rows, l2=args.l2, recover=args.recover)
    model.save(args.out)
    print(f"\nSaved → {args.out}", file=sys.stderr)
    print(json.dumps(model.metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
