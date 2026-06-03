#!/usr/bin/env python
"""Analytics/report layer — turn the rich telemetry into answers, not manual SQL.

One serious sweep now yields allocation + capability + research metrics; this
aggregates them from live Neon into `data/analytics.json` (for a future dashboard)
and prints a readable summary. $0, read-only, no deploy, no git. Re-run anytime;
re-bundle + `vercel --prod` when a UI consumes the JSON.

Sections:
  CAPABILITY   graduations (by modality + rate), breach rate, validity rate
  DISCOVERY    source yield (techniques/source + graduation rate), per-harvest yield,
               modality growth (by source month)
  CONTEXTUAL   family × model breach spread + crossover (per-model-ladder signal)
  ALLOCATION   reachability, starvation rate, rank-of-winner, avg ladder depth
  COST         cost per breach, cost per graduation
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

OUT = _ROOT / "data" / "analytics.json"
BREACH = "('full_breach','partial_breach')"
_ARX = re.compile(r"arxiv\.org/(?:abs|pdf|html)/(\d{2})(\d{2})\.", re.I)


def _domain(url: str) -> str:
    if not url:
        return "unknown"
    if "arxiv" in url:
        return "arxiv"
    m = re.search(r"https?://(?:www\.)?([^/]+)", url)
    return (m.group(1).split(".")[-2] if m and "." in m.group(1) else (m.group(1) if m else "unknown"))


def capability(c) -> dict:
    by_status = dict(c.execute(text(
        "SELECT status, count(*) FROM attack_strategies GROUP BY status")).all())
    grad_by_mod = dict(c.execute(text(
        "SELECT modality, count(*) FROM attack_strategies WHERE first_breach_at IS NOT NULL GROUP BY modality")).all())
    harvested = sum(by_status.values())
    graduated = c.execute(text("SELECT count(*) FROM attack_strategies WHERE first_breach_at IS NOT NULL")).scalar()
    # validity: real tests vs orchestration noise (n_valid_trials / n_attempts_total)
    vrow = c.execute(text("""SELECT sum(n_valid_trials)::float AS v, sum(n_attempts_total)::float AS a
                             FROM attack_strategies WHERE n_attempts_total>0""")).first()
    overall_breach = c.execute(text(f"""SELECT count(*) FILTER (WHERE verdict IN {BREACH})::float
                                        / nullif(count(*),0) FROM breach_results""")).scalar()
    return {
        "strategies_total": harvested,
        "by_status": {k: int(v) for k, v in by_status.items()},
        "graduated": int(graduated),
        "graduation_rate": round(graduated / harvested, 3) if harvested else None,
        "graduations_by_modality": {k: int(v) for k, v in grad_by_mod.items()},
        "overall_breach_rate": round(overall_breach, 3) if overall_breach else None,
        "validity_rate": round(vrow.v / vrow.a, 3) if vrow and vrow.a else None,
    }


def discovery(c) -> dict:
    # source yield: techniques + graduations per source domain
    rows = c.execute(text("""SELECT source_url, status, first_breach_at FROM attack_strategies""")).all()
    by_src = defaultdict(lambda: {"techniques": 0, "graduated": 0})
    by_month = defaultdict(lambda: {"techniques": 0, "graduated": 0})
    for r in rows:
        d = _domain(r.source_url or "")
        by_src[d]["techniques"] += 1
        if r.first_breach_at:
            by_src[d]["graduated"] += 1
        m = _ARX.search(r.source_url or "")
        if m:
            key = f"20{m.group(1)}-{m.group(2)}"
            by_month[key]["techniques"] += 1
            if r.first_breach_at:
                by_month[key]["graduated"] += 1
    src_yield = {k: {**v, "grad_rate": round(v["graduated"] / v["techniques"], 2) if v["techniques"] else 0}
                 for k, v in sorted(by_src.items(), key=lambda kv: -kv[1]["techniques"])}
    # per-harvest yield (harvest_run_id populated from migration 0020 forward)
    per_run = dict(c.execute(text(
        "SELECT harvest_run_id, count(*) FROM attack_strategies WHERE harvest_run_id IS NOT NULL GROUP BY harvest_run_id")).all())
    return {
        "source_yield": src_yield,
        "per_harvest_run": {k: int(v) for k, v in per_run.items()},
        "modality_growth_by_source_month": dict(sorted(by_month.items())),
    }


def contextual(c, min_n: int = 20) -> dict:
    rows = c.execute(text(f"""
        SELECT p.family::text AS fam, d.target_model AS model, count(*) AS n,
               count(*) FILTER (WHERE b.verdict IN {BREACH}) AS br
        FROM breach_results b JOIN attack_primitives p ON p.primitive_id=b.primitive_id
        JOIN deployment_configs d ON d.config_id=b.deployment_config_id
        GROUP BY p.family, d.target_model HAVING count(*)>={min_n}""")).all()
    by_fam = defaultdict(dict)
    by_model = defaultdict(dict)
    for r in rows:
        by_fam[r.fam][r.model] = round(r.br / r.n, 2)
        by_model[r.model][r.fam] = r.br / r.n
    spreads = {f: round(max(m.values()) - min(m.values()), 2) for f, m in by_fam.items() if len(m) > 1}
    # crossover: how many models' best family differs from the global-best
    fam_mean = {f: sum(m.values()) / len(m) for f, m in by_fam.items()}
    gbest = max(fam_mean, key=fam_mean.get) if fam_mean else None
    crossover = sum(1 for mdl, fams in by_model.items()
                    if len(fams) >= 3 and max(fams, key=fams.get) != gbest
                    and fams[max(fams, key=fams.get)] - fams.get(gbest, 0) >= 0.10)
    return {
        "family_x_model_breach": {f: m for f, m in by_fam.items()},
        "biggest_spreads": dict(sorted(spreads.items(), key=lambda kv: -kv[1])[:6]),
        "global_best_family": gbest,
        "crossover_models": crossover,
        "routing_verdict": ("worth evaluating" if crossover >= 3
                            else "NOT worth a rewrite (main effect, not interaction)"),
    }


def allocation(c) -> dict:
    n = c.execute(text("SELECT count(*) FROM ladder_rotation_membership")).scalar()
    if not n:
        return {"note": "no ladder_rotation_membership rows yet"}
    elig = c.execute(text("SELECT count(*) FROM ladder_rotation_membership WHERE eligible")).scalar()
    execd = c.execute(text("SELECT count(*) FROM ladder_rotation_membership WHERE eligible AND executed")).scalar()
    starved = c.execute(text("SELECT count(*) FROM ladder_rotation_membership WHERE eligible AND NOT executed AND skipped_reason='early_stop'")).scalar()
    # rank-of-winner: rank of the strategy that breached, per ladder
    ranks = [r[0] for r in c.execute(text(
        "SELECT rank FROM ladder_rotation_membership WHERE outcome='breach' AND rank IS NOT NULL")).all()]
    depth = c.execute(text(
        "SELECT avg(cnt) FROM (SELECT count(*) cnt FROM ladder_attempts WHERE outcome<>'stopped' GROUP BY parent_id) s")).scalar()
    return {
        "reachability": round(execd / elig, 3) if elig else None,
        "starvation_rate": round(starved / elig, 3) if elig else None,
        "avg_rank_of_winner": round(sum(ranks) / len(ranks), 2) if ranks else None,
        "avg_ladder_depth": round(float(depth), 1) if depth else None,
        "eligible_rows": int(elig),
    }


def cost(c, grad: int) -> dict:
    spend = c.execute(text("SELECT coalesce(sum(cost_usd),0) FROM breach_results")).scalar()
    breaches = c.execute(text(f"SELECT count(*) FROM breach_results WHERE verdict IN {BREACH}")).scalar()
    return {
        "total_breach_spend_usd": round(float(spend), 2),
        "cost_per_breach_usd": round(float(spend) / breaches, 4) if breaches else None,
        "cost_per_graduation_usd": round(float(spend) / grad, 2) if grad else None,
    }


def main() -> int:
    load_dotenv(str(_ROOT / ".env"))
    e = create_engine(os.environ["DATABASE_URL"])
    with e.connect() as c:
        cap = capability(c)
        rep = {
            "capability": cap,
            "discovery": discovery(c),
            "contextual": contextual(c),
            "allocation": allocation(c),
            "cost": cost(c, cap["graduated"]),
        }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2, default=str))

    # ---- readable summary ----
    cap, disc, ctx, alloc, cst = (rep[k] for k in ("capability", "discovery", "contextual", "allocation", "cost"))
    print("\n" + "=" * 70 + "\nROGUE ANALYTICS\n" + "=" * 70)
    print(f"\nCAPABILITY  strategies={cap['strategies_total']}  graduated={cap['graduated']} "
          f"({100*(cap['graduation_rate'] or 0):.0f}%)  validity={cap['validity_rate']}  "
          f"overall_breach={cap['overall_breach_rate']}")
    print(f"  graduations by modality: {cap['graduations_by_modality']}")
    print("\nDISCOVERY  source yield (techniques | graduated | grad-rate):")
    for src, v in list(disc["source_yield"].items())[:6]:
        print(f"    {src:14} {v['techniques']:3} | {v['graduated']:2} | {v['grad_rate']}")
    print(f"  per-harvest-run yield: {disc['per_harvest_run']}")
    print(f"  modality growth (source-month → techniques): "
          f"{ {k: v['techniques'] for k, v in disc['modality_growth_by_source_month'].items()} }")
    print(f"\nCONTEXTUAL  global-best family={ctx['global_best_family']}  crossover_models={ctx['crossover_models']}"
          f"  → routing {ctx['routing_verdict']}")
    print(f"  biggest family×model spreads: {ctx['biggest_spreads']}")
    print(f"\nALLOCATION  reachability={alloc.get('reachability')}  starvation={alloc.get('starvation_rate')}  "
          f"avg_rank_of_winner={alloc.get('avg_rank_of_winner')}  avg_depth={alloc.get('avg_ladder_depth')}")
    print(f"\nCOST  total=${cst['total_breach_spend_usd']}  per_breach=${cst['cost_per_breach_usd']}  "
          f"per_graduation=${cst['cost_per_graduation_usd']}")
    print(f"\nwrote {OUT.relative_to(_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
