"""$0 offline validator for the Q18 hybrid-acquisition ordering — the honest headline, no live spend.

Q18 replaces ROGUE's shipped *static* fire order (``reproducibility_score`` DESC — a config-blind harvest-
time self-rating) with an active-learning acquisition score. This script asks the only question a $0 replay
can answer: **given the (primitive × config) pairs ROGUE has already paid to fire, does the acquisition order
surface the true breaches — and cover more distinct attack families — earlier in the budget than the shipped
order?**

Leak-free by construction:
  * The pairs are split by *primitive* (group hash) into a train fold and a held-out test fold.
  * The Q7 P(breach) value/uncertainty term is fit on the **train fold only** (``train_and_backtest``), then
    scores the held-out primitives it never saw.
  * The info-gain cell counts are built from the **train fold only**, so a test primitive's own outcome
    never sets its own info-gain.
  * Diversity uses the stored ``payload_embedding`` (pure geometry — no label leakage).

Three orderings, ranked *within each config's budget* and macro-averaged across configs:
  1. ``reproducibility``   — the shipped default (baseline).
  2. ``value-only``        — Q7 P(breach) DESC (pure exploitation; isolates the config-aware value signal).
  3. ``acquisition-full``  — value + α·uncertainty + β·diversity + γ·info-gain (the shipped Q18 order).

Reports **breaches captured** and **families covered** at 25% / 50% of the budget, each with a percentile
bootstrap CI over configs. HONEST CAVEAT: this is a *re-ranking of an already-fired set* (labels exist only
for fired pairs), not a counterfactual over unfired primitives; the live budget-saved / breaches-per-dollar
number needs the gated paid A/B (folds into the queued ~$32 sweep).

    uv run python scripts/reproduce/replay_acquisition.py        # against $DATABASE_URL (Neon)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import numpy as np
from dotenv import load_dotenv

from rogue.reproduce.acquisition.gate import AcquisitionGate
from rogue.reproduce.prefire.train import fetch_pair_rows, train_and_backtest
from rogue.reproduce.survival.train import _group_test_mask

_DEFAULT_DB = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"
_RNG_SEED = 20260524  # fixed → reproducible bootstrap (matches the repo's diff/bootstrap seed)
_BUDGETS = (0.25, 0.50)


def _emb_of(primitive) -> list[float] | None:
    e = getattr(primitive, "payload_embedding", None)
    if e is None:
        return None
    e = list(e)
    return e if e else None


def _capture_and_coverage(order, budgets) -> dict:
    """Given an ordered list of (breached: bool, family: str), return breaches-captured and distinct-
    families-covered fractions at each budget fraction."""
    n = len(order)
    total_breaches = sum(1 for b, _ in order if b)
    total_families = len({f for _, f in order})
    out: dict = {}
    for k in budgets:
        cut = max(1, int(round(k * n)))
        top = order[:cut]
        cap = (sum(1 for b, _ in top if b) / total_breaches) if total_breaches else float("nan")
        cov = (len({f for _, f in top}) / total_families) if total_families else float("nan")
        out[k] = (cap, cov)
    return out


def _boot_ci(values: list[float], *, iters: int = 5000, alpha: float = 0.05) -> tuple[float, float, float]:
    """Percentile bootstrap over a list of per-config metric values (mean statistic)."""
    arr = np.asarray([v for v in values if not np.isnan(v)], dtype=np.float64)
    if arr.size == 0:
        return (float("nan"), float("nan"), float("nan"))
    rng = np.random.default_rng(_RNG_SEED)
    means = arr[rng.integers(0, arr.size, size=(iters, arr.size))].mean(axis=1)
    lo, hi = np.percentile(means, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return (float(arr.mean()), float(lo), float(hi))


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL", _DEFAULT_DB))
    ap.add_argument("--test-frac", type=float, default=0.40, help="held-out primitive fraction")
    ap.add_argument("--min-breaches", type=int, default=2, help="min breaches for a config to count")
    ap.add_argument("--min-prims", type=int, default=5, help="min held-out primitives for a config to count")
    ap.add_argument("--w-value", type=float, default=0.60)
    ap.add_argument("--alpha", type=float, default=0.25)
    ap.add_argument("--beta", type=float, default=0.10)
    ap.add_argument("--gamma", type=float, default=0.05)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    print(f"Reading breach_results from {args.database_url.split('@')[-1]} …", file=sys.stderr)
    rows = fetch_pair_rows(args.database_url)
    if not rows:
        print("No breach_results rows — nothing to replay.", file=sys.stderr)
        return 1

    groups = [r.primitive.primitive_id for r in rows]
    test_mask = _group_test_mask(groups, test_frac=args.test_frac, salt="rogue-acquisition")
    train_rows = [r for r, t in zip(rows, test_mask) if not t]
    test_rows = [r for r, t in zip(rows, test_mask) if t]
    if len(train_rows) < 20 or len(test_rows) < 20:
        print(f"Insufficient split (train={len(train_rows)} test={len(test_rows)}).", file=sys.stderr)
        return 1

    # Value/uncertainty: Q7 predictor fit on the TRAIN fold only (never sees the held-out primitives).
    predictor = train_and_backtest(train_rows)

    # Info-gain: (target_model, family) → (breaches, trials) counted on the TRAIN fold only.
    cell_evidence: dict[tuple[str, str], tuple[int, int]] = {}
    for r in train_rows:
        key = (r.config.target_model, r.primitive.family.value)
        b, t = cell_evidence.get(key, (0, 0))
        cell_evidence[key] = (b + (1 if r.breached else 0), t + 1)

    # Diversity: stored payload_embedding, keyed by payload text for the gate's embed_fn seam.
    emb_by_payload = {
        r.primitive.payload_template: e
        for r in rows if (e := _emb_of(r.primitive)) is not None
    }
    embed_fn = emb_by_payload.get

    orderings = {
        "reproducibility": None,  # baseline — sorted directly below
        "value-only": AcquisitionGate(predictor=predictor, embed_fn=embed_fn, cell_evidence=cell_evidence,
                                      w_value=1.0, alpha=0.0, beta=0.0, gamma=0.0),
        "acquisition-full": AcquisitionGate(predictor=predictor, embed_fn=embed_fn, cell_evidence=cell_evidence,
                                            w_value=args.w_value, alpha=args.alpha, beta=args.beta, gamma=args.gamma),
    }

    # group test rows by config
    by_cfg: dict[str, list] = {}
    for r in test_rows:
        by_cfg.setdefault(r.config.config_id, []).append(r)

    # per-config metric samples: name -> budget -> {"cap": [...], "cov": [...]}
    samples: dict[str, dict[float, dict[str, list[float]]]] = {
        name: {k: {"cap": [], "cov": []} for k in _BUDGETS} for name in orderings
    }
    n_configs_used = 0
    for cid, crows in by_cfg.items():
        prims = [r.primitive for r in crows]
        breached_by_pid = {r.primitive.primitive_id: r.breached for r in crows}
        if sum(breached_by_pid.values()) < args.min_breaches or len(prims) < args.min_prims:
            continue
        n_configs_used += 1
        cfg = crows[0].config
        for name, gate in orderings.items():
            if gate is None:  # reproducibility DESC (shipped baseline); stable on primitive_id
                ordered_prims = sorted(prims, key=lambda p: (-(p.reproducibility_score or 0), p.primitive_id))
            else:
                ordered_prims = gate.rank(prims, cfg).ordered
            order = [(bool(breached_by_pid[p.primitive_id]), p.family.value) for p in ordered_prims]
            m = _capture_and_coverage(order, _BUDGETS)
            for k in _BUDGETS:
                cap, cov = m[k]
                samples[name][k]["cap"].append(cap)
                samples[name][k]["cov"].append(cov)

    if n_configs_used < 3:
        print(f"Only {n_configs_used} configs met the min-breaches/min-prims bar — too few to report.",
              file=sys.stderr)
        return 1

    print("\n=== Q18 hybrid acquisition — offline ranking back-test ($0) ===")
    print(f"pairs={len(rows)}  train={len(train_rows)}  held-out test={len(test_rows)}  "
          f"configs scored={n_configs_used}  weights(w={args.w_value} α={args.alpha} β={args.beta} γ={args.gamma})")
    print(f"predictor: status={predictor.metrics.get('status')} "
          f"base_rate={predictor.metrics.get('base_rate_all')} cells(train)={len(cell_evidence)}")
    for k in _BUDGETS:
        print(f"\n-- at {int(k*100)}% of the per-config budget --")
        print(f"  {'ordering':<18} {'breaches captured':<28} {'families covered'}")
        for name in orderings:
            cap = _boot_ci(samples[name][k]["cap"])
            cov = _boot_ci(samples[name][k]["cov"])
            print(f"  {name:<18} {cap[0]*100:5.1f}% [{cap[1]*100:4.1f}, {cap[2]*100:4.1f}]        "
                  f"{cov[0]*100:5.1f}% [{cov[1]*100:4.1f}, {cov[2]*100:4.1f}]")

    # headline deltas vs the shipped baseline
    print("\n-- deltas vs the shipped reproducibility_score order --")
    for k in _BUDGETS:
        base_cap = np.nanmean(samples["reproducibility"][k]["cap"])
        for name in ("value-only", "acquisition-full"):
            d_cap = np.nanmean(samples[name][k]["cap"]) - base_cap
            base_cov = np.nanmean(samples["reproducibility"][k]["cov"])
            d_cov = np.nanmean(samples[name][k]["cov"]) - base_cov
            print(f"  @{int(k*100)}%  {name:<18} breaches {d_cap*100:+5.1f} pts   families {d_cov*100:+5.1f} pts")

    print("\nHONEST CAVEAT: a re-ranking of the already-fired set (labels exist only for fired pairs), not a "
          "counterfactual over unfired primitives. The live breaches-per-dollar number needs the gated paid "
          "A/B (folds into the queued ~$32 sweep).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
