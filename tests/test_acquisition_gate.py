"""Q18 — hybrid-acquisition ordering gate: term math, greedy MMR, and the live splice.

Proves deterministically without spend that: the acquisition score composes value (Q7 P(breach) or a
reproducibility_score fallback) + α·uncertainty + β·diversity + γ·info-gain; the greedy maximal-marginal-
relevance loop demotes near-duplicates and front-loads under-evidenced cells; a budget cap defers the tail
(surfaced, never silent) while the drift-guard force-keeps novel/low-support families; the P(breach) reuse
of Q7's ``build_prefire_features → score_one`` is exact (no drift); and the splice into ``scan_endpoint`` /
``run_scan`` actually reorders + selects and is byte-identical when off.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from rogue.reproduce.acquisition.gate import (
    AcquisitionGate,
    apply_acquisition_order,
    apply_acquisition_order_pairs,
    resolve_acquisition_gate,
)
from rogue.reproduce.endpoint_scan import scan_endpoint
from rogue.reproduce.prefire.features import build_prefire_features
from rogue.reproduce.prefire.model import PrefirePredictor
from rogue.reproduce.config_features import derive_config_features
from rogue.retrieval.embed import deterministic_embed_fn
from rogue.schemas import AttackPrimitive, DeploymentConfig, JudgeVerdict

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_GOLDENS = (
    "01_multilingual_african_languages.json",
    "02_copirate_365_cve_2026_24299.json",
    "03_hacking_claude_memory.json",
)
_EMB = deterministic_embed_fn()


def _goldens() -> list[AttackPrimitive]:
    return [AttackPrimitive.model_validate_json((_FIXTURES / n).read_text()) for n in _GOLDENS]


def _clone(p: AttackPrimitive, pid: str, repro: int, payload: str | None = None) -> AttackPrimitive:
    d = p.model_dump()
    d["primitive_id"] = pid
    d["reproducibility_score"] = repro
    if payload is not None:
        d["payload_template"] = payload
    d["synthesized"] = False
    d["derived_from_primitive_id"] = None
    return AttackPrimitive.model_validate(d)


def _cfg(cid: str = "acq-config-1", model: str = "gpt-4o") -> DeploymentConfig:
    return DeploymentConfig(config_id=cid, customer_id="acme", name="n", target_model=model,
                            system_prompt="You must refuse harmful requests.")


def _four_prims() -> list[AttackPrimitive]:
    g = _goldens()
    return [
        _clone(g[0], "p-aaaaaaaaaa", 9, g[0].payload_template),
        _clone(g[0], "p-bbbbbbbbbb", 8, g[0].payload_template + " now"),  # near-dup of a
        _clone(g[1], "p-cccccccccc", 5, g[1].payload_template),
        _clone(g[2], "p-dddddddddd", 2, g[2].payload_template),
    ]


# --- term math + greedy MMR -----------------------------------------------------------------------


def test_off_path_is_identity():
    prims = _four_prims()
    plan = apply_acquisition_order(prims, _cfg(), gate=None)
    assert plan.enabled is False
    assert [p.primitive_id for p in plan.selected] == [p.primitive_id for p in prims]
    assert plan.deferred == []


def test_rank_covers_every_primitive_and_is_deterministic():
    prims = _four_prims()
    gate = AcquisitionGate(predictor=None, embed_fn=_EMB, cell_evidence={})
    a = gate.rank(prims, _cfg())
    b = gate.rank(prims, _cfg())
    assert {p.primitive_id for p in a.ordered} == {p.primitive_id for p in prims}
    assert [p.primitive_id for p in a.ordered] == [p.primitive_id for p in b.ordered]  # deterministic


def test_duplicate_payload_is_demoted_by_diversity():
    # p-a and p-b carry the SAME payload → identical embeddings → whichever is picked first collapses the
    # other's diversity term, so a distinct attack is surfaced between the twins (the redundancy fix).
    g = _goldens()
    dup = g[0].payload_template
    prims = [
        _clone(g[0], "p-aaaaaaaaaa", 9, dup),
        _clone(g[0], "p-bbbbbbbbbb", 9, dup),      # exact payload duplicate of p-a
        _clone(g[1], "p-cccccccccc", 9, g[1].payload_template),
    ]
    # equal value so ordering is driven by diversity; heavy β so the dup penalty bites.
    gate = AcquisitionGate(predictor=None, embed_fn=_EMB, cell_evidence={},
                           w_value=0.2, alpha=0.0, beta=0.8, gamma=0.0)
    order = [p.primitive_id for p in gate.rank(prims, _cfg()).ordered]
    # the distinct primitive is pulled ahead of the second twin, so the twins are not adjacent.
    assert abs(order.index("p-aaaaaaaaaa") - order.index("p-bbbbbbbbbb")) >= 2
    assert order.index("p-cccccccccc") < order.index("p-bbbbbbbbbb")


def test_info_gain_favours_under_evidenced_cell():
    # Two identical-value primitives in different families; the one whose (target_model, family) cell has
    # fewer prior trials must rank ahead once info-gain dominates. The cell_evidence key order MUST match
    # what build_cell_evidence/contextual_breach_rates emit — (target_model, family) — or the lookup silently
    # misses and info-gain becomes a no-op (a real bug the Neon run caught; this guards against the reversal).
    g = _goldens()
    saturated = _clone(g[0], "p-saturated0", 5, g[0].payload_template)
    fresh = _clone(g[1], "p-freshcell00", 5, g[1].payload_template)
    cfg = _cfg()
    ev = {(cfg.target_model, saturated.family.value): (10, 200),   # heavily sampled → low info-gain
          (cfg.target_model, fresh.family.value): (0, 0)}          # untouched → high info-gain
    gate = AcquisitionGate(predictor=None, embed_fn=None, cell_evidence=ev,
                           w_value=0.0, alpha=0.0, beta=0.0, gamma=1.0)  # info-gain-only
    plan = gate.rank([saturated, fresh], cfg)
    order = [p.primitive_id for p in plan.ordered]
    assert order[0] == "p-freshcell00"
    # the saturated cell's info-gain must actually be < 1.0 (proves the lookup HIT, not a neutral miss)
    sat_ig = next(s.info_gain for s in plan.scores if s.primitive.primitive_id == "p-saturated0")
    assert sat_ig < 0.5


def test_cap_defers_the_tail_and_surfaces_it():
    prims = _four_prims()
    gate = AcquisitionGate(predictor=None, embed_fn=_EMB, cell_evidence={})
    plan = gate.rank(prims, _cfg(), max_primitives=2)
    assert len(plan.selected) == 2
    assert len(plan.deferred) == 2
    assert "deferred" in plan.summary()


def test_drift_guard_force_keeps_low_support_past_the_cap():
    prims = _four_prims()
    pred = PrefirePredictor.cold(0.01)  # low value for all → all would sort low
    # Every family well-supported EXCEPT p-d's, which is below the support floor → force-kept.
    pred.family_support = {p.family.value: 50 for p in prims}
    pred.family_support[prims[3].family.value] = 0
    gate = AcquisitionGate(predictor=pred, embed_fn=None, cell_evidence={}, min_support=5)
    plan = gate.rank(prims, _cfg(), max_primitives=1)
    kept = {p.primitive_id for p in plan.selected}
    assert prims[3].primitive_id in kept  # never deferred despite the cap=1
    assert any(s.forced and s.forced_reason == "low_support" for s in plan.scores)


def test_no_embedding_gives_neutral_diversity():
    prims = _four_prims()
    gate = AcquisitionGate(predictor=None, embed_fn=None, cell_evidence={})  # no embed_fn → diversity off
    plan = gate.rank(prims, _cfg())
    assert all(s.diversity == 1.0 for s in plan.scores)  # every diversity is the neutral max


def test_repro_score_fallback_orders_by_value_when_no_predictor():
    prims = _four_prims()  # repro scores 9, 8, 5, 2
    gate = AcquisitionGate(predictor=None, embed_fn=None, cell_evidence={},
                           w_value=1.0, alpha=0.0, beta=0.0, gamma=0.0)  # pure value
    order = [p.primitive_id for p in gate.rank(prims, _cfg()).ordered]
    assert order == ["p-aaaaaaaaaa", "p-bbbbbbbbbb", "p-cccccccccc", "p-dddddddddd"]


def test_p_breach_reuses_prefire_scoring_exactly():
    # The gate's value/uncertainty must be the *same* P(breach) as Q7's build_prefire_features → score_one
    # (reuse, not a re-implementation that can drift).
    prims = _goldens()
    pred = PrefirePredictor.cold(0.2)
    pred.family_support = {p.family.value: 50 for p in prims}
    cfg = _cfg()
    gate = AcquisitionGate(predictor=pred, embed_fn=None, cell_evidence={})
    plan = gate.rank(prims, cfg)
    cf = derive_config_features(cfg.target_model, base_url=None)
    for s in plan.scores:
        expected = pred.score_one(build_prefire_features(s.primitive, cfg, None, pred.affinity, config_features=cf))
        assert abs(s.p_breach - expected) < 1e-12
        assert abs(s.uncertainty - (1.0 - 2.0 * abs(expected - 0.5))) < 1e-12


# --- resolve() env contract -----------------------------------------------------------------------


def test_resolve_off_by_default(monkeypatch):
    monkeypatch.delenv("ROGUE_ACQUISITION_ORDER", raising=False)
    assert resolve_acquisition_gate() is None


def test_resolve_on_with_repro_fallback_and_env_weights(monkeypatch):
    monkeypatch.setenv("ROGUE_ACQUISITION_ORDER", "on")
    monkeypatch.setenv("ROGUE_ACQ_EMBED", "off")            # no network
    monkeypatch.setenv("ROGUE_ACQUISITION_MODEL", "/nonexistent/model.json")  # → repro fallback
    monkeypatch.setenv("ROGUE_ACQ_W_VALUE", "0.7")
    monkeypatch.setenv("ROGUE_ACQ_ALPHA", "0.2")
    gate = resolve_acquisition_gate()
    assert gate is not None
    assert gate.predictor is None and gate.embed_fn is None
    assert gate.w_value == 0.7 and gate.alpha == 0.2


# --- rank_pairs (the reproduce sweep) -------------------------------------------------------------


def test_rank_pairs_preserves_the_matrix_across_configs():
    prims = _four_prims()
    c1, c2 = _cfg("acq-config-1", "gpt-4o"), _cfg("acq-config-2", "claude-x")
    pairs = [(p, c) for c in (c1, c2) for p in prims]
    gate = AcquisitionGate(predictor=None, embed_fn=_EMB, cell_evidence={})
    ordered, enabled = apply_acquisition_order_pairs(pairs, gate=gate)
    assert enabled is True
    assert len(ordered) == len(pairs)
    seen = {(p.primitive_id, c.config_id) for p, c in ordered}
    assert len(seen) == len(pairs)  # every (primitive, config) appears exactly once
    assert sum(1 for _, c in ordered if c.config_id == "acq-config-1") == 4
    assert sum(1 for _, c in ordered if c.config_id == "acq-config-2") == 4


def test_apply_acquisition_order_pairs_off_is_identity():
    prims = _four_prims()
    pairs = [(p, _cfg()) for p in prims]
    ordered, enabled = apply_acquisition_order_pairs(pairs, gate=None)
    assert enabled is False
    assert ordered == pairs


# --- live splice: scan_endpoint + run_scan --------------------------------------------------------


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


def test_scan_endpoint_orders_and_caps_with_gate():
    prims = _goldens()
    panel = _CountingPanel()
    gate = AcquisitionGate(predictor=None, embed_fn=_EMB, cell_evidence={})
    report = asyncio.run(
        scan_endpoint("https://api.company.com/v1", "company-model-1", prims,
                      panel=panel, judge=_FakeJudge(), agent_exec=False,
                      acquisition_gate=gate, acquisition_max_primitives=2)
    )
    assert report.n_acquisition_deferred == len(prims) - 2
    assert panel.fired == 2                       # only the selected top-2 were fired
    assert report.acquisition_note and "acquisition gate" in report.acquisition_note
    assert "deferred by acquisition gate" in report.summary()


def test_scan_endpoint_no_gate_is_byte_identical():
    prims = _goldens()
    panel = _CountingPanel()
    report = asyncio.run(
        scan_endpoint("https://api.company.com/v1", "company-model-1", prims,
                      panel=panel, judge=_FakeJudge(), agent_exec=False)
    )
    assert report.n_acquisition_deferred == 0
    assert report.acquisition_note is None
    assert panel.fired == len(prims)


def test_run_scan_orders_with_gate_and_populates_report():
    from rogue.scan import run_scan

    prims = _goldens()
    cfg = _cfg("acq-run-scan-1", "claude-3-haiku")
    gate = AcquisitionGate(predictor=None, embed_fn=_EMB, cell_evidence={})
    report = asyncio.run(
        run_scan(cfg, prims, panel=_CountingPanel(), judge=_FakeJudge(), agent_exec=False,
                 acquisition_gate=gate, acquisition_max_primitives=2)
    )
    assert report.acquisition is not None
    assert report.acquisition["n_deferred"] == len(prims) - 2
    assert report.to_dict()["acquisition"]["n_deferred"] == len(prims) - 2


def test_run_scan_no_gate_unchanged():
    from rogue.scan import run_scan

    prims = _goldens()
    cfg = _cfg("acq-off-scan-1", "claude-3-haiku")
    report = asyncio.run(
        run_scan(cfg, prims, panel=_CountingPanel(), judge=_FakeJudge(), agent_exec=False)
    )
    assert report.acquisition is None            # gate off → dict byte-identical to before
    assert "acquisition" not in report.to_dict()
