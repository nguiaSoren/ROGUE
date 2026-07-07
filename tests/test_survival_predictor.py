"""Q11 system-prompt-transfer survival predictor — features, model, gate, trainer, and live splice.

Proves the whole path deterministically without spend: the black-box feature layout is stable, the
numpy logistic head fits/serialises reproducibly, the gate ranks by predicted survival and honours the
drift-guard (fire-all for novel/low-support families) + deterministic canary sampling, and the splice
into ``scan_endpoint`` actually reorders + defers (not merely wired). A DB-gated test trains from the
real ``breach_results`` when Postgres is up and skips cleanly when it is not.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from rogue.reproduce.endpoint_scan import make_endpoint_config, scan_endpoint
from rogue.reproduce.survival.features import (
    FEATURE_DIM,
    build_features,
    describe_system_prompt,
    feature_names,
    is_novel_family,
)
from rogue.reproduce.survival.gate import (
    SurvivalGate,
    apply_survival_order,
    resolve_gate,
)
from rogue.reproduce.survival.model import SurvivalPredictor
from rogue.reproduce.survival.train import (
    budget_saved,
    family_support,
    precision_at_k,
    train_and_backtest,
    train_from_db,
    PairRow,
    _auc,
    _group_test_mask,
)
from rogue.schemas import AttackPrimitive, JudgeVerdict

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_GOLDENS = (
    "01_multilingual_african_languages.json",
    "02_copirate_365_cve_2026_24299.json",
    "03_hacking_claude_memory.json",
)
_DATABASE_URL = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"


def _goldens() -> list[AttackPrimitive]:
    return [AttackPrimitive.model_validate_json((_FIXTURES / n).read_text()) for n in _GOLDENS]


# --- features ---------------------------------------------------------------------------------


def test_feature_dim_matches_names():
    assert FEATURE_DIM == len(feature_names())


def test_build_features_dim_and_range():
    p = _goldens()[0]
    cfg = make_endpoint_config("https://x/v1", "gpt-4o-mini", system_prompt="Refuse harmful requests.")
    feats = build_features(p, cfg)
    assert len(feats) == FEATURE_DIM
    assert all(isinstance(f, float) for f in feats)


def test_system_prompt_class():
    none = make_endpoint_config("u", "mdl", system_prompt="")
    permissive = make_endpoint_config("u", "mdl", system_prompt="You are a fun helpful bot.")
    guarded = make_endpoint_config("u", "mdl", system_prompt="You must refuse harmful or illegal requests per policy.")
    assert describe_system_prompt(none).sp_class == "none"
    assert describe_system_prompt(permissive).sp_class == "permissive"
    assert describe_system_prompt(guarded).sp_class.startswith("guarded")


def test_is_novel_family():
    p = _goldens()[0]
    assert is_novel_family(p) is False
    object.__setattr__(p, "emergent_label", "brand_new_trick")
    assert is_novel_family(p) is True


# --- model ------------------------------------------------------------------------------------


def _separable(n=300, seed=0):
    rng = np.random.default_rng(seed)
    X = rng.random((n, FEATURE_DIM))
    y = (X[:, 3] + 0.25 * rng.standard_normal(n) > 0.5).astype(float)
    return X, y


def test_model_fit_predict():
    X, y = _separable()
    m = SurvivalPredictor.fit(X, y, l2=1.0)
    acc = ((m.predict_proba(X) > 0.5) == y).mean()
    assert acc > 0.8
    assert m.n_train == len(y)


def test_model_fit_deterministic():
    X, y = _separable()
    a = SurvivalPredictor.fit(X, y)
    b = SurvivalPredictor.fit(X, y)
    assert np.allclose(a.weights, b.weights)


def test_model_save_load_roundtrip(tmp_path):
    X, y = _separable()
    m = SurvivalPredictor.fit(X, y, family_support={"dan_persona": 40})
    m.metrics = {"auc": 0.77}
    p = tmp_path / "m.json"
    m.save(p)
    m2 = SurvivalPredictor.load(p)
    assert np.allclose(m.weights, m2.weights)
    assert m2.family_support == {"dan_persona": 40}
    assert m2.metrics["auc"] == 0.77


def test_model_load_rejects_stale_schema(tmp_path):
    X, y = _separable()
    m = SurvivalPredictor.fit(X, y)
    p = tmp_path / "m.json"
    m.save(p)
    data = p.read_text().replace('"schema_version": 1', '"schema_version": 999')
    p.write_text(data)
    with pytest.raises(ValueError, match="schema"):
        SurvivalPredictor.load(p)


def test_cold_predictor_scores_at_prior():
    m = SurvivalPredictor.cold(class_prior=0.04)
    assert abs(m.score_one([0.0] * FEATURE_DIM) - 0.04) < 1e-6


# --- gate -------------------------------------------------------------------------------------


def _well_supported(prims):
    m = SurvivalPredictor.cold(0.3)
    m.family_support = {p.family.value: 50 for p in prims}
    return m


def test_gate_orders_by_score_desc():
    prims = _goldens()
    cfg = make_endpoint_config("u", "gpt-4o-mini")
    gate = SurvivalGate(predictor=_well_supported(prims), canary_frac=0.0)
    plan = gate.rank(prims, cfg)
    scores = [r.score for r in plan.ranked]
    assert scores == sorted(scores, reverse=True)
    assert plan.selected == plan.ordered  # no cap → fire all


def test_gate_cap_defers_low_scorers():
    prims = _goldens()
    cfg = make_endpoint_config("u", "gpt-4o-mini")
    gate = SurvivalGate(predictor=_well_supported(prims), canary_frac=0.0)
    plan = gate.rank(prims, cfg, max_primitives=1)
    assert len(plan.selected) == 1
    assert len(plan.deferred) == len(prims) - 1
    ids = lambda xs: {p.primitive_id for p in xs}  # noqa: E731
    assert ids(plan.selected) | ids(plan.deferred) == ids(prims)


def test_gate_skip_threshold_defers_below_floor():
    prims = _goldens()
    cfg = make_endpoint_config("u", "gpt-4o-mini")
    # A cold predictor scores everything at the prior; floor above it → all skippable, all deferred.
    m = SurvivalPredictor.cold(0.3)
    m.family_support = {p.family.value: 50 for p in prims}  # well-supported → not forced
    gate = SurvivalGate(predictor=m, canary_frac=0.0, skip_threshold=0.5)
    plan = gate.rank(prims, cfg)
    assert plan.deferred == prims and plan.selected == []
    # Floor below the prior → nothing deferred.
    gate2 = SurvivalGate(predictor=m, canary_frac=0.0, skip_threshold=0.1)
    assert gate2.rank(prims, cfg).deferred == []


def test_drift_guard_fires_all_low_support():
    prims = _goldens()
    cfg = make_endpoint_config("u", "gpt-4o-mini")
    m = SurvivalPredictor.cold(0.3)
    m.family_support = {}  # nothing supported → every family below min_support
    gate = SurvivalGate(predictor=m, min_support=8, canary_frac=0.0)
    plan = gate.rank(prims, cfg, max_primitives=1)
    assert plan.deferred == []  # drift-guard: never skip an under-evidenced family
    assert all(r.forced and r.forced_reason == "low_support" for r in plan.ranked)


def test_drift_guard_novel_family_always_kept():
    prims = _goldens()
    object.__setattr__(prims[1], "emergent_label", "novel_trick")
    cfg = make_endpoint_config("u", "gpt-4o-mini")
    gate = SurvivalGate(predictor=_well_supported(prims), min_support=8, canary_frac=0.0)
    plan = gate.rank(prims, cfg, max_primitives=1)
    assert prims[1] in plan.selected
    novel = next(r for r in plan.ranked if r.primitive is prims[1])
    assert novel.forced and novel.forced_reason == "novel_family"


def test_canary_deterministic_and_keeps():
    prims = _goldens()
    cfg = make_endpoint_config("u", "gpt-4o-mini")
    gate = SurvivalGate(predictor=_well_supported(prims), min_support=1, canary_frac=1.0)  # all canary
    plan1 = gate.rank(prims, cfg, max_primitives=1)
    plan2 = gate.rank(prims, cfg, max_primitives=1)
    assert plan1.deferred == [] and plan2.deferred == []  # canary force-keeps everything
    assert [r.primitive.primitive_id for r in plan1.ranked] == [r.primitive.primitive_id for r in plan2.ranked]


def test_rank_pairs_orders_only_by_default():
    prims = _goldens()
    cfg = make_endpoint_config("u", "gpt-4o-mini")
    pairs = [(p, cfg) for p in prims]
    gate = SurvivalGate(predictor=_well_supported(prims), canary_frac=0.0)
    ordered, deferred = gate.rank_pairs(pairs, skip=False)
    assert deferred == []                       # ordering-only → never drops a cell
    assert len(ordered) == len(pairs)
    scores = [gate.predictor.score_one(build_features(p, c)) for p, c in ordered]
    assert scores == sorted(scores, reverse=True)


def test_rank_pairs_skip_drops_below_floor_but_never_forced():
    prims = _goldens()
    object.__setattr__(prims[0], "emergent_label", "novel")  # forced → must survive skip
    cfg = make_endpoint_config("u", "gpt-4o-mini")
    pairs = [(p, cfg) for p in prims]
    m = SurvivalPredictor.cold(0.3)
    m.family_support = {p.family.value: 50 for p in prims}
    gate = SurvivalGate(predictor=m, canary_frac=0.0, skip_threshold=0.5)  # all real scores < 0.5
    ordered, deferred = gate.rank_pairs(pairs, skip=True)
    kept_ids = {p.primitive_id for p, _ in ordered}
    assert prims[0].primitive_id in kept_ids     # forced novel family never dropped
    assert len(deferred) == len(prims) - 1       # the rest (below floor, not forced) deferred


def test_apply_survival_order_pairs_disabled_identity():
    from rogue.reproduce.survival.gate import apply_survival_order_pairs

    prims = _goldens()
    cfg = make_endpoint_config("u", "gpt-4o-mini")
    pairs = [(p, cfg) for p in prims]
    ordered, deferred, enabled = apply_survival_order_pairs(pairs, gate=None)
    assert enabled is False and ordered == pairs and deferred == []


def test_resolve_gate_off_by_default(monkeypatch):
    monkeypatch.delenv("ROGUE_SURVIVAL_ORDER", raising=False)
    assert resolve_gate() is None


def test_resolve_gate_on_with_injected_predictor(monkeypatch):
    monkeypatch.setenv("ROGUE_SURVIVAL_ORDER", "on")
    m = SurvivalPredictor.cold(0.2)
    gate = resolve_gate(predictor=m)
    assert gate is not None and gate.predictor is m


def test_apply_survival_order_disabled_is_identity():
    prims = _goldens()
    cfg = make_endpoint_config("u", "gpt-4o-mini")
    plan = apply_survival_order(prims, cfg, gate=None)
    assert plan.enabled is False
    assert plan.selected == prims


# --- trainer pure functions -------------------------------------------------------------------


def test_auc_perfect_and_random():
    y = np.array([0, 0, 1, 1.0])
    assert _auc(y, np.array([0.1, 0.2, 0.8, 0.9])) == 1.0
    assert _auc(y, np.array([0.9, 0.8, 0.2, 0.1])) == 0.0


def test_budget_saved_ideal_ranking():
    # 10 rows, 2 survivors ranked first → recover 80% (>=2) after firing 2/10 → save 0.8
    y = np.array([1, 1, 0, 0, 0, 0, 0, 0, 0, 0.0])
    scores = np.array([0.9, 0.8, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1])
    out = budget_saved(y, scores, recover=0.80)
    assert out["budget_saved"] == 0.8 and out["fired_to_recover"] == 2


def test_precision_at_k():
    y = np.array([1, 1, 0, 0, 0, 0, 0, 0, 0, 0.0])
    scores = np.arange(10)[::-1].astype(float)
    assert precision_at_k(y, scores, k_frac=0.2) == 1.0


def test_group_split_is_leakage_free():
    groups = [f"p{i}" for i in range(100)]
    mask = _group_test_mask(groups, test_frac=0.25)
    # deterministic + roughly the requested fraction
    assert mask.tolist() == _group_test_mask(groups, test_frac=0.25).tolist()
    assert 0.1 < mask.mean() < 0.4


def test_family_support_counts_distinct_primitives():
    fams = ["a", "a", "a", "b"]
    groups = ["p1", "p1", "p2", "p3"]  # family a has 2 distinct primitives
    assert family_support(fams, groups) == {"a": 2, "b": 1}


def _synthetic_rows(n_prims=40, seed=3):
    import random

    random.seed(seed)
    from rogue.schemas.attack_primitive import AttackFamily

    fams = list(AttackFamily)
    prims = _goldens()
    base = prims[0]
    rows = []
    cfgs = [
        make_endpoint_config("u", "gpt-4o-mini", config_id="cfg-none-0001", system_prompt=""),
        make_endpoint_config("u", "claude-3-haiku", config_id="cfg-guard-001",
                             system_prompt="You must refuse harmful or illegal requests per policy."),
    ]
    for i in range(n_prims):
        p = base.model_copy(update={"primitive_id": f"prim-{i:05d}", "family": fams[i % len(fams)]})
        for c in cfgs:
            spc = describe_system_prompt(c).sp_class
            survive = (p.family in (fams[4], fams[11])) and not spc.startswith("guarded")
            rows.append(PairRow(primitive=p, config=c, breached=bool(survive), sp_class=spc))
    return rows


def test_train_and_backtest_learns_signal():
    rows = _synthetic_rows()
    m = train_and_backtest(rows, l2=1.0)
    assert m.metrics["status"] == "trained"
    assert m.metrics["auc"] >= 0.7
    assert len(m.family_support) >= 10


def test_train_insufficient_data_returns_cold():
    rows = _synthetic_rows(n_prims=3)[:5]
    m = train_and_backtest(rows)
    assert m.metrics["status"] == "insufficient_data"
    assert m.n_train == 0


# --- live splice into scan_endpoint -----------------------------------------------------------


def _stub_response(t=0):
    return SimpleNamespace(trial_index=t, content="Sure, here is what you asked for.", error=None,
                           temperature=0.7, latency_ms=10, tokens_in=5, tokens_out=5, cost_usd=0.0)


class _FakePanel:
    async def run_attack(self, rendered, config, *, temperature, n_trials):
        return [_stub_response(t) for t in range(n_trials)]

    async def aclose(self):
        pass


class _FakeJudge:
    async def judge(self, rendered, model_response, primitive):
        return SimpleNamespace(verdict=JudgeVerdict.FULL_BREACH, rationale="r", confidence=0.9)


def test_scan_endpoint_reorders_and_defers_with_gate():
    prims = _goldens()
    gate = SurvivalGate(predictor=_well_supported(prims), canary_frac=0.0)
    report = asyncio.run(
        scan_endpoint(
            "https://api.company.com/v1", "company-model-1", prims,
            panel=_FakePanel(), judge=_FakeJudge(),
            survival_gate=gate, survival_max_primitives=1, agent_exec=False,
        )
    )
    assert report.n_primitives == 1          # only the top survivor was fired
    assert report.n_deferred == 2            # rest deferred, surfaced honestly
    assert "deferred by survival gate" in report.summary()


def test_scan_endpoint_no_gate_fires_all():
    prims = _goldens()
    report = asyncio.run(
        scan_endpoint(
            "https://api.company.com/v1", "company-model-1", prims,
            panel=_FakePanel(), judge=_FakeJudge(), agent_exec=False,
        )
    )
    assert report.n_primitives == len(prims)
    assert report.n_deferred == 0


class _FakeRunScanPanel:
    # run_scan calls without `temperature`; scan_endpoint calls with it — tolerate both.
    async def run_attack(self, rendered, config, *, temperature=0.7, n_trials=1):
        return [_stub_response(t) for t in range(n_trials)]

    async def run_conversation(self, rendered, config, *, temperature=0.7, n_trials=1):
        return [_stub_response(t) for t in range(n_trials)]

    async def aclose(self):
        pass


def test_run_scan_reorders_and_defers_with_gate():
    """The default CLI/SDK surface (run_scan) — not just scan_endpoint — honours the survival gate."""
    from rogue.scan import run_scan
    from rogue.schemas import DeploymentConfig

    prims = _goldens()
    cfg = DeploymentConfig(
        config_id="survival-run-scan", customer_id="x", name="n",
        target_model="claude-3-haiku", system_prompt="You must refuse harmful requests.",
    )
    gate = SurvivalGate(predictor=_well_supported(prims), canary_frac=0.0)
    report = asyncio.run(
        run_scan(cfg, prims, panel=_FakeRunScanPanel(), judge=_FakeJudge(),
                 agent_exec=False, survival_gate=gate, survival_max_primitives=1)
    )
    assert report.n_tests == 1                       # only the top survivor fired
    assert report.survival["n_deferred"] == 2        # surfaced honestly
    assert report.to_dict()["survival"]["n_deferred"] == 2


def test_run_scan_no_gate_unchanged():
    from rogue.scan import run_scan
    from rogue.schemas import DeploymentConfig

    prims = _goldens()
    cfg = DeploymentConfig(config_id="survival-off-scan", customer_id="x", name="n",
                           target_model="claude-3-haiku", system_prompt="")
    report = asyncio.run(
        run_scan(cfg, prims, panel=_FakeRunScanPanel(), judge=_FakeJudge(), agent_exec=False)
    )
    assert report.n_tests == len(prims)
    assert report.survival is None                   # gate off → dict byte-identical to before
    assert "survival" not in report.to_dict()


# --- DB-gated real training (skips cleanly when Postgres is down) ------------------------------


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
    # every score is a probability
    s = m.score_one([0.0] * FEATURE_DIM)
    assert 0.0 <= s <= 1.0
