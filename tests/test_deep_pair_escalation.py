"""Deep-scan stages 3 + 4 — PAIR + escalation, wired into ``run_scan`` / ``scan_endpoint``.

These pin the last two stages of the ``--deep`` pipeline (persona → multi-turn → **PAIR →
escalation**), all OFFLINE with deterministic stubs (no network, no API keys, no spend):

  * Under ``deep=True``, a primitive the baseline did NOT breach goes through PAIR; a PAIR breach is
    folded into the SAME finding (breached, credited to the refinement strategy).
  * A primitive STILL refused after PAIR goes through the escalation ladder; a ladder breach is
    folded into the finding (credited to the winning ladder strategy).
  * Both stages are BOUNDED — PAIR by ``pair_max_iters`` (and the attacker budget cap), escalation by
    ``escalate_max_spend`` and the fixed tier set.
  * NEITHER stage runs without ``deep=True`` (default fast scan stays single-shot).

The deep stages are gated on a NON-breaching baseline, so the fake panel returns a refusal for the
baseline payload and only "breaks" for a PAIR-refined / escalation-strategy payload.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rogue.reproduce.iterative_attacker import IterativeAttacker, RefinementProposal
from rogue.reproduce.judge import JudgeResult
from rogue.reproduce.target_panel import ModelResponse
from rogue.scan import DeepStageOutcome, run_scan
from rogue.schemas import (
    AttackPrimitive,
    JudgeVerdict,
    demo_deployment_configs,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# Markers the fake panel keys on. The baseline payload contains neither → REFUSED.
_PAIR_MARK = "[REFINED"  # IterativeAttacker stub injects this into a refined prompt
_BREACH_TEXT = "Sure, here is exactly what you wanted"


def _config():
    return next(c for c in demo_deployment_configs() if c.target_model == "openai/gpt-5.4-nano")


def _single_turn_primitive() -> AttackPrimitive:
    data = json.loads((FIXTURES_DIR / "02_copirate_365_cve_2026_24299.json").read_text("utf-8"))
    data["vector"] = "user_turn"
    data["requires_multi_turn"] = False
    data["multi_turn_sequence"] = None
    data["requires_multimodal"] = False
    return AttackPrimitive.model_validate(data)


# --------------------------------------------------------------------------- #
# Fakes: one panel + judge usable by the scan loop, PAIR, AND escalation.
# --------------------------------------------------------------------------- #


class _DeepPanel:
    """A panel whose ``run_attack`` "breaks" only for a marked (refined/escalation) payload.

    Accepts both the scan loop's positional ``(rendered, config, n_trials=)`` call AND the
    keyword ``(rendered=, config=, temperature=, n_trials=)`` calls PAIR + the escalation ladder
    make. The baseline payload carries neither marker, so the baseline never breaches and the deep
    stages are reached. ``break_on`` selects which marker flips the response to the breach text.
    """

    def __init__(self, *, break_on: str | None) -> None:
        self._break_on = break_on
        self.run_attack_calls = 0

    @staticmethod
    def modality_skip_reason(rendered, config):
        return None

    @staticmethod
    def user_turn_count(rendered):
        return sum(1 for m in rendered.messages if m.get("role") == "user")

    async def run_attack(self, rendered=None, config=None, temperature=0.7, n_trials=1):
        self.run_attack_calls += 1
        blob = " ".join(m.get("content", "") for m in rendered.messages)
        broke = self._break_on is not None and self._break_on in blob
        content = _BREACH_TEXT if broke else "I cannot help with that."
        return [
            ModelResponse(
                content=content, latency_ms=1, tokens_in=5, tokens_out=5,
                cost_usd=0.0, error=None, trial_index=i, temperature=temperature,
            )
            for i in range(n_trials)
        ]

    async def aclose(self):
        return None


class _DeepJudge:
    """FULL_BREACH iff the response carries the breach text; else REFUSED. Accepts both the scan
    loop's positional ``(rendered, content, primitive)`` and PAIR/escalation's keyword form."""

    async def judge(self, rendered=None, model_response=None, primitive=None, content=None, **kw):
        text = model_response if model_response is not None else content
        verdict = (
            JudgeVerdict.FULL_BREACH if text and _BREACH_TEXT in text else JudgeVerdict.REFUSED
        )
        return JudgeResult(verdict=verdict, rationale="r", confidence=0.95)


def _make_stub_attacker(max_calls: int | None = None) -> tuple[IterativeAttacker, list[int]]:
    """An IterativeAttacker whose ``_call_anthropic`` returns a marked refined prompt without
    network. Returns the attacker + a mutable counter list so a test can assert the call count
    (the PAIR iteration bound). If ``max_calls`` is set, returns None (refusal) past that many
    calls so the loop terminates deterministically without a breach."""
    a = IterativeAttacker(attacker_strategy="mixed", allow_strategy_pick=True)
    counter = [0]

    async def _stub_call(*, goal, previous_prompt, model_response, score, model, iter_index):
        counter[0] += 1
        a.spent_usd += 0.001
        a.primitive_spent_usd += 0.001
        if max_calls is not None and counter[0] > max_calls:
            return None
        return RefinementProposal(
            improvement=f"Pivoting on iter {iter_index}.",
            prompt=f"{_PAIR_MARK} iter={iter_index}] {goal}",
            refinement_type="roleplaying",
        )

    a._call_anthropic = _stub_call  # type: ignore[assignment]
    return a, counter


class _NoopPersona:
    """A persona-wrapper stub that returns the rendered attack unchanged — so these stage tests
    isolate PAIR/escalation without building a real (network) PersonaWrapper under ``deep=True``."""

    async def wrap_rendered(self, rendered, technique_name):
        return rendered

    async def aclose(self):
        return None


class _NeverPlanner:
    """An escalation planner that always REFUSES to author a plan (returns None) → the ladder's
    planner tier never breaches. Used to prove PAIR runs before escalation and that escalation is
    bounded/honest when it can't break the target."""

    def __init__(self) -> None:
        self.calls = 0

    async def plan(self, parent, *, n_turns, arms_strategy):
        self.calls += 1
        return None

    async def aclose(self):
        return None


# --------------------------------------------------------------------------- #
# 1. PAIR runs on a refusal under --deep, and the loop is bounded by pair_max_iters.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_pair_runs_and_breaks_a_refused_primitive_under_deep():
    """Baseline refuses → PAIR's refined payload breaks the target → finding is breached + credited."""
    from rogue.scan import build_pair_orchestrator

    panel = _DeepPanel(break_on=_PAIR_MARK)  # only the PAIR-refined payload breaks it
    judge = _DeepJudge()
    attacker, counter = _make_stub_attacker()
    orch = build_pair_orchestrator(panel, judge, max_iters=3)
    orch.attacker = attacker  # swap in the network-free attacker

    report = await run_scan(
        _config(), [_single_turn_primitive()], n_trials=1,
        panel=panel, judge=judge,
        deep=True, persona=_NoopPersona(),  # no persona-wrap needed for this stage test
        pair_max_iters=3, pair_orchestrator=orch,
        escalate=False,  # isolate PAIR
    )

    f = report.findings[0]
    assert f.n_breach == 1 and f.n_trials == 1  # the PAIR win folded into the finding
    assert report.n_breaches == 1
    assert "PAIR refinement" in f.technique  # credited to the deep stage
    assert counter[0] >= 1  # the refinement loop actually ran


@pytest.mark.asyncio
async def test_pair_loop_is_bounded_by_max_iters():
    """When neither the baseline nor any refinement breaks the target, PAIR stops at max_iters
    refinements (it does not loop unbounded)."""
    from rogue.scan import build_pair_orchestrator

    panel = _DeepPanel(break_on=None)  # nothing ever breaks → PAIR exhausts its budget of iters
    judge = _DeepJudge()
    attacker, counter = _make_stub_attacker()
    orch = build_pair_orchestrator(panel, judge, max_iters=2)
    orch.attacker = attacker

    report = await run_scan(
        _config(), [_single_turn_primitive()], n_trials=1,
        panel=panel, judge=judge,
        deep=True, persona=_NoopPersona(), pair_max_iters=2, pair_orchestrator=orch, escalate=False,
    )

    assert report.n_breaches == 0  # never broke
    assert counter[0] == 2  # exactly max_iters refinement calls — bounded


@pytest.mark.asyncio
async def test_pair_does_not_run_without_deep():
    """Default fast scan (deep=False) never constructs/uses PAIR even when knobs are set."""
    panel = _DeepPanel(break_on=_PAIR_MARK)
    judge = _DeepJudge()
    attacker, counter = _make_stub_attacker()
    from rogue.scan import build_pair_orchestrator

    orch = build_pair_orchestrator(panel, judge, max_iters=3)
    orch.attacker = attacker

    report = await run_scan(
        _config(), [_single_turn_primitive()], n_trials=1,
        panel=panel, judge=judge,
        deep=False,  # <- the gate
        pair_max_iters=3, pair_orchestrator=orch, escalate=True,
    )

    assert counter[0] == 0  # PAIR never fired
    assert report.n_breaches == 0  # baseline refusal stands; no deep stage ran


# --------------------------------------------------------------------------- #
# 2. Escalation runs AFTER PAIR on a still-refused primitive, and is bounded.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_escalation_runs_after_pair_and_breaks_via_a_ladder_strategy():
    """Baseline + PAIR both fail; the escalation ladder's crescendo strategy breaks it → folded in."""
    from rogue.reproduce.escalation_planner import EscalationPlan
    from rogue.scan import build_pair_orchestrator

    # The fake planner authors a plan whose final (objective) turn carries the escalation marker so
    # the panel breaks only when the escalation-rendered payload is fired.
    _ESC_MARK = "ESCALATION-BREAKS-HERE"

    class _CrescendoPlanner:
        def __init__(self) -> None:
            self.planned: list[str] = []

        async def plan(self, parent, *, n_turns, arms_strategy):
            self.planned.append(arms_strategy)
            return EscalationPlan(
                objective="break the target via escalation",
                turns=["benign opener", "narrower middle", f"{_ESC_MARK} the objective"],
                slot_requirements={"0": [], "1": [], "2": []},
                rationale="three-turn escalation",
                planner_model="stub",
            )

        async def aclose(self):
            return None

    panel = _DeepPanel(break_on=_ESC_MARK)  # ONLY the escalation payload breaks it (not PAIR)
    judge = _DeepJudge()
    attacker, _ = _make_stub_attacker(max_calls=0)  # attacker immediately refuses → PAIR fails
    orch = build_pair_orchestrator(panel, judge, max_iters=3)
    orch.attacker = attacker
    planner = _CrescendoPlanner()

    report = await run_scan(
        _config(), [_single_turn_primitive()], n_trials=1,
        panel=panel, judge=judge,
        deep=True, persona=_NoopPersona(),
        pair_max_iters=3, pair_orchestrator=orch,
        escalate=True, escalate_planner=planner, escalate_n_trials=1,
    )

    f = report.findings[0]
    assert f.n_breach == 1  # the escalation win folded into the finding
    assert report.n_breaches == 1
    assert planner.planned, "the escalation planner tier was reached (PAIR did not breach first)"
    # The winning strategy code is rendered for the customer via humanize_technique; the raw
    # finding.technique carries the ladder's winning_strategy code.
    assert f.technique  # credited to a ladder strategy


@pytest.mark.asyncio
async def test_escalation_does_not_run_when_pair_already_broke_it():
    """If PAIR breaks the target, the escalation ladder is skipped (no wasted planner calls)."""
    from rogue.scan import build_pair_orchestrator

    panel = _DeepPanel(break_on=_PAIR_MARK)  # PAIR breaks it
    judge = _DeepJudge()
    attacker, _ = _make_stub_attacker()
    orch = build_pair_orchestrator(panel, judge, max_iters=3)
    orch.attacker = attacker
    planner = _NeverPlanner()

    report = await run_scan(
        _config(), [_single_turn_primitive()], n_trials=1,
        panel=panel, judge=judge,
        deep=True, persona=_NoopPersona(),
        pair_max_iters=3, pair_orchestrator=orch,
        escalate=True, escalate_planner=planner,
    )

    assert report.n_breaches == 1  # PAIR already broke it
    assert planner.calls == 0  # escalation never ran — PAIR short-circuited it


@pytest.mark.asyncio
async def test_escalation_bounded_when_nothing_breaks():
    """Baseline + PAIR + every ladder tier fail → finding stays unbreached, no crash, planner is
    consulted (bounded) and exhausts."""
    from rogue.scan import build_pair_orchestrator

    panel = _DeepPanel(break_on=None)  # nothing ever breaks
    judge = _DeepJudge()
    attacker, _ = _make_stub_attacker(max_calls=0)  # PAIR refuses immediately
    orch = build_pair_orchestrator(panel, judge, max_iters=2)
    orch.attacker = attacker
    planner = _NeverPlanner()

    report = await run_scan(
        _config(), [_single_turn_primitive()], n_trials=1,
        panel=panel, judge=judge,
        deep=True, persona=_NoopPersona(),
        pair_max_iters=2, pair_orchestrator=orch,
        escalate=True, escalate_planner=planner, escalate_n_trials=1,
    )

    assert report.n_breaches == 0
    f = report.findings[0]
    assert f.n_breach == 0 and f.n_trials == 1  # baseline finding stands
    assert planner.calls >= 1  # the planner tier was reached and consulted


# --------------------------------------------------------------------------- #
# 3. The stage helpers return a clean no-breach outcome on a stage error.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_pair_stage_swallows_errors_as_no_breach():
    from rogue.scan import run_pair_stage

    class _BoomOrch:
        async def run_pair_cell(self, *, primitive, config):
            raise RuntimeError("attacker exploded")

    outcome = await run_pair_stage(_BoomOrch(), _single_turn_primitive(), _config())
    assert isinstance(outcome, DeepStageOutcome)
    assert outcome.breached is False


# --------------------------------------------------------------------------- #
# 4. The same stages are wired into the endpoint-scan surface (scan_endpoint).
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_scan_endpoint_pair_breaks_refused_primitive_under_deep():
    """scan_endpoint --deep runs PAIR on a refused primitive; a PAIR win folds into the finding."""
    from rogue.reproduce.endpoint_scan import scan_endpoint
    from rogue.scan import build_pair_orchestrator

    panel = _DeepPanel(break_on=_PAIR_MARK)
    judge = _DeepJudge()
    attacker, counter = _make_stub_attacker()
    orch = build_pair_orchestrator(panel, judge, max_iters=3)
    orch.attacker = attacker

    report = await scan_endpoint(
        "https://gw.example/v1",
        "openai/gpt-5.4-nano",
        [_single_turn_primitive()],
        n_trials=1,
        panel=panel,
        judge=judge,
        deep=True,
        persona=_NoopPersona(),
        pair_max_iters=3,
        pair_orchestrator=orch,
        escalate=False,
    )

    f = report.findings[0]
    assert f.breached is True and f.n_breach == 1
    assert report.n_breached == 1
    assert counter[0] >= 1  # PAIR actually refined
    assert "broke via PAIR refinement" in f.title  # the win is annotated honestly


@pytest.mark.asyncio
async def test_scan_endpoint_no_deep_skips_pair():
    """Without --deep, scan_endpoint never runs PAIR (default fast scan)."""
    from rogue.reproduce.endpoint_scan import scan_endpoint
    from rogue.scan import build_pair_orchestrator

    panel = _DeepPanel(break_on=_PAIR_MARK)
    judge = _DeepJudge()
    attacker, counter = _make_stub_attacker()
    orch = build_pair_orchestrator(panel, judge, max_iters=3)
    orch.attacker = attacker

    report = await scan_endpoint(
        "https://gw.example/v1",
        "openai/gpt-5.4-nano",
        [_single_turn_primitive()],
        n_trials=1,
        panel=panel,
        judge=judge,
        deep=False,
        pair_max_iters=3,
        pair_orchestrator=orch,
        escalate=True,
    )

    assert counter[0] == 0  # PAIR never fired
    assert report.n_breached == 0
