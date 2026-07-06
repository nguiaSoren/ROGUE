"""``rogue.scan.run_scan`` — the async engine behind ``client.scan()``.

Every test injects a fake ``panel`` (so no adapter/network) and a fake ``judge`` (so grading is
deterministic). The config is built with ``make_endpoint_config``; primitives come from the bundled
``default`` pack. pytest-asyncio runs in STRICT mode, so each coroutine test is marked explicitly.

Run from project root::

    uv run pytest tests/test_sdk_scan.py -v
"""

from __future__ import annotations

import types

import pytest

from rogue.packs import load_pack
from rogue.reproduce.endpoint_scan import make_endpoint_config
from rogue.scan import run_scan
from rogue.schemas import JudgeVerdict


# --- fakes ------------------------------------------------------------------------------------


class FakeResponse:
    """One trial's worth of a target reply, as the scan loop consumes it."""

    def __init__(self, content: str | None = "answer", *, cost_usd: float = 0.001, error=None) -> None:
        self.content = content
        self.cost_usd = cost_usd
        self.error = error


class FakePanel:
    """Returns a fixed list of responses per attack; records that it was closed."""

    def __init__(self, responses_per_attack) -> None:
        # responses_per_attack: callable(n_trials) -> list[FakeResponse], or a static list.
        self._make = responses_per_attack
        self.closed = False
        self.calls = 0

    async def run_attack(self, rendered, config, n_trials=1):
        self.calls += 1
        if callable(self._make):
            return list(self._make(n_trials))
        return list(self._make)

    async def aclose(self):
        self.closed = True


class FakeJudge:
    def __init__(self, verdict: JudgeVerdict) -> None:
        self._verdict = verdict
        self.calls = 0

    async def judge(self, rendered, content, prim):
        self.calls += 1
        return types.SimpleNamespace(verdict=self._verdict)


def _config():
    return make_endpoint_config("https://x/v1", "default")


def _prims(n: int = 3):
    return load_pack("default")[:n]


# --- tests ------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_breach():
    panel = FakePanel(lambda n: [FakeResponse("sure") for _ in range(n)])
    judge = FakeJudge(JudgeVerdict.FULL_BREACH)
    report = await run_scan(_config(), _prims(3), n_trials=2, panel=panel, judge=judge)
    assert report.n_tests == 3
    assert report.n_breaches == 3
    assert all(f.success_rate == 1.0 for f in report.findings)


@pytest.mark.asyncio
async def test_all_refuse():
    panel = FakePanel(lambda n: [FakeResponse("no") for _ in range(n)])
    judge = FakeJudge(JudgeVerdict.REFUSED)
    report = await run_scan(_config(), _prims(3), n_trials=2, panel=panel, judge=judge)
    assert report.n_tests == 3
    assert report.n_breaches == 0
    assert all(f.success_rate == 0.0 for f in report.findings)


@pytest.mark.asyncio
async def test_budget_early_stop():
    # Each attack costs 0.5; budget=0.4 → first attack runs (cost→0.5), next iteration sees
    # accumulated 0.5 >= 0.4 and halts. Exactly one attack executed.
    panel = FakePanel(lambda n: [FakeResponse("sure", cost_usd=0.5)])
    judge = FakeJudge(JudgeVerdict.FULL_BREACH)
    report = await run_scan(_config(), _prims(5), n_trials=1, budget=0.4, panel=panel, judge=judge)
    assert report.n_tests == 1
    assert panel.calls == 1
    assert report.cost_usd == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_breach_threshold_below_cutoff_not_breached():
    # 1 of 3 trials breaches → rate 0.333 < default threshold 0.4 → finding present but not counted.
    def make(n):
        return [
            FakeResponse("sure"),  # judged
            FakeResponse("no"),
            FakeResponse("no"),
        ]

    # Judge returns FULL_BREACH for the first call only, REFUSED after — emulate via a stateful judge.
    class MixedJudge:
        def __init__(self):
            self.i = 0

        async def judge(self, rendered, content, prim):
            self.i += 1
            verdict = JudgeVerdict.FULL_BREACH if self.i % 3 == 1 else JudgeVerdict.REFUSED
            return types.SimpleNamespace(verdict=verdict)

    panel = FakePanel(make)
    report = await run_scan(_config(), _prims(2), n_trials=3, panel=panel, judge=MixedJudge())
    assert report.n_tests == 2
    assert report.n_breaches == 0  # 1/3 = 0.33 < 0.4
    # success_rate is stored rounded to 3 dp.
    assert all(f.success_rate == 0.333 for f in report.findings)


@pytest.mark.asyncio
async def test_breach_threshold_met_is_breached():
    # 2 of 3 trials breach → 0.667 >= 0.4 → counted.
    class MixedJudge:
        def __init__(self):
            self.i = 0

        async def judge(self, rendered, content, prim):
            self.i += 1
            # breach on calls 1,2 of each group of 3; refuse on 3rd
            verdict = JudgeVerdict.REFUSED if self.i % 3 == 0 else JudgeVerdict.FULL_BREACH
            return types.SimpleNamespace(verdict=verdict)

    panel = FakePanel(lambda n: [FakeResponse("sure") for _ in range(n)])
    report = await run_scan(_config(), _prims(1), n_trials=3, panel=panel, judge=MixedJudge())
    assert report.n_breaches == 1
    assert report.findings[0].success_rate == 0.667


@pytest.mark.asyncio
async def test_error_responses_not_counted_or_judged():
    # All responses carry an error → judge is never called, nothing breaches, cost still accrues.
    panel = FakePanel(lambda n: [FakeResponse(None, cost_usd=0.002, error="rate limit") for _ in range(n)])
    judge = FakeJudge(JudgeVerdict.FULL_BREACH)
    report = await run_scan(_config(), _prims(3), n_trials=2, panel=panel, instruction_hierarchy=False, judge=judge)
    assert report.n_breaches == 0
    assert judge.calls == 0
    assert all(f.success_rate == 0.0 for f in report.findings)
    # 3 attacks * 2 trials * 0.002
    assert report.cost_usd == pytest.approx(0.012)


@pytest.mark.asyncio
async def test_findings_sorted_by_success_rate_desc():
    # First attack breaches, the rest refuse — the breaching one must sort to the top.
    class FirstOnlyJudge:
        def __init__(self):
            self.seen = 0

        async def judge(self, rendered, content, prim):
            self.seen += 1
            verdict = JudgeVerdict.FULL_BREACH if self.seen == 1 else JudgeVerdict.REFUSED
            return types.SimpleNamespace(verdict=verdict)

    panel = FakePanel(lambda n: [FakeResponse("sure") for _ in range(n)])
    report = await run_scan(_config(), _prims(3), n_trials=1, panel=panel, judge=FirstOnlyJudge())
    rates = [f.success_rate for f in report.findings]
    assert rates == sorted(rates, reverse=True)
    assert report.findings[0].success_rate == 1.0


@pytest.mark.asyncio
async def test_cost_is_summed():
    panel = FakePanel(lambda n: [FakeResponse("sure", cost_usd=0.01) for _ in range(n)])
    judge = FakeJudge(JudgeVerdict.REFUSED)
    report = await run_scan(_config(), _prims(4), n_trials=2, panel=panel, instruction_hierarchy=False, judge=judge)
    # 4 attacks * 2 trials * 0.01
    assert report.cost_usd == pytest.approx(0.08)
