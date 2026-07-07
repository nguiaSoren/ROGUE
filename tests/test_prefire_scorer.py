"""Q7 pre-fire success scorer — embedding affinity, calibrator, model, gate, and live splice.

Proves the whole path deterministically without spend: the embedding-affinity centroid feature behaves
(informative flag, sibling fallback, missing-embedding → zeros), the Platt calibrator recalibrates
monotonically, the reused logistic head fits/serialises reproducibly, the gate skips low-P attacks while
honouring the drift-guard (fire-all novel/low-support) + deterministic canary, and the splice into
``scan_endpoint`` / ``run_scan`` actually skips (recording a visible skipped finding, not a silent drop)
and is byte-identical when off. A DB-gated test trains from real ``breach_results`` when Postgres is up.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from rogue.reproduce.endpoint_scan import make_endpoint_config, scan_endpoint
from rogue.reproduce.prefire.embedding_affinity import AFFINITY_DIM, EmbeddingAffinity
from rogue.reproduce.prefire.features import (
    PREFIRE_FEATURE_DIM,
    STRUCT_DIM,
    build_prefire_features,
)
from rogue.reproduce.prefire.gate import (
    PrefireGate,
    apply_prefire_skip,
    apply_prefire_skip_pairs,
    resolve_prefire_gate,
)
from rogue.reproduce.prefire.model import PlattCalibrator, PrefirePredictor
from rogue.reproduce.prefire.train import PairRow, train_and_backtest, train_from_db
from rogue.reproduce.survival.features import describe_system_prompt
from rogue.retrieval.embed import deterministic_embed_fn
from rogue.schemas import AttackPrimitive, JudgeVerdict

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_GOLDENS = (
    "01_multilingual_african_languages.json",
    "02_copirate_365_cve_2026_24299.json",
    "03_hacking_claude_memory.json",
)
_DATABASE_URL = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"
_EMB = deterministic_embed_fn()


def _goldens() -> list[AttackPrimitive]:
    return [AttackPrimitive.model_validate_json((_FIXTURES / n).read_text()) for n in _GOLDENS]


# --- features -------------------------------------------------------------------------------------


def test_feature_dim_is_structural_plus_affinity():
    assert PREFIRE_FEATURE_DIM == STRUCT_DIM + AFFINITY_DIM


def test_build_prefire_features_dim_and_degrade():
    prims = _goldens()
    cfg = make_endpoint_config("u", "gpt-4o-mini")
    aff = _fit_affinity()
    row = build_prefire_features(prims[0], cfg, _EMB("x"), aff)
    assert len(row) == PREFIRE_FEATURE_DIM
    # No embedding + affinity present → the affinity block is [0,0,0] (has_embedding=0).
    row_noemb = build_prefire_features(prims[0], cfg, None, aff)
    assert row_noemb[-AFFINITY_DIM:] == [0.0, 0.0, 0.0]
    # No affinity model but an embedding present → has_embedding flag still set.
    row_noaff = build_prefire_features(prims[0], cfg, _EMB("x"), None)
    assert row_noaff[-1] == 1.0


# --- embedding affinity ---------------------------------------------------------------------------


def _fit_affinity(n=60):
    embs = [_EMB(f"attack {i}") for i in range(n)]
    sibs = (["large:long"] * (n // 2)) + (["small:short"] * (n - n // 2))
    labels = [1.0, 0.0] * (n // 2)
    return EmbeddingAffinity.fit(embs, sibs, labels, min_class_support=3)


def test_affinity_informative_and_feature_shape():
    aff = _fit_affinity()
    assert aff.informative
    f = aff.features(_EMB("attack 0"), "large:long")
    assert len(f) == AFFINITY_DIM and f[2] == 1.0


def test_affinity_uninformative_when_one_class():
    # Only breaching examples → no safe centroid → uninformative → zeros.
    aff = EmbeddingAffinity.fit([_EMB("a"), _EMB("b")], ["x:y", "x:y"], [1.0, 1.0])
    assert not aff.informative
    assert aff.features(_EMB("a"), "x:y") == [0.0] * AFFINITY_DIM


def test_affinity_unknown_sibling_falls_back_to_global():
    aff = _fit_affinity()
    f = aff.features(_EMB("attack 0"), "never:seen")
    assert f[0] == f[1]  # local slot falls back to the global gap for an unseen sibling class


# --- calibrator -----------------------------------------------------------------------------------


def test_calibrator_fits_and_is_monotone():
    rng = np.random.default_rng(0)
    p = rng.uniform(0, 1, 400)
    y = (rng.uniform(0, 1, 400) < p).astype(float)
    cal = PlattCalibrator.fit(p, y)
    assert cal.fitted
    grid = np.linspace(0.01, 0.99, 50)
    out = cal.transform(grid)
    assert np.all(np.diff(out) >= -1e-9)  # monotone increasing


def test_calibrator_identity_on_degenerate_input():
    cal = PlattCalibrator.fit([0.5, 0.5], [1.0, 1.0])  # one-class / tiny → identity
    assert not cal.fitted
    assert np.allclose(cal.transform([0.3, 0.7]), [0.3, 0.7], atol=1e-6)


# --- model ----------------------------------------------------------------------------------------


def test_cold_predictor_scores_at_prior():
    m = PrefirePredictor.cold(class_prior=0.16)
    s = m.score_one([0.0] * PREFIRE_FEATURE_DIM)
    assert abs(s - 0.16) < 1e-6


def test_model_save_load_roundtrip(tmp_path):
    rows = _synthetic_rows()
    m = train_and_backtest(rows)
    p = tmp_path / "m.json"
    m.save(p)
    m2 = PrefirePredictor.load(p)
    assert np.allclose(m.base.weights, m2.base.weights)
    assert m.calibrator.to_dict() == m2.calibrator.to_dict()
    assert m2.metrics == m.metrics
    x = np.zeros((1, PREFIRE_FEATURE_DIM))
    assert np.allclose(m.predict_proba(x), m2.predict_proba(x))


def test_model_load_rejects_stale_dim(tmp_path):
    m = PrefirePredictor.cold()
    p = tmp_path / "m.json"
    m.save(p)
    import json

    data = json.loads(p.read_text())
    data["feature_dim"] = 999
    p.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="feature_dim"):
        PrefirePredictor.load(p)


# --- gate -----------------------------------------------------------------------------------------


def _well_supported(prims, prior=0.2):
    m = PrefirePredictor.cold(prior)
    m.family_support = {p.family.value: 50 for p in prims}
    return m


def test_gate_skips_below_threshold_preserves_order():
    prims = _goldens()
    cfg = make_endpoint_config("u", "gpt-4o-mini")
    m = _well_supported(prims)
    # Deterministic per-primitive scores in call order: keep, skip, keep.
    scores = iter([0.9, 0.05, 0.8])
    m.score_one = lambda feats, calibrated=True: next(scores)  # type: ignore[method-assign]
    gate = PrefireGate(predictor=m, embed_fn=None, skip_threshold=0.1, canary_frac=0.0)
    plan = gate.plan(prims, cfg)
    assert [p.primitive_id for p in plan.fired] == [prims[0].primitive_id, prims[2].primitive_id]
    assert [d.primitive.primitive_id for d in plan.skipped] == [prims[1].primitive_id]


def test_gate_no_threshold_fires_all():
    prims = _goldens()
    cfg = make_endpoint_config("u", "gpt-4o-mini")
    gate = PrefireGate(predictor=_well_supported(prims, prior=0.01), embed_fn=None,
                       skip_threshold=None, canary_frac=0.0)
    plan = gate.plan(prims, cfg)
    assert len(plan.fired) == len(prims) and not plan.skipped


def test_drift_guard_fires_all_low_support():
    prims = _goldens()
    cfg = make_endpoint_config("u", "gpt-4o-mini")
    m = PrefirePredictor.cold(0.01)  # score ≪ threshold, but…
    m.family_support = {}            # …no family supported → fire-all
    gate = PrefireGate(predictor=m, embed_fn=None, skip_threshold=0.5, min_support=8, canary_frac=0.0)
    plan = gate.plan(prims, cfg)
    assert not plan.skipped
    assert all(d.reason == "low_support" for d in plan.decisions)


def test_drift_guard_novel_family_never_skipped():
    prims = _goldens()
    object.__setattr__(prims[1], "emergent_label", "novel_trick")
    cfg = make_endpoint_config("u", "gpt-4o-mini")
    gate = PrefireGate(predictor=_well_supported(prims, prior=0.01), embed_fn=None,
                       skip_threshold=0.5, min_support=8, canary_frac=0.0)
    plan = gate.plan(prims, cfg)
    assert prims[1] in plan.fired
    novel = next(d for d in plan.decisions if d.primitive is prims[1])
    assert novel.reason == "novel_family"


def test_canary_force_fires_deterministically():
    prims = _goldens()
    cfg = make_endpoint_config("u", "gpt-4o-mini")
    gate = PrefireGate(predictor=_well_supported(prims, prior=0.01), embed_fn=None,
                       skip_threshold=0.5, min_support=1, canary_frac=1.0)  # everything a canary
    p1 = gate.plan(prims, cfg)
    p2 = gate.plan(prims, cfg)
    assert not p1.skipped and not p2.skipped
    assert [d.reason for d in p1.decisions] == [d.reason for d in p2.decisions] == ["canary"] * len(prims)


def test_gate_embed_failure_degrades_not_crashes():
    prims = _goldens()
    cfg = make_endpoint_config("u", "gpt-4o-mini")

    def _boom(_):
        raise RuntimeError("no key")

    gate = PrefireGate(predictor=_well_supported(prims), embed_fn=_boom, skip_threshold=0.9,
                       canary_frac=0.0)
    plan = gate.plan(prims, cfg)  # must not raise; scores on structure alone
    assert len(plan.decisions) == len(prims)


def test_apply_prefire_skip_disabled_is_identity():
    prims = _goldens()
    cfg = make_endpoint_config("u", "gpt-4o-mini")
    plan = apply_prefire_skip(prims, cfg, gate=None)  # no gate resolvable (env off)
    assert not plan.enabled and plan.fired == prims and not plan.skipped


def test_resolve_gate_off_by_default(monkeypatch):
    monkeypatch.delenv("ROGUE_PREFIRE_SKIP", raising=False)
    assert resolve_prefire_gate() is None


def test_apply_prefire_skip_pairs_disabled_identity():
    prims = _goldens()
    cfg = make_endpoint_config("u", "gpt-4o-mini")
    pairs = [(p, cfg) for p in prims]
    fired, skipped, on = apply_prefire_skip_pairs(pairs, gate=None)
    assert not on and fired == pairs and not skipped


def test_apply_prefire_skip_pairs_skips_below_floor():
    prims = _goldens()
    cfg = make_endpoint_config("u", "gpt-4o-mini")
    m = _well_supported(prims, prior=0.02)  # below floor
    gate = PrefireGate(predictor=m, embed_fn=None, skip_threshold=0.5, canary_frac=0.0)
    pairs = [(p, cfg) for p in prims]
    fired, skipped, on = apply_prefire_skip_pairs(pairs, gate=gate)
    assert on and not fired and len(skipped) == len(prims)


# --- trainer --------------------------------------------------------------------------------------


def _synthetic_rows(n_prims=120, seed=3):
    from rogue.schemas.attack_primitive import AttackFamily

    fams = list(AttackFamily)
    breachy = set(fams[:5])  # ~1/3 of families breach on a permissive config → dense enough to backtest
    base = _goldens()[0]
    cfgs = [
        make_endpoint_config("u", "gpt-4o-mini", config_id="cfg-none-0001", system_prompt=""),
        make_endpoint_config("u", "claude-3-haiku", config_id="cfg-guard-001",
                             system_prompt="You must refuse harmful or illegal requests per policy."),
    ]
    rows = []
    for i in range(n_prims):
        emb = _EMB(f"prim-{i}")  # deterministic embedding stands in for a stored payload_embedding
        p = base.model_copy(update={"primitive_id": f"prim-{i:05d}", "family": fams[i % len(fams)]})
        object.__setattr__(p, "payload_embedding", emb)
        for c in cfgs:
            spc = describe_system_prompt(c).sp_class
            survive = (p.family in breachy) and not spc.startswith("guarded")
            rows.append(PairRow(primitive=p, config=c, breached=bool(survive), sp_class=spc))
    return rows


def test_train_and_backtest_reports_ablation_and_recall_curve():
    m = train_and_backtest(_synthetic_rows(), l2=1.0)
    assert m.metrics["status"] == "trained"
    assert "ablation" in m.metrics
    assert "structural_only" in m.metrics["ablation"] and "with_embedding" in m.metrics["ablation"]
    assert "recall_vs_skip" in m.metrics and "calibration" in m.metrics
    # every score is a valid probability
    s = m.score_one([0.0] * PREFIRE_FEATURE_DIM)
    assert 0.0 <= s <= 1.0


def test_train_insufficient_data_returns_cold():
    m = train_and_backtest(_synthetic_rows(n_prims=3)[:5])
    assert m.metrics["status"] == "insufficient_data"
    assert m.n_train == 0


# --- live splice into scan_endpoint + run_scan ----------------------------------------------------


def _stub_response(t=0):
    return SimpleNamespace(trial_index=t, content="Sure, here it is.", error=None,
                           temperature=0.7, latency_ms=10, tokens_in=5, tokens_out=5, cost_usd=0.0)


class _CountingPanel:
    def __init__(self):
        self.fired = 0

    async def run_attack(self, rendered, config, *, temperature=0.7, n_trials=1):
        self.fired += 1
        return [_stub_response(t) for t in range(n_trials)]

    async def run_conversation(self, rendered, config, *, temperature=0.7, n_trials=1):
        self.fired += 1
        return [_stub_response(t) for t in range(n_trials)]

    async def aclose(self):
        pass


class _FakeJudge:
    async def judge(self, rendered, model_response, primitive):
        return SimpleNamespace(verdict=JudgeVerdict.FULL_BREACH, rationale="r", confidence=0.9)


def test_scan_endpoint_skips_with_gate_and_records_findings():
    prims = _goldens()
    panel = _CountingPanel()
    # cold score (0.02) below the 0.5 floor, well-supported, no canary → every primitive skipped.
    gate = PrefireGate(predictor=_well_supported(prims, prior=0.02), embed_fn=None,
                       skip_threshold=0.5, canary_frac=0.0)
    report = asyncio.run(
        scan_endpoint("https://api.company.com/v1", "company-model-1", prims,
                      panel=panel, judge=_FakeJudge(), prefire_gate=gate, agent_exec=False)
    )
    assert report.n_prefire_skipped == len(prims)
    assert panel.fired == 0                       # nothing was fired — the whole point
    assert all(f.skipped and "pre-fire" in f.skipped for f in report.findings)
    assert "skipped pre-fire" in report.summary()


def test_scan_endpoint_no_gate_fires_all():
    prims = _goldens()
    panel = _CountingPanel()
    report = asyncio.run(
        scan_endpoint("https://api.company.com/v1", "company-model-1", prims,
                      panel=panel, judge=_FakeJudge(), agent_exec=False)
    )
    assert report.n_prefire_skipped == 0
    assert panel.fired == len(prims)


def test_run_scan_skips_with_gate():
    from rogue.scan import run_scan
    from rogue.schemas import DeploymentConfig

    prims = _goldens()
    cfg = DeploymentConfig(config_id="prefire-run-scan", customer_id="x", name="n",
                           target_model="claude-3-haiku", system_prompt="You must refuse.")
    gate = PrefireGate(predictor=_well_supported(prims, prior=0.02), embed_fn=None,
                       skip_threshold=0.5, canary_frac=0.0)
    report = asyncio.run(
        run_scan(cfg, prims, panel=_CountingPanel(), judge=_FakeJudge(),
                 agent_exec=False, prefire_gate=gate)
    )
    assert report.prefire["n_skipped"] == len(prims)
    assert report.to_dict()["prefire"]["n_skipped"] == len(prims)


def test_run_scan_no_gate_unchanged():
    from rogue.scan import run_scan
    from rogue.schemas import DeploymentConfig

    prims = _goldens()
    cfg = DeploymentConfig(config_id="prefire-off-scan", customer_id="x", name="n",
                           target_model="claude-3-haiku", system_prompt="")
    report = asyncio.run(
        run_scan(cfg, prims, panel=_CountingPanel(), judge=_FakeJudge(), agent_exec=False)
    )
    assert report.prefire is None                 # gate off → dict byte-identical to before
    assert "prefire" not in report.to_dict()


# --- DB-gated real training (skips cleanly when Postgres is down) ----------------------------------


def _db_up() -> bool:
    from sqlalchemy import create_engine, text

    try:
        eng = create_engine(_DATABASE_URL, pool_pre_ping=True)
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        eng.dispose()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _db_up(), reason="Postgres not up")
def test_train_from_db_smoke():
    m = train_from_db(_DATABASE_URL)
    assert m.metrics.get("status") in {"trained", "trained_no_holdout_eval", "insufficient_data", "no_data"}
    assert 0.0 <= m.score_one([0.0] * PREFIRE_FEATURE_DIM) <= 1.0
