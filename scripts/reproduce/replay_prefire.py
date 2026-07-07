"""$0 offline validator for the Q7 pre-fire scorer — the honest headline, no live spend.

Trains + group-aware back-tests the pre-fire scorer over the ``breach_results`` ROGUE has already paid
for, and prints the three numbers that decide whether the gate is worth turning on:

  1. the ablation — does the payload embedding beat structure-only (Q11's exact features)?
  2. the recall-vs-skip tradeoff — what fraction of trials can we skip at 95% / 99% breach recall?
  3. calibration — is the score a real probability (Brier before/after Platt)?

    uv run python scripts/reproduce/replay_prefire.py            # against $DATABASE_URL (Neon)

This reproduces the offline number for the design doc; the *live* budget-saved % needs the gated ~$35
prospective A/B (a separate, deliberately-gated paid run).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

from rogue.reproduce.prefire.train import fetch_pair_rows, train_and_backtest

_DEFAULT_DB = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"


def _pct(x) -> str:
    return f"{x * 100:.1f}%" if x is not None else "—"


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL", _DEFAULT_DB))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    print(f"Reading breach_results from {args.database_url.split('@')[-1]} …", file=sys.stderr)
    rows = fetch_pair_rows(args.database_url)
    if not rows:
        print("No breach_results rows — nothing to replay.", file=sys.stderr)
        return 1
    m = train_and_backtest(rows)
    md = m.metrics
    if md.get("status") != "trained" or "ablation" not in md:
        print(f"Insufficient data for a held-out replay (status={md.get('status')}).", file=sys.stderr)
        return 1

    ab, cal, rvs = md["ablation"], md["calibration"], md["recall_vs_skip"]
    print("\n=== Q7 pre-fire scorer — offline back-test ($0) ===")
    print(f"pairs={md['n_pairs']} ({md['n_with_embedding']} embedded)  "
          f"fit={md['n_fit']} calib={md['n_calib']} test={md['n_test']}  "
          f"base rate={_pct(md['base_rate_all'])}")
    print("\n-- ablation (does the payload embedding beat Q11's structure-only features?) --")
    print(f"  structural-only : AUC {ab['structural_only']['auc']:.3f}  "
          f"P@10%={_pct(ab['structural_only']['precision_at_10pct'])}  "
          f"budget-saved@80%recall={_pct(ab['structural_only']['budget_saved'])}")
    print(f"  + embedding     : AUC {ab['with_embedding']['auc']:.3f}  "
          f"P@10%={_pct(ab['with_embedding']['precision_at_10pct'])}  "
          f"budget-saved@80%recall={_pct(ab['with_embedding']['budget_saved'])}")
    print(f"  embedding AUC gain: {md['auc_gain_from_embedding']:+.4f}")
    print("\n-- recall-vs-skip tradeoff (the cost of a hard skip Zhang never measured) --")
    print(f"  skip {_pct(rvs['skip_at_95pct_recall'])} of trials at 95% breach recall "
          f"(P<{rvs['threshold_at_95pct_recall']})")
    print(f"  skip {_pct(rvs['skip_at_99pct_recall'])} of trials at 99% breach recall "
          f"(P<{rvs['threshold_at_99pct_recall']})")
    print("\n-- calibration (Platt) --")
    print(f"  Brier raw {cal['brier_raw']:.4f} → calibrated {cal['brier_calibrated']:.4f}  "
          f"(a={cal['platt_a']}, b={cal['platt_b']})")
    print(f"\nrecommended default skip threshold: P(breach) < {md['recommended_threshold']} "
          "(fires everything above; drift-guard fires-all novel/low-support families)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
