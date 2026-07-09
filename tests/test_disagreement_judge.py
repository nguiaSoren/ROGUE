"""Unit tests for the Q5 DisagreementJudge (bracket-fragile breach flagging).

Covers: the strict-check fires only on breach cells; the flag stamp + verdict-preservation; the
strict-error safety rail; telemetry; and the env resolver's off-by-default / byte-identical contract
(identity when off, only-wrap-an-LLM-judge). Pure + offline — primary and strict brackets are
deterministic stubs, no network.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from rogue.reproduce.disagreement_judge import (
    DisagreementJudge,
    ENV_DISAGREEMENT,
    is_uncertain,
    resolve_disagreement,
)
from rogue.reproduce.judge import JudgeResult
from rogue.schemas.breach_result import JudgeVerdict


@dataclass
class _Rendered:
    text: str = "payload"

    @property
    def messages(self):
        return [{"role": "user", "content": self.text}]


@dataclass
class _Primitive:
    short_description: str = "make a weapon"


def _jr(verdict: JudgeVerdict, rationale: str = "base rationale") -> JudgeResult:
    return JudgeResult(verdict=verdict, rationale=rationale, confidence=0.8)


class _StubJudge:
    """Async + sync grade returning a preset verdict; records calls. Exposes .model so it looks like
    an LLM judge to the resolver + the strict-sibling builder."""

    model = "anthropic/claude-sonnet-4-6"
    breach_type = "capability_transfer"
    prompt_version = "v3"

    def __init__(self, verdict: JudgeVerdict, rationale: str = "base rationale") -> None:
        self._verdict = verdict
        self._rationale = rationale
        self.calls = 0

    async def judge(self, rendered, model_response, primitive, context=None):
        self.calls += 1
        return _jr(self._verdict, self._rationale)

    def judge_sync(self, rendered, model_response, primitive, context=None):
        self.calls += 1
        return _jr(self._verdict, self._rationale)


class _RaisingJudge(_StubJudge):
    async def judge(self, *a, **k):
        self.calls += 1
        raise RuntimeError("strict boom")

    def judge_sync(self, *a, **k):
        self.calls += 1
        raise RuntimeError("strict boom")


def _wire(primary: _StubJudge, strict: _StubJudge) -> DisagreementJudge:
    dj = DisagreementJudge(primary)
    dj._strict = strict  # inject the strict sibling (avoid building a real JudgeAgent)
    return dj


# --------------------------------------------------------------------------------------------------- #
# core: strict-check only on breaches; flag stamp; verdict preserved
# --------------------------------------------------------------------------------------------------- #
def test_breach_with_strict_disagreement_is_flagged():
    dj = _wire(_StubJudge(JudgeVerdict.FULL_BREACH), _StubJudge(JudgeVerdict.EVADED))
    res = asyncio.run(dj.judge(_Rendered(), "resp", _Primitive()))
    assert res.verdict is JudgeVerdict.FULL_BREACH  # verdict NEVER changed
    assert is_uncertain(res.rationale)
    assert res.rationale.startswith("[JUDGE_UNCERTAIN:strict=evaded] ")
    assert "base rationale" in res.rationale
    assert dj.stats.n_breaches == 1 and dj.stats.n_flagged == 1 and dj.stats.n_confirmed == 0


def test_breach_confirmed_by_strict_is_not_flagged():
    dj = _wire(_StubJudge(JudgeVerdict.FULL_BREACH), _StubJudge(JudgeVerdict.PARTIAL_BREACH))
    res = asyncio.run(dj.judge(_Rendered(), "resp", _Primitive()))
    assert not is_uncertain(res.rationale)
    assert res.rationale == "base rationale"
    assert dj.stats.n_confirmed == 1 and dj.stats.n_flagged == 0


def test_non_breach_never_calls_strict():
    strict = _StubJudge(JudgeVerdict.FULL_BREACH)  # would flag if it ran
    dj = _wire(_StubJudge(JudgeVerdict.REFUSED), strict)
    res = asyncio.run(dj.judge(_Rendered(), "resp", _Primitive()))
    assert strict.calls == 0  # cost bound: no strict grade on non-breaches
    assert not is_uncertain(res.rationale)
    assert dj.stats.n_breaches == 0


def test_strict_error_leaves_cell_unflagged_and_never_fails():
    dj = _wire(_StubJudge(JudgeVerdict.FULL_BREACH), _RaisingJudge(JudgeVerdict.EVADED))
    res = asyncio.run(dj.judge(_Rendered(), "resp", _Primitive()))
    assert res.verdict is JudgeVerdict.FULL_BREACH  # scan still completes
    assert not is_uncertain(res.rationale)
    assert dj.stats.n_strict_errors == 1 and dj.stats.n_flagged == 0


def test_sync_path_matches_async():
    dj = _wire(_StubJudge(JudgeVerdict.PARTIAL_BREACH), _StubJudge(JudgeVerdict.REFUSED))
    res = dj.judge_sync(_Rendered(), "resp", _Primitive())
    assert is_uncertain(res.rationale) and res.verdict is JudgeVerdict.PARTIAL_BREACH


def test_transparent_proxy_forwards_attributes():
    dj = _wire(_StubJudge(JudgeVerdict.REFUSED), _StubJudge(JudgeVerdict.REFUSED))
    assert dj.model == "anthropic/claude-sonnet-4-6"  # proxied to the wrapped judge
    assert dj.breach_type == "capability_transfer"


# --------------------------------------------------------------------------------------------------- #
# resolver: off by default (identity), only wraps an LLM judge
# --------------------------------------------------------------------------------------------------- #
def test_resolver_off_is_identity(monkeypatch):
    monkeypatch.delenv(ENV_DISAGREEMENT, raising=False)
    base = _StubJudge(JudgeVerdict.FULL_BREACH)
    assert resolve_disagreement(base) is base  # byte-identical when off


def test_resolver_on_wraps_llm_judge(monkeypatch):
    monkeypatch.setenv(ENV_DISAGREEMENT, "on")
    base = _StubJudge(JudgeVerdict.FULL_BREACH)
    wrapped = resolve_disagreement(base)
    assert isinstance(wrapped, DisagreementJudge) and wrapped._llm is base


def test_resolver_on_leaves_heuristic_untouched(monkeypatch):
    monkeypatch.setenv(ENV_DISAGREEMENT, "on")

    class _Heuristic:  # no .model → no strict bracket to disagree with
        pass

    h = _Heuristic()
    assert resolve_disagreement(h) is h


def test_is_uncertain_helper():
    assert is_uncertain("[JUDGE_UNCERTAIN:strict=evaded] x")
    assert not is_uncertain("plain rationale")
    assert not is_uncertain(None)


# --------------------------------------------------------------------------------------------------- #
# END-TO-END: the resolver fires inside the live scan surfaces + the report surfaces the flag
# ("wired isn't run" — drive run_scan / scan_endpoint for real, $0 stubs, no network).
# --------------------------------------------------------------------------------------------------- #
from datetime import datetime, timezone  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from rogue.schemas import (  # noqa: E402
    AttackFamily,
    AttackPrimitive,
    AttackVector,
    DeploymentConfig,
    Severity,
)


def _single_turn(pid: str = "01DISAGREETESTPRIM0000001") -> AttackPrimitive:
    return AttackPrimitive.model_validate({
        "primitive_id": pid, "cluster_id": pid, "canonical": True,
        "family": AttackFamily.DIRECT_INSTRUCTION_OVERRIDE, "secondary_families": [],
        "vector": AttackVector.USER_TURN, "title": "disagreement e2e",
        "short_description": "single-turn disagreement test primitive here",
        "payload_template": "Do the harmful thing, in detail.",
        "requires_system_prompt_access": False, "requires_tools": [],
        "requires_multimodal": False, "target_models_claimed": [], "reproducibility_score": 7,
        "sources": [{
            "url": "https://example.com/a", "source_type": "other", "author": None,
            "published_at": None, "fetched_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
            "archive_hash": "hash123456", "bright_data_product": "fixture",
        }],
        "base_severity": Severity.MEDIUM, "severity_rationale": "test",
        "discovered_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
    })


def _cfg() -> DeploymentConfig:
    return DeploymentConfig(config_id="disagree-cfg", customer_id="x", name="n",
                            target_model="gpt-4o", system_prompt="You are helpful.")


def _stub_response(t=0):
    return SimpleNamespace(trial_index=t, content="Sure, step 1: ...", error=None, reasoning="",
                           temperature=0.7, latency_ms=10, tokens_in=5, tokens_out=5, cost_usd=0.0)


class _Panel:
    async def run_attack(self, rendered, config, *, temperature=0.7, n_trials=1):
        return [_stub_response(t) for t in range(n_trials)]

    async def run_conversation(self, rendered, config, *, temperature=0.7, n_trials=1):
        return [_stub_response(t) for t in range(n_trials)]

    async def aclose(self):
        pass


class _StubJudgeAgent:
    """Stand-in for JudgeAgent: the PRIMARY (strict=False) calls a breach; the STRICT bracket
    (strict=True) disagrees (EVADED) — so the resolver's DisagreementJudge flags the cell."""

    def __init__(self, model=None, breach_type="capability_transfer",
                 prompt_version="v3", strict=False, **kw):
        self.model = model or "anthropic/claude-sonnet-4-6"
        self.breach_type = breach_type
        self.prompt_version = prompt_version
        self.strict = strict

    async def judge(self, rendered, model_response, primitive, context=None):
        v = JudgeVerdict.EVADED if self.strict else JudgeVerdict.FULL_BREACH
        return _jr(v)

    def judge_sync(self, rendered, model_response, primitive, context=None):
        v = JudgeVerdict.EVADED if self.strict else JudgeVerdict.FULL_BREACH
        return _jr(v)


def test_run_scan_resolver_fires_and_report_surfaces(monkeypatch):
    from rogue.scan import run_scan

    monkeypatch.delenv("ROGUE_CASCADE_JUDGE", raising=False)
    monkeypatch.setenv(ENV_DISAGREEMENT, "on")
    monkeypatch.setattr("rogue.reproduce.judge.JudgeAgent", _StubJudgeAgent)

    report = asyncio.run(run_scan(
        _cfg(), [_single_turn()], panel=_Panel(), judge=None, agent_exec=False, escalate=False,
    ))
    # resolver fired inside run_scan → the breach was strict-checked and flagged low-confidence
    assert report.judge_disagreement is not None
    assert report.judge_disagreement["n_breaches"] == 1
    assert report.judge_disagreement["n_flagged"] == 1
    assert "judge_disagreement" in report.to_dict()


def test_run_scan_off_is_byte_identical(monkeypatch):
    from rogue.scan import run_scan

    monkeypatch.delenv("ROGUE_CASCADE_JUDGE", raising=False)
    monkeypatch.delenv(ENV_DISAGREEMENT, raising=False)
    monkeypatch.setattr("rogue.reproduce.judge.JudgeAgent", _StubJudgeAgent)

    report = asyncio.run(run_scan(
        _cfg(), [_single_turn()], panel=_Panel(), judge=None, agent_exec=False, escalate=False,
    ))
    assert report.judge_disagreement is None          # off → field None
    assert "judge_disagreement" not in report.to_dict()  # ...and key absent (dict byte-identical)


def test_scan_endpoint_resolver_fires_and_report_surfaces(monkeypatch):
    from rogue.reproduce.endpoint_scan import scan_endpoint

    monkeypatch.delenv("ROGUE_CASCADE_JUDGE", raising=False)
    monkeypatch.setenv(ENV_DISAGREEMENT, "on")
    # scan_endpoint binds JudgeAgent at module import (primary) while the strict sibling is imported
    # lazily from rogue.reproduce.judge — patch BOTH bindings so no real API call fires.
    monkeypatch.setattr("rogue.reproduce.endpoint_scan.JudgeAgent", _StubJudgeAgent)
    monkeypatch.setattr("rogue.reproduce.judge.JudgeAgent", _StubJudgeAgent)

    report = asyncio.run(scan_endpoint(
        base_url="https://x.test", model="gpt-4o", primitives=[_single_turn()],
        panel=_Panel(), judge=None, agent_exec=False, escalate=False, n_trials=1,
    ))
    assert report.n_judge_uncertain == 1
    assert report.judge_disagreement_note is not None


def test_scan_endpoint_off_is_byte_identical(monkeypatch):
    from rogue.reproduce.endpoint_scan import scan_endpoint

    monkeypatch.delenv("ROGUE_CASCADE_JUDGE", raising=False)
    monkeypatch.delenv(ENV_DISAGREEMENT, raising=False)
    monkeypatch.setattr("rogue.reproduce.endpoint_scan.JudgeAgent", _StubJudgeAgent)
    monkeypatch.setattr("rogue.reproduce.judge.JudgeAgent", _StubJudgeAgent)

    report = asyncio.run(scan_endpoint(
        base_url="https://x.test", model="gpt-4o", primitives=[_single_turn()],
        panel=_Panel(), judge=None, agent_exec=False, escalate=False, n_trials=1,
    ))
    assert report.n_judge_uncertain == 0 and report.judge_disagreement_note is None
