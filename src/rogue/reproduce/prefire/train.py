"""Train + offline-backtest the pre-fire scorer from historical ``breach_results`` — free ($0).

The join and the group-aware, split-by-primitive back-test are Q11's, reused wholesale: one row is a
distinct (primitive × config) pair; the label is whether that pair breached (any-breach rate ≥ the
threat-brief threshold); a primitive is entirely in train or entirely in test, so the numbers measure
"will a *new* attack breach," not memorisation. Q7 adds three things on top:

1. **An ablation.** We fit the same head twice — structural-only (= Q11's exact features) and
   structural ⊕ embedding-affinity — and report both AUCs, so whether the payload embedding earns its
   place is *measured*, not assumed (ROGUE's own silhouette≈0 probe says it might not).
2. **Calibration.** A Platt slice (group-disjoint from both fit and test) recalibrates the head into a
   real probability; we report the Brier score before and after so the calibration is auditable.
3. **A recall-vs-skip curve.** Sorting held-out trials by predicted P(breach) and skipping the lowest,
   what fraction of trials can we skip while still recovering ≥95% / ≥99% of real breaches? This is the
   operational number — and precisely the missed-breach cost Zhang's FASC ordering never quantified.

No live spend: it reads only breach data ROGUE already paid for and the payload embeddings already
stored on ``attack_primitives``. A prospective A/B for a live budget-saved headline is a separate,
deliberately-gated ~$35 reproduce run, not this.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from rogue.reproduce.config_features import derive_config_features
from rogue.reproduce.endpoint_scan import DEFAULT_BREACH_THRESHOLD
from rogue.reproduce.prefire.embedding_affinity import DEFAULT_MIN_CLASS_SUPPORT, EmbeddingAffinity
from rogue.reproduce.prefire.features import build_prefire_features
from rogue.reproduce.prefire.model import PlattCalibrator, PrefirePredictor
from rogue.reproduce.survival.features import build_features as build_structural_features
from rogue.reproduce.survival.model import SurvivalPredictor
from rogue.reproduce.survival.train import (
    DEFAULT_MIN_SUPPORT,
    PairRow,
    _auc,
    _group_test_mask,
    budget_saved,
    family_support,
    fetch_pair_rows,
    precision_at_k,
)

_log = logging.getLogger(__name__)


@dataclass
class _Assembled:
    x_struct: np.ndarray          # (n, STRUCT_DIM)
    x_full: np.ndarray            # (n, PREFIRE_FEATURE_DIM)
    y: np.ndarray
    families: list[str]
    groups: list[str]
    embeddings: list[list[float] | None]
    siblings: list[str]


def _embedding_of(primitive) -> list[float] | None:
    emb = getattr(primitive, "payload_embedding", None)
    if emb is None:
        return None
    emb = list(emb)
    return emb if emb else None


def _brier(y: np.ndarray, p: np.ndarray) -> float:
    if len(y) == 0:
        return float("nan")
    return round(float(np.mean((p - y) ** 2)), 4)


def _recall_vs_skip(y: np.ndarray, p: np.ndarray, *, recalls=(0.95, 0.99)) -> dict:
    """Skip the lowest-``p`` trials first; report the max skip fraction that still recovers each recall
    target, and the P(breach) threshold at that point. This is the honest cost of a hard skip."""
    n = len(y)
    total_pos = int(y.sum())
    out: dict = {"n": n, "n_breaches": total_pos}
    if n == 0 or total_pos == 0:
        for r in recalls:
            out[f"skip_at_{int(r * 100)}pct_recall"] = 0.0
            out[f"threshold_at_{int(r * 100)}pct_recall"] = None
        return out
    order = np.argsort(p, kind="mergesort")  # ascending — skip the least promising first
    skipped_pos = 0
    # best[r] = (max skip_frac with recall>=r, threshold at that point)
    best = {r: (0.0, None) for r in recalls}
    for k, idx in enumerate(order, start=1):
        if y[idx] == 1:
            skipped_pos += 1
        recall = 1.0 - skipped_pos / total_pos
        skip_frac = k / n
        for r in recalls:
            if recall >= r and skip_frac > best[r][0]:
                best[r] = (skip_frac, float(p[idx]))
    for r in recalls:
        out[f"skip_at_{int(r * 100)}pct_recall"] = round(best[r][0], 4)
        out[f"threshold_at_{int(r * 100)}pct_recall"] = (
            round(best[r][1], 4) if best[r][1] is not None else None
        )
    return out


def assemble(rows: list[PairRow], affinity: EmbeddingAffinity) -> _Assembled:
    """Build structural-only and full (⊕ affinity) matrices, reusing one derived config descriptor per
    config so the ModelSpec lookup is not repeated per pair."""
    cf_cache: dict[str, object] = {}
    x_struct, x_full, y, families, groups, embeddings, siblings = [], [], [], [], [], [], []
    for r in rows:
        c = r.config
        key = getattr(c, "config_id", None) or c.target_model
        cf = cf_cache.get(key)
        if cf is None:
            cf = derive_config_features(c.target_model, base_url=getattr(c, "base_url", None))
            cf_cache[key] = cf
        emb = _embedding_of(r.primitive)
        x_struct.append(build_structural_features(r.primitive, c, config_features=cf))
        x_full.append(build_prefire_features(r.primitive, c, emb, affinity, config_features=cf))
        y.append(1.0 if r.breached else 0.0)
        families.append(r.primitive.family.value)
        groups.append(r.primitive.primitive_id)
        embeddings.append(emb)
        siblings.append(cf.sibling_key)
    return _Assembled(
        x_struct=np.asarray(x_struct, dtype=np.float64),
        x_full=np.asarray(x_full, dtype=np.float64),
        y=np.asarray(y, dtype=np.float64),
        families=families, groups=groups, embeddings=embeddings, siblings=siblings,
    )


def _backtest_block(y_test: np.ndarray, scores: np.ndarray, *, recover: float) -> dict:
    base = float(y_test.mean()) if len(y_test) else 0.0
    block = {
        "auc": round(_auc(y_test, scores), 4),
        "precision_at_10pct": precision_at_k(y_test, scores, k_frac=0.10),
        "test_base_rate": round(base, 4),
    }
    block["lift_at_10pct"] = (
        round(block["precision_at_10pct"] / base, 3) if base else None
    )
    block.update(budget_saved(y_test, scores, recover=recover))
    return block


def train_and_backtest(
    rows: list[PairRow],
    *,
    l2: float = 1.0,
    test_frac: float = 0.25,
    calib_frac: float = 0.20,
    recover: float = 0.80,
    min_support: int = DEFAULT_MIN_SUPPORT,
    min_class_support: int = DEFAULT_MIN_CLASS_SUPPORT,
) -> PrefirePredictor:
    """Fit affinity + head on the fit slice, calibrate on a disjoint slice, back-test on held-out
    primitives, and stamp the ablation + recall-vs-skip curve onto the shipped artifact."""
    y_all = np.asarray([1.0 if r.breached else 0.0 for r in rows], dtype=np.float64)
    n_emb = sum(1 for r in rows if _embedding_of(r.primitive) is not None)
    if len(rows) < 20 or int(y_all.sum()) < 3 or int((y_all == 0).sum()) < 3:
        _log.warning(
            "prefire: insufficient data (n=%d, breaches=%d) — returning cold predictor",
            len(rows), int(y_all.sum()),
        )
        m = PrefirePredictor.cold(class_prior=float(y_all.mean()) if len(y_all) else 0.5)
        fams = [r.primitive.family.value for r in rows]
        grps = [r.primitive.primitive_id for r in rows]
        m.family_support = family_support(fams, grps)
        m.metrics = {"status": "insufficient_data", "n": len(rows), "n_breaches": int(y_all.sum())}
        return m

    groups = [r.primitive.primitive_id for r in rows]
    test = _group_test_mask(groups, test_frac=test_frac, salt="rogue-prefire")
    # Carve a calibration slice out of the *train* primitives only (disjoint from test AND from fit).
    calib_all = _group_test_mask(groups, test_frac=calib_frac, salt="rogue-prefire-calib")
    calib = calib_all & ~test
    fit = ~test & ~calib

    # Affinity is fit on the FIT slice alone → neither the calibration slice nor the test primitives
    # contribute to a centroid they are later scored against (no leakage).
    fit_rows = [r for r, m in zip(rows, fit) if m]
    affinity = EmbeddingAffinity.fit(
        [_embedding_of(r.primitive) for r in fit_rows],
        [derive_config_features(r.config.target_model,
                                base_url=getattr(r.config, "base_url", None)).sibling_key
         for r in fit_rows],
        [1.0 if r.breached else 0.0 for r in fit_rows],
        min_class_support=min_class_support,
    )

    data = assemble(rows, affinity)
    supp = family_support(data.families, data.groups)

    head_struct = SurvivalPredictor.fit(data.x_struct[fit], data.y[fit], l2=l2)
    head_full = SurvivalPredictor.fit(data.x_full[fit], data.y[fit], l2=l2)

    # Calibrate the full head on the disjoint calibration slice.
    calibrator = PlattCalibrator()
    if int(calib.sum()) >= 8 and 0 < int(data.y[calib].sum()) < int(calib.sum()):
        calibrator = PlattCalibrator.fit(
            head_full.predict_proba(data.x_full[calib]), data.y[calib]
        )

    metrics: dict = {
        "status": "trained",
        "n_pairs": len(rows),
        "n_with_embedding": n_emb,
        "n_fit": int(fit.sum()),
        "n_calib": int(calib.sum()),
        "n_test": int(test.sum()),
        "base_rate_all": round(float(y_all.mean()), 4),
        "min_support": min_support,
        "n_families": len(supp),
        "affinity_informative": affinity.informative,
        "affinity_sibling_classes": len(affinity.breach_centroids),
    }

    if int(test.sum()) >= 10 and 0 < int(data.y[test].sum()) < int(test.sum()):
        y_test = data.y[test]
        s_struct = head_struct.predict_proba(data.x_struct[test])
        s_full_raw = head_full.predict_proba(data.x_full[test])
        s_full_cal = calibrator.transform(s_full_raw) if calibrator.fitted else s_full_raw

        metrics["ablation"] = {
            "structural_only": _backtest_block(y_test, s_struct, recover=recover),
            "with_embedding": _backtest_block(y_test, s_full_raw, recover=recover),
        }
        metrics["auc_gain_from_embedding"] = round(
            metrics["ablation"]["with_embedding"]["auc"]
            - metrics["ablation"]["structural_only"]["auc"], 4
        )
        metrics["calibration"] = {
            "brier_raw": _brier(y_test, s_full_raw),
            "brier_calibrated": _brier(y_test, s_full_cal),
            "platt_a": round(calibrator.a, 4),
            "platt_b": round(calibrator.b, 4),
            "fitted": calibrator.fitted,
        }
        metrics["recall_vs_skip"] = _recall_vs_skip(y_test, s_full_cal)
        # The recommended default skip threshold: the calibrated P(breach) that still recovers 95% of
        # breaches on held-out data. The gate reads this when no explicit threshold is set.
        metrics["recommended_threshold"] = metrics["recall_vs_skip"]["threshold_at_95pct_recall"]
    else:
        metrics["status"] = "trained_no_holdout_eval"

    model = PrefirePredictor(
        base=head_full,
        affinity=affinity,
        calibrator=calibrator,
        family_support=supp,
        class_prior=round(float(y_all.mean()), 4),
        l2=l2,
        n_train=int(fit.sum()),
    )
    model.metrics = metrics
    return model


def train_from_db(
    database_url: str,
    *,
    breach_threshold: float = DEFAULT_BREACH_THRESHOLD,
    l2: float = 1.0,
    recover: float = 0.80,
) -> PrefirePredictor:
    """End-to-end: fetch → train → back-test. Returns a cold model on empty data (never raises)."""
    rows = fetch_pair_rows(database_url, breach_threshold=breach_threshold)
    if not rows:
        _log.warning("prefire: no breach_results rows — returning cold predictor")
        m = PrefirePredictor.cold()
        m.metrics = {"status": "no_data"}
        return m
    return train_and_backtest(rows, l2=l2, recover=recover)


__all__ = [
    "assemble",
    "train_and_backtest",
    "train_from_db",
    "fetch_pair_rows",
]
