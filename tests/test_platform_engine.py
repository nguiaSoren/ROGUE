"""Offline tests for :class:`rogue.platform.engine.DefaultScanEngine`.

Everything here runs with no network, no LLM, no money, no DB: a fake panel and a fake judge are
injected, and the real (pure, in-process) ``render`` / ``filter_attacks`` / ``load_pack`` path is
exercised against the bundled ``default`` pack. pytest-asyncio is in STRICT mode, so every async test
is explicitly marked.
"""

from __future__ import annotations

import pytest

from rogue.platform.engine import DefaultScanEngine, _default_model
from rogue.platform.schemas import ScanSpec, TargetSpec
from rogue.report import ScanReport
from rogue.schemas import JudgeVerdict


class _FakeResponse:
    """Stand-in for a ``ModelResponse``: only the fields the engine loop reads."""

    def __init__(self, content: str = "sure, here you go", *, error: str | None = None,
                 cost_usd: float = 0.0001) -> None:
        self.content = content
        self.error = error
        self.cost_usd = cost_usd


class _FakeVerdict:
    def __init__(self, verdict: JudgeVerdict) -> None:
        self.verdict = verdict


class FakePanel:
    """Returns a fixed list of fake responses per attack; records nothing about the network."""

    def __init__(self, responses: list[_FakeResponse] | None = None) -> None:
        self._responses = responses if responses is not None else [_FakeResponse()]
        self.closed = False
        self.calls = 0

    async def run_attack(self, rendered, config, n_trials: int = 1):
        self.calls += 1
        return list(self._responses)

    async def aclose(self) -> None:
        self.closed = True


class FakeJudge:
    """Grades every response with a verdict drawn (round-robin) from a fixed list."""

    def __init__(self, verdicts: list[JudgeVerdict]) -> None:
        self._verdicts = verdicts
        self._i = 0

    async def judge(self, rendered, content, prim):
        v = self._verdicts[self._i % len(self._verdicts)]
        self._i += 1
        return _FakeVerdict(v)


def _spec(**kw) -> ScanSpec:
    target = kw.pop("target", TargetSpec(endpoint="https://x/v1", api_key="k"))
    return ScanSpec(target=target, pack="default", max_tests=3, n_trials=1, **kw)


@pytest.mark.asyncio
async def test_run_returns_scanreport_with_capped_tests():
    panel = FakePanel([_FakeResponse()])
    judge = FakeJudge([JudgeVerdict.REFUSED])
    engine = DefaultScanEngine(panel=panel, judge=judge)

    report = await engine.run(_spec())

    assert isinstance(report, ScanReport)
    assert report.n_tests == 3  # max_tests cap honoured
    assert panel.calls == 3
    assert panel.closed is False  # injected panel is NOT owned by the engine → never closed


@pytest.mark.asyncio
async def test_run_counts_breaches_from_verdicts():
    # All trials full-breach → rate 1.0 ≥ 0.4 threshold → every primitive counts as a breach.
    panel = FakePanel([_FakeResponse()])
    judge = FakeJudge([JudgeVerdict.FULL_BREACH])
    engine = DefaultScanEngine(panel=panel, judge=judge)

    report = await engine.run(_spec())

    assert report.n_breaches == 3
    assert all(f.n_breach == 1 for f in report.findings)


@pytest.mark.asyncio
async def test_run_refusals_yield_no_breaches():
    panel = FakePanel([_FakeResponse()])
    judge = FakeJudge([JudgeVerdict.REFUSED])
    engine = DefaultScanEngine(panel=panel, judge=judge)

    report = await engine.run(_spec())

    assert report.n_breaches == 0


@pytest.mark.asyncio
async def test_progress_callback_invoked_once_per_primitive_monotonic():
    panel = FakePanel([_FakeResponse()])
    judge = FakeJudge([JudgeVerdict.REFUSED])
    engine = DefaultScanEngine(panel=panel, judge=judge)

    seen: list[tuple[int, int, str | None]] = []

    async def progress(n_completed: int, n_total: int, current: str | None) -> None:
        seen.append((n_completed, n_total, current))

    await engine.run(_spec(), progress=progress)

    assert len(seen) == 3
    assert [s[0] for s in seen] == [1, 2, 3]  # monotonic n_completed
    assert all(s[1] == 3 for s in seen)  # n_total constant
    assert all(s[2] for s in seen)  # a technique label every step


@pytest.mark.asyncio
async def test_errored_responses_are_not_judged_and_cost_still_summed():
    # An errored trial is skipped by the judge but its cost still accrues (mirrors run_scan).
    panel = FakePanel([_FakeResponse(error="rate_limit_exhausted", cost_usd=0.0)])
    judge = FakeJudge([JudgeVerdict.FULL_BREACH])  # would breach if it were consulted
    engine = DefaultScanEngine(panel=panel, judge=judge)

    report = await engine.run(_spec())

    assert report.n_breaches == 0  # judge never ran on the errored response
    assert all(f.n_breach == 0 for f in report.findings)


def test_endpoint_mode_config_routes_through_custom_http():
    engine = DefaultScanEngine()
    spec = _spec(target=TargetSpec(endpoint="https://gw.acme.com/v1", model="my-model", api_key="k"))
    config = engine._build_config(spec)

    assert config.base_url == "https://gw.acme.com/v1"
    assert config.target_model == "my-model"


def test_provider_mode_config_normalises_model_slug():
    engine = DefaultScanEngine()

    # bare model name → provider/model slug
    cfg = engine._build_config(_spec(target=TargetSpec(provider="openai", model="gpt-x")))
    assert cfg.base_url is None
    assert cfg.target_model == "openai/gpt-x"

    # already-slugged model is left untouched
    cfg2 = engine._build_config(_spec(target=TargetSpec(provider="openai", model="openai/gpt-x")))
    assert cfg2.target_model == "openai/gpt-x"

    # no model → per-provider default
    cfg3 = engine._build_config(_spec(target=TargetSpec(provider="openai")))
    assert cfg3.target_model == _default_model("openai")


def test_default_model_unknown_provider_raises():
    with pytest.raises(ValueError):
        _default_model("nope-not-a-provider")
