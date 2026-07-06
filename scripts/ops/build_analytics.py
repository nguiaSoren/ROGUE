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
  ATP          §10.10 contextual scheduler: benchmark deltas by order mode
               (canonical→contextual rank/ASR/cost) + vendor/family prior warming
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

OUT = _ROOT / "data" / "analytics.json"
BREACH = "('full_breach','partial_breach')"
_ARX = re.compile(r"arxiv\.org/(?:abs|pdf|html)/(\d{2})(\d{2})\.", re.I)


_DOMAIN_LABEL = {  # friendly names for the raw hosts people wouldn't recognise
    "githubusercontent": "github",
    "embracethered": "embracethered.com (blog)",
}


def _domain(url: str) -> str:
    if not url:
        return "unknown"
    # doi.org/10.48550/arXiv.* IS arXiv (linked via DOI) — merge, don't show "doi".
    if "arxiv" in url.lower() or "10.48550" in url:
        return "arxiv"
    m = re.search(r"https?://(?:www\.)?([^/]+)", url)
    host = (m.group(1).split(".")[-2] if m and "." in m.group(1) else (m.group(1) if m else "unknown"))
    return _DOMAIN_LABEL.get(host, host)


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


def research_metrics(c) -> dict:
    """Derived from ladder_rotation_membership — the §10.10 research dataset:
    opportunity cost, early-stop bias, exploration efficiency, scheduler quality."""
    n = c.execute(text("SELECT count(*) FROM ladder_rotation_membership")).scalar()
    if not n:
        return {"note": "no ladder_rotation_membership rows yet"}
    # opportunity cost: eligible strategies starved by early-stop = shots never taken.
    starved = c.execute(text("""SELECT count(*) FROM ladder_rotation_membership
        WHERE eligible AND NOT executed AND skipped_reason='early_stop'""")).scalar()
    elig = c.execute(text("SELECT count(*) FROM ladder_rotation_membership WHERE eligible")).scalar()
    # early-stop bias: fraction of LADDERS that stopped with eligible work still unrun.
    early_stop_bias = c.execute(text("""
        WITH per_ladder AS (
          SELECT run_id, parent_id,
                 bool_or(eligible AND NOT executed AND skipped_reason='early_stop') AS starved
          FROM ladder_rotation_membership GROUP BY run_id, parent_id)
        SELECT avg(starved::int)::float FROM per_ladder""")).scalar()
    # exploration efficiency: distinct strategies ever executed ÷ distinct ever eligible
    # (coverage of the strategy space — low means the ladder keeps re-trying the same few).
    exec_d = c.execute(text("SELECT count(DISTINCT strategy_id) FROM ladder_rotation_membership WHERE executed")).scalar()
    elig_d = c.execute(text("SELECT count(DISTINCT strategy_id) FROM ladder_rotation_membership WHERE eligible")).scalar()
    # scheduler allocation quality: do winners land EARLY? 1 = winner always first in its
    # rotation, 0 = always last. Averaged over ladders that breached (rotation size>1).
    quality = c.execute(text("""
        WITH w AS (
          SELECT run_id, parent_id,
                 min(rank) FILTER (WHERE outcome='breach') AS wrank, max(rank) AS maxrank
          FROM ladder_rotation_membership GROUP BY run_id, parent_id
          HAVING count(*) FILTER (WHERE outcome='breach')>0 AND max(rank)>1)
        SELECT avg(1 - (wrank-1.0)/(maxrank-1))::float FROM w""")).scalar()
    return {
        "opportunity_cost_starved_shots": int(starved),
        "opportunity_cost_pct_of_eligible": round(starved / elig, 3) if elig else None,
        "early_stop_bias": round(float(early_stop_bias), 3) if early_stop_bias is not None else None,
        "exploration_efficiency": round(exec_d / elig_d, 3) if elig_d else None,
        "scheduler_allocation_quality": round(float(quality), 3) if quality is not None else None,
        "_note": "starved/quality are aggregates over ALL runs (mostly canonical mode); "
                 "growth-mode runs drive starvation→~0 (see §10.10). Slice by run for fairness.",
    }


def cost(c, grad: int) -> dict:
    spend = c.execute(text("SELECT coalesce(sum(cost_usd),0) FROM breach_results")).scalar()
    breaches = c.execute(text(f"SELECT count(*) FROM breach_results WHERE verdict IN {BREACH}")).scalar()
    return {
        "total_breach_spend_usd": round(float(spend), 2),
        "cost_per_breach_usd": round(float(spend) / breaches, 4) if breaches else None,
        "cost_per_graduation_usd": round(float(spend) / grad, 2) if grad else None,
    }


def atp(c) -> dict:
    """§10.10 ATP — the contextual scheduler's measured impact + the vendor/family prior warming.

    ``by_order_mode`` aggregates ALL ATP benchmark runs (``benchmark_runs.ladder_order`` non-NULL,
    i.e. runs recorded since the 2026-06-06 deploy) per order mode; ``median_winner_rank`` is the
    mean of per-run medians, ``asr`` and ``cost_per_success`` are goal-weighted. The
    ``canonical→contextual`` pair is the headline (production baseline vs the new default). The
    ``prior_warming`` block tracks the migration-0025 vendor/family tags filling in as scans run on
    the new code (0 = cold; rises with every contextual scan/sweep)."""
    rows = c.execute(text("""
        SELECT ladder_order AS mode, n_goals, n_breached, cost_usd, detail
        FROM benchmark_runs WHERE ladder_order IS NOT NULL""")).all()
    agg: dict = defaultdict(lambda: {"goals": 0, "breached": 0, "cost": 0.0, "ranks": []})
    for r in rows:
        m = agg[r.mode]
        m["goals"] += int(r.n_goals or 0)
        m["breached"] += int(r.n_breached or 0)
        m["cost"] += float(r.cost_usd or 0)
        det = r.detail if isinstance(r.detail, dict) else json.loads(r.detail or "{}")
        mr = det.get("median_winner_rank")
        if mr is not None:
            m["ranks"].append(float(mr))
    by_mode = {
        mode: {
            "goals": v["goals"],
            "asr": round(v["breached"] / v["goals"], 3) if v["goals"] else None,
            "median_winner_rank": round(sum(v["ranks"]) / len(v["ranks"]), 1) if v["ranks"] else None,
            "cost_per_success_usd": round(v["cost"] / v["breached"], 3) if v["breached"] else None,
        }
        for mode, v in agg.items()
    }
    base, ctx = by_mode.get("canonical"), by_mode.get("contextual")
    delta = None
    if base and ctx:
        delta = {
            "median_winner_rank": [base["median_winner_rank"], ctx["median_winner_rank"]],
            "asr": [base["asr"], ctx["asr"]],
            "cost_per_success_usd": [base["cost_per_success_usd"], ctx["cost_per_success_usd"]],
        }
    # vendor/family prior warming (migration 0025 tags; cold until scans run on the new code)
    t = c.execute(text("""SELECT count(*) AS total, count(target_vendor) AS tagged,
                          count(*) FILTER (WHERE is_winner) AS winners FROM ladder_attempts""")).first()
    by_vendor = {r.v: {"attempts": int(r.n), "breaches": int(r.br)} for r in c.execute(text("""
        SELECT target_vendor AS v, count(*) AS n, count(*) FILTER (WHERE breached) AS br
        FROM ladder_attempts WHERE target_vendor IS NOT NULL GROUP BY target_vendor""")).all()}
    by_family = {r.f: {"attempts": int(r.n), "breaches": int(r.br)} for r in c.execute(text("""
        SELECT target_family AS f, count(*) AS n, count(*) FILTER (WHERE breached) AS br
        FROM ladder_attempts WHERE target_family IS NOT NULL GROUP BY target_family""")).all()}
    return {
        "default_mode": "contextual",
        "by_order_mode": by_mode,
        "canonical_to_contextual": delta,
        "prior_warming": {
            "ladder_attempts_total": int(t.total),
            "vendor_tagged": int(t.tagged),
            "vendor_tagged_pct": round(t.tagged / t.total, 3) if t.total else None,
            "winners": int(t.winners),
            "by_vendor": by_vendor,
            "by_family": by_family,
        },
    }


def corpus_health(c) -> dict:
    """Harvest-authorship provenance (dedupe.llm_authored, XDAC-inspired): human-vs-LLM authorship of
    the OPEN-WEB-HARVESTED corpus. Synthesized/generator rows are excluded (machine-made by
    construction). A flag-for-review PRIOR (~0.74 precision, HC3-calibrated AUC 0.84), not an
    auto-drop gate. Auto-refreshes here on every harvest via regenerate()."""
    total = c.execute(text("SELECT count(*) FROM attack_primitives")).scalar()
    synthesized = c.execute(text("SELECT count(*) FROM attack_primitives WHERE synthesized = true")).scalar()
    dist = dict(c.execute(text(
        "SELECT authorship_label, count(*) FROM attack_primitives "
        "WHERE synthesized = false AND authorship_label IS NOT NULL GROUP BY authorship_label")).all())
    scored = sum(int(v) for v in dist.values())
    llm = int(dist.get("llm_generated", 0))
    return {
        "corpus_total": int(total or 0),
        "synthesized_excluded": int(synthesized or 0),
        "harvested_scored": scored,
        "human_authored": int(dist.get("human_authored", 0)),
        "ambiguous": int(dist.get("ambiguous", 0)),
        "llm_generated": llm,
        "pct_likely_ai_generated": round(llm / scored, 3) if scored else None,
        "note": "flag-for-review prior (~0.74 precision, HC3-calibrated); not an auto-drop gate",
    }


def regenerate(database_url: str | None = None, ts: str | None = None) -> dict:
    """Query live Neon → write data/analytics.json. Returns the report dict. No
    printing — safe to call from a harvest/reproduce end-hook. ``ts`` (the caller's
    UTC clock) stamps generated_at; falls back to now() for the CLI path."""
    load_dotenv(str(_ROOT / ".env"))
    e = create_engine(database_url or os.environ["DATABASE_URL"])
    with e.connect() as c:
        cap = capability(c)
        rep = {
            "generated_at": ts,
            "capability": cap,
            "discovery": discovery(c),
            "contextual": contextual(c),
            "allocation": allocation(c),
            "research": research_metrics(c),
            "cost": cost(c, cap["graduated"]),
            "atp": atp(c),
            "corpus_health": corpus_health(c),
        }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2, default=str))
    return rep


def refresh_and_maybe_publish(database_url: str | None = None, ts: str | None = None) -> str:
    """harvest/reproduce end-hook: refresh the analytics snapshot, and — only if
    ROGUE_AUTO_PUBLISH_ANALYTICS=1 — publish it live (vercel --prod, git-free).
    Best-effort: returns a status string, never raises into the caller. Default
    (flag unset) just regenerates the local JSON — no surprise deploys."""
    import subprocess
    try:
        if os.environ.get("ROGUE_AUTO_PUBLISH_ANALYTICS") == "1":
            # publish.sh regenerates + bundles + deploys (so no double-query here)
            r = subprocess.run([str(_ROOT / "scripts" / "ops" / "publish_analytics.sh")],
                               capture_output=True, text=True, timeout=600)
            return f"analytics: regenerated + auto-published (vercel exit={r.returncode})"
        rep = regenerate(database_url, ts=ts)
        return (f"analytics: regenerated data/analytics.json "
                f"(graduated={rep['capability']['graduated']}, "
                f"cost/grad=${rep['cost'].get('cost_per_graduation_usd')}) "
                f"— set ROGUE_AUTO_PUBLISH_ANALYTICS=1 to also push it live")
    except Exception as exc:  # noqa: BLE001 — analytics refresh must never fail a run
        return f"analytics refresh skipped: {exc}"


def main() -> int:
    import datetime
    rep = regenerate(ts=datetime.datetime.now(datetime.timezone.utc).isoformat())

    # ---- readable summary ----
    cap, disc, ctx, alloc, res, cst = (rep[k] for k in
                                       ("capability", "discovery", "contextual", "allocation", "research", "cost"))
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
    print(f"\nRESEARCH  opportunity_cost={res.get('opportunity_cost_starved_shots')} starved shots "
          f"({100*(res.get('opportunity_cost_pct_of_eligible') or 0):.0f}% of eligible)  "
          f"early_stop_bias={res.get('early_stop_bias')}")
    print(f"  exploration_efficiency={res.get('exploration_efficiency')}  "
          f"scheduler_allocation_quality={res.get('scheduler_allocation_quality')}")
    print(f"\nCOST  total=${cst['total_breach_spend_usd']}  per_breach=${cst['cost_per_breach_usd']}  "
          f"per_graduation=${cst['cost_per_graduation_usd']}")
    atpd = rep["atp"]
    dlt = atpd.get("canonical_to_contextual")
    if dlt:
        print(f"\nATP  default={atpd['default_mode']}  canonical→contextual: "
              f"rank {dlt['median_winner_rank'][0]}→{dlt['median_winner_rank'][1]}  "
              f"ASR {100*(dlt['asr'][0] or 0):.0f}%→{100*(dlt['asr'][1] or 0):.0f}%  "
              f"$/success {dlt['cost_per_success_usd'][0]}→{dlt['cost_per_success_usd'][1]}")
    else:
        print(f"\nATP  default={atpd['default_mode']}  (no canonical+contextual benchmark pair yet)")
    pw = atpd["prior_warming"]
    print(f"  prior warming: {pw['vendor_tagged']}/{pw['ladder_attempts_total']} attempts vendor-tagged "
          f"({100*(pw['vendor_tagged_pct'] or 0):.0f}%)  winners={pw['winners']}")
    print(f"\nwrote {OUT.relative_to(_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
