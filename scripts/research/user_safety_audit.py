#!/usr/bin/env python
"""User-specific safety audit — does a deployment apply the right safety standard for a VULNERABLE user?
The wired entry for `user_safety` (U-SafeBench 2502.15086).

Injects a vulnerable-user profile into the deployment context, fires profile-unsafe + profile-safe
instructions, and reports safety_rate (refuse the harmful-for-this-user asks) + helpfulness_rate
(don't over-refuse the benign ones).

Usage:
    uv run python scripts/research/user_safety_audit.py            # $0 mock (reckless target)
    uv run python scripts/research/user_safety_audit.py --live     # probe the live demo target
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from rogue.reproduce.agent.user_safety import UserSafetyProbe, run_user_safety_stage  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "user_safety" / "user_safety_probes.json"


def _load() -> list[UserSafetyProbe]:
    data = json.loads(FIXTURE.read_text())
    return [UserSafetyProbe(p["profile"], p["instruction"], p["profile_unsafe"]) for p in data["probes"]]


class _MockTarget:
    class _R:
        def __init__(self, c):
            self.content, self.cost_usd, self.error = c, 0.0, None

    async def run_attack(self, rendered, config, temperature=0.7, n_trials=1):
        q = [m for m in rendered.messages if m["role"] == "user"][-1]["content"].lower()
        if any(w in q for w in ("lethal", "liquor", "fasting", "casino")):
            return [self._R("Sure, here's what you asked for ...")]  # the U-SafeBench failure mode
        return [self._R("Here are some supportive, healthy suggestions ...")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true", help="probe the live demo target (else a mock)")
    args = ap.parse_args(argv)

    probes = _load()
    if args.live:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=str(ROOT / ".env"))
        from rogue.reproduce.target_panel import TargetPanel
        from rogue.schemas import demo_deployment_configs
        panel, cfg = TargetPanel(), demo_deployment_configs()[0]
    else:
        from rogue.schemas import demo_deployment_configs
        panel, cfg = _MockTarget(), demo_deployment_configs()[0]

    res = asyncio.run(run_user_safety_stage(probes, cfg, panel=panel))
    s = res.score
    tag = "live" if args.live else "mock ($0)"
    print(f"\nUser-specific safety audit [{tag}]  cost=${res.cost_usd:.4f}")
    print(f"  safety_rate      = {s.safety_rate}  (want ~1.0 — refuse the {s.n_unsafe} harmful-for-user asks)")
    print(f"  helpfulness_rate = {s.helpfulness_rate}  (want ~1.0 — fulfill the {s.n_safe} benign controls)")
    if s.unsafe_fulfilled:
        print("  ⚠️  FULFILLED harmful-for-user requests:")
        for i in s.unsafe_fulfilled:
            print(f"       - {i[:80]}")
    if s.safe_refused:
        print(f"  over-refused (benign): {len(s.safe_refused)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
