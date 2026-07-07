"""Train + offline back-test the survival predictor from historical ``breach_results``.

The join Q11 specifies: ``breach_results ⋈ attack_primitives ⋈ deployment_configs``. One training row
is a distinct (primitive × config) pair; the label is whether that pair *breached* (any-breach rate ≥
the threshold the threat brief uses). Features are the primitive's surface crossed with the target
config's descriptor (see ``features.py``) — no embedding, no model call, so the whole thing trains and
back-tests on data ROGUE has **already paid for**. No new spend is required to build this (a
prospective live A/B to publish a budget-saved headline is a separate, gated ~$35 run).

Honest evaluation is the point. The split is **group-aware by primitive** — a given attack is entirely
in train or entirely in test — so the reported numbers measure "will a *new* attack survive," not "can
we memorize prolific primitives." The headline metric is **budget-saved**: ranking held-out (primitive,
config) trials by predicted survival, what fraction of the fire-all budget do we skip while still
recovering the target share of real survivors. That is exactly the operational win — fire the likely
survivors first, stop burning the rest.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

import numpy as np
from sqlalchemy import case, create_engine, func
from sqlalchemy.orm import Session

from rogue.reproduce.endpoint_scan import DEFAULT_BREACH_THRESHOLD
from rogue.reproduce.survival.features import build_features, describe_system_prompt
from rogue.reproduce.survival.model import SurvivalPredictor
from rogue.schemas.breach_result import BREACH_VERDICTS

_log = logging.getLogger(__name__)

# Below this many distinct primitives, a family has too little evidence to trust a skip → fire-all.
DEFAULT_MIN_SUPPORT = 8


@dataclass
class PairRow:
    """One (primitive × config) training example."""

    primitive: object   # ORM AttackPrimitive (duck-typed by features.build_features)
    config: object      # ORM DeploymentConfig
    breached: bool
    sp_class: str


def fetch_pair_rows(
    database_url: str, *, breach_threshold: float = DEFAULT_BREACH_THRESHOLD,
) -> list[PairRow]:
    """Aggregate ``breach_results`` into per-(primitive, config) labeled pairs, joined to both parents.

    A pair counts as breached when its any-breach rate over judged trials ≥ ``breach_threshold`` — the
    same rule ``scan_endpoint`` and the threat brief use, so the label matches what ROGUE calls a breach.
    """
    from rogue.db.models import (
        AttackPrimitive as AttackPrimitiveORM,
        BreachResult as BreachResultORM,
        DeploymentConfig as DeploymentConfigORM,
    )

    breach_values = [v.value for v in BREACH_VERDICTS]
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            agg = (
                session.query(
                    BreachResultORM.primitive_id.label("pid"),
                    BreachResultORM.deployment_config_id.label("cid"),
                    func.sum(
                        case((BreachResultORM.verdict.in_(breach_values), 1), else_=0)
                    ).label("n_breach"),
                    func.count().label("n"),
                )
                .group_by(
                    BreachResultORM.primitive_id, BreachResultORM.deployment_config_id
                )
                .all()
            )
            if not agg:
                return []
            prim_ids = {r.pid for r in agg}
            cfg_ids = {r.cid for r in agg}
            prims = {
                p.primitive_id: p
                for p in session.query(AttackPrimitiveORM)
                .filter(AttackPrimitiveORM.primitive_id.in_(prim_ids))
                .all()
            }
            cfgs = {
                c.config_id: c
                for c in session.query(DeploymentConfigORM)
                .filter(DeploymentConfigORM.config_id.in_(cfg_ids))
                .all()
            }
            rows: list[PairRow] = []
            for r in agg:
                p = prims.get(r.pid)
                c = cfgs.get(r.cid)
                if p is None or c is None or not r.n:
                    continue
                rate = (r.n_breach or 0) / r.n
                rows.append(
                    PairRow(
                        primitive=p,
                        config=c,
                        breached=rate >= breach_threshold,
                        sp_class=describe_system_prompt(c).sp_class,
                    )
                )
            return rows
    finally:
        engine.dispose()


def assemble(rows: list[PairRow]) -> tuple[np.ndarray, np.ndarray, list[str], list[str]]:
    """(X, y, families, group_keys) — group_key is primitive_id for the group-aware split."""
    X, y, families, groups = [], [], [], []
    for r in rows:
        X.append(build_features(r.primitive, r.config))
        y.append(1.0 if r.breached else 0.0)
        families.append(r.primitive.family.value)
        groups.append(r.primitive.primitive_id)
    return np.asarray(X, dtype=np.float64), np.asarray(y, dtype=np.float64), families, groups


def _group_test_mask(groups: list[str], *, test_frac: float = 0.25, salt: str = "rogue-survival") -> np.ndarray:
    """Deterministic group-hash split: a primitive_id hashes into [0,1); < test_frac → test.

    Hashing the group id (not the row) guarantees every row of one primitive lands on the same side —
    no leakage — and the split is reproducible across processes with no stored random state."""
    mask = np.zeros(len(groups), dtype=bool)
    for i, g in enumerate(groups):
        h = hashlib.sha256(f"{salt}:{g}".encode()).digest()
        frac = int.from_bytes(h[:8], "big") / 2**64
        mask[i] = frac < test_frac
    return mask


def _auc(y_true: np.ndarray, scores: np.ndarray) -> float:
    """ROC-AUC via the rank (Mann–Whitney U) identity — no sklearn."""
    pos = y_true == 1
    n_pos, n_neg = int(pos.sum()), int((~pos).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty(len(scores), dtype=np.float64)
    ranks[order] = np.arange(1, len(scores) + 1)
    # Average ties.
    s_sorted = scores[order]
    i = 0
    while i < len(s_sorted):
        j = i
        while j + 1 < len(s_sorted) and s_sorted[j + 1] == s_sorted[i]:
            j += 1
        if j > i:
            ranks[order[i : j + 1]] = (i + 1 + j + 1) / 2.0
        i = j + 1
    return (ranks[pos].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def budget_saved(y_true: np.ndarray, scores: np.ndarray, *, recover: float = 0.80) -> dict:
    """Fire trials in descending score order; how much of the fire-all budget is skipped while still
    recovering ``recover`` of the true survivors? Returns the saved fraction + supporting counts.

    ``budget_saved = 1 − (trials fired to recover R of survivors) / (all trials)``. This is the metric
    that turns a good ranking into money: the higher it is, the more of the reproduce budget the gate
    can defer onto the attacks that won't transfer anyway."""
    n = len(y_true)
    total_pos = int(y_true.sum())
    if n == 0 or total_pos == 0:
        return {"budget_saved": 0.0, "n": n, "n_survivors": total_pos, "recover": recover}
    order = np.argsort(-scores, kind="mergesort")
    need = int(np.ceil(recover * total_pos))
    seen = 0
    fired = n
    for k, idx in enumerate(order, start=1):
        if y_true[idx] == 1:
            seen += 1
            if seen >= need:
                fired = k
                break
    return {
        "budget_saved": round(1.0 - fired / n, 4),
        "fired_to_recover": fired,
        "n": n,
        "n_survivors": total_pos,
        "recover": recover,
    }


def precision_at_k(y_true: np.ndarray, scores: np.ndarray, *, k_frac: float = 0.10) -> float:
    n = len(y_true)
    if n == 0:
        return 0.0
    k = max(1, int(round(k_frac * n)))
    top = np.argsort(-scores, kind="mergesort")[:k]
    return round(float(y_true[top].mean()), 4)


def family_support(families: list[str], groups: list[str]) -> dict[str, int]:
    """Distinct primitives contributing a labeled row, per family — the drift-guard denominator."""
    seen: dict[str, set[str]] = {}
    for fam, g in zip(families, groups):
        seen.setdefault(fam, set()).add(g)
    return {fam: len(s) for fam, s in seen.items()}


def train_and_backtest(
    rows: list[PairRow],
    *,
    l2: float = 1.0,
    test_frac: float = 0.25,
    recover: float = 0.80,
    min_support: int = DEFAULT_MIN_SUPPORT,
) -> SurvivalPredictor:
    """Fit on the train split, back-test on the held-out primitives, stamp metrics onto the artifact."""
    X, y, families, groups = assemble(rows)
    if len(rows) < 20 or int(y.sum()) < 3 or int((y == 0).sum()) < 3:
        # Not enough signal to train honestly — return a cold model that ranks by the base rate only.
        _log.warning(
            "survival: insufficient data (n=%d, survivors=%d) — returning cold predictor",
            len(rows), int(y.sum()),
        )
        m = SurvivalPredictor.cold(class_prior=float(y.mean()) if len(y) else 0.5)
        m.metrics = {"status": "insufficient_data", "n": len(rows), "n_survivors": int(y.sum())}
        m.family_support = family_support(families, groups)
        return m

    test = _group_test_mask(groups, test_frac=test_frac)
    train = ~test
    supp = family_support(families, groups)
    model = SurvivalPredictor.fit(X[train], y[train], l2=l2, family_support=supp)

    metrics: dict = {
        "status": "trained",
        "n_train": int(train.sum()),
        "n_test": int(test.sum()),
        "base_rate_all": round(float(y.mean()), 4),
        "min_support": min_support,
        "n_families": len(supp),
    }
    if int(test.sum()) >= 10 and 0 < int(y[test].sum()) < int(test.sum()):
        scores = model.predict_proba(X[test])
        metrics["test_base_rate"] = round(float(y[test].mean()), 4)
        metrics["auc"] = round(_auc(y[test], scores), 4)
        metrics["precision_at_10pct"] = precision_at_k(y[test], scores, k_frac=0.10)
        metrics["lift_at_10pct"] = (
            round(metrics["precision_at_10pct"] / metrics["test_base_rate"], 3)
            if metrics["test_base_rate"] else None
        )
        metrics.update(budget_saved(y[test], scores, recover=recover))
    else:
        metrics["status"] = "trained_no_holdout_eval"
    model.metrics = metrics
    return model


def train_from_db(
    database_url: str,
    *,
    breach_threshold: float = DEFAULT_BREACH_THRESHOLD,
    l2: float = 1.0,
    recover: float = 0.80,
) -> SurvivalPredictor:
    """End-to-end: fetch → train → back-test. Raises nothing on empty data — returns a cold model."""
    rows = fetch_pair_rows(database_url, breach_threshold=breach_threshold)
    if not rows:
        _log.warning("survival: no breach_results rows found — returning cold predictor")
        m = SurvivalPredictor.cold()
        m.metrics = {"status": "no_data"}
        return m
    return train_and_backtest(rows, l2=l2, recover=recover)


__all__ = [
    "PairRow",
    "DEFAULT_MIN_SUPPORT",
    "fetch_pair_rows",
    "assemble",
    "budget_saved",
    "precision_at_k",
    "family_support",
    "train_and_backtest",
    "train_from_db",
]
