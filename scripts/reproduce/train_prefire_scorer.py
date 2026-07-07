"""Train the Q7 pre-fire success scorer from historical ``breach_results`` — FREE ($0).

Scores each harvested attack against the specific target config it is about to be fired at and skips the
ones predicted not to breach, so a paid scan never spends target+judge calls on the obvious misses. This
trainer reads only breach data ROGUE has already paid for plus the payload embeddings already stored on
``attack_primitives`` — no live LLM/Bright-Data spend. (A prospective live budget-saved A/B is a
separate, deliberately-gated ~$35 reproduce run — not this.)

    uv run python scripts/reproduce/train_prefire_scorer.py \
        --out data/models/prefire_scorer.json

Then turn the gate on for scans:

    export ROGUE_PREFIRE_SKIP=on
    export ROGUE_PREFIRE_MODEL=data/models/prefire_scorer.json
    # scans now skip attacks whose calibrated P(breach) is below the model's recommended threshold
    # (the P that still recovers 95% of breaches on held-out data); the drift-guard fires-all for
    # novel/low-support families and a deterministic 15% canary keeps validating the skips.

``--database-url`` defaults to ``$DATABASE_URL`` (Neon in this repo). The saved artifact carries its
back-test metrics inline (``.metrics``) — including the structural-only-vs-embedding ablation, the
calibration Brier before/after, and the recall-vs-skip curve.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from dotenv import load_dotenv

from rogue.reproduce.endpoint_scan import DEFAULT_BREACH_THRESHOLD
from rogue.reproduce.prefire.train import fetch_pair_rows, train_and_backtest

_DEFAULT_DB = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", default="data/models/prefire_scorer.json", help="artifact output path")
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL", _DEFAULT_DB))
    ap.add_argument("--breach-threshold", type=float, default=DEFAULT_BREACH_THRESHOLD)
    ap.add_argument("--l2", type=float, default=1.0, help="L2 penalty (higher = smoother)")
    ap.add_argument("--recover", type=float, default=0.80, help="survivor-recall target for budget-saved")
    ap.add_argument("--min-rows", type=int, default=20, help="refuse to ship a model below this many pairs")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    print(f"Fetching breach pairs from {args.database_url.split('@')[-1]} …", file=sys.stderr)
    rows = fetch_pair_rows(args.database_url, breach_threshold=args.breach_threshold)
    n_emb = sum(1 for r in rows if getattr(r.primitive, "payload_embedding", None) is not None)
    print(f"  {len(rows)} (primitive × config) pairs ({n_emb} with an embedding); "
          f"{sum(r.breached for r in rows)} breached", file=sys.stderr)
    if len(rows) < args.min_rows:
        print(f"ERROR: only {len(rows)} pairs (< --min-rows {args.min_rows}); "
              "run more reproduce cycles first — refusing to ship a model on too little data.",
              file=sys.stderr)
        return 1

    model = train_and_backtest(rows, l2=args.l2, recover=args.recover)
    model.save(args.out)
    print(f"\nSaved {args.out}", file=sys.stderr)
    print(json.dumps(model.metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
