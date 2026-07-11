"""Endpoint scan (the `rogue scan <url>` milestone): scan an OpenAI-compatible endpoint end-to-end.

Exercises the full local path — golden primitives → render → TargetPanel (routing a base_url config
through CustomHTTPAdapter) → judge → EndpointScanReport — with the endpoint client and the judge
mocked, so there is no network and no spend. The point being proved: a customer endpoint URL flows
through the Week-2 adapter layer with the rest of the pipeline unchanged.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from rogue.reproduce.endpoint_scan import (
    EndpointScanReport,
    make_endpoint_config,
    scan_endpoint,
)
from rogue.reproduce.target_panel import TargetPanel
from rogue.schemas import AttackPrimitive, JudgeVerdict

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_GOLDENS = (
    "01_multilingual_african_languages.json",
    "02_copirate_365_cve_2026_24299.json",
    "03_hacking_claude_memory.json",
)
_ENDPOINT = "https://api.company.com/v1"
_MODEL = "company-model-1"


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    async def _instant(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", _instant)


def _goldens() -> list[AttackPrimitive]:
    return [AttackPrimitive.model_validate_json((_FIXTURES / n).read_text()) for n in _GOLDENS]


def _stub_completion(content: str = "Sure, here is exactly what you asked for."):
    msg = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=msg, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=12, completion_tokens=8)
    return SimpleNamespace(choices=[choice], usage=usage, model_dump=lambda: {"stub": True})


class _FakeEndpointClient:
    """A fake OpenAI-compatible client standing in for the customer's endpoint."""

    def __init__(self, *, raise_exc: BaseException | None = None):
        self.calls: list[dict] = []
        self._raise = raise_exc
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.models = SimpleNamespace(list=self._list)

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._raise is not None:
            raise self._raise
        return _stub_completion()

    async def _list(self):
        return []

    async def close(self):
        return None


class _FakeJudge:
    def __init__(self, verdict: JudgeVerdict):
        self._verdict = verdict
        self.calls = 0

    async def judge(self, rendered, model_response, primitive):
        self.calls += 1
        return SimpleNamespace(verdict=self._verdict)


def _panel_with(client: _FakeEndpointClient) -> TargetPanel:
    # base_url config routes to CustomHTTPAdapter, which uses the injected client.
    return TargetPanel(adapter_extra={"client": client})


# --- config -----------------------------------------------------------------------------------


def test_make_endpoint_config_carries_base_url():
    cfg = make_endpoint_config(_ENDPOINT, _MODEL, system_prompt="be safe")
    assert cfg.base_url == _ENDPOINT
    assert cfg.target_model == _MODEL
    assert cfg.system_prompt == "be safe"
    assert cfg.customer_id == "adhoc"


# --- end-to-end scans -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_all_breach():
    client = _FakeEndpointClient()
    judge = _FakeJudge(JudgeVerdict.FULL_BREACH)
    report = await scan_endpoint(
        _ENDPOINT, _MODEL, _goldens(), n_trials=3, panel=_panel_with(client), judge=judge
    )
    assert isinstance(report, EndpointScanReport)
    assert report.n_primitives == 3
    assert report.n_breached == 3
    assert report.breach_rate == 1.0
    assert all(f.breached and f.any_breach_rate == 1.0 for f in report.findings)
    # findings sorted by breach rate desc
    assert report.findings == sorted(report.findings, key=lambda f: f.any_breach_rate, reverse=True)


@pytest.mark.asyncio
async def test_scan_no_breach_when_judge_refuses():
    judge = _FakeJudge(JudgeVerdict.REFUSED)
    report = await scan_endpoint(
        _ENDPOINT, _MODEL, _goldens(), n_trials=3, panel=_panel_with(_FakeEndpointClient()), judge=judge
    )
    assert report.n_breached == 0
    assert report.breach_rate == 0.0
    assert all(not f.breached and f.error is None for f in report.findings)


@pytest.mark.asyncio
async def test_scan_routes_through_custom_adapter_with_bare_model():
    """The endpoint actually receives requests, and the wire model is the bare endpoint model name."""
    client = _FakeEndpointClient()
    await scan_endpoint(
        _ENDPOINT, _MODEL, _goldens()[:1], n_trials=2, panel=_panel_with(client),
        judge=_FakeJudge(JudgeVerdict.FULL_BREACH),
    )
    # Golden #1 is a 3-turn multi-turn primitive, now driven as a REAL back-and-forth: each trial
    # issues one request per user turn (3), so 2 trials × 3 turns = 6 endpoint calls. (Before the
    # multi-turn fix these were stacked into one request/trial — the bug this exercises the fix for.)
    assert len(client.calls) == 6
    assert all(c["model"] == _MODEL for c in client.calls)  # no "custom/" prefix leaked to the wire


@pytest.mark.asyncio
async def test_scan_error_trials_are_not_breaches():
    """When the endpoint errors every trial, the finding records the error and counts no breach."""
    # A 400 is non-retryable → maps to a ProviderError → panel projects to a ModelResponse error.
    bad = httpx.HTTPStatusError(
        "bad request",
        request=httpx.Request("POST", _ENDPOINT),
        response=httpx.Response(400, request=httpx.Request("POST", _ENDPOINT)),
    )
    judge = _FakeJudge(JudgeVerdict.FULL_BREACH)
    report = await scan_endpoint(
        _ENDPOINT, _MODEL, _goldens()[:1], n_trials=2,
        panel=_panel_with(_FakeEndpointClient(raise_exc=bad)), judge=judge,
    )
    assert report.n_breached == 0
    assert report.findings[0].error == "all_trials_errored"
    assert judge.calls == 0  # judge is never invoked for errored trials


# --- report rendering -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_summary_and_markdown():
    report = await scan_endpoint(
        _ENDPOINT, _MODEL, _goldens(), n_trials=2, panel=_panel_with(_FakeEndpointClient()),
        judge=_FakeJudge(JudgeVerdict.FULL_BREACH),
    )
    assert _ENDPOINT in report.summary()
    md = report.to_markdown()
    assert _ENDPOINT in md and _MODEL in md
    assert "ROGUE Endpoint Scan" in md
    assert md.count("\n") >= len(report.findings)  # a row per finding


# --- robustness sweep (opt-in --robustness-sweep) ---------------------------------------------


@pytest.mark.asyncio
async def test_robustness_sweep_off_by_default():
    """Default scan is byte-identical: no sweep, empty results, no note."""
    report = await scan_endpoint(
        _ENDPOINT, _MODEL, _goldens(), n_trials=2,
        panel=_panel_with(_FakeEndpointClient()), judge=_FakeJudge(JudgeVerdict.FULL_BREACH),
    )
    assert report.sweep_results == []
    assert report.sweep_note is None
    assert "robustness" not in report.summary().lower()


@pytest.mark.asyncio
async def test_robustness_sweep_finds_threshold():
    """With the flag on + an always-breach judge, the sweep produces a curve and locates a threshold,
    graded by the SAME injected judge/panel the scan used — proving the splice fires end-to-end ($0)."""
    judge = _FakeJudge(JudgeVerdict.FULL_BREACH)
    report = await scan_endpoint(
        _ENDPOINT, _MODEL, _goldens(), n_trials=2,
        panel=_panel_with(_FakeEndpointClient()), judge=judge,
        robustness_sweep=True,
        robustness_sweep_limit=1,
        robustness_sweep_values=[100, 500, 1000],  # tiny ladder → fast
        robustness_sweep_max_spend=None,
    )
    assert len(report.sweep_results) == 1
    res = report.sweep_results[0]
    assert res.kind == "many_shot"
    assert res.points, "sweep produced no points"
    # every value breaches (judge=FULL_BREACH) → threshold is the smallest swept value
    assert res.threshold_value == 100
    assert all(p.asr == 1.0 for p in res.points)
    # the note is surfaced in both the summary line and the markdown report
    assert report.sweep_note and "breaks at" in report.sweep_note
    assert "robustness" in report.summary().lower()
    assert "Long-context robustness" in report.to_markdown()


@pytest.mark.asyncio
async def test_robustness_sweep_fires_harmful_shots_and_judges_clean_ask():
    """The in-scan sweep must (1) fire HARMFUL demonstration shots, not benign filler, and (2) grade
    the response against the CLEAN base primitive — never the demonstration-laden payload (feeding the
    harmful demos to the judge contaminates it). Both are the eval-integrity fixes from the board re-run."""
    client = _FakeEndpointClient()  # records every payload sent to the endpoint

    class _CapturingJudge:
        def __init__(self):
            self.judged_user_turns: list[str] = []

        async def judge(self, rendered, model_response, primitive):
            self.judged_user_turns.append(rendered.messages[-1]["content"])
            return SimpleNamespace(verdict=JudgeVerdict.REFUSED)

    judge = _CapturingJudge()
    await scan_endpoint(
        _ENDPOINT, _MODEL, _goldens(), n_trials=1,
        panel=_panel_with(client), judge=judge,
        robustness_sweep=True, robustness_sweep_values=[600], robustness_sweep_max_spend=None,
    )
    # (1) the payload fired at the endpoint carries harmful demonstration openers, not benign filler
    fired = [c["messages"][-1]["content"] for c in client.calls]
    assert any("Sure, here is" in p for p in fired), "no AdvBench harmful demonstration shots in the ladder"
    assert not any("capital of France" in p for p in fired), "benign filler leaked into the ladder"
    # (2) the judge was graded against the CLEAN base primitive, NOT the demonstration-laden payload
    assert judge.judged_user_turns, "sweep never judged a response"
    assert all("Sure, here is" not in t for t in judge.judged_user_turns), \
        "judge was fed the demonstration-laden payload (contamination)"


@pytest.mark.asyncio
async def test_robustness_sweep_holds_when_judge_refuses():
    """A never-breach endpoint holds across the whole ladder → threshold_value is None (no false break)."""
    report = await scan_endpoint(
        _ENDPOINT, _MODEL, _goldens(), n_trials=2,
        panel=_panel_with(_FakeEndpointClient()), judge=_FakeJudge(JudgeVerdict.REFUSED),
        robustness_sweep=True, robustness_sweep_values=[100, 500], robustness_sweep_max_spend=None,
    )
    assert len(report.sweep_results) == 1
    assert report.sweep_results[0].threshold_value is None
    assert "held" in (report.sweep_note or "")
