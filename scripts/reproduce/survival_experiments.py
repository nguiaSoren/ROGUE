"""Offline strengthening experiments for the survival predictor — all $0, read-only.

Runs the three experiments a security reviewer asks for, over breach history ROGUE has already paid for
(no LLM / no paid calls): (1) leave-one-family-out (LOFO) generalization, (2) a calibration curve
(reliability + ECE), (3) baselines — budget-saved of survival ranking vs random vs a reproducibility
heuristic, plus the survivors-recovered-vs-budget curve.

    uv run python scripts/reproduce/survival_experiments.py                 # against $DATABASE_URL
    uv run python scripts/reproduce/survival_experiments.py --database-url postgresql://rogue:...@localhost:5432/rogue

Reads the ORM directly (no Pydantic conversion), so it runs even against a redacted local snapshot.
Numbers are deterministic given the corpus (the survival split + fit are deterministic; the random
baseline averages a fixed number of seeded shuffles).
"""

from __future__ import annotations

import argparse
import os

import numpy as np

from rogue.reproduce.survival.model import SurvivalPredictor
from rogue.reproduce.survival.train import (
    _auc,
    _group_test_mask,
    assemble,
    budget_saved,
    family_support,
    fetch_pair_rows,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    ap.add_argument("--l2", type=float, default=1.0)
    ap.add_argument("--shuffles", type=int, default=500, help="seeded random baselines to average")
    args = ap.parse_args()
    if not args.database_url:
        raise SystemExit("need --database-url or $DATABASE_URL")

    rows = fetch_pair_rows(args.database_url)
    if not rows:
        raise SystemExit("no breach_results rows")
    X, y, families, groups = assemble(rows)
    families = np.array(families)
    groups = np.array(groups)
    repro = np.array([float(getattr(r.primitive, "reproducibility_score", 0) or 0) for r in rows])
    print(f"corpus: {len(rows)} pairs, {int(y.sum())} survivors ({y.mean():.1%}), "
          f"{len(set(families))} families")

    # In-distribution baseline (should reproduce the artifact's headline).
    test = _group_test_mask(list(groups))
    train = ~test
    model = SurvivalPredictor.fit(
        X[train], y[train], l2=args.l2, family_support=family_support(list(families), list(groups)))
    scores = model.predict_proba(X[test])
    auc_id = _auc(y[test], scores)
    bs_surv = budget_saved(y[test], scores)["budget_saved"]
    print(f"[in-dist, group-split] test_n={int(test.sum())} AUC={auc_id:.3f} budget_saved={bs_surv:.3f}")

    # 1) Leave-one-family-out.
    print("\n=== 1) LEAVE-ONE-FAMILY-OUT ===")
    lofo = {}
    for fam in sorted(set(families)):
        te = families == fam
        tr = ~te
        if te.sum() < 10 or not (0 < int(y[te].sum()) < int(te.sum())):
            continue
        if int(y[tr].sum()) < 3 or int((y[tr] == 0).sum()) < 3:
            continue
        m = SurvivalPredictor.fit(X[tr], y[tr], l2=args.l2,
                                  family_support=family_support(list(families[tr]), list(groups[tr])))
        lofo[fam] = (round(_auc(y[te], m.predict_proba(X[te])), 3), int(te.sum()), int(y[te].sum()))
    for fam, (a, n, s) in sorted(lofo.items(), key=lambda kv: -kv[1][0]):
        print(f"  {fam:<32} AUC={a:.3f}  (n={n}, survivors={s})")
    if lofo:
        aucs = [a for a, _, _ in lofo.values()]
        print(f"  → {len(lofo)} evaluable families | mean AUC={np.mean(aucs):.3f} "
              f"median={np.median(aucs):.3f} min={min(aucs):.3f} max={max(aucs):.3f}")

    # 2) Calibration.
    print("\n=== 2) CALIBRATION (group-split test set) ===")
    edges = np.linspace(0, 1, 6)
    ece = 0.0
    print(f"  {'bin':<12}{'n':>5}{'pred':>8}{'obs':>8}")
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (scores >= lo) & (scores < hi) if hi < 1 else (scores >= lo) & (scores <= hi)
        if m.sum() == 0:
            continue
        conf = float(scores[m].mean())
        acc = float(y[test][m].mean())
        ece += (int(m.sum()) / len(scores)) * abs(conf - acc)
        print(f"  [{lo:.1f},{hi:.1f})   {int(m.sum()):>5}{conf:>8.3f}{acc:>8.3f}")
    print(f"  → ECE={ece:.3f}")

    # 3) Baselines.
    print("\n=== 3) BASELINES: budget-saved @80% recall ===")
    rng = np.random.default_rng(0)
    rand_bs = float(np.mean(
        [budget_saved(y[test], rng.random(len(scores)))["budget_saved"] for _ in range(args.shuffles)]))
    heur_bs = budget_saved(y[test], repro[test])["budget_saved"]
    print(f"  survival ranking : {bs_surv:.3f}")
    print(f"  reproducibility  : {heur_bs:.3f}   (heuristic: reproducibility_score alone)")
    print(f"  random           : {rand_bs:.3f}   (avg of {args.shuffles} shuffles)")

    def curve(sc):
        order = np.argsort(-sc, kind="mergesort")
        return np.cumsum(y[test][order]) / max(int(y[test].sum()), 1)

    c_surv, c_heur = curve(scores), curve(repro[test])
    c_rand = np.mean([curve(rng.random(len(scores))) for _ in range(args.shuffles)], axis=0)
    n = len(scores)
    print("\n  survivors recovered vs budget fired:")
    print(f"    {'budget%':>8}{'survival':>10}{'repro':>8}{'random':>8}")
    for frac in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8):
        k = max(1, int(frac * n)) - 1
        print(f"    {int(frac*100):>7}%{c_surv[k]:>10.0%}{c_heur[k]:>8.0%}{c_rand[k]:>8.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
