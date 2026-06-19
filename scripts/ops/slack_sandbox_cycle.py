"""Ops CLI: fire ONE sandbox red-team cycle at every registered Slack agent (build-area 06 §3).

After a harvest/reproduce run lands new attack primitives, this fans a *repertoire* scan across
every registered Slack agent that has at least one newly-landed family (`discovered_at >= --since`),
aiming this cycle's newly-landed selection at each agent's own deployed configuration through its
`base_url`. It is the deliberate enqueue step of the continuous-red-team loop — `run_sandbox_cycle`
calls `ScanService.create_scan`, which only WRITES the scan record + enqueues a job; the worker runs
the scan later. Nothing is executed inline here.

  ⚠️  COSTLY — DELIBERATE INVOCATION ONLY. Each enqueued scan, when the worker actually runs it,
  makes real downstream calls: the target Slack-agent endpoint + judge-LLM calls = real money, and
  it WRITES to the live DB. This is "invoked after a harvest/reproduce run completes" — chained, not
  timed. NEVER run it on a loop / timer / cron. Run it by hand, once per cycle.

Run from the repo root against the target deployment's `DATABASE_URL`::

    # all orgs, default since = now − 24h
    uv run python scripts/ops/slack_sandbox_cycle.py

    # one org, explicit cutoff
    uv run python scripts/ops/slack_sandbox_cycle.py --org org_123 \
        --since 2026-06-09T00:00:00Z --max-tests 50 --n-trials 1

Requires `SECRET_ENCRYPTION_KEY` (see `src/rogue/platform/secrets.py`): the durable scan path persists
the target spec and fails closed without an encryption key, so the command refuses to run without it.

This connects to a real database ONLY when a human runs `main()` against `DATABASE_URL`. Importing the
module (or calling its functions with injected fakes) opens no connection and builds no engine.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Defensive `src/` insert so the script runs even without the editable install on path.
_SRC = str(Path(__file__).resolve().parents[2] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


def _parse_since(raw: str) -> datetime:
    """Parse an ISO-8601 timestamp to a tz-aware UTC datetime (a bare/naive stamp is read as UTC)."""
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fire one sandbox red-team cycle at every registered Slack agent. COSTLY — deliberate "
            "invocation only, never on a loop/timer/cron."
        )
    )
    parser.add_argument(
        "--org",
        default=None,
        help="Organization id to fan across (default: all orgs).",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="ISO-8601 cutoff; newly-landed = discovered_at >= since (default: now − 24h).",
    )
    parser.add_argument(
        "--max-tests",
        type=int,
        default=50,
        help="Per-scan max_tests floor (default: 50).",
    )
    parser.add_argument(
        "--n-trials",
        type=int,
        default=1,
        help="Trials per attack (default: 1).",
    )
    args = parser.parse_args(argv)

    since = _parse_since(args.since) if args.since else datetime.now(timezone.utc) - timedelta(hours=24)

    # Imports live inside main() so importing this module opens no DB connection / engine.
    from rogue.integrations.slack import run_sandbox_cycle
    from rogue.integrations.slack.agent_store import build_postgres_slack_agent_store
    from rogue.platform.queue import build_postgres_job_queue
    from rogue.platform.scan_service import DefaultScanService
    from rogue.platform.secrets import build_postgres_secret_store
    from rogue.platform.store import build_postgres_scan_store

    secret_store = build_postgres_secret_store()  # None unless SECRET_ENCRYPTION_KEY is set
    if secret_store is None:
        print(
            "error: set SECRET_ENCRYPTION_KEY — the durable scan path fails closed without it",
            file=sys.stderr,
        )
        return 1

    store = build_postgres_scan_store()  # lazy engine — no connection until used
    queue = build_postgres_job_queue()
    scan_service = DefaultScanService(
        store, queue, secret_store=secret_store, require_secret_store=True
    )
    agent_store = build_postgres_slack_agent_store(secret_store)

    records = asyncio.run(
        run_sandbox_cycle(
            args.org,
            agent_store=agent_store,
            scan_service=scan_service,
            since=since,
            max_tests=args.max_tests,
            n_trials=args.n_trials,
        )
    )

    scope = args.org or "ALL orgs"
    print(f"enqueued {len(records)} sandbox scan(s) for {scope} (since {since.isoformat()}):")
    for rec in records:
        print(f"  scan_id={rec.scan_id}  org={rec.org_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
