#!/usr/bin/env python
"""Run a command under a hard WALL-CLOCK deadline — kill it on overrun.

Belt-and-suspenders for paid runs. The first line of defense is per-request
network timeouts on every provider client (planner / target panel / judge, all
90s + bounded retries, added 2026-06-03 after a request hung a run ~8h). This
wrapper is the second: even if many calls each time out and retry, the WHOLE run
can't exceed ``seconds`` — it gets SIGTERM, then SIGKILL if it ignores that.

Usage::

    uv run python scripts/ops/run_with_deadline.py 5400 uv run python scripts/reproduce/reproduce_once.py --escalate ...

Exit codes: the child's own code on clean finish; 124 on deadline kill.
"""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    if len(sys.argv) < 3:
        raise SystemExit("usage: run_with_deadline.py <seconds> <cmd> [args...]")
    deadline = float(sys.argv[1])
    cmd = sys.argv[2:]
    print(f"[run_with_deadline] launching with a {deadline:.0f}s wall-clock cap: "
          f"{' '.join(cmd)}", flush=True)
    proc = subprocess.Popen(cmd)
    try:
        return proc.wait(timeout=deadline)
    except subprocess.TimeoutExpired:
        print(f"\n[run_with_deadline] DEADLINE {deadline:.0f}s EXCEEDED — terminating "
              "child (SIGTERM)", file=sys.stderr, flush=True)
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            print("[run_with_deadline] child ignored SIGTERM — SIGKILL",
                  file=sys.stderr, flush=True)
            proc.kill()
        return 124


if __name__ == "__main__":
    raise SystemExit(main())
