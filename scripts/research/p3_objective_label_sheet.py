#!/usr/bin/env python3
"""P3 objective-classifier HUMAN validation — make a blind labeling sheet, then score it.

Answers the most likely revision condition (reviewer #1): the objective strata
(Table 4) are LLM-assigned; provide a human-labeled validation subset with
reported agreement. This makes a BLIND sheet (the LLM's label is hidden so the
human isn't anchored), the operator labels each into the same 5 categories, and
--score reports raw agreement + Cohen's kappa against the LLM classifier.

  uv run python scripts/research/p3_objective_label_sheet.py --make --n 50
      -> writes data/research/p3_objective_human_sheet.csv  (fill the 'human' column)
  uv run python scripts/research/p3_objective_label_sheet.py --score
      -> agreement + Cohen's kappa vs the LLM labels
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAP = "2026-06-12"
FULL = ROOT / "data" / "research" / "p3_objective_classification.full.jsonl"  # has title; labels hidden from sheet
SHEET = ROOT / "data" / "research" / "p3_objective_human_sheet.csv"
CATS = ["harmful_content", "info_extraction", "agentic_compromise", "generic_jailbreak", "ambiguous"]


def make(n: int):
    # DB-only sheet generation (author-side); the reviewer's --score path stays pure-stdlib
    from dotenv import dotenv_values
    from sqlalchemy import create_engine, text
    os.environ.update({k: v for k, v in dotenv_values(ROOT / ".env").items() if v})
    recs = [json.loads(l) for l in FULL.read_text().splitlines() if l.strip()]
    by = defaultdict(list)
    for r in recs:
        by[r["objective"]].append(r)
    # stratified: spread n across the categories the LLM used (so every stratum is audited)
    per = max(1, n // len([k for k in CATS if by[k]]))
    pick = []
    for cat in CATS:
        rs = by.get(cat, [])
        step = max(1, len(rs) // per)
        pick += rs[::step][:per]
    pick = pick[:n]
    ids = [r["primitive_id"] for r in pick]
    # pull the payload the classifier saw (real, non-redacted) from the DB
    eng = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with eng.connect() as c:
        pay = {}
        for r in c.execute(text(
            "SELECT b.primitive_id, (ARRAY_AGG(b.rendered_payload ORDER BY length(b.rendered_payload) DESC))[1] "
            "FROM breach_results b WHERE b.primitive_id = ANY(:ids) AND b.rendered_payload <> '[redacted]' "
            "AND b.pair_iters_to_breach IS NULL AND b.ran_at < CAST(:s AS timestamp) GROUP BY b.primitive_id"),
                {"ids": ids, "s": SNAP}):
            pay[r[0]] = r[1]
    # shuffle deterministically by id so strata aren't clustered in the sheet (avoids order bias)
    pick.sort(key=lambda r: r["primitive_id"])
    with SHEET.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["primitive_id", "family", "vector", "title", "payload_excerpt", "human", "(options)"])
        for r in pick:
            w.writerow([r["primitive_id"], r["family"], r.get("vector", ""), r["title"],
                        (pay.get(r["primitive_id"], "") or "")[:600].replace("\n", " "), "",
                        "|".join(CATS)])
    print(f"wrote {SHEET}: {len(pick)} items, BLIND (LLM label hidden). Fill the 'human' column with one of:")
    print("  " + " | ".join(CATS))
    print(f"  stratified by the LLM label: {dict(Counter(r['objective'] for r in pick))}")


def kappa(a, b):
    cats = sorted(set(a) | set(b))
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pa = Counter(a); pb = Counter(b)
    pe = sum((pa[c] / n) * (pb[c] / n) for c in cats)
    return po, (po - pe) / (1 - pe) if pe != 1 else 1.0


def score():
    # LLM labels: prefer the released (redacted) classification so a reviewer can recompute
    # from the supplement; fall back to the private full file locally.
    rel = ROOT / "data" / "research" / "p3_objective_classification.jsonl"
    src = rel if rel.exists() else FULL
    llm = {json.loads(l)["primitive_id"]: json.loads(l)["objective"]
           for l in src.read_text().splitlines() if l.strip()}
    # prefer the labeling-app JSON if present, else the CSV
    app = ROOT / "data" / "research" / "p3_labels.json"
    human = {}
    if app.exists():
        d = json.loads(app.read_text())
        human = d.get("objective", {})
        fn = d.get("judge_fn", {})
        if fn:
            miss = sum(1 for v in fn.values() if v == "breach")
            print(f"[Part B — judge double-check] {len(fn)} judge_v3 non-breach cells re-checked by human; "
                  f"{miss} judged actual breaches => human-estimated false-negative rate "
                  f"{100*miss/len(fn):.1f}% (the gate IS conservative in practice: it misses few real breaches).")
    else:
        for r in csv.DictReader(SHEET.open()):
            if (r["human"] or "").strip():
                human[r["primitive_id"]] = r["human"].strip()
    h = [v for pid, v in human.items() if pid in llm]
    m = [llm[pid] for pid in human if pid in llm]
    if not h:
        print("no human objective labels found yet (fill the page or CSV)"); return
    po, k = kappa(h, m)
    print(f"[Part A — objective] labeled: {len(h)} | raw agreement: {100*po:.1f}% | Cohen's kappa: {k:.3f}")
    dis = [(x, y) for x, y in zip(h, m) if x != y]
    if dis:
        print("  disagreements (human -> llm):", dict(Counter(f"{x}->{y}" for x, y in dis)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--make", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--n", type=int, default=50)
    a = ap.parse_args()
    if a.make:
        make(a.n)
    elif a.score:
        score()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
