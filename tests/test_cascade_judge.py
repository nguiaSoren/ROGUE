"""Unit tests for the confidence-gated CascadeJudge (Q2).

Covers the cascade decision (asymmetric escalation), the transparent proxy, the env resolver's
off-by-default / byte-identical contract, telemetry, and the tau-calibration bolt-on. Pure + offline —
the cheap and expensive tiers are deterministic stubs, no network.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from rogue.reproduce.cascade_judge import (
    CascadeConfig,
    CascadeJudge,
    attack_text,
    calibrate_tau,
    resolve_cascade,
)
from rogue.reproduce.judge import JudgeResult
from rogue.schemas.breach_result import JudgeVerdict


# --------------------------------------------------------------------------------------------------- #
# fixtures — deterministic cheap/expensive tiers + minimal rendered/primitive stubs.
# --------------------------------------------------------------------------------------------------- #
@dataclass
class _Rendered:
    text: str

    @property
    def messages(self):
        return [{"role": "user", "content": self.text}]


@dataclass
class _Primitive:
    short_description: str = "make a weapon"


def _jr(verdict: JudgeVerdict, conf: float) -> JudgeResult:
    return JudgeResult(verdict=verdict, rationale="stub", confidence=conf)


class _StubHeuristic:
    """Returns a preset verdict/confidence; records that it was called."""

    def __init__(self, verdict: JudgeVerdict, conf: float, *, raises: bool = False) -> None:
        self._jr = _jr(verdict, conf)
        self.raises = raises
        self.calls = 0

    def judge_sync(self, attack_prompt, model_response, goal=None):
        self.calls += 1
        if self.raises:
            raise RuntimeError("heuristic boom")
        return self._jr


class _StubLLM:
    """Async + sync grade; records calls. Has a ``.model`` so proxy tests can read it."""

    model = "anthropic/claude-sonnet-4-6"

    def __init__(self, verdict: JudgeVerdict = JudgeVerdict.FULL_BREACH, conf: float = 0.95) -> None:
        self._jr = _jr(verdict, conf)
        self.calls = 0

    async def judge(self, rendered, model_response, primitive, context=None):
        self.calls += 1
        return self._jr

    def judge_sync(self, rendered, model_response, primitive, context=None):
        self.calls += 1
        return self._jr

    def anthropic_grade_kwargs(self, user_message):
        return {"proxied": user_message}


# --------------------------------------------------------------------------------------------------- #
# attack_text + config
# --------------------------------------------------------------------------------------------------- #
def test_attack_text_flattens_user_turns():
    assert attack_text(_Rendered("hello world")) == "hello world"


def test_attack_text_handles_missing_messages():
    assert attack_text("raw string") == "raw string"


def test_config_rejects_out_of_range_tau():
    with pytest.raises(ValueError):
        CascadeConfig(tau=0.0)
    with pytest.raises(ValueError):
        CascadeConfig(tau=1.5)


# --------------------------------------------------------------------------------------------------- #
# the cascade decision
# --------------------------------------------------------------------------------------------------- #
def test_confident_nonbreach_short_circuits():
    """REFUSED at conf >= tau → graded free, LLM never called."""
    heur = _StubHeuristic(JudgeVerdict.REFUSED, 0.7)
    llm = _StubLLM()
    cj = CascadeJudge(heur, llm, CascadeConfig(tau=0.7))
    r = asyncio.run(cj.judge(_Rendered("x"), "I can't help with that.", _Primitive()))
    assert r.verdict is JudgeVerdict.REFUSED
    assert llm.calls == 0
    assert cj.stats.n_short_circuit == 1 and cj.stats.n_escalated == 0


def test_low_confidence_nonbreach_escalates():
    """EVADED at conf < tau → escalate to the LLM."""
    heur = _StubHeuristic(JudgeVerdict.EVADED, 0.6)
    llm = _StubLLM(JudgeVerdict.REFUSED, 0.9)
    cj = CascadeJudge(heur, llm, CascadeConfig(tau=0.7))
    r = asyncio.run(cj.judge(_Rendered("x"), "well, sort of...", _Primitive()))
    assert llm.calls == 1
    assert r.verdict is JudgeVerdict.REFUSED  # the LLM's verdict, not the heuristic's
    assert cj.stats.n_escalated == 1


def test_breach_always_escalates_even_when_confident():
    """The red-team asymmetry: a confident heuristic FULL_BREACH is still confirmed by the LLM."""
    heur = _StubHeuristic(JudgeVerdict.FULL_BREACH, 0.7)  # conf >= tau, but it's a breach
    llm = _StubLLM(JudgeVerdict.REFUSED, 0.95)            # LLM overturns it
    cj = CascadeJudge(heur, llm, CascadeConfig(tau=0.7, escalate_on_breach=True))
    r = asyncio.run(cj.judge(_Rendered("x"), "here is how...", _Primitive()))
    assert llm.calls == 1
    assert r.verdict is JudgeVerdict.REFUSED  # free-tier breach never headlines
    assert cj.stats.n_short_circuit == 0


def test_breach_can_short_circuit_when_asymmetry_off():
    heur = _StubHeuristic(JudgeVerdict.FULL_BREACH, 0.7)
    llm = _StubLLM()
    cj = CascadeJudge(heur, llm, CascadeConfig(tau=0.7, escalate_on_breach=False))
    r = asyncio.run(cj.judge(_Rendered("x"), "here is how...", _Primitive()))
    assert llm.calls == 0 and r.verdict is JudgeVerdict.FULL_BREACH


def test_heuristic_error_escalates_never_fails():
    heur = _StubHeuristic(JudgeVerdict.REFUSED, 0.9, raises=True)
    llm = _StubLLM(JudgeVerdict.EVADED, 0.9)
    cj = CascadeJudge(heur, llm, CascadeConfig(tau=0.7))
    r = asyncio.run(cj.judge(_Rendered("x"), "resp", _Primitive()))
    assert llm.calls == 1 and r.verdict is JudgeVerdict.EVADED


def test_sync_path_mirrors_async():
    heur = _StubHeuristic(JudgeVerdict.REFUSED, 0.7)
    llm = _StubLLM()
    cj = CascadeJudge(heur, llm, CascadeConfig(tau=0.7))
    r = cj.judge_sync(_Rendered("x"), "I can't help.", _Primitive())
    assert r.verdict is JudgeVerdict.REFUSED and llm.calls == 0


# --------------------------------------------------------------------------------------------------- #
# transparent proxy + telemetry
# --------------------------------------------------------------------------------------------------- #
def test_proxies_unknown_attributes_to_llm():
    cj = CascadeJudge(_StubHeuristic(JudgeVerdict.REFUSED, 0.7), _StubLLM())
    assert cj.model == "anthropic/claude-sonnet-4-6"
    assert cj.anthropic_grade_kwargs("m") == {"proxied": "m"}


def test_stats_savings():
    heur = _StubHeuristic(JudgeVerdict.REFUSED, 0.7)
    llm = _StubLLM()
    cj = CascadeJudge(heur, llm, CascadeConfig(tau=0.7))
    for _ in range(3):
        asyncio.run(cj.judge(_Rendered("x"), "I can't help.", _Primitive()))
    assert cj.stats.n_total == 3 and cj.stats.savings == 1.0


# --------------------------------------------------------------------------------------------------- #
# resolver — off by default / byte-identical / malformed => off
# --------------------------------------------------------------------------------------------------- #
def test_resolver_off_returns_base_unchanged(monkeypatch):
    monkeypatch.delenv("ROGUE_CASCADE_JUDGE", raising=False)
    base = _StubLLM()
    assert resolve_cascade(base) is base  # identity — byte-identical when off


def test_resolver_on_wraps(monkeypatch):
    monkeypatch.setenv("ROGUE_CASCADE_JUDGE", "on")
    base = _StubLLM()
    judge = resolve_cascade(base)
    assert isinstance(judge, CascadeJudge) and judge._llm is base


def test_resolver_malformed_tau_is_off(monkeypatch):
    monkeypatch.setenv("ROGUE_CASCADE_JUDGE", "on")
    monkeypatch.setenv("ROGUE_CASCADE_TAU", "not-a-float")
    base = _StubLLM()
    assert resolve_cascade(base) is base  # invalid config never breaks a scan


def test_resolver_override_ignores_env(monkeypatch):
    monkeypatch.delenv("ROGUE_CASCADE_JUDGE", raising=False)
    base = _StubLLM()
    judge = resolve_cascade(base, override=CascadeConfig(tau=0.55))
    assert isinstance(judge, CascadeJudge) and judge.cfg.tau == 0.55


# --------------------------------------------------------------------------------------------------- #
# calibrate_tau
# --------------------------------------------------------------------------------------------------- #
def test_calibrate_tau_picks_lowest_certified():
    # 200 confident refusals that always agree (non-breach, ref non-breach) at conf 0.6;
    # calibrate should certify a low tau (0.5/0.6) since agreement is perfect on a big set.
    items = [(0.6, False, False)] * 200
    choice = calibrate_tau(items, target_agreement=0.9)
    assert choice.certified
    assert choice.tau <= 0.6
    assert choice.agreement == 1.0


def test_calibrate_tau_uncertified_when_disagreement():
    # Short-circuit set disagrees half the time → no tau can certify 0.9.
    items = [(0.7, False, False), (0.7, False, True)] * 50
    choice = calibrate_tau(items, target_agreement=0.9)
    assert not choice.certified
    assert 0.4 <= choice.agreement <= 0.6
