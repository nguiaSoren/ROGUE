"""Agent-exec scan stage (Phase 7-live-b) — run the agentic tier for ONE customer config and
map breaches to report ``Finding``s, engagement-gated.

Pure orchestration: the caller (``scan.py:run_scan``) builds an :class:`AgentExecRunner` and the
adapter; this runs each agentic primitive over N trials, and emits a ``Finding`` per *measurable*
primitive (one where the model actually engaged a tool ≥1 trial). A primitive the model never
engaged produces NO finding — its "0 breaches" would be confounded by not-calling-tools, not
resistance, so it's counted in ``n_agentic - n_measurable`` and left out of the findings.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from rogue.report import Finding
from rogue.schemas import AttackPrimitive, DeploymentConfig, Severity

from .canaries import new_run_secret
from .context import AgentRunContext
from .scenarios import build_scenario, render_primitive
from .tier import AgentExecBudget, _has_agentic_surface, run_agent_exec_one, to_persistence_rows
from .trace_judge import headline_findings

_SEV = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2, Severity.CRITICAL: 3}


@dataclass
class AgentStageResult:
    """Outcome of the agent-exec stage for one config."""

    findings: list[Finding] = field(default_factory=list)
    persist_rows: list = field(default_factory=list)  # [(BreachResultORM, AgentTranscriptORM, [TraceFindingORM])]
    cost_usd: float = 0.0
    n_agentic: int = 0      # agentic primitives tested
    n_measurable: int = 0   # primitives the model engaged (≥1 tool call in ≥1 trial)
    n_breaching: int = 0    # primitives with ≥1 headline breach


def _severity_str(best: Any, prim: AttackPrimitive) -> str:
    """Max severity of the breach's headline findings, else the primitive's base severity."""
    if best is not None:
        sevs = [f.severity for f in headline_findings(best.findings)]
        if sevs:
            return max(sevs, key=lambda s: _SEV[s]).value
    return prim.base_severity.value


def _evidence(best: Any) -> tuple[str, str]:
    """(what the attack did, what the model did) — the breaching tool-call slice, canary redacted."""
    if best is None or best.transcript is None:
        return ("indirect tool-output injection", "")
    signals = [f.signal.value for f in headline_findings(best.findings)]
    call_desc = ""
    for turn in best.transcript.turns:
        for c in turn.tool_calls:
            if c.tool_name == "send_email" or c.is_forbidden or c.smuggled_secret_ids:
                call_desc = f"{c.tool_name}({', '.join(sorted(c.arguments.keys()))})"
                break
    return (f"tool-hijack / indirect injection → signals {signals}", call_desc or "followed injected tool directive")


async def run_agent_exec_stage(
    config: DeploymentConfig,
    primitives: list[AttackPrimitive],
    *,
    runner: Any,
    seeds: int = 3,
    framing: str = "raw",
    temperature: float = 0.7,
    per_run_timeout: float = 90.0,
    concurrency: int = 6,
    adapter: Any = None,
    want_persist: bool = False,
) -> AgentStageResult:
    agentic = [p for p in primitives if _has_agentic_surface(p)]
    res = AgentStageResult(n_agentic=len(agentic))
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one_trial(prim, rendered, trial):
        async with sem:
            budget = AgentExecBudget(runner.cfg)
            budget.start_run()
            user, injections = build_scenario(prim, rendered, framing=framing)
            ctx = AgentRunContext(seed=trial, run_secret=new_run_secret(), injections=injections)
            try:
                return await asyncio.wait_for(
                    run_agent_exec_one(
                        prim, config, harness=runner.harness, judge=runner.judge, cfg=runner.cfg,
                        budget=budget, user_prompt=user, ctx=ctx, trial_index=trial, temperature=temperature,
                        adapter=adapter,
                    ),
                    timeout=per_run_timeout,
                )
            except Exception:  # noqa: BLE001 — timeout/provider error → this trial is dropped
                return None

    async def _prim(prim):
        rendered = render_primitive(prim, config)
        outs = await asyncio.gather(*[_one_trial(prim, rendered, s) for s in range(seeds)])
        engaged = breach = 0
        cost = 0.0
        best = None
        for o in outs:
            if o is None:
                continue
            cost += o.spend_usd
            if o.transcript is not None and o.transcript.n_turns > 1 and not o.errored:
                engaged += 1
                if o.headline_breached:
                    breach += 1
                    best = best or o
        return prim, engaged, breach, best, cost

    for prim, engaged, breach, best, cost in await asyncio.gather(*[_prim(p) for p in agentic]):
        res.cost_usd += cost
        if engaged == 0:
            continue  # not measurable — no finding (not a false 0%)
        res.n_measurable += 1
        if breach > 0:
            res.n_breaching += 1
        atk, resp = _evidence(best)
        res.findings.append(Finding(
            family=prim.family.value, technique="agent-exec", vector=prim.vector.value,
            severity=_severity_str(best, prim), title=prim.title,
            success_rate=breach / engaged, n_trials=engaged, n_breach=breach,
            example_attack=atk, example_response=resp, agentic=True, primitive_id=prim.primitive_id,
        ))
        if want_persist and best is not None:
            res.persist_rows.append(to_persistence_rows(best, prim, config))

    res.findings.sort(key=lambda f: f.success_rate, reverse=True)
    return res


__all__ = ["AgentStageResult", "run_agent_exec_stage"]
