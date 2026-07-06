"""Axis B steps 3-4 — calibrate the PII detector against real labeled data (ai4privacy).

Scores the detector two ways — regex-only, and regex + the live LLM SemanticFn — against
ai4privacy/pii-masking-200k ground-truth spans, reporting precision / recall / F1 (overall,
per-attribute, and by detection method). Two slices (calibration + held-out) confirm stability;
no parameters are fit here (regex + a frozen prompt), so the split is a stability check.

This is the gate: the numbers here are what license flipping PII_EMITTED to headline-eligible.

Usage:  uv run python scripts/research/pii_calibration.py [--model openai/gpt-5.4-nano] [--n 250] [--heldout 150]
Cost:   ~$0.05-0.30 (one cheap LLM call per text). Real spend — run deliberately.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from pii_axis_lib import PRF, Meter, build_adapter, map_label, value_overlap  # noqa: E402

from rogue.reproduce.agent import pii_detector as det  # noqa: E402
from rogue.reproduce.agent import pii_semantic as sem  # noqa: E402

DATA = os.path.join(os.path.dirname(__file__), "..", "..", "data", "research", "pii")


async def detect_all(rows, invoke, *, use_semantic: bool, concurrency: int = 8):
    """Return per-row list of PIIMatch (regex always; + semantic if requested), concurrently."""
    semaphore = asyncio.Semaphore(concurrency)

    async def one(row):
        regex = det.detect_regex(row["text"])
        if not use_semantic:
            return regex
        async with semaphore:
            semantic = await sem.classify_unstructured(row["text"], invoke)
        # merge, de-dupe by (attribute, value)
        seen = {(m.attribute, m.value) for m in regex}
        return regex + [m for m in semantic if (m.attribute, m.value) not in seen]

    return await asyncio.gather(*(one(r) for r in rows))


def score(rows, detections) -> tuple[PRF, PRF, dict]:
    """detection-recall (any attribute) + attribute-recall over in-scope GT spans.

    detection-recall: of in-scope ground-truth PII spans, how many did we flag at all.
    attribute-recall: ... and with the correct mapped attribute.
    method_tp: which detection method (regex/semantic) scored each recalled span.
    """
    det_recall, attr_recall = PRF(), PRF()
    method_tp = {"regex": 0, "semantic": 0}
    for row, matches in zip(rows, detections):
        in_scope = [(m["value"], map_label(m["label"])) for m in row["mask"] if map_label(m["label"])]
        for gt_value, gt_attr in in_scope:
            hit = next((m for m in matches if value_overlap(m.value, gt_value)), None)
            if hit is None:
                det_recall.fn += 1
                attr_recall.fn += 1
            else:
                det_recall.tp += 1
                method_tp[hit.method] = method_tp.get(hit.method, 0) + 1
                if hit.attribute == gt_attr:
                    attr_recall.tp += 1
                else:
                    attr_recall.fn += 1
    return det_recall, attr_recall, method_tp


def precision_prf(rows, detections) -> PRF:
    p = PRF()
    for row, matches in zip(rows, detections):
        masks = row["mask"]
        for m in matches:
            if any(value_overlap(m.value, mk["value"]) for mk in masks):
                p.tp += 1
            else:
                p.fp += 1
    return p


def per_attr_recall(rows, detections) -> dict:
    agg: dict[str, list[int]] = {}
    for row, matches in zip(rows, detections):
        for mk in row["mask"]:
            attr = map_label(mk["label"])
            if not attr:
                continue
            hit = any(value_overlap(m.value, mk["value"]) for m in matches)
            a = agg.setdefault(attr, [0, 0])  # [tp, fn]
            a[0 if hit else 1] += 1
    return {k: {"recall": round(v[0] / (v[0] + v[1]), 3), "n": v[0] + v[1]} for k, v in sorted(agg.items())}


async def run_slice(name, rows, invoke):
    out = {"slice": name, "n_rows": len(rows)}
    for use_sem in (False, True):
        dets = await detect_all(rows, invoke, use_semantic=use_sem)
        det_recall, attr_recall, method_tp = score(rows, dets)
        prec = precision_prf(rows, dets)
        tag = "regex+semantic" if use_sem else "regex_only"
        out[tag] = {
            "detection_recall": round(det_recall.recall(), 4),
            "attribute_recall": round(attr_recall.recall(), 4),
            "precision": round(prec.precision(), 4),
            "n_detections": prec.tp + prec.fp,
            "n_inscope_gt": det_recall.tp + det_recall.fn,
            "recall_tp": det_recall.tp, "recall_fn": det_recall.fn,
            "precision_tp": prec.tp, "precision_fp": prec.fp,
            "tp_by_method": method_tp,
            "per_attribute_recall": per_attr_recall(rows, dets),
        }
        if use_sem:
            # per-row raw detail for the full detector (all data saved locally; ai4privacy is
            # synthetic PII, so literals are safe to persist to a gitignored file).
            detail = []
            for row, matches in zip(rows, dets):
                in_scope = [(m["value"], map_label(m["label"])) for m in row["mask"] if map_label(m["label"])]
                detail.append({
                    "id": row["id"],
                    "text": row["text"],
                    "gt_inscope": [{"value": v, "attr": a} for v, a in in_scope],
                    "detections": [
                        {"attribute": m.attribute, "method": m.method, "value": m.value} for m in matches
                    ],
                })
            out["detail"] = detail
    return out


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="openai/gpt-5.4-nano")
    ap.add_argument("--n", type=int, default=250)
    ap.add_argument("--heldout", type=int, default=150)
    args = ap.parse_args()

    rows = json.load(open(os.path.join(DATA, "ai4privacy_en_sample.json")))
    cal, held = rows[: args.n], rows[args.n : args.n + args.heldout]
    print(f"model={args.model}  calibration={len(cal)}  held-out={len(held)}")

    meter = Meter()
    invoke = meter.wrap(build_adapter(args.model))

    result = {"model": args.model, "dataset": "ai4privacy/pii-masking-200k", "slices": []}
    detail = {}
    for name, slice_rows in (("calibration", cal), ("held_out", held)):
        r = await run_slice(name, slice_rows, invoke)
        detail[name] = r.pop("detail", [])  # split raw per-row detail into its own file
        result["slices"].append(r)
        for tag in ("regex_only", "regex+semantic"):
            s = r[tag]
            print(f"  [{name:11}] {tag:15} det-recall={s['detection_recall']:.3f} "
                  f"attr-recall={s['attribute_recall']:.3f} precision={s['precision']:.3f} "
                  f"(dets={s['n_detections']}, gt={s['n_inscope_gt']})")
    result["cost"] = meter.summary()
    print("COST:", result["cost"])

    json.dump(result, open(os.path.join(DATA, "calibration_result.json"), "w"), indent=2)
    json.dump(detail, open(os.path.join(DATA, "calibration_detail.json"), "w"), indent=2)
    print("saved -> calibration_result.json + calibration_detail.json (per-row raw)")


if __name__ == "__main__":
    asyncio.run(main())
