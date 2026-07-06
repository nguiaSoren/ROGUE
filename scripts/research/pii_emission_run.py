"""Axis B steps 1+2+6 — the emission matrix: probes × target models × trials, live.

This is the "real scan" for research: send each PII-extraction probe to each target deployment,
judge the response with the CALIBRATED detector (fixed model, separate from the target), and
record whether PII was emitted, which attributes, and its provenance. Emission rate per model =
fraction of (probe×trial) that emitted any PII. Findings are non-headline (the judge stamps that);
the calibration run licenses reading the rate as precision≈0.89 / recall≈0.7.

Usage:  uv run python scripts/research/pii_emission_run.py \
            [--models openai/gpt-5.4-nano,openai/gpt-5.4] [--detector openai/gpt-5.4-nano] [--trials 3]
Cost:   ~$0.05-0.30. Real spend — run deliberately.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))
from pii_axis_lib import Meter, ask, build_adapter  # noqa: E402

from rogue.reproduce.agent import pii_semantic as sem  # noqa: E402
from rogue.reproduce.agent.pii_probes import PII_PROBES  # noqa: E402
from rogue.reproduce.agent.trace_judge import TraceJudge  # noqa: E402
from rogue.schemas import AgentTranscript, AgentTurn, DeterminismHeader  # noqa: E402

DATA = os.path.join(os.path.dirname(__file__), "..", "..", "data", "research", "pii")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="openai/gpt-5.4-nano,openai/gpt-5.4")
    ap.add_argument("--detector", default="openai/gpt-5.4-nano")
    ap.add_argument("--trials", type=int, default=3)
    args = ap.parse_args()
    targets = [m.strip() for m in args.models.split(",") if m.strip()]

    meter = Meter()
    det_invoke = meter.wrap(build_adapter(args.detector))  # fixed, calibrated detector
    sem_fn = sem.make_semantic_fn(invoke_fn=det_invoke)
    judge = TraceJudge()

    per_model = {}
    records = []
    for model in targets:
        t_invoke = meter.wrap(build_adapter(model))
        n_cells = 0
        n_emitted = 0
        attr_counter: Counter = Counter()
        prov_counter: Counter = Counter()
        by_probe: dict = {}
        for probe in PII_PROBES:
            probe_emit = 0
            for _ in range(args.trials):
                n_cells += 1
                resp = await ask(t_invoke, probe.prompt)
                tr = AgentTranscript(
                    transcript_id=f"{model}:{probe.probe_id}", primitive_id="p", config_id="c",
                    header=DeterminismHeader(seed=1, target_model=model),
                    turns=[AgentTurn(role="model", text=resp)],
                )
                findings = judge.judge_pii_emission(tr, semantic_fn=sem_fn)
                if findings:
                    n_emitted += 1
                    probe_emit += 1
                    for f in findings:
                        attr_counter[f.evidence["pii_attribute"]] += 1
                        prov_counter[f.evidence["provenance"]] += 1
                records.append({"model": model, "probe": probe.probe_id,
                                "emitted": bool(findings),
                                "attrs": [f.evidence["pii_attribute"] for f in findings],
                                "resp": resp[:160]})
            by_probe[probe.probe_id] = round(probe_emit / args.trials, 3)
        per_model[model] = {
            "emission_rate": round(n_emitted / n_cells, 4),
            "n_cells": n_cells, "n_emitted": n_emitted,
            "attributes": dict(attr_counter), "provenance": dict(prov_counter),
            "by_probe": by_probe,
        }

    result = {"targets": targets, "detector": args.detector, "trials": args.trials,
              "note": "uncalibrated-headline: findings non-headline; rate read with precision~0.89/recall~0.7 (see calibration_result.json)",
              "per_model": per_model, "cost": meter.summary(), "records": records}
    json.dump(result, open(os.path.join(DATA, "emission_result.json"), "w"), indent=2)

    print(f"detector={args.detector} trials={args.trials}")
    for model, s in per_model.items():
        print(f"  {model:22} emission-rate={s['emission_rate']:.3f} "
              f"({s['n_emitted']}/{s['n_cells']})  attrs={s['attributes']}  prov={s['provenance']}")
    print("COST:", meter.summary())


if __name__ == "__main__":
    asyncio.run(main())
