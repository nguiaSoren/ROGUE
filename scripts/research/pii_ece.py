"""Axis B certification centerpiece — ECE + reliability + pick_threshold (Paper A "seeded-liar").

Runs the k-run ensemble detector on ai4privacy, assigns each detection a confidence (vote
fraction), and scores confidence-vs-correctness: expected calibration error (ECE), a reliability
table, and `pick_threshold(target_precision)` — the confidence above which precision clears the
gate. That threshold is what makes individual PII_EMITTED findings headline-eligible.

Usage:  uv run python scripts/research/pii_ece.py [--model openai/gpt-5.4-nano] [--k 5] [--n 200] [--target 0.97]
Cost:   k × the semantic calls (~$0.05-0.15). Real spend — run deliberately.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from pii_axis_lib import Meter, build_adapter, value_overlap  # noqa: E402

from rogue.reproduce.agent import pii_detector as det  # noqa: E402
from rogue.reproduce.agent import pii_semantic as sem  # noqa: E402

DATA = os.path.join(os.path.dirname(__file__), "..", "..", "data", "research", "pii")


def _is_tp(m, masks) -> bool:
    return any(value_overlap(m.value, mk["value"]) for mk in masks)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="openai/gpt-5.4-nano")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--target", type=float, default=0.97)
    args = ap.parse_args()

    rows = json.load(open(os.path.join(DATA, "ai4privacy_en_sample.json")))[: args.n]
    meter = Meter()
    invoke = meter.wrap(build_adapter(args.model))
    sem_bar = asyncio.Semaphore(8)

    async def one(row):
        async with sem_bar:
            ens = await sem.classify_ensemble(row["text"], invoke, k=args.k)
        # regex detections are deterministic-shape → confidence 1.0
        regex = det.detect_regex(row["text"])
        return regex + [m for m in ens if not any(value_overlap(m.value, r.value) for r in regex)]

    per_row = await asyncio.gather(*(one(r) for r in rows))

    # (confidence, is_tp) points
    pts = []
    for row, matches in zip(rows, per_row):
        for m in matches:
            pts.append((m.confidence, 1 if _is_tp(m, row["mask"]) else 0))

    # ECE over confidence bins
    bins = [(i / 10, (i + 1) / 10) for i in range(10)]
    reliability = []
    ece = 0.0
    N = len(pts) or 1
    for lo, hi in bins:
        b = [(c, t) for c, t in pts if (c > lo and c <= hi) or (lo == 0 and c == 0)]
        if not b:
            continue
        conf = sum(c for c, _ in b) / len(b)
        acc = sum(t for _, t in b) / len(b)
        reliability.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": len(b), "mean_conf": round(conf, 3), "accuracy": round(acc, 3)})
        ece += len(b) / N * abs(acc - conf)

    # pick_threshold: smallest confidence c* where precision of {conf >= c*} >= target
    confs = sorted({c for c, _ in pts})
    chosen = None
    for c in confs:
        sel = [t for cc, t in pts if cc >= c]
        if sel and sum(sel) / len(sel) >= args.target:
            chosen = {"threshold": c, "precision": round(sum(sel) / len(sel), 4),
                      "recall_kept": round(len(sel) / N, 4), "n_kept": len(sel)}
            break

    result = {"model": args.model, "k": args.k, "n_rows": len(rows), "n_detections": N,
              "target_precision": args.target, "ece": round(ece, 4),
              "reliability": reliability, "headline_threshold": chosen, "cost": meter.summary()}
    json.dump(result, open(os.path.join(DATA, "ece_result.json"), "w"), indent=2)

    print(f"model={args.model} k={args.k} n_det={N}  ECE={ece:.4f}")
    print("reliability (mean_conf → accuracy):")
    for r in reliability:
        print(f"  {r['bin']}  n={r['n']:4}  conf={r['mean_conf']:.3f}  acc={r['accuracy']:.3f}")
    if chosen:
        print(f"HEADLINE THRESHOLD: confidence >= {chosen['threshold']:.2f} → precision {chosen['precision']:.3f} "
              f"(keeps {chosen['n_kept']}/{N} = {chosen['recall_kept']:.0%} of detections)")
    else:
        print(f"NO threshold reaches precision {args.target} — certification not met at k={args.k}")
    print("COST:", meter.summary())


if __name__ == "__main__":
    asyncio.run(main())
