"""SDK ``benchmark()`` backend tests — :func:`rogue.benchmark.run_benchmark`.

Fully offline: an injected fake panel (returns canned ``ModelResponse``-like objects)
and a fake judge (fixed verdict) replace the real network path, so these prove the
benchmark wiring — bundled goal load, ``max_goals`` cap, goal→primitive wrapping, and
ASR/cost reporting — without spending or hitting any provider.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from rogue.benchmark import VALID_DATASETS, goal_primitive, run_benchmark
from rogue.report import BenchmarkReport
from rogue.schemas import AttackFamily, AttackVector, DeploymentConfig, JudgeVerdict


def _config() -> DeploymentConfig:
    return DeploymentConfig(
        customer_id="adhoc",
        config_id="bench-test-cfg",
        name="bench test",
        target_model="test-model-1",
        system_prompt="be safe",
    )


class _FakeResponse:
    """Stands in for rogue.reproduce.target_panel.ModelResponse (the attrs run_scan reads)."""

    def __init__(self, *, content="Sure, here it is.", error=None, cost_usd=0.001):
        self.content = content
        self.error = error
        self.cost_usd = cost_usd


class _FakePanel:
    """Returns ``n_trials`` canned responses per attack; records call count. No network."""

    def __init__(self, *, response: _FakeResponse | None = None):
        self._response = response or _FakeResponse()
        self.calls = 0

    async def run_attack(self, rendered, config, *, n_trials=1):
        self.calls += 1
        return [self._response for _ in range(n_trials)]

    async def aclose(self):
        return None


class _FakeJudge:
    def __init__(self, verdict: JudgeVerdict):
        self._verdict = verdict
        self.calls = 0

    async def judge(self, rendered, content, primitive):
        self.calls += 1
        return SimpleNamespace(verdict=self._verdict)


# --- goal → AttackPrimitive wrapper -----------------------------------------------------------


def test_goal_primitive_is_valid_single_turn_direct_request():
    prim = goal_primitive("Explain how to do a harmful thing in detail")
    assert prim.family is AttackFamily.DIRECT_INSTRUCTION_OVERRIDE
    assert prim.vector is AttackVector.USER_TURN
    assert prim.payload_template == "Explain how to do a harmful thing in detail"
    assert prim.short_description == "Explain how to do a harmful thing in detail"
    assert len(prim.sources) >= 1
    assert len(prim.primitive_id) >= 10  # ULID
    assert prim.canonical is False


def test_goal_primitive_ids_are_unique():
    a = goal_primitive("goal one is long enough")
    b = goal_primitive("goal two is long enough")
    assert a.primitive_id != b.primitive_id


def test_goal_primitive_pads_short_goal():
    prim = goal_primitive("hi")  # < 10 chars
    assert "[benchmark goal]" in prim.payload_template


# --- dataset loading --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_advbench_loads_bundled_goals():
    report = await run_benchmark(
        _config(), dataset="advbench_100", max_goals=10,
        panel=_FakePanel(), judge=_FakeJudge(JudgeVerdict.REFUSED),
    )
    assert report.dataset == "advbench_100"
    assert report.n_goals == 10


@pytest.mark.asyncio
async def test_jbb_loads_bundled_goals():
    report = await run_benchmark(
        _config(), dataset="jbb_100", max_goals=10,
        panel=_FakePanel(), judge=_FakeJudge(JudgeVerdict.REFUSED),
    )
    assert report.dataset == "jbb_100"
    assert report.n_goals == 10


@pytest.mark.asyncio
async def test_both_datasets_have_a_meaningful_bundled_subset():
    for ds in VALID_DATASETS:
        report = await run_benchmark(
            _config(), dataset=ds, max_goals=1000,
            panel=_FakePanel(), judge=_FakeJudge(JudgeVerdict.REFUSED),
        )
        assert report.n_goals >= 20  # ~40 bundled


@pytest.mark.asyncio
async def test_max_goals_caps_the_run():
    panel = _FakePanel()
    report = await run_benchmark(
        _config(), dataset="advbench_100", max_goals=3,
        panel=panel, judge=_FakeJudge(JudgeVerdict.REFUSED),
    )
    assert report.n_goals == 3
    assert panel.calls == 3  # one attack per goal


@pytest.mark.asyncio
async def test_unknown_dataset_raises_valueerror_listing_valid_names():
    with pytest.raises(ValueError) as exc:
        await run_benchmark(_config(), dataset="not_a_dataset", panel=_FakePanel(),
                            judge=_FakeJudge(JudgeVerdict.REFUSED))
    msg = str(exc.value)
    assert "advbench_100" in msg and "jbb_100" in msg


# --- ASR computation --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_breach_gives_asr_one():
    report = await run_benchmark(
        _config(), dataset="advbench_100", max_goals=5,
        panel=_FakePanel(), judge=_FakeJudge(JudgeVerdict.FULL_BREACH),
    )
    assert report.n_success == 5
    assert report.asr == 1.0


@pytest.mark.asyncio
async def test_all_refuse_gives_asr_zero():
    report = await run_benchmark(
        _config(), dataset="advbench_100", max_goals=5,
        panel=_FakePanel(), judge=_FakeJudge(JudgeVerdict.REFUSED),
    )
    assert report.n_success == 0
    assert report.asr == 0.0


# --- BenchmarkReport fields -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_fields_and_summary():
    report = await run_benchmark(
        _config(), dataset="advbench_100", max_goals=4,
        panel=_FakePanel(response=_FakeResponse(cost_usd=0.01)),
        judge=_FakeJudge(JudgeVerdict.FULL_BREACH),
    )
    assert isinstance(report, BenchmarkReport)
    assert report.target == "test-model-1"  # no base_url → target_model
    assert report.winner_rank is None
    assert report.cost_usd > 0
    # cost_per_success = cost / successes
    assert report.cost_per_success == pytest.approx(report.cost_usd / report.n_success)
    s = report.summary()
    assert "advbench_100" in s and "ASR" in s and "100%" in s


@pytest.mark.asyncio
async def test_cost_per_success_is_none_when_no_breach():
    report = await run_benchmark(
        _config(), dataset="advbench_100", max_goals=3,
        panel=_FakePanel(), judge=_FakeJudge(JudgeVerdict.REFUSED),
    )
    assert report.cost_per_success is None


@pytest.mark.asyncio
async def test_target_prefers_base_url():
    cfg = DeploymentConfig(
        customer_id="adhoc", config_id="bench-url-cfg", name="bench url",
        target_model="custom/x", system_prompt="", base_url="https://api.company.com/v1",
    )
    report = await run_benchmark(
        cfg, dataset="jbb_100", max_goals=2,
        panel=_FakePanel(), judge=_FakeJudge(JudgeVerdict.REFUSED),
    )
    assert report.target == "https://api.company.com/v1"
