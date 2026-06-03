#!/usr/bin/env python
"""Track the `needs_implementation` backlog over time — the 3b-v2 trigger metric.

The decision to build 3b-v2 (renderer discovery/synthesis) is gated NOT on the
absolute backlog (currently 7) but on its GROWTH RATE across harvest cycles
(Soren 2026-06-04): 7→8→9 keeps 3b parked; 7→12→18 makes it inevitable. This
appends one timestamped snapshot per call to `data/backlog_history.csv` (append-
only, $0, read-only on the corpus). `snapshot()` is called automatically at the
end of every `harvest_once` run (the only time the backlog can change), so the
time series builds itself — no cron, no timer.

    uv run python scripts/track_backlog.py            # take a snapshot now
    uv run python scripts/track_backlog.py --show     # print the trend, no new row
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

HISTORY = _ROOT / "data" / "backlog_history.csv"
_FIELDS = ["ts", "run_id", "needs_implementation", "audio", "image",
           "candidate", "active", "total_strategies"]


def _counts(database_url: str | None = None) -> dict[str, int]:
    from dotenv import load_dotenv
    from sqlalchemy import create_engine, text
    load_dotenv(str(_ROOT / ".env"))
    url = database_url or os.environ["DATABASE_URL"]
    with create_engine(url).connect() as c:
        def scal(q: str) -> int:
            return c.execute(text(q)).scalar() or 0
        ni = "WHERE status='needs_implementation'"
        return {
            "needs_implementation": scal(f"SELECT count(*) FROM attack_strategies {ni}"),
            "audio": scal(f"SELECT count(*) FROM attack_strategies {ni} AND modality='audio'"),
            "image": scal(f"SELECT count(*) FROM attack_strategies {ni} AND modality='image'"),
            "candidate": scal("SELECT count(*) FROM attack_strategies WHERE status='candidate'"),
            "active": scal("SELECT count(*) FROM attack_strategies WHERE status='active'"),
            "total_strategies": scal("SELECT count(*) FROM attack_strategies"),
        }


def snapshot(database_url: str | None = None, run_id: str = "", ts: str = "") -> dict[str, int]:
    """Append one backlog snapshot. ``ts`` should be passed by the caller (the
    harvest run already has a UTC timestamp) — this module never calls now()
    itself so it stays import-safe and deterministic-friendly. Best-effort: a
    failure here must never break the harvest, so callers wrap in try/except."""
    c = _counts(database_url)
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    new = not HISTORY.exists()
    with HISTORY.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=_FIELDS)
        if new:
            w.writeheader()
        w.writerow({"ts": ts, "run_id": run_id, **c})
    return c


def _show() -> None:
    if not HISTORY.exists():
        print("no history yet — run a harvest (or `track_backlog.py`) to seed it.")
        return
    rows = list(csv.DictReader(HISTORY.open()))
    print(f"{'timestamp':20} {'needs_impl':>10} {'(audio/image)':>14} {'candidate':>10} {'active':>7}")
    prev = None
    for r in rows:
        ni = int(r["needs_implementation"])
        delta = f"  ({ni - prev:+d})" if prev is not None else ""
        print(f"{r['ts'][:19]:20} {ni:>10}{delta:7} {r['audio']+'/'+r['image']:>10} "
              f"{r['candidate']:>10} {r['active']:>7}")
        prev = ni
    if len(rows) >= 3:
        series = [int(r["needs_implementation"]) for r in rows]
        recent = series[-3:]
        trend = ("GROWING → 3b-v2 trigger approaching" if recent[-1] - recent[0] >= 4
                 else "flat/slow → 3b stays parked" if recent[-1] - recent[0] <= 1
                 else "watch")
        print(f"\n  last-3 trend: {recent}  →  {trend}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--show", action="store_true", help="print the trend, take no snapshot")
    ap.add_argument("--run-id", default="manual")
    args = ap.parse_args()
    if args.show:
        _show()
        return 0
    # a manual snapshot: stamp it from the OS clock here (CLI entry only, never the lib path)
    import datetime
    c = snapshot(run_id=args.run_id, ts=datetime.datetime.now(datetime.timezone.utc).isoformat())
    print(f"snapshot: needs_implementation={c['needs_implementation']} "
          f"(audio={c['audio']} image={c['image']})  → {HISTORY.relative_to(_ROOT)}")
    _show()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
