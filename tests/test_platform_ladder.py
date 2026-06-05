"""Ladder-mode scans: the engine's `mode="ladder"` branch, with the escalation machinery mocked.

The real ladder needs a DB + attacker/target/judge LLMs (money), so here both the escalation context
and the per-goal ladder runner are injected — this verifies the engine's orchestration (per-goal fan-out,
budget→per-goal split, LadderResult→Finding mapping), not the ladder internals (covered by
tests/test_escalation_ladder.py)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from rogue.platform.engine import DefaultScanEngine
from rogue.platform.schemas import ScanSpec, TargetSpec


def _fake_ctx():
    return SimpleNamespace(
        planner=SimpleNamespace(),  # no aclose → engine skips it
        rotation=("crescendo", "actor_attack"),
        image_renderers=(),
        coj_operations=(),
        structured_formats=(),
        audio_styles=(),
        effective_quota=0,
        candidate_ids=frozenset(),
    )


def _ladder_result(winning):
    return SimpleNamespace(
        parent_id="p",
        winning_strategy=winning,
        breached_on="m" if winning else None,
        attempts=[("crescendo", "breach" if winning else "no_breach")],
        child_orm=None,
        spend_usd=0.01,
    )


@pytest.mark.asyncio
async def test_ladder_mode_orchestrates_per_goal():
    ctx_calls: list = []
    runner_kwargs: list = []

    def ctx_builder(config, n_goals, n_trials):
        ctx_calls.append((n_goals, n_trials))
        return _fake_ctx()

    async def runner(goal, **kw):
        runner_kwargs.append(kw)
        return _ladder_result("crescendo")  # every goal breaches

    engine = DefaultScanEngine(
        panel=object(), judge=object(), escalation_ctx_builder=ctx_builder, ladder_runner=runner
    )
    spec = ScanSpec(target=TargetSpec(provider="openai"), mode="ladder", pack="default", max_tests=3, budget=1.0)
    report = await engine.run(spec)

    # context built once, sized to the goal count
    assert ctx_calls == [(3, spec.n_trials)]
    # ran the ladder per goal, with the per-goal budget split (1.0 / 3) and the ctx's rotation/quota
    assert len(runner_kwargs) == 3
    assert runner_kwargs[0]["budget_usd"] == pytest.approx(1.0 / 3)
    assert runner_kwargs[0]["strategies"] == ("crescendo", "actor_attack")
    assert runner_kwargs[0]["candidate_attempt_quota"] == 0
    # LadderResult → Finding mapping: winning_strategy becomes the technique, breach counts, cost sums
    assert report.n_tests == 3
    assert report.n_breaches == 3
    # engine humanizes winning_strategy at persist time (report.humanize_technique), so the raw
    # "crescendo" code surfaces as its customer-facing display label.
    assert all(
        f.technique == "Crescendo (gradual escalation)" and f.success_rate == 1.0 and f.n_breach == 1
        for f in report.findings
    )
    assert report.cost_usd == pytest.approx(0.03)


@pytest.mark.asyncio
async def test_ladder_mode_no_breach_falls_back_to_family_label():
    async def runner(goal, **kw):
        return _ladder_result(None)  # nothing breached

    engine = DefaultScanEngine(
        panel=object(), judge=object(), escalation_ctx_builder=lambda c, n, t: _fake_ctx(), ladder_runner=runner
    )
    spec = ScanSpec(target=TargetSpec(provider="openai"), mode="ladder", pack="default", max_tests=2)
    report = await engine.run(spec)

    assert report.n_tests == 2
    assert report.n_breaches == 0
    # held goals: success_rate 0, technique is the family label (not a winning strategy)
    assert all(f.success_rate == 0.0 and f.n_breach == 0 for f in report.findings)


@pytest.mark.asyncio
async def test_ladder_mode_defaults_budget_when_unset():
    # No budget on the spec → the engine falls back to its safe cap and still splits per goal.
    captured: list = []

    async def runner(goal, **kw):
        captured.append(kw["budget_usd"])
        return _ladder_result(None)

    from rogue.platform.engine import _DEFAULT_LADDER_BUDGET

    engine = DefaultScanEngine(
        panel=object(), judge=object(), escalation_ctx_builder=lambda c, n, t: _fake_ctx(), ladder_runner=runner
    )
    spec = ScanSpec(target=TargetSpec(provider="openai"), mode="ladder", pack="default", max_tests=4)
    await engine.run(spec)
    assert captured and captured[0] == pytest.approx(_DEFAULT_LADDER_BUDGET / 4)
