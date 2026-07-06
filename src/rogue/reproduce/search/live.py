"""Real adapters wiring the search subsystem (AutoPT F1-F4) to ROGUE's live components — makes the
paid A/B one command away:

- ``make_rollout`` — a RolloutFn that renders a prompt, runs it against a live ``DeploymentConfig``
  via ``TargetPanel``, and grades it with the ``JudgeAgent`` (the search's evaluation unit).
- ``make_refine_action`` — the LLM-refine expansion, wrapping the PAIR ``IterativeAttacker`` and
  conditioning on the parent rollout (the target's last response + compliance→score).
- ``make_embed_fn`` — OpenAI ``text-embedding-3-small`` for the Feature 3 novelty reward.

Everything else (mock rollout/embed for offline tests) shares the same seams, so nothing here is
search-specific plumbing — it's the live glue.
"""

from __future__ import annotations

from typing import Optional

from rogue.reproduce.instantiator import RenderedAttack
from rogue.schemas.breach_result import JudgeVerdict

from .actions import refine_action
from .searcher import Action, RolloutOutcome


def _rendered_from_prompt(prompt: str, primitive, config) -> RenderedAttack:
    """Wrap a raw prompt as a single-turn RenderedAttack for the current primitive × config."""
    return RenderedAttack(
        messages=[{"role": "user", "content": prompt}],
        is_multi_turn=False,
        resolved_slots={},
        primitive_id=primitive.primitive_id,
        deployment_config_id=config.config_id,
    )


def make_rollout(panel, judge, config, primitive, *, temperature: float = 0.9, judge_cost_usd: float = 0.001):
    """A live RolloutFn: prompt → target (TargetPanel, 1 trial) → judge → RolloutOutcome.

    ``judge_cost_usd`` is a per-grade cost estimate (JudgeResult carries no cost); set it to your
    judge's measured per-call price for a faithful breach-per-dollar A/B.
    """

    async def rollout(prompt: str) -> RolloutOutcome:
        rendered = _rendered_from_prompt(prompt, primitive, config)
        try:  # a flaky target/judge call must degrade to ERROR, never crash the whole search
            responses = await panel.run_attack(rendered, config, temperature=temperature, n_trials=1)
            resp = responses[0]
        except Exception:  # noqa: BLE001
            return RolloutOutcome(JudgeVerdict.ERROR, response="", cost_usd=0.0)
        if resp.error:
            return RolloutOutcome(JudgeVerdict.ERROR, response="", cost_usd=resp.cost_usd)
        try:
            jr = await judge.judge(rendered, resp.content, primitive)
        except Exception:  # noqa: BLE001 — e.g. an OpenRouter judge returning a null-choices response
            return RolloutOutcome(JudgeVerdict.ERROR, response=resp.content, cost_usd=resp.cost_usd)
        return RolloutOutcome(
            jr.verdict, confidence=jr.confidence, response=resp.content,
            cost_usd=resp.cost_usd + judge_cost_usd,
        )

    return rollout


def _compliance_to_pair_score(compliance: Optional[float]) -> int:
    """Map continuous compliance [0,1] onto PAIR's 1-10 score the attacker's refine expects."""
    return max(1, min(10, round(1 + (compliance or 0.5) * 9)))


def make_refine_action(attacker, goal: str, *, name: str = "pair_refine") -> Action:
    """The LLM-refine expansion — one PAIR step conditioned on the parent's response + compliance.

    Cost is the attacker's ``primitive_spent_usd`` delta across the call. A refusal/parse-fail returns
    the prompt unchanged (a $0-ish no-op child), so the searcher just learns the action didn't pay.
    """

    async def refine_fn(prompt: str, parent: Optional[RolloutOutcome]) -> tuple[str, float]:
        before = float(getattr(attacker, "primitive_spent_usd", 0.0) or 0.0)
        response = parent.response if parent is not None else ""
        score = _compliance_to_pair_score(parent.compliance if parent is not None else None)
        try:
            proposal = await attacker.refine(
                goal=goal, previous_prompt=prompt, model_response=response, score=score,
            )
        except Exception:  # noqa: BLE001 — a flaky attacker must not crash the search
            proposal = None
        cost = max(0.0, float(getattr(attacker, "primitive_spent_usd", 0.0) or 0.0) - before)
        return (proposal.prompt if proposal is not None else prompt), cost

    return refine_action(refine_fn, name=name)


def make_seed_primitive(payload: str, *, goal: str = "", title: str = "search-seed"):
    """A minimal single-turn AttackPrimitive wrapping a raw payload — the search seed + judge rubric."""
    import hashlib
    from datetime import datetime, timezone

    from rogue.schemas import (
        AttackFamily, AttackPrimitive, AttackVector, Severity, SourceProvenance,
    )

    pid = "seed-" + hashlib.sha256(payload.encode()).hexdigest()[:12]
    src = SourceProvenance(
        url="https://local/search-ab", source_type="other",
        fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        archive_hash=pid, bright_data_product="fixture",
    )
    return AttackPrimitive(
        primitive_id=pid, family=AttackFamily.DIRECT_INSTRUCTION_OVERRIDE,
        vector=AttackVector.USER_TURN, title=title,
        short_description=(goal or payload)[:200], payload_template=payload,
        reproducibility_score=5, sources=[src], discovered_at=datetime.now(timezone.utc),
        base_severity=Severity.MEDIUM, severity_rationale="search A/B seed",
    )


def make_embed_fn(model: str = "text-embedding-3-small"):
    """OpenAI embedding fn (``Callable[[str], list[float]]``) for the Feature 3 novelty reward."""
    from openai import OpenAI  # lazy: keep the offline/mock paths free of the SDK

    client = OpenAI()

    def embed_fn(text: str) -> list[float]:
        resp = client.embeddings.create(model=model, input=text or " ")
        return resp.data[0].embedding

    return embed_fn


__all__ = ["make_rollout", "make_refine_action", "make_embed_fn"]
