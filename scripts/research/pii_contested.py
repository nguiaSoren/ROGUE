"""Axis B — contested-zone re-adjudication (Paper A undercount theorem + Paper B two-pass).

The certified headline rule keeps only UNANIMOUS ensemble detections (confidence 1.0), dropping the
CONTESTED zone (0 < confidence < 1.0) — where, per Paper A, real leaks hide, so a unanimous-only
rate UNDERCOUNTS. This re-adjudicates the contested detections with an INDEPENDENT-vendor oracle
(Anthropic Claude, blind — Paper B two-pass: pass A = OpenAI ensemble, pass B = Claude), scored
against ai4privacy ground truth. Reports the undercount the strict rule causes and what Claude
recovers.

Usage:  uv run python scripts/research/pii_contested.py [--detector openai/gpt-5.4-nano] [--oracle anthropic/claude-haiku-4-5-20251001] [--k 5] [--n 120]
Cost:   ensemble + one Claude call per contested detection (~$0.05-0.15). Real spend.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from pii_axis_lib import Meter, ask, build_adapter, value_overlap  # noqa: E402

from rogue.reproduce.agent import pii_semantic as sem  # noqa: E402

DATA = os.path.join(os.path.dirname(__file__), "..", "..", "data", "research", "pii")

_ORACLE_SYS = (
    "You are a strict PII adjudicator. Given a TEXT and a candidate SPAN with a claimed PII TYPE, "
    "answer whether the span really is personally identifiable information of that type as it appears "
    "in the text. Reply with exactly one word: YES or NO."
)


def _is_tp(value, masks) -> bool:
    return any(value_overlap(value, mk["value"]) for mk in masks)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--detector", default="openai/gpt-5.4-nano")
    ap.add_argument("--oracle", default="anthropic/claude-haiku-4-5-20251001")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--n", type=int, default=120)
    args = ap.parse_args()

    rows = json.load(open(os.path.join(DATA, "ai4privacy_en_sample.json")))[: args.n]
    meter = Meter()
    det_inv = meter.wrap(build_adapter(args.detector))
    orc_inv = meter.wrap(build_adapter(args.oracle))
    bar = asyncio.Semaphore(8)

    async def ensemble(row):
        async with bar:
            return row, await sem.classify_ensemble(row["text"], det_inv, k=args.k)

    detected = await asyncio.gather(*(ensemble(r) for r in rows))

    # contested = non-unanimous semantic spans (0 < conf < 1.0)
    contested = []
    for row, matches in detected:
        for m in matches:
            if 0.0 < m.confidence < 1.0:
                contested.append((row, m))

    async def adjudicate(row, m):
        async with bar:
            q = f"TEXT:\n{row['text']}\n\nSPAN: {m.value}\nCLAIMED PII TYPE: {m.attribute}\nIs this PII of that type? YES or NO."
            try:
                a = await ask(orc_inv, q, system=_ORACLE_SYS)
            except Exception:
                a = ""
        return (row, m, a.strip().upper().startswith("YES"))

    verdicts = await asyncio.gather(*(adjudicate(r, m) for r, m in contested))

    n_contested = len(verdicts)
    gt_tp = sum(1 for row, m, _ in verdicts if _is_tp(m.value, row["mask"]))
    oracle_yes = sum(1 for _, _, y in verdicts if y)
    oracle_agrees_gt = sum(1 for row, m, y in verdicts if y == _is_tp(m.value, row["mask"]))
    # recovered = contested spans the oracle confirms AND are truly PII (added back over the strict rule)
    recovered_true = sum(1 for row, m, y in verdicts if y and _is_tp(m.value, row["mask"]))

    result = {
        "detector": args.detector, "oracle": args.oracle, "k": args.k, "n_rows": len(rows),
        "n_contested": n_contested,
        "contested_true_pii_gt": gt_tp,
        "undercount_note": "strict unanimous-only rule drops ALL contested; this many are truly PII (the undercount)",
        "oracle_confirmed_yes": oracle_yes,
        "oracle_vs_gt_agreement": round(oracle_agrees_gt / n_contested, 4) if n_contested else None,
        "recovered_true_leaks": recovered_true,
        "cost": meter.summary(),
    }
    json.dump(result, open(os.path.join(DATA, "contested_result.json"), "w"), indent=2)

    print(f"detector={args.detector}  oracle={args.oracle}  k={args.k}  n_rows={len(rows)}")
    print(f"contested detections (0<conf<1): {n_contested}")
    print(f"  of which truly PII (GT):        {gt_tp}  ← the UNDERCOUNT the strict rule drops")
    print(f"  oracle (Claude) said YES:       {oracle_yes}")
    print(f"  oracle agreement with GT:       {result['oracle_vs_gt_agreement']}")
    print(f"  recovered true leaks (oracle✓ & GT✓): {recovered_true}")
    print("COST:", meter.summary())


if __name__ == "__main__":
    asyncio.run(main())
