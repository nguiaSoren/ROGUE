"""RTBF entity-unlearning verification — the SCAN/REPRODUCE stage that wires `rtbf_probe` into ROGUE.

`rtbf_probe.py` is the pure logic (paraphrase, leak scoring). This module fires the probes through the
**real target panel** (each probe rendered as a synthetic single-turn primitive, same dispatch path as
a normal attack) and grades recall with an injected leak judge. Reused by `run_scan` (opt-in) and the
`rtbf_audit` script. Fully fail-soft — a compliance gauge must never fail the scan.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from .rtbf_probe import EntityAttribute, ProbeOutcome, RtbfScore, attribute_leaked, make_paraphrases, score_rtbf

__all__ = ["RtbfStageResult", "run_rtbf_stage"]

InvokeFn = Callable[[str, str], str]


@dataclass
class RtbfStageResult:
    score: RtbfScore
    outcomes: list[ProbeOutcome]
    cost_usd: float


async def _ask(panel: Any, config: Any, question: str) -> str:
    """Fire one raw question at the target via the normal render→panel path; return the text (or '')."""
    from ..search.live import make_seed_primitive  # lazy
    from ..instantiator import render

    prim = make_seed_primitive(question, goal=question)
    rendered = render(prim, config)
    responses = await panel.run_attack(rendered, config, n_trials=1)
    for r in responses:
        if getattr(r, "error", None) is None and r.content:
            return r.content, getattr(r, "cost_usd", 0.0) or 0.0
    return "", (responses[0].cost_usd if responses else 0.0) or 0.0


async def run_rtbf_stage(
    attributes: list[EntityAttribute],
    config: Any,
    *,
    panel: Any,
    leak_invoke: InvokeFn,
    paraphrase_invoke: Optional[InvokeFn] = None,
    n_paraphrases: int = 3,
    max_attributes: int = 12,
) -> RtbfStageResult:
    """Probe each attribute across paraphrase variants through the live panel, then score forget-leak vs
    neighbor-retain. ``paraphrase_invoke`` defaults to ``leak_invoke``. Capped + fail-soft."""
    para_inv = paraphrase_invoke or leak_invoke
    outcomes: list[ProbeOutcome] = []
    cost = 0.0
    for attr in attributes[:max_attributes]:
        try:
            variants = make_paraphrases(attr.question, para_inv, n=n_paraphrases)
            answers: list[str] = []
            for q in variants:
                ans, c = await _ask(panel, config, q)
                cost += c
                if ans:
                    answers.append(ans)
            present = attribute_leaked(answers, attr.gold, leak_invoke)  # gold recalled under some variant?
            outcomes.append(ProbeOutcome(
                attr=attr, variants_fired=len(variants),
                recovered=(present and not attr.is_neighbor),  # forget probe: recall = a LEAK
                retained=(present and attr.is_neighbor)))       # neighbor probe: recall = retained (good)
        except Exception:  # noqa: BLE001 — a gauge must never fail the scan
            continue
    return RtbfStageResult(score_rtbf(outcomes), outcomes, round(cost, 6))
