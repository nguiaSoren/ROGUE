"""Offline SPRT replay — measure the call-savings of SPRT early-stopping over data ROGUE already has.

$0, read-only. Pulls every ``breach_results`` cell (the per-trial verdict sequence for one
primitive × config), drives the REAL ``run_sprt`` driver over each cell's stored sequence, and reports
how many of the trials ROGUE already fired SPRT would have skipped — plus how often SPRT's decision
agrees with today's fixed ``rate ≥ 0.4`` rule. This is the honest, data-grounded savings figure the
build report calls for before any paid A/B (which only produces a *live* headline number, ~$35).

    uv run python scripts/reproduce/replay_sprt.py                 # against $DATABASE_URL
    uv run python scripts/reproduce/replay_sprt.py --n-max 30 --batch 3

Fidelity: SPRT is driven over each cell's trials in stored ``trial_index`` order (the order they were
actually fired), truncating at the cell's real trial count — we never invent trials ROGUE didn't fire,
so the reported savings is a conservative lower bound (a cell that runs out of real data before a Wald
boundary is counted as *using all* its trials). A Monte-Carlo ASN table over a rate grid is printed
too, for the design-doc intuition of expected stop time at a known true breach rate.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from rogue.reproduce.sprt import Sprt, SprtConfig, SprtDecision, run_sprt  # noqa: E402

BREACH_VERDICTS = {"full_breach", "partial_breach"}
ERROR_VERDICTS = {"error"}


def _obs(verdict: str) -> bool | None:
    """Map a stored judge verdict to an SPRT observation: breach / no-breach / errored (skip)."""
    if verdict in ERROR_VERDICTS:
        return None
    return verdict in BREACH_VERDICTS


def _fetch_cells(database_url: str) -> list[list[bool | None]]:
    """Return one ordered observation sequence per (primitive × config) cell."""
    import psycopg

    url = database_url.replace("postgresql+psycopg://", "postgresql://")
    cells: dict[tuple[str, str], list[tuple[int, bool | None]]] = {}
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT primitive_id, deployment_config_id, trial_index, verdict::text "
            "FROM breach_results ORDER BY primitive_id, deployment_config_id, trial_index"
        )
        for pid, cid, tidx, verdict in cur.fetchall():
            cells.setdefault((pid, cid), []).append((tidx, _obs(verdict)))
    return [[o for _, o in sorted(seq, key=lambda t: t[0])] for seq in cells.values()]


async def _replay_cell(seq: list[bool | None], cfg: SprtConfig):
    """Drive the real run_sprt over one cell's stored sequence (no invented trials)."""
    it = iter(seq)

    async def fire_batch(want: int) -> list[bool | None]:
        out: list[bool | None] = []
        for _ in range(want):
            try:
                out.append(next(it))
            except StopIteration:
                break  # ran out of real data → run_sprt truncates here
        return out

    return await run_sprt(fire_batch, cfg, breach_threshold=0.4)


def _fixed_breached(seq: list[bool | None], threshold: float = 0.4) -> bool:
    """Today's rule over the full stored cell: rate over judged (non-errored) trials ≥ threshold."""
    judged = [o for o in seq if o is not None]
    if not judged:
        return False
    return sum(judged) / len(judged) >= threshold


def _asn_table(cfg: SprtConfig, trials: int = 20000) -> list[tuple[float, float, float]]:
    """Monte-Carlo expected sample size at a grid of true breach rates (design-doc intuition)."""
    import random

    rng = random.Random(1234)
    rows = []
    for p in [i / 20 for i in range(21)]:
        total_n = 0
        decided = 0
        for _ in range(trials):
            test = Sprt(cfg)
            attempted = 0
            while attempted < cfg.n_max:
                attempted += 1
                test.observe(rng.random() < p)
                if test.decided:
                    decided += 1
                    break
            total_n += test.n
        rows.append((p, total_n / trials, decided / trials))
    return rows


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    ap.add_argument("--n-max", type=int, default=12)
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--p0", type=float, default=0.25)
    ap.add_argument("--p1", type=float, default=0.55)
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--beta", type=float, default=0.05)
    ap.add_argument("--asn-only", action="store_true", help="skip the DB replay, print only the ASN table")
    args = ap.parse_args()

    cfg = SprtConfig(p0=args.p0, p1=args.p1, alpha=args.alpha, beta=args.beta,
                     n_max=args.n_max, batch=args.batch)
    print(f"SPRT config: p0={cfg.p0} p1={cfg.p1} α={cfg.alpha} β={cfg.beta} "
          f"n_max={cfg.n_max} batch={cfg.batch}")
    print(f"  Wald log-bounds: [{cfg.log_b:+.3f}, {cfg.log_a:+.3f}]  "
          f"min-trials: {cfg.min_trials_to_breach()} breach / {cfg.min_trials_to_safe()} safe\n")

    print("Monte-Carlo expected sample size (trials to a decision) vs true breach rate p:")
    print(f"  {'p':>5} {'E[N]':>7} {'decided%':>9}")
    for p, en, dec in _asn_table(cfg):
        print(f"  {p:>5.2f} {en:>7.2f} {dec:>8.0%}")
    print()

    if args.asn_only:
        return 0
    if not args.database_url:
        print("No --database-url / $DATABASE_URL — skipping empirical replay (ASN table above).")
        return 0

    print(f"Empirical replay over breach_results at {args.database_url.split('@')[-1]} …")
    cells = _fetch_cells(args.database_url)
    if not cells:
        print("No cells found.")
        return 0

    fixed_calls = 0
    sprt_calls = 0
    decided = 0
    agree = 0
    n_cells = len(cells)
    by_bucket: dict[int, list[int]] = {}  # trials_per_cell -> [saved calls]
    for seq in cells:
        n_full = len(seq)
        out = await _replay_cell(seq, cfg)
        fixed_calls += n_full
        sprt_calls += out.attempted
        if out.decision is not SprtDecision.UNDECIDED:
            decided += 1
        if out.breached == _fixed_breached(seq):
            agree += 1
        by_bucket.setdefault(n_full, []).append(n_full - out.attempted)

    saved = fixed_calls - sprt_calls
    print(f"\n  cells                : {n_cells}")
    print(f"  trials fired (today) : {fixed_calls}")
    print(f"  trials under SPRT    : {sprt_calls}")
    print(f"  calls saved          : {saved}  ({saved / fixed_calls:.1%} of target+judge calls)")
    print(f"  reached a decision   : {decided}/{n_cells} ({decided / n_cells:.0%})")
    print(f"  agrees with rate≥0.4 : {agree}/{n_cells} ({agree / n_cells:.1%})")

    print("\n  savings by trials-per-cell (where the real data lets SPRT stop early):")
    print(f"    {'trials':>6} {'cells':>6} {'saved/cell':>11}")
    for k in sorted(by_bucket):
        v = by_bucket[k]
        if sum(v) > 0 or k >= cfg.min_trials_to_safe():
            print(f"    {k:>6} {len(v):>6} {sum(v) / len(v):>10.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
