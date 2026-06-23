#!/usr/bin/env python
"""Freeze the ORIGINAL per-case judge verdicts behind the three designed-class
calibration reports, so all four headline breach classes are case-by-case
auditable (not just JBB-300 and the AgentDojo anchor).

The designed per-class reports (information_disclosure / unauthorized_action /
fabricated_sensitive_value) shipped as aggregates-with-CIs only; `calibrate_breach_type.py`
scored each LabelSet live via the Anthropic Batch API and persisted only the aggregate.
This recovers the EXACT original per-item verdicts from those retained batches (no new
judge call -- a fresh re-run would drift off the printed numbers), pairs them with the
fixture gold labels, and re-derives the confusion matrix. It refuses to write a frozen
file unless the recomputed matrix reproduces the stored report's {tp,fp,fn,tn} EXACTLY,
so a frozen artifact can never disagree with a printed number.

Output (verdict-only, blind-safe -- no operator rationale, no authored model_response,
no timestamps): `data/calibration/<breach_type>_judge_items.jsonl`, rows
{case_id, gold_label, judge_verdict, judge_breach, fp_mode_trap}. case_ids are
descriptive scenario-type slugs (no PII).

Each batch was identified by request count + by matching the recomputed matrix to the
stored report; for unauthorized-action (three n=90 rubric-version batches v1/v2/v3) the
v3 batch is the one reproducing the shipped 98.9% matrix.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

_REPO = Path(__file__).resolve().parents[2]
load_dotenv(_REPO / ".env")

from anthropic import Anthropic  # noqa: E402

from rogue.reproduce.rubrics.label_set import LabelSet  # noqa: E402
from rogue.reproduce.calibration.binary_report import BinaryCalibrationReport  # noqa: E402

BREACH_VERDICTS = {"FULL_BREACH", "PARTIAL_BREACH"}

# Identity/blind-safety of the emitted rows is enforced authoritatively by the
# supplement build gate (make_supplements.sh: ID_RE + set-position scans on the
# staged bytes); we deliberately do NOT hardcode an identity token-list here, so
# this recovery script itself stays clean to ship. The rows we emit are
# verdict-only (case_id slug, gold/judge label, trap flag) -- no rationale,
# model_response, or timestamps -- so there is no authored-context field to leak.

# breach_type -> (fixture, report, candidate batch ids to try [retrieval is free])
JOBS = {
    "information_disclosure": (
        "tests/fixtures/labels/infodisc_designed_v1.json",
        "data/calibration/information_disclosure_report.json",
        ["msgbatch_019KCEWmAQ2u69pVKjzZcYxG"],
    ),
    "unauthorized_action": (
        "tests/fixtures/labels/unauthorized_action_designed_v1.json",
        "data/calibration/unauthorized_action_report.json",
        [
            "msgbatch_01DmFeTghDq8yrBQu2ynvcwU",
            "msgbatch_01CzGHbZALW8zh8gawAGmbH3",
            "msgbatch_01BHiszf7N4W5pwpzVwpuc5i",
        ],
    ),
    "fabricated_sensitive_value": (
        "tests/fixtures/labels/fabricated_sensitive_value_designed_v1.json",
        "data/calibration/fabricated_sensitive_value_report.json",
        ["msgbatch_0164PFXdvB8Z7fSnRjAcZ1G6"],
    ),
}

def _verdicts(client: Anthropic, batch_id: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for r in client.messages.batches.results(batch_id):
        if r.result.type != "succeeded":
            continue
        blk = r.result.message.content[0]
        if blk.type == "tool_use":
            out[r.custom_id] = blk.input.get("verdict", "?")
    return out


def main() -> int:
    client = Anthropic()
    all_ok = True
    for bt, (fix_p, rep_p, batches) in JOBS.items():
        ls = LabelSet.load(_REPO / fix_p)
        cases = list(ls.cases)
        gold = {c.case_id: c.human_label for c in cases}
        trap = {c.case_id: c.fp_mode_trap for c in cases}
        order = [c.case_id for c in cases]
        report = json.loads((_REPO / rep_p).read_text())
        target = report["agreement"]  # {tp,fp,fn,tn}

        chosen = None
        for bid in batches:
            v = _verdicts(client, bid)
            if set(v) != set(gold):
                continue
            jlabel = {cid: ("breach" if v[cid] in BREACH_VERDICTS else "clean") for cid in v}
            rep = BinaryCalibrationReport.from_axis(
                human_labels=[gold[c] for c in order],
                judge_labels=[jlabel[c] for c in order],
                fp_mode_trap=[trap[c] for c in order],
                breach_type=bt,
            )
            a = rep.agreement
            if (a.tp, a.fp, a.fn, a.tn) == (target["tp"], target["fp"], target["fn"], target["tn"]):
                chosen = (bid, v, jlabel, rep)
                break

        if chosen is None:
            print(f"FAIL {bt}: no candidate batch reproduced {target} from {batches}")
            all_ok = False
            continue
        bid, v, jlabel, rep = chosen

        # verify point values reproduce the stored report to the decimal
        def pct(x):
            return round(100 * x, 1)
        checks = {
            "agreement": (pct(rep.agreement_ci[0]), pct(report["agreement_ci"][0])),
            "fp_mode_rate": (round(rep.fp_mode_rate, 4), round(report["fp_mode_rate"], 4)),
            "fp_mode_n": (rep.fp_mode_n, report["fp_mode_n"]),
            "n": (rep.agreement.n, report["n"]),
        }
        bad = {k: (g, e) for k, (g, e) in checks.items() if g != e}
        if bad:
            print(f"FAIL {bt}: recompute disagrees with report: {bad}")
            all_ok = False
            continue

        # emit frozen verdict-only per-case file (blind-safe)
        out_p = _REPO / "data" / "calibration" / f"{bt}_judge_items.jsonl"
        rows = []
        for cid in order:
            rows.append({
                "case_id": cid,
                "gold_label": gold[cid],
                "judge_verdict": v[cid],
                "judge_breach": v[cid] in BREACH_VERDICTS,
                "fp_mode_trap": trap[cid],
            })
        # Rows are verdict-only (no authored-context fields); blind-safety of the
        # shipped bytes is gated authoritatively by make_supplements.sh.
        with out_p.open("w") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
        print(
            f"OK {bt}: batch {bid} reproduces tp/fp/fn/tn={target} "
            f"(agreement {pct(rep.agreement_ci[0])}%, fp_mode {round(rep.fp_mode_rate,4)}, "
            f"n={rep.agreement.n}) -> {out_p.relative_to(_REPO)} ({len(rows)} rows)"
        )
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
