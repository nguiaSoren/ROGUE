#!/usr/bin/env python3
"""Reproduce Table 1 (corpus by source type) OFFLINE from the frozen snapshot CSV.

Table 1 reports the corpus composition as of the frozen harvest snapshot. The live
harvest database has grown since, so these counts are released as a fixed snapshot of
record (data/research/p3_corpus_source_types.csv) rather than re-queried live; this
script prints the table and checks the per-row counts sum to the stated totals, so the
numbers in Table 1 recompute from the supplement with no database access.

  python3 scripts/research/p3_corpus_table.py
"""
from __future__ import annotations
import csv
from pathlib import Path

CSV = Path(__file__).resolve().parents[2] / "data" / "research" / "p3_corpus_source_types.csv"


def main() -> int:
    rows = list(csv.DictReader(CSV.open()))
    body = [r for r in rows if r["source_type"] != "total"]
    total = next(r for r in rows if r["source_type"] == "total")
    print(f"{'source type':12s} {'primitives':>11} {'with a claimed rate':>20}")
    for r in body:
        print(f"{r['source_type']:12s} {int(r['primitives']):>11} {int(r['with_claimed_rate']):>20}")
    sp = sum(int(r["primitives"]) for r in body)
    sc = sum(int(r["with_claimed_rate"]) for r in body)
    print(f"{'TOTAL':12s} {sp:>11} {sc:>20}")
    ok = sp == int(total["primitives"]) and sc == int(total["with_claimed_rate"])
    print(f"\nself-check: rows sum to {sp}/{sc}; stated total {total['primitives']}/{total['with_claimed_rate']}  -> {'OK' if ok else 'MISMATCH'}")
    print("Expected (paper Table 1): 391 primitives, 70 with a claimed rate.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
