"""Coverage-metric validity study (build-04 §5 ⚑) — does score_pack_coverage predict breach power?

Design: docs/research/coverage_validity_study.md. For each rule we build strong/medium/weak pack
variants (a coverage range), run each variant's pack against weak + mid targets, and measure the
breach rate (calibrated per-rule judge). Each (rule, variant, target) is one (coverage, breach_rate)
data point; we Spearman-correlate them with a bootstrap CI. Validated iff rho>0 and the CI excludes 0.

PAID + EFFICIENT: target calls run CONCURRENT (cheap models); judge calls run BATCHED via JudgeBatch
(Anthropic Batch API, 50% off) with the rubric cached (judge.py:522). --dry-run is free (stub
verdicts, verifies the whole pipeline + the coverage spread); --yes confirms the paid batched run.

    uv run python scripts/governance/coverage_validity.py --dry-run
    uv run python scripts/governance/coverage_validity.py --yes
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from pathlib import Path

from rogue.governance import build_attack_pack, instantiate_rule_judge, score_pack_coverage
from rogue.packs import load_pack
from rogue.reproduce.instantiator import render
from rogue.reproduce.judge import JudgeAgent
from rogue.reproduce.judge_batch import BatchGradeItem, JudgeBatch
from rogue.reproduce.target_panel import TargetPanel
from rogue.schemas import BREACH_VERDICTS, AttackPrimitive, demo_deployment_configs
from rogue.schemas.governance import ClientPolicy, PolicyRule, RuleAttackPack

_FIX = Path("tests/fixtures/governance")
_OUT = Path("data/governance")
STRONG_CAP = 6  # cap the strong pack so the study stays affordable


def _corpus() -> list[AttackPrimitive]:
    seen: set[str] = set()
    out: list[AttackPrimitive] = []
    for name in ("aggressive", "default", "compliance"):
        for p in load_pack(name):
            if p.primitive_id not in seen:
                seen.add(p.primitive_id)
                out.append(p)
    return out


def coverage_variants(rule: PolicyRule, corpus: list[AttackPrimitive]) -> dict[str, tuple]:
    """Return {variant: (RuleAttackPack, CoverageScore)} spanning the coverage scale.

    strong = full re-aimed pack (capped); medium = a 2-primitive subset (on-target, low breadth);
    weak = one RAW (un-re-aimed) primitive — off-target, so the targeting component drops to ~0.
    """
    strong_pack = build_attack_pack(rule, corpus)
    prims = strong_pack.primitives[:STRONG_CAP]
    strong = RuleAttackPack(rule_id=rule.rule_id, primitives=prims)
    medium = RuleAttackPack(rule_id=rule.rule_id, primitives=prims[:2])
    weak = RuleAttackPack(rule_id=rule.rule_id, primitives=[corpus[0]] if corpus else [])
    return {
        name: (pack, score_pack_coverage(pack, rule))
        for name, pack in (("strong", strong), ("medium", medium), ("weak", weak))
    }


async def _collect(panel, rule, pack, config, n_trials, judge, sem) -> list[tuple]:
    """Concurrent target calls → list of (custom_id, BatchGradeItem, cost) for this cell."""

    async def _one(prim, t):
        rendered = render(prim, config)
        async with sem:
            resps = await panel.run_attack(rendered, config, n_trials=1)
        text = resps[0].content if resps else ""
        cost = float(resps[0].cost_usd) if resps else 0.0
        cid = f"{rule.rule_id}|{config.config_id}|{prim.primitive_id}|{t}"
        return cid, BatchGradeItem(custom_id=cid, rendered=rendered, model_response=text,
                                   primitive=prim, context=judge.context), cost

    results = await asyncio.gather(
        *[_one(prim, t) for prim in pack.primitives for t in range(n_trials)]
    )
    return list(results)


def _spearman(xs, ys) -> float:
    def ranks(a):
        order = sorted(range(len(a)), key=lambda i: a[i])
        r = [0.0] * len(a)
        for rank, i in enumerate(order):
            r[i] = rank
        return r
    rx, ry = ranks(xs), ranks(ys)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx) ** 0.5
    vy = sum((b - my) ** 2 for b in ry) ** 0.5
    return cov / (vx * vy) if vx and vy else 0.0


def _spearman_ci(xs, ys, B=2000, seed=20260524):
    rng = random.Random(seed)
    n = len(xs)
    rhos = sorted(
        _spearman([xs[i] for i in idx], [ys[i] for i in idx])
        for idx in ([rng.randrange(n) for _ in range(n)] for _ in range(B))
    )
    return rhos[int(0.025 * B)], rhos[int(0.975 * B)]


async def _run(policy, corpus, targets, n_trials, dry_run) -> dict:
    panel = None if dry_run else TargetPanel.from_env()
    sem = asyncio.Semaphore(8)
    by_type: dict[str, list] = {}        # breach_type -> [(cid, BatchGradeItem)]
    cell_keys: dict[str, list[str]] = {} # (rule|variant|target) -> [cid...]
    cov_of: dict[str, float] = {}
    target_cost = 0.0

    for rule in policy.rules:
        judge = instantiate_rule_judge(rule)
        variants = coverage_variants(rule, corpus)
        for tgt in targets:
            for vname, (pack, cov) in variants.items():
                key = f"{rule.rule_id}|{vname}|{tgt.config_id}"
                cov_of[key] = cov.score
                cell_keys[key] = []
                if dry_run:
                    # stub: synthesise responses (no API) just to exercise the pipeline
                    for prim in pack.primitives:
                        for t in range(n_trials):
                            cid = f"{key}|{prim.primitive_id}|{t}"
                            cell_keys[key].append(cid)
                    continue
                collected = await _collect(panel, rule, pack, tgt, n_trials, judge, sem)
                for cid, item, cost in collected:
                    target_cost += cost
                    by_type.setdefault(rule.breach_type.value, []).append((cid, item))
                    cell_keys[key].append(cid)

    # PHASE 2: batched judge per breach_type (Anthropic Batch API, rubric cached)
    verdict_breach: dict[str, bool] = {}
    if dry_run:
        # deterministic stub: higher coverage -> more breaches, so the pipeline + analysis run.
        for key, cids in cell_keys.items():
            c = cov_of[key]
            for i, cid in enumerate(cids):
                verdict_breach[cid] = (i / max(1, len(cids))) < c  # ~breach_rate≈coverage
    else:
        for btype, items in by_type.items():
            batch = JudgeBatch(JudgeAgent(breach_type=btype))
            results = await batch.grade([it for _, it in items])
            for cid, _ in items:
                jr = results.get(cid)
                verdict_breach[cid] = bool(jr and getattr(jr, "verdict", None) in BREACH_VERDICTS)

    # tally cells
    cells = []
    for key, cids in cell_keys.items():
        rid, vname, tgt = key.split("|")
        nb = sum(1 for c in cids if verdict_breach.get(c))
        n = len(cids)
        cells.append({"rule_id": rid, "variant": vname, "target": tgt,
                      "coverage": round(cov_of[key], 4), "n_trials": n,
                      "n_breaches": nb, "breach_rate": round(nb / n, 4) if n else 0.0})
    return {"cells": cells, "target_cost_usd": round(target_cost, 4)}


def _analyze(cells: list[dict]) -> dict:
    xs = [c["coverage"] for c in cells]
    ys = [c["breach_rate"] for c in cells]
    rho = _spearman(xs, ys)
    lo, hi = _spearman_ci(xs, ys)
    # strong>weak paired sign test, per (rule,target)
    by_cell: dict[tuple, dict] = {}
    for c in cells:
        by_cell.setdefault((c["rule_id"], c["target"]), {})[c["variant"]] = c["breach_rate"]
    pairs = [(v["strong"], v["weak"]) for v in by_cell.values() if "strong" in v and "weak" in v]
    strong_gt_weak = sum(1 for s, w in pairs if s > w)
    strong_lt_weak = sum(1 for s, w in pairs if s < w)
    return {
        "n_cells": len(cells), "spearman_rho": round(rho, 4),
        "spearman_ci95": [round(lo, 4), round(hi, 4)],
        "ci_excludes_zero": (lo > 0 or hi < 0),
        "strong_gt_weak": strong_gt_weak, "strong_lt_weak": strong_lt_weak, "n_pairs": len(pairs),
        "verdict": ("VALIDATED" if (lo > 0 and rho > 0) else "WEAK/NULL — keep as heuristic"),
    }


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default=str(_FIX / "validity_policy.json"))
    ap.add_argument("--targets", default="acme-llama3,acme-mistralsm")
    ap.add_argument("--n-trials", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    policy = ClientPolicy.model_validate_json(Path(args.policy).read_text())
    corpus = _corpus()
    cfgs = {c.config_id: c for c in demo_deployment_configs()}
    targets = [cfgs[t] for t in args.targets.split(",")]
    n_cells = len(policy.rules) * 3 * len(targets)
    print(f"rules={len(policy.rules)} · variants=3 · targets={len(targets)} → {n_cells} cells · "
          f"n_trials={args.n_trials} · corpus={len(corpus)}")

    if not args.dry_run and not args.yes:
        print("\nPAID batched run. Re-run with --yes to confirm (or --dry-run for a free check).")
        return

    out = asyncio.run(_run(policy, corpus, targets, args.n_trials, args.dry_run))
    analysis = _analyze(out["cells"])
    _OUT.mkdir(parents=True, exist_ok=True)
    tag = "dryrun" if args.dry_run else "live"
    dest = _OUT / f"coverage_validity_{tag}.json"
    dest.write_text(json.dumps({"analysis": analysis, **out}, indent=2))

    print(f"\n{'[DRY-RUN]' if args.dry_run else '[LIVE]'} analysis:")
    for k, v in analysis.items():
        print(f"  {k}: {v}")
    if not args.dry_run:
        print(f"  target spend: ~${out['target_cost_usd']:.4f} (judge batched separately)")
    print(f"--- cells → {dest} ---")


if __name__ == "__main__":
    main()
