#!/usr/bin/env python3
"""Power simulation for growing the canary set (20 -> 40-50) on the instruct-vs-abliterated arm.

Free, no model calls: projects the paired sign-flip p-value at larger n FROM the existing
per-skill recovery-rate differences, so we can decide whether the (slow, Featherless) larger
run is worth it BEFORE spending the time.

Two parts, because the bootstrap alone is optimistic:
  (1) OPTIMISTIC bootstrap -- resample the 20 observed per-skill diffs with replacement up to
      n=40/45/50 and recompute the (two-sided sign-test) p. Since the primary pack's nonzero
      diffs are ALL one-directional, the resampled sets are too, so this is the best case: it
      assumes new canaries behave like the ones we've seen.
  (2) COUNTER-PAIR sensitivity -- the bootstrap cannot manufacture a counter-directional pair
      (a skill where instruct leaks and abliterated doesn't), and new canaries are exactly where
      one could appear. So we inject c=0..3 counter pairs at the expected discordant count and
      report how the p degrades. This is the downside the bootstrap hides.

For all-one-directional discordant pairs the exact two-sided sign-flip p is 2/2^k; with mixed
signs it is the two-sided sign test, which we compute exactly.

Usage:  uv run python scripts/memory/power_sim_canary.py
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

random.seed(0)
DATA = Path(__file__).resolve().parents[2] / "data" / "research"
CAN = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "memory" / "leakage_canaries.json"


def signtest_p(k: int, pos: int) -> float:
    """Two-sided sign test: k discordant pairs, `pos` in the majority direction."""
    if k == 0:
        return 1.0
    m = max(pos, k - pos)
    tail = sum(math.comb(k, j) for j in range(m, k + 1))
    return min(1.0, 2 * tail / 2 ** k)


def diffs(path: Path, aligned: str, less: str) -> list[float]:
    res = json.loads(path.read_text())["results"]
    skills = [r["skill_id"] for r in json.loads(CAN.read_text())]
    def rate(model):
        rec = next(r for r in res if r.get("canonical_id") == model or r["model"] == model)
        f = rec.get("canary_recovery_freq", {}); n = rec["runs"]
        return {s: f.get(s, 0) / n for s in skills}
    a, l = rate(aligned), rate(less)
    return [l[s] - a[s] for s in skills]


def analyse(tag: str, d: list[float]) -> None:
    nz = [x for x in d if x != 0]
    k0, pos0 = len(nz), sum(x > 0 for x in nz)
    p_disc = k0 / len(d)
    print(f"\n== {tag} ==")
    print(f"  observed: {len(d)} skills, {k0} discordant ({pos0} one-directional), p = {signtest_p(k0, pos0):.4g}")
    print(f"  (1) OPTIMISTIC bootstrap -- assumes new canaries behave like observed:")
    B = 20000
    for n in (40, 45, 50):
        ps = []
        for _ in range(B):
            samp = [random.choice(d) for _ in range(n)]
            snz = [x for x in samp if x != 0]
            ps.append(signtest_p(len(snz), sum(x > 0 for x in snz)))
        ps.sort()
        med = ps[B // 2]
        lo, hi = ps[int(B * .05)], ps[int(B * .95)]
        print(f"     n={n}: median p={med:.2g}  90%-spread[{lo:.2g},{hi:.2g}]  "
              f"P(p<0.01)={sum(x < .01 for x in ps)/B:.2f}  P(p<0.05)={sum(x < .05 for x in ps)/B:.2f}")
    k45 = round(45 * p_disc)
    print(f"  (2) COUNTER-PAIR sensitivity at n=45 (expected ~{k45} discordant), the bootstrap can't see:")
    for c in range(0, 4):
        print(f"     {c} counter-directional of {k45}: p = {signtest_p(k45, k45 - c):.3g}")


def main() -> int:
    analyse("primary pack (8B instruct vs abliterated) -- the p=0.031 everything routes through",
            diffs(DATA / "skill_leak_tint_2026-06-16.json",
                  "meta-llama/Llama-3.1-8B-Instruct", "mlabonne/Meta-Llama-3.1-8B-Instruct-abliterated"))
    analyse("disjoint second pack (packB) -- already has 1 counter-pair",
            diffs(DATA / "skill_leak_packB_llama_3run.json",
                  "meta-llama/Llama-3.1-8B-Instruct", "mlabonne/Meta-Llama-3.1-8B-Instruct-abliterated"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
