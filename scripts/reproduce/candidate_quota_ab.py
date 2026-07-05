#!/usr/bin/env python
"""Candidate-quota A/B — measure the reserved-exploration-slot's value.

Runs the SAME escalation sweep twice — ``quota=0`` (baseline; the Tier-1 image
renderers early-stop and starve candidates) vs ``quota=1`` (reserve one slot so a
harvested candidate is guaranteed an attempt) — then reads the ``ladder_attempts``
orchestration trace and prints the comparison. Because ``--primitive-limit N`` picks
the top-N primitives by reproducibility_score deterministically, both arms hit the
SAME parents, so the only varying factor is the scheduler policy.

This is the empirical baseline for the adaptive break-bandit scheduler.

Usage::

    # one command — run BOTH arms then analyze  (COSTS REAL MONEY: target+judge calls)
    uv run python scripts/reproduce/candidate_quota_ab.py run --limit 12 --max-spend 8

    # FREE — re-print the comparison from already-logged ladder_attempts (live DB)
    uv run python scripts/reproduce/candidate_quota_ab.py analyze
    uv run python scripts/reproduce/candidate_quota_ab.py analyze --run-prefix abq_1733180000

    # FREE — export the raw rows to a frozen CSV (run once when the DB is up), then
    # regenerate the comparison OFFLINE from that CSV with no database:
    uv run python scripts/reproduce/candidate_quota_ab.py dump --out data/research/ladder_attempts_snapshot.csv
    uv run python scripts/reproduce/candidate_quota_ab.py analyze --from-dump data/research/ladder_attempts_snapshot.csv

⚠ The ``run`` mode spends real money and writes to the live Neon DB. It is never
run automatically — only when you invoke it. ``analyze`` and ``dump`` are read-only
and free; ``analyze --from-dump`` needs no database at all.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

# Surface run_reproduction's INFO logs (start / [progress] / escalation breach) —
# without this the run is silent because we call run_reproduction() directly
# rather than through reproduce_once's main(), which is where logging is set up.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

# Put the project root on sys.path so `scripts.*` (the escalation ladder) and
# `rogue.*` both import when run as a bare script.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# dotenv + sqlalchemy are imported lazily inside the DB-only helpers below, so the
# offline `analyze --from-dump` reproduction path runs on the Python standard library
# alone — no third-party install is needed to regenerate the headline 3/4/8 counts.


def _db_url() -> str:
    from dotenv import load_dotenv
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set (check .env)")
    return url


async def _run_arm(*, quota: int, run_id: str, limit: int, max_spend: float) -> None:
    from scripts.reproduce.reproduce_once import run_reproduction

    print(f"\n>>> A/B arm quota={quota}  run_id={run_id}  "
          f"(primitive-limit={limit}, max-spend=${max_spend})", flush=True)
    await run_reproduction(
        database_url=_db_url(),
        primitive_limit=limit,
        n_trials=1,
        temperature=0.7,
        concurrency=5,
        escalate=True,
        escalate_candidate_quota=quota,
        escalate_max_spend=max_spend,
        run_id=run_id,
    )


def run(args: argparse.Namespace) -> None:
    """Run both arms (quota=0 then quota=1), then analyze. Spends money."""
    stamp = f"abq_{int(time.time())}"
    sq = getattr(args, "single_quota", None)
    if sq is not None:
        asyncio.run(
            _run_arm(quota=sq, run_id=f"{stamp}_q{sq}", limit=args.limit,
                     max_spend=args.max_spend)
        )
        print(f"\n>>> single arm (quota={sq}) done. comparison (run-prefix {stamp}):")
        analyze(argparse.Namespace(run_prefix=stamp))
        return
    asyncio.run(
        _run_arm(quota=0, run_id=f"{stamp}_q0", limit=args.limit, max_spend=args.max_spend)
    )
    asyncio.run(
        _run_arm(quota=1, run_id=f"{stamp}_q1", limit=args.limit, max_spend=args.max_spend)
    )
    print(f"\n>>> both arms done. comparison (run-prefix {stamp}):")
    analyze(argparse.Namespace(run_prefix=stamp))


# The raw columns the comparison needs. Both the live-DB path and the offline
# dump path load exactly these, then aggregate in Python — one source of truth
# for the arithmetic and no SQL-dialect dependence, so a reviewer can regenerate
# the comparison from a frozen CSV with no database (analyze --from-dump).
_COLS = ["candidate_attempt_quota", "entity_type", "breached", "stopped_run",
         "technique_id", "run_id"]
_FETCH_SQL = "SELECT " + ", ".join(_COLS) + " FROM ladder_attempts"


def _rows_from_db(prefix: str | None) -> list[dict]:
    """Fetch the raw rows from the live DB (read-only). IPv4-forced fallback for
    Neon endpoints that resolve IPv6-only on hosts without an IPv6 route."""
    import socket
    from sqlalchemy import create_engine
    url = _db_url()
    try:
        eng = create_engine(url, connect_args={"connect_timeout": 20})
        with eng.connect() as c:
            return _select(c, prefix)
    except Exception:
        host = url.split("@")[-1].split("/")[0].split(":")[0]
        v4 = socket.getaddrinfo(host, 5432, socket.AF_INET)[0][4][0]
        eng = create_engine(url, connect_args={"hostaddr": v4, "connect_timeout": 20})
        with eng.connect() as c:
            return _select(c, prefix)
    finally:
        try:
            eng.dispose()
        except Exception:
            pass


def _select(c, prefix: str | None) -> list[dict]:
    from sqlalchemy import text
    where = " WHERE run_id LIKE :pfx" if prefix else ""
    params = {"pfx": f"{prefix}%"} if prefix else {}
    return [dict(r._mapping) for r in c.execute(text(_FETCH_SQL + where), params)]


def _rows_from_dump(path: str, prefix: str | None) -> list[dict]:
    """Load the frozen CSV dump — the offline, DB-free reproduction path."""
    import csv
    def _b(v): return str(v).strip().lower() in ("1", "true", "t")
    out = []
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            if prefix and not str(r.get("run_id", "")).startswith(prefix):
                continue
            r["breached"] = _b(r["breached"])
            r["stopped_run"] = _b(r["stopped_run"])
            try:
                r["candidate_attempt_quota"] = int(r["candidate_attempt_quota"])
            except (TypeError, ValueError, KeyError):
                pass
            out.append(r)
    return out


def _aggregate_and_print(rows: list[dict], prefix: str | None) -> None:
    """The single source of truth for the comparison arithmetic — used by both
    the live-DB and the offline-dump paths, so they cannot drift."""
    from collections import defaultdict
    print(f"\nladder_attempts rows: {len(rows)}"
          + (f"  (filtered to run-prefix '{prefix}')" if prefix else ""))

    by = defaultdict(lambda: {"attempts": 0, "breaches": 0, "early_stops": 0})
    for r in rows:
        a = by[(r["candidate_attempt_quota"], r["entity_type"])]
        a["attempts"] += 1
        a["breaches"] += 1 if r["breached"] else 0
        a["early_stops"] += 1 if r["stopped_run"] else 0
    print("\n── attempts by (quota × entity_type) ──")
    print(f"  {'quota':>5} {'entity':>10} {'attempts':>9} {'breaches':>9} "
          f"{'succ%':>6} {'early_stops':>11}")
    for k in sorted(by, key=lambda x: (x[0], str(x[1]))):
        a = by[k]
        rate = round(a["breaches"] / a["attempts"], 3) if a["attempts"] else 0.0
        print(f"  {k[0]:>5} {str(k[1]):>10} {a['attempts']:>9} {a['breaches']:>9} "
              f"{rate:>6.3f} {a['early_stops']:>11}")

    cand = defaultdict(lambda: {"attempts": 0, "breaches": 0, "tids": set(), "grad_tids": set()})
    for r in rows:
        if r["entity_type"] != "candidate":
            continue
        a = cand[r["candidate_attempt_quota"]]
        a["attempts"] += 1
        a["tids"].add(r.get("technique_id"))
        if r["breached"]:
            a["breaches"] += 1
            a["grad_tids"].add(r.get("technique_id"))  # a candidate graduates on its FIRST breach
    print("\n── candidate evaluation (the reserved-slot payoff) ──")
    print(f"  {'quota':>5} {'reached':>8} {'graduated':>10} {'attempts':>9} {'breaches':>9}")
    for q in sorted(cand):
        a = cand[q]
        # graduated == distinct candidates with >=1 breach (the headline metric);
        # reached == distinct candidates evaluated; attempts/breaches are row-level.
        print(f"  {q:>5} {len(a['tids']):>8} {len(a['grad_tids']):>10} {a['attempts']:>9} {a['breaches']:>9}")
    print("\nRead: greedy/quota=0 starves candidates (reached~0); a reserved slot "
          "lets candidates run and graduate. graduated = distinct candidates with "
          ">=1 breach (the headline metric); reached = distinct candidates evaluated.")


def analyze(args: argparse.Namespace) -> None:
    """Print the A/B comparison. Read-only and free. Source is the live DB by
    default, or a frozen CSV dump via --from-dump (no database — the offline
    reproduction path a reviewer uses to regenerate the numbers)."""
    prefix = getattr(args, "run_prefix", None)
    dump_path = getattr(args, "from_dump", None)
    rows = _rows_from_dump(dump_path, prefix) if dump_path else _rows_from_db(prefix)
    _aggregate_and_print(rows, prefix)


def dump(args: argparse.Namespace) -> None:
    """Export the raw ladder_attempts rows the comparison needs to a frozen CSV,
    so ``analyze --from-dump`` regenerates the numbers offline. Read-only on the
    DB; run once when the DB is reachable to produce the released artifact."""
    import csv
    raw = getattr(args, "run_prefix", None)
    prefixes = [p.strip() for p in raw.split(",")] if raw else [None]
    # The projection has no unique row key, so DO NOT dedup — identical projections
    # are genuinely distinct attempts and must all be kept for correct counts. The
    # prefixes are disjoint full run_ids, so no row is fetched twice.
    rows: list[dict] = []
    for pfx in prefixes:
        rows.extend(_rows_from_db(pfx))
    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in _COLS})
    print(f"wrote {len(rows)} rows → {args.out}"
          + (f"  (run-prefixes: {', '.join(p for p in prefixes if p)})" if raw else "  (all rows)"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="run BOTH arms then analyze (SPENDS MONEY)")
    pr.add_argument("--limit", type=int, default=12,
                    help="--primitive-limit for each arm (default 12)")
    pr.add_argument("--max-spend", type=float, default=8.0,
                    help="--escalate-max-spend per arm (default $8)")
    pr.add_argument("--single-quota", type=int, default=None,
                    help="run ONE arm at this quota (skip the q0/q1 pair). "
                         "Use when the baseline already exists and you want the "
                         "full budget on one treatment arm, e.g. --single-quota 3")
    pr.set_defaults(func=run)

    pa = sub.add_parser("analyze", help="print the comparison (FREE); use --from-dump <csv> for the offline DB-free path (reviewers), else live DB")
    pa.add_argument("--run-prefix", default=None,
                    help="restrict to a specific A/B (e.g. abq_1733180000)")
    pa.add_argument("--from-dump", default=None,
                    help="read a frozen ladder_attempts CSV instead of the live DB "
                         "(offline, DB-free reproduction)")
    pa.set_defaults(func=analyze)

    pdmp = sub.add_parser("dump", help="export raw ladder_attempts rows to a frozen CSV (FREE, read-only)")
    pdmp.add_argument("--out", required=True, help="output CSV path")
    pdmp.add_argument("--run-prefix", default=None,
                      help="restrict the export to a specific run prefix (default: all rows)")
    pdmp.set_defaults(func=dump)

    args = p.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
