#!/usr/bin/env python
"""§10.10 Growth Scheduler — decide growth vs canonical for the next sweep, then
optionally dispatch it. Turns "should I run a growth sweep?" from a human call into
a deterministic, schedulable system decision.

Default is DECIDE-AND-REPORT (read-only, $0): it prints the verdict and the exact
command it would run. Pass ``--run`` to actually dispatch — that is the only path
that spends money. To make growth automatic, wire ``--run`` into cron, e.g. daily::

    GROWTH_MIN_POOL=5 GROWTH_MIN_AGE_DAYS=7 \\
      uv run python scripts/growth_scheduler.py --run --primitive-limit 40 --max-spend 28

The scheduler self-regulates: a growth sweep graduates candidates, draining the pool
below the threshold, so it reverts to canonical until harvesting refills it.

Usage::

    uv run python scripts/growth_scheduler.py                 # decide + report ($0)
    uv run python scripts/growth_scheduler.py --run           # decide + dispatch ($)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from rogue.reproduce.growth_scheduler import decide_sweep_mode  # noqa: E402


def _growth_cmd(d, *, limit: int, spend: float, run_id: str) -> list[str]:
    # growth_sweep.sh encodes the bundle (sets CAND_LADDER_CAP, order, locks quota=K).
    env_run_id = run_id
    return ["env", f"RUN_ID={env_run_id}", "scripts/growth_sweep.sh",
            str(d.K), str(limit), str(spend)]


def _canonical_cmd(*, limit: int, spend: float, run_id: str) -> list[str]:
    # canonical mode = the default reproduce_once (K=3, quota=0, canonical order),
    # behind the wall-clock watchdog for parity.
    return [
        "uv", "run", "python", "scripts/run_with_deadline.py", "14400",
        "uv", "run", "python", "scripts/reproduce_once.py",
        "--escalate", "--primitive-limit", str(limit), "--n-trials", "1",
        "--escalate-max-spend", str(spend), "--escalate-n-trials", "1",
        "--run-id", run_id,
    ]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", action="store_true",
                   help="dispatch the chosen mode (SPENDS money for growth). Default: report only.")
    p.add_argument("--primitive-limit", type=int, default=40)
    p.add_argument("--max-spend", type=float, default=28.0)
    p.add_argument("--min-pool", type=int, default=None, help="override GROWTH_MIN_POOL")
    p.add_argument("--min-age-days", type=float, default=None, help="override GROWTH_MIN_AGE_DAYS")
    args = p.parse_args()

    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")
    session = sessionmaker(bind=create_engine(url))()
    now = datetime.now(timezone.utc)
    kw = {}
    if args.min_pool is not None:
        kw["min_pool"] = args.min_pool
    if args.min_age_days is not None:
        kw["min_age_days"] = args.min_age_days
    try:
        d = decide_sweep_mode(session, now=now, **kw)
    finally:
        session.close()

    stamp = int(now.timestamp())
    run_id = f"{d.mode}_K{d.K}_{stamp}"
    cmd = (_growth_cmd(d, limit=args.primitive_limit, spend=args.max_spend, run_id=run_id)
           if d.is_growth
           else _canonical_cmd(limit=args.primitive_limit, spend=args.max_spend, run_id=run_id))

    print(f"\n  Growth Scheduler decision: {d.mode.upper()}")
    print(f"    reason:         {d.reason}")
    print(f"    candidate pool: {d.candidate_pool}  (avg age {d.avg_age_days:.1f}d)")
    print(f"    bundle:         K={d.K}  quota={d.quota}  order={d.order}")
    print(f"    run_id:         {run_id}")
    print(f"    command:        {' '.join(cmd)}")

    if not args.run:
        print("\n  (report only — pass --run to dispatch; growth spends ~$30)")
        return 0

    print(f"\n  >>> dispatching {d.mode} mode...")
    return subprocess.call(cmd, cwd=str(_ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
