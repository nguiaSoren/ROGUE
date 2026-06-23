#!/usr/bin/env python
"""Freeze the paper-figure data: live Neon → docs/research/figs/data/ (CSVs + metrics.json).

This is the reproducibility step. `paper_figs.py` plots ONLY from the frozen files
this writes, so figures regenerate offline (no DB, no run-ids) once the data is
exported. Run this whenever the underlying runs change; otherwise the frozen
snapshot is the citable source of every number in the paper.

READ-ONLY against the DB (queries only). Sources:
  - F2/F3/F5/F7/F10  → live SQL  → one CSV each
  - graduations/run  → live SQL (first_breach_at within the run's time window)
  - escalation spend → parsed from the run `done:` line in /tmp/rogue_*.log
  - quota simulation → re-run `simulate_quota.py` (deterministic replay) and parse

    uv run python scripts/export_paper_data.py
"""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

DATA = _ROOT / "docs" / "research" / "figs" / "data"  # MUST match paper_figs.py:DATA
RUNS = {
    "greedy": {"run_id": "sweep_p2_1780457963", "K": 3, "quota": 0, "order": "canonical"},
    "starv_q3": {"run_id": "sweep_starv_q3_1780462736", "K": 3, "quota": 3, "order": "starvation"},
    "growth_k5": {"run_id": "sweep_K5_q5_1780477935", "K": 5, "quota": 5, "order": "starvation"},
}


def _conn():
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")
    return create_engine(url).connect()


def _csv(name: str, header: list[str], rows: list) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    p = DATA / f"{name}.csv"
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  wrote {p.relative_to(_ROOT)}  ({len(rows)} rows)")


def _spend_from_logs(run_id: str) -> float | None:
    """escalation_spend from the run's done: line in any /tmp/rogue_*.log."""
    for log in Path("/tmp").glob("rogue_*.log"):
        try:
            txt = log.read_text(errors="ignore")
        except OSError:
            continue
        m = re.search(rf"run_id={re.escape(run_id)} done:.*?escalation_spend=\$([0-9.]+)", txt)
        if m:
            return float(m.group(1))
    return None


def _planner_metrics_from_logs(
    t0, t1, path: Path = _ROOT / "llm_cost_log.csv"
) -> dict:
    """Planner (``module=escalation_planner``) call-count + token totals within a
    run's ``[t0, t1]`` window, summed from ``llm_cost_log.csv``.

    Closes the paper's "one planner backbone is currently unpriced" caveat
    WITHOUT new spend: the OpenRouter planner (Mistral) logs ``cost_usd=$0``
    (it isn't in the Anthropic price table), but its real token counts ARE
    logged, so we return tokens for *post-hoc* pricing at OpenRouter's live
    rate, plus the call count.

    Attribution is by timestamp window because the CSV has no ``run_id`` column
    — the same scheme ``graduations``/``escalation_spend`` already use. Safe
    because K-saturation runs are sequential (non-overlapping windows); leave a
    >2 min gap between paid runs so boundary plans don't bleed across windows.
    Only API calls are logged (plan-cache hits make no call), so
    ``planner_calls`` == cache misses == billable plans. Bounds are exact (no
    pad), which can slightly *under*-count plans authored just before the first
    attempt row — the conservative direction for a cost bound.
    """
    empty = {"planner_calls": 0, "planner_tokens_in": 0, "planner_tokens_out": 0}
    if t0 is None or t1 is None or not path.exists():
        return empty

    def _aware(dt):
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    lo, hi = _aware(t0), _aware(t1)
    calls = tin = tout = 0
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("module") != "escalation_planner":
                continue
            try:
                ts = _aware(row["timestamp_utc"])
            except (ValueError, KeyError, TypeError):
                continue
            if lo <= ts <= hi:
                calls += 1
                tin += int(row.get("input_tokens") or 0)
                tout += int(row.get("output_tokens") or 0)
    return {"planner_calls": calls, "planner_tokens_in": tin, "planner_tokens_out": tout}


def _quota_sim(run_id: str) -> dict | None:
    """Re-run simulate_quota (deterministic replay) and parse its table."""
    try:
        out = subprocess.run(
            ["uv", "run", "python", "scripts/benchmark/simulate_quota.py", "--run-id", run_id],
            cwd=str(_ROOT), capture_output=True, text=True, timeout=120,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    q, reach, cost = [], [], []
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\s+([0-9.]+)\s+[0-9.]+\s+\d+\s+\$([0-9.]+)", line)
        if m:
            q.append(int(m.group(1)))
            reach.append(float(m.group(2)))
            cost.append(float(m.group(3)))
    return {"source_run": run_id, "quota": q, "candidate_reach": reach, "est_cost": cost} if q else None


def main() -> int:
    c = _conn()
    DATA.mkdir(parents=True, exist_ok=True)
    print(f"exporting frozen figure data → {DATA.relative_to(_ROOT)}/")

    g, s = RUNS["greedy"]["run_id"], RUNS["starv_q3"]["run_id"]

    # F2 — reachability by tier (greedy + growth)
    f2 = []
    for run in (g, s):
        for r in c.execute(text("""SELECT tier,
              sum((eligible AND executed)::int)::float/NULLIF(sum(eligible::int),0) reach,
              sum(eligible::int) n FROM ladder_rotation_membership WHERE run_id=:r GROUP BY tier"""), {"r": run}):
            f2.append([run, r.tier, round(float(r.reach or 0), 4), int(r.n)])
    _csv("F2_reachability", ["run_id", "tier", "reachability", "n_eligible"], f2)

    # F3 — starvation outcome distribution
    f3 = []
    for run in (g, s):
        for r in c.execute(text("""SELECT COALESCE(skipped_reason,'executed') o, count(*) n
              FROM ladder_rotation_membership WHERE run_id=:r GROUP BY 1"""), {"r": run}):
            f3.append([run, r.o, int(r.n)])
    _csv("F3_starvation", ["run_id", "outcome", "n"], f3)

    # F5 — ladder win-share (greedy) vs unbiased per-model breach rate
    win = {r.model: float(r.s) for r in c.execute(text("""
        SELECT config_id model, count(*)::float/sum(count(*)) OVER () s
        FROM ladder_attempts WHERE breached AND config_id IS NOT NULL AND run_id=:r GROUP BY 1"""), {"r": g})}
    f5 = []
    for r in c.execute(text("""SELECT dc.target_model m,
          sum((br.verdict IN ('partial_breach','full_breach'))::int)::float/count(*) rate, count(*) n
          FROM breach_results br JOIN deployment_configs dc ON dc.config_id=br.deployment_config_id
          GROUP BY 1""")):
        f5.append([r.m, round(win.get(r.m, 0.0), 4), round(float(r.rate), 4), int(r.n)])
    _csv("F5_allocation", ["model", "ladder_win_share", "unbiased_breach_rate", "n_trials"], f5)

    # F7 — per-model × family breach rate
    f7 = []
    for r in c.execute(text("""SELECT dc.target_model m, ap.family f,
          sum((br.verdict IN ('partial_breach','full_breach'))::int)::float/count(*) rate, count(*) n
          FROM breach_results br
          JOIN deployment_configs dc ON dc.config_id=br.deployment_config_id
          JOIN attack_primitives ap ON ap.primitive_id=br.primitive_id GROUP BY 1,2""")):
        f7.append([r.m, str(r.f), round(float(r.rate), 4), int(r.n)])
    _csv("F7_heatmap", ["model", "family", "breach_rate", "n"], f7)

    # F10 — rank-of-winner per ladder
    f10 = []
    for run in (g, s):
        for r in c.execute(text("""SELECT rank FROM ladder_rotation_membership
              WHERE run_id=:r AND executed AND config_id IS NOT NULL"""), {"r": run}):
            f10.append([run, int(r.rank)])
    _csv("F10_rank", ["run_id", "rank"], f10)

    # metrics.json — graduations (queried), spend (logs), snapshots (derived), quota sim
    metrics: dict = {"provenance": "scripts/export_paper_data.py — graduations queried via "
                     "first_breach_at within each run's [min,max](ladder_attempts.created_at) window; "
                     "escalation_spend parsed from /tmp/rogue_*.log done: lines; snapshots derived from "
                     "cumulative graduations + current active total; quota_sim re-run from simulate_quota.py.",
                     "runs": {}}
    grads = {}
    for name, meta in RUNS.items():
        rid = meta["run_id"]
        win_t = c.execute(text("SELECT min(created_at) a, max(created_at) b FROM ladder_attempts WHERE run_id=:r"),
                          {"r": rid}).one()
        n_grad = c.execute(text("SELECT count(*) FROM attack_strategies WHERE first_breach_at BETWEEN :a AND :b"),
                           {"a": win_t.a, "b": win_t.b}).scalar() if win_t.a else 0
        grads[name] = int(n_grad or 0)
        metrics["runs"][name] = {**meta, "graduations": int(n_grad or 0),
                                 "escalation_spend": _spend_from_logs(rid),
                                 **_planner_metrics_from_logs(win_t.a, win_t.b)}
    # derive active/candidate snapshots from current totals minus later graduations
    cur = dict(c.execute(text("SELECT status, count(*) FROM attack_strategies GROUP BY 1")).all())
    active_now = int(cur.get("active", 0))
    cand_now = int(cur.get("candidate", 0))
    # checkpoints in run order: greedy → starv_q3 → growth_k5
    seq = ["greedy", "starv_q3", "growth_k5"]
    after_active, after_cand, run_a, run_c = {}, {}, active_now, cand_now
    for nm in reversed(seq):
        after_active[nm] = run_a
        after_cand[nm] = run_c
        run_a -= grads[nm]      # before this run, active was lower by its graduations
        run_c += grads[nm]      # and candidate pool was higher (graduated ones were still candidates)
    for nm in seq:
        metrics["runs"][nm]["active_after"] = after_active[nm]
        metrics["runs"][nm]["candidate_after"] = after_cand[nm]
    metrics["quota_sim"] = _quota_sim(g)
    (DATA / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str))
    print(f"  wrote {(DATA / 'metrics.json').relative_to(_ROOT)}")
    c.close()
    print("done — now: uv run python scripts/paper_figs.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
