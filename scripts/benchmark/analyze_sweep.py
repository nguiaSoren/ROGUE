#!/usr/bin/env python
"""§10.10 Phase-2 sweep analysis — read-only, reproducible.

Codifies the post-sweep analysis order (evidence, not features):

  1. Reachability vs value     — high-value / low-reachability = scheduler blind spots
  2. Starvation distribution   — where opportunity is lost (early_stop / budget / config)
  3. Rank-of-winner            — how deep the winner sat (the reorder-efficiency KPI)
  4. Graduation efficiency     — is the repertoire actually growing?
  5. Winner-model vs contextual map — ladder allocation bias (biased vs unbiased)
  6. Cost-per-breach           — did adaptive allocation buy more breaches/$?

READ-ONLY (no writes, no model calls, no cost). Sections degrade gracefully when a
table is empty (e.g. run mid-sweep). Reachability comes from `ladder_rotation_membership`
(populated only by §10.10 Phase 2.1+ runs), so it is effectively run-scoped already.

Usage::

    uv run python scripts/benchmark/analyze_sweep.py --run-id sweep_p2_1780457963
    uv run python scripts/benchmark/analyze_sweep.py --run-id $(cat /tmp/rogue_sweep_runid.txt)
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402


def _db():
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")
    return sessionmaker(bind=create_engine(url))()


def _h(title: str) -> None:
    print(f"\n{'─' * 78}\n{title}\n{'─' * 78}")


# 1 ─────────────────────────────────────────────────────────────────────────
def reachability_vs_value(session) -> None:
    """The headline: strategies the scheduler values but can't reach."""
    from rogue.reproduce.ladder_priors import strategy_reachability, strategy_values

    _h("1. REACHABILITY vs VALUE  (high value + low reach = scheduler blind spots)")
    now = datetime.now(timezone.utc)
    values = strategy_values(session)
    reach = strategy_reachability(session)
    if not reach:
        print("  no ladder_rotation_membership rows yet (sweep hasn't logged any).")
        return
    rows = []
    for sid, rs in reach.items():
        sv = values.get(sid)
        vscore = sv.value_score(now) if sv else 0.5  # unseen → neutral EV
        rows.append((sid, vscore, rs.reachability, rs.starvation_rate, rs.eligible))
    rows.sort(key=lambda r: -r[1])  # by value desc
    print(f"  {'strategy':<34}{'value':>7}{'reach':>7}{'starv':>7}{'elig':>6}  flag")
    for sid, v, reach_r, starv, elig in rows[:20]:
        flag = "  ◀ BLIND SPOT" if (v >= 0.45 and reach_r <= 0.5 and elig >= 2) else ""
        print(f"  {sid[:34]:<34}{v:>7.2f}{reach_r:>7.2f}{starv:>7.2f}{elig:>6}{flag}")
    blind = [r for r in rows if r[1] >= 0.45 and r[2] <= 0.5 and r[4] >= 2]
    print(f"\n  → {len(blind)} high-value / low-reachability strategies "
          "= Phase 2.2 targets (reachability-aware EV).")


# 2 ─────────────────────────────────────────────────────────────────────────
def starvation_distribution(session, run_id: str | None) -> None:
    _h("2. STARVATION DISTRIBUTION  (where eligible opportunities were lost)")
    where = "WHERE run_id = :rid" if run_id else ""
    by_reason = session.execute(text(
        f"SELECT COALESCE(skipped_reason, 'executed') AS reason, count(*) n "
        f"FROM ladder_rotation_membership {where} GROUP BY 1 ORDER BY 2 DESC"
    ), {"rid": run_id} if run_id else {}).all()
    if not by_reason:
        print("  no rotation-membership rows yet.")
        return
    total = sum(n for _, n in by_reason)
    print("  by outcome (of all eligible appearances):")
    for reason, n in by_reason:
        print(f"    {reason:<22}{n:>6}  ({n / total:.0%})")
    by_tier = session.execute(text(
        f"SELECT tier, "
        f"  sum((eligible AND executed)::int) executed, "
        f"  sum((skipped_reason='early_stop')::int) early_stop, "
        f"  sum(eligible::int) eligible "
        f"FROM ladder_rotation_membership {where} GROUP BY 1 ORDER BY 1"
    ), {"rid": run_id} if run_id else {}).all()
    print("\n  by tier (reach = executed/eligible, starv = early_stop/eligible):")
    print(f"    {'tier':<12}{'reach':>7}{'starv':>7}{'elig':>7}")
    for tier, ex, es, el in by_tier:
        el = el or 1
        print(f"    {tier:<12}{(ex or 0) / el:>7.2f}{(es or 0) / el:>7.2f}{el:>7}")


# 3 ─────────────────────────────────────────────────────────────────────────
def rank_of_winner(session, run_id: str | None) -> None:
    _h("3. RANK-OF-WINNER  (how deep the winner sat — reorder efficiency KPI)")
    where = "WHERE run_id = :rid AND " if run_id else "WHERE "
    # Winner rows in rotation_membership carry config_id (the winning model).
    ranks = session.execute(text(
        f"SELECT rank FROM ladder_rotation_membership "
        f"{where} executed AND config_id IS NOT NULL ORDER BY rank"
    ), {"rid": run_id} if run_id else {}).scalars().all()
    if not ranks:
        print("  no winning ladders yet (no breach with a recorded winner).")
        return
    n = len(ranks)
    median = ranks[n // 2]
    mean = sum(ranks) / n
    print(f"  winners: {n}   rank → min {min(ranks)} / median {median} / "
          f"mean {mean:.1f} / max {max(ranks)}")
    print("  (rank 0 = tried first. Lower = the reorder front-loaded the winner = "
          "fewer wasted attempts.)")


# 4 ─────────────────────────────────────────────────────────────────────────
def graduation_efficiency(session) -> None:
    _h("4. GRADUATION EFFICIENCY  (is the repertoire growing?)")
    rows = session.execute(text(
        "SELECT status, count(*) n, "
        "  COALESCE(sum(n_attempts_total),0) attempts, "
        "  COALESCE(sum(n_valid_trials),0) valid "
        "FROM attack_strategies GROUP BY status ORDER BY 2 DESC"
    )).all()
    if not rows:
        print("  no attack_strategies rows.")
        return
    print(f"  {'status':<22}{'count':>6}{'attempts':>10}{'valid':>7}")
    for status, n, att, val in rows:
        print(f"  {str(status):<22}{n:>6}{att:>10}{val:>7}")


# 5 ─────────────────────────────────────────────────────────────────────────
def winner_model_vs_contextual(session, run_id: str | None) -> None:
    _h("5. WINNER-MODEL (ladder, order-biased) vs CONTEXTUAL MAP (full matrix) "
       "→ allocation bias")
    from rogue.reproduce.ladder_priors import (
        contextual_breach_rates,
        winning_model_distribution,
    )

    wins = winning_model_distribution(session, run_id=run_id)
    ctx = contextual_breach_rates(session)
    # collapse contextual map to per-model breach rate (trial-weighted).
    per_model: dict[str, list[int]] = {}
    for (model, _fam), stat in ctx.items():
        agg = per_model.setdefault(model, [0, 0])
        agg[0] += stat.breaches
        agg[1] += stat.trials
    total_wins = sum(wins.values()) or 1
    models = sorted(set(wins) | set(per_model), key=lambda m: -wins.get(m, 0))
    print(f"  {'model':<34}{'ladder win%':>12}{'unbiased breach%':>18}")
    for m in models:
        win_share = wins.get(m, 0) / total_wins
        b, t = per_model.get(m, [0, 0])
        unbiased = b / t if t else 0.0
        print(f"  {m[-34:]:<34}{win_share:>11.0%}{unbiased:>17.0%}")
    print("\n  Δ(ladder win-share − unbiased rate) ≈ early-stop ALLOCATION BIAS "
          "(config order over-credits earlier models).")


# 6 ─────────────────────────────────────────────────────────────────────────
def _num(line: str, key: str) -> float | None:
    """Pull the number after ``key`` (handles ``key=$1.23``, ``key=8``, ``key=12]``)."""
    import re
    m = re.search(re.escape(key) + r"=\$?([0-9.]+)", line)
    return float(m.group(1)) if m else None


def cost_per_breach(session, run_id: str | None, log_path: str | None) -> None:
    _h("6. COST-PER-BREACH  (baseline vs escalation — NOT conflated)")
    # The `done:` summary line is authoritative: est_cost, escalation_spend,
    # escalation_breaches, and the baseline verdict mix all in one place.
    done = None
    if log_path and Path(log_path).exists():
        for line in reversed(Path(log_path).read_text(errors="ignore").splitlines()):
            if "done:" in line and "escalation_spend" in line:
                done = line
                break
    if not done:
        print("  no `done:` summary line found in the log — run to completion first.")
        return
    total = _num(done, "est_cost")
    esc_spend = _num(done, "escalation_spend")
    esc_breaches = _num(done, "escalation_breaches")
    full = _num(done, "full_breach") or 0
    partial = _num(done, "partial_breach") or 0
    base_breaches = full + partial          # baseline any-breach cells
    base_spend = (total - esc_spend) if (total and esc_spend is not None) else None

    print("  ── ESCALATION (the adaptive-allocation layer) ──")
    if esc_spend is not None and esc_breaches:
        print(f"    spend ${esc_spend:.2f} / {esc_breaches:.0f} breaches "
              f"= ${esc_spend / esc_breaches:.2f} per escalation breach")
    print("  ── BASELINE (full reproduction matrix) ──")
    if base_spend is not None and base_breaches:
        print(f"    spend ${base_spend:.2f} / {base_breaches:.0f} breaches "
              f"(full+partial) = ${base_spend / base_breaches:.2f} per baseline breach")
    print(f"  ── TOTAL ${total:.2f} across {base_breaches:.0f} baseline + "
          f"{esc_breaches:.0f} escalation breaches ──")
    print("  (escalation cost-per-breach is the metric to watch across reorder modes; "
          "baseline cost is fixed sweep overhead.)")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-id", default=None, help="scope run-specific sections")
    p.add_argument("--log", default="/tmp/rogue_sweep.log",
                   help="sweep log for the est_cost line (section 6)")
    args = p.parse_args()
    s = _db()
    try:
        reachability_vs_value(s)
        starvation_distribution(s, args.run_id)
        rank_of_winner(s, args.run_id)
        graduation_efficiency(s)
        winner_model_vs_contextual(s, args.run_id)
        cost_per_breach(s, args.run_id, args.log)
    finally:
        s.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
