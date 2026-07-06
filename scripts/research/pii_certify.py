"""Axis B certification — push detector precision toward headline-grade via two-model confirmation.

The fuzzy semantic step false-flags ~11% (precision ~0.89). Two-model **confirmation** = keep only
detections BOTH detector models surface (agreement is the abstention signal: abstain when they
disagree). This trades a little recall for precision. Measured against ai4privacy, reports
precision/recall for each single detector and for their confirmed intersection. If the confirmed
precision clears ~0.97, confirmed detections earn headline-eligibility.

Usage:  uv run python scripts/research/pii_certify.py [--a openai/gpt-5.4-nano] [--b openai/gpt-5.4] [--n 200]
Cost:   ~$0.05-0.20 (two detector models over the set). Real spend — run deliberately.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from pii_axis_lib import Meter, build_adapter, map_label, value_overlap  # noqa: E402

from rogue.reproduce.agent import pii_detector as det  # noqa: E402
from rogue.reproduce.agent import pii_semantic as sem  # noqa: E402

DATA = os.path.join(os.path.dirname(__file__), "..", "..", "data", "research", "pii")


def _confirm(a_matches, b_matches):
    """Semantic matches from A that a B match value-overlaps (two-model agreement)."""
    return [m for m in a_matches if any(value_overlap(m.value, n.value) for n in b_matches)]


def _score(rows, per_row_matches):
    """precision (detection overlaps any GT mask) + detection-recall (over in-scope GT spans)."""
    tp = fp = rtp = rfn = 0
    for row, matches in zip(rows, per_row_matches):
        masks = row["mask"]
        for m in matches:
            if any(value_overlap(m.value, mk["value"]) for mk in masks):
                tp += 1
            else:
                fp += 1
        for mk in masks:
            if not map_label(mk["label"]):
                continue
            if any(value_overlap(m.value, mk["value"]) for m in matches):
                rtp += 1
            else:
                rfn += 1
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = rtp / (rtp + rfn) if (rtp + rfn) else 0.0
    return {"precision": round(prec, 4), "detection_recall": round(rec, 4),
            "tp": tp, "fp": fp, "n_detections": tp + fp, "n_inscope_gt": rtp + rfn}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="openai/gpt-5.4-nano")
    ap.add_argument("--b", default="openai/gpt-5.4")
    ap.add_argument("--n", type=int, default=200)
    args = ap.parse_args()

    rows = json.load(open(os.path.join(DATA, "ai4privacy_en_sample.json")))[: args.n]
    meter = Meter()
    inv_a = meter.wrap(build_adapter(args.a))
    inv_b = meter.wrap(build_adapter(args.b))
    semaphore = asyncio.Semaphore(8)

    async def detect_two(row):
        regex = det.detect_regex(row["text"])
        async with semaphore:
            a = await sem.classify_unstructured(row["text"], inv_a)
        async with semaphore:
            b = await sem.classify_unstructured(row["text"], inv_b)
        return regex, a, b

    triples = await asyncio.gather(*(detect_two(r) for r in rows))

    def merged(sel):  # sel(regex,a,b) -> match list
        return [sel(rx, a, b) for rx, a, b in triples]

    variants = {
        "regex_only": merged(lambda rx, a, b: rx),
        f"regex+A({args.a.split('/')[-1]})": merged(lambda rx, a, b: rx + a),
        f"regex+B({args.b.split('/')[-1]})": merged(lambda rx, a, b: rx + b),
        "regex+confirmed(A∩B)": merged(lambda rx, a, b: rx + _confirm(a, b)),
        "regex+union(A∪B)": merged(lambda rx, a, b: rx + a + [m for m in b if not any(value_overlap(m.value, n.value) for n in a)]),
    }
    result = {"a": args.a, "b": args.b, "n": len(rows),
              "variants": {k: _score(rows, v) for k, v in variants.items()}, "cost": meter.summary()}
    json.dump(result, open(os.path.join(DATA, "certify_result.json"), "w"), indent=2)

    print(f"certification: A={args.a} B={args.b} n={len(rows)}")
    for k, s in result["variants"].items():
        print(f"  {k:28} precision={s['precision']:.3f} det-recall={s['detection_recall']:.3f} (dets={s['n_detections']})")
    print("COST:", meter.summary())
    confirmed = result["variants"]["regex+confirmed(A∩B)"]["precision"]
    print(f"\nconfirmed precision = {confirmed:.3f} → {'HEADLINE-ELIGIBLE (≥0.97)' if confirmed >= 0.97 else 'still below 0.97 gate'}")


if __name__ == "__main__":
    asyncio.run(main())
