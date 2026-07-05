#!/usr/bin/env python3
"""Paired significance test for the load-bearing instruct-vs-abliterated alignment arm.

Reviewer ask (TMLR): at n=20, across-run t-intervals are weak for binomial data; report a
proper PAIRED test on the per-skill outcomes. This does exactly that, from the released
records (no model calls): for each of the 20 canary skills it pairs the recovery rate
(recovered runs / 3) under Llama-3.1-8B-Instruct vs its abliterated twin, and runs

  (1) an exact-ish sign-flip PERMUTATION test on the 20 per-skill rate differences
      (the pairing is by skill; under H0 the instruct/abliterated label is exchangeable
      within each skill, so flipping the sign of d_i is the null), and
  (2) a Wilcoxon signed-rank test as a distribution-free cross-check.

Run for the primary pack (tint) and the disjoint second pack (packB). Deterministic
(fixed enumeration / seed) so the printed p-values are reproducible.

Usage:  uv run python scripts/memory/paired_alignment_test.py
"""
from __future__ import annotations

import json
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "research"
CANARIES = ROOT / "tests" / "fixtures" / "memory" / "leakage_canaries.json"

INSTRUCT = "NousResearch/Meta-Llama-3.1-8B-Instruct"
ABLITERATED = "mlabonne/Meta-Llama-3.1-8B-Instruct-abliterated"


def _universe(path: Path = CANARIES) -> list[str]:
    return [r["skill_id"] for r in json.loads(Path(path).read_text())]


def _rates(path: Path, model: str, skills: list[str], runs: int) -> dict[str, float]:
    rec = next(r for r in json.loads(path.read_text())["results"] if r["model"] == model)
    freq = rec.get("canary_recovery_freq", {})
    n = rec.get("runs", runs)
    return {s: freq.get(s, 0) / n for s in skills}


def _wilcoxon_p(diffs: list[float]) -> float:
    """Two-sided Wilcoxon signed-rank, normal approximation with continuity correction."""
    import math
    nz = [d for d in diffs if d != 0]
    n = len(nz)
    if n == 0:
        return 1.0
    order = sorted(range(n), key=lambda i: abs(nz[i]))
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(nz[order[j + 1]]) == abs(nz[order[i]]):
            j += 1
        avg = (i + 1 + j + 1) / 2
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    w_plus = sum(ranks[i] for i in range(n) if nz[i] > 0)
    mu = n * (n + 1) / 4
    sigma = math.sqrt(n * (n + 1) * (2 * n + 1) / 24)
    if sigma == 0:
        return 1.0
    z = (abs(w_plus - mu) - 0.5) / sigma
    return math.erfc(z / math.sqrt(2))  # two-sided


def _signflip_p(diffs: list[float]) -> tuple[float, str]:
    """Two-sided paired sign-flip permutation test on the per-skill differences.

    Exact full enumeration of 2^k sign assignments over the k nonzero pairs (k<=20 here,
    so 2^k is tractable); zeros contribute nothing to the statistic under any flip.
    """
    nz = [d for d in diffs if d != 0]
    k = len(nz)
    obs = abs(sum(diffs))
    if k == 0:
        return 1.0, "no nonzero pairs"
    if k <= 22:  # 2^22 ~ 4M, exact full enumeration is tractable
        ge = 0
        total = 0
        base = 0.0  # ties contribute 0 to the statistic
        for signs in product((1, -1), repeat=k):
            stat = abs(base + sum(s * v for s, v in zip(signs, nz)))
            ge += stat >= obs - 1e-12
            total += 1
        return ge / total, f"exact, 2^{k} flips"
    # Large k (e.g. the N=100 panel): exact 2^k is infeasible, so sample the sign-flip
    # null with a FIXED seed (deterministic, reproducible). Add-one estimator (ge+1)/(B+1)
    # so the p-value is never an impossible 0.
    import random
    rng = random.Random(0)
    B = 200_000
    ge = 0
    for _ in range(B):
        stat = abs(sum((v if rng.random() < 0.5 else -v) for v in nz))
        ge += stat >= obs - 1e-12
    return (ge + 1) / (B + 1), f"sampled, {B} flips (k={k}, seed=0)"


def run(tag: str, path: Path, aligned: str = INSTRUCT, less_aligned: str = ABLITERATED,
        canaries: Path = CANARIES) -> None:
    skills = _universe(canaries)
    ins = _rates(path, aligned, skills, 3)
    abl = _rates(path, less_aligned, skills, 3)
    diffs = [abl[s] - ins[s] for s in skills]  # >0 means the less-aligned model leaks more
    mean_d = sum(diffs) / len(diffs)
    n_abl_more = sum(d > 0 for d in diffs)
    n_ins_more = sum(d < 0 for d in diffs)
    n_tie = sum(d == 0 for d in diffs)
    p_perm, how = _signflip_p(diffs)
    p_wil = _wilcoxon_p(diffs)
    print(f"\n== {tag} ({path.name}) ==")
    print(f"  paired skills: {len(skills)}   mean per-skill rate diff (abl - instruct): {mean_d:+.3f}")
    print(f"  skills where abliterated leaks more / fewer / tie: {n_abl_more} / {n_ins_more} / {n_tie}")
    print(f"  sign-flip permutation test ({how}): p = {p_perm:.4g}")
    print(f"  Wilcoxon signed-rank (normal approx, two-sided):  p = {p_wil:.4g}")


def main() -> int:
    run("primary pack (Featherless, instruct vs abliterated, 8B)",
        DATA / "skill_leak_tint_2026-06-16.json")
    run("disjoint second pack (packB, Featherless, 8B)",
        DATA / "skill_leak_packB_llama_3run.json")
    run("second-provider check (OpenRouter, Llama-3.1-70B instruct vs Hermes-3 permissive)",
        DATA / "skill_leak_alignment_or.json",
        aligned="meta-llama/llama-3.1-70b-instruct",
        less_aligned="nousresearch/hermes-3-llama-3.1-70b")
    run("recency check (OpenRouter, Llama-3.1-70B instruct vs Hermes-4 permissive, Aug 2025)",
        DATA / "skill_leak_hermes4_or.json",
        aligned="meta-llama/llama-3.1-70b-instruct",
        less_aligned="nousresearch/hermes-4-70b")
    # Powered panel: N=100 REAL-doc canaries (20 bundled + 18 distilled + 62 crawled upstream
    # SKILL.md), same Llama-3.1-70B base, alignment varied. Lifts the paired test off n=20.
    N100 = ROOT / "tests" / "fixtures" / "memory" / "leakage_canaries_n100.json"
    run("POWERED panel N=100 (OpenRouter, Llama-3.1-70B instruct vs Hermes-3 permissive)",
        DATA / "skill_leak_alignment_n100_2026-06-28.json",
        aligned="meta-llama/llama-3.1-70b-instruct",
        less_aligned="nousresearch/hermes-3-llama-3.1-70b", canaries=N100)
    run("POWERED panel N=100 (OpenRouter, Llama-3.1-70B instruct vs Hermes-4 permissive)",
        DATA / "skill_leak_alignment_n100_2026-06-28.json",
        aligned="meta-llama/llama-3.1-70b-instruct",
        less_aligned="nousresearch/hermes-4-70b", canaries=N100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
