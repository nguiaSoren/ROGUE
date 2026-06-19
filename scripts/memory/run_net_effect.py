"""REAL net-effect run for Surface 3 (build-08 §4) — the verified-promotion gate, live.

The verified-promotion gate admits a shared skill to ``active`` ONLY after a *measured*
net-positive effect on a held-out set: ``net_effect = repairs - regressions``, whose
bootstrap repair-fraction CI lower bound is confidently above ``PROMOTION_RATE_FLOOR``
(0.5). This script runs that gate for real over the harvested 55-skill pool:

- For each candidate skill it builds a per-skill held-out set = the held-out tasks whose
  ``applicable_skill_ids`` name that skill (only skills with >= ``--min-tasks`` tasks are
  verified, so the bootstrap CI is meaningful).
- A real :class:`GroqRolloutRunner` rolls each held-out task out TWICE against a weak
  agent model (Groq): once with a plain assistant system prompt (WITHOUT the skill), once
  with the skill's ``skill_md`` injected into the system prompt (WITH the skill).
- The real ``net_effect_judge`` (Anthropic) grades each (without, with) pair REPAIR /
  REGRESSION / NEUTRAL — a worse OUTCOME (not "looks worse") is the only breach.
- ``evaluate_promotion`` bootstraps the repair fraction and PROMOTES iff the CI lower
  bound > 0.5. The summary line is the real "N of M skills verified net-positive" number
  for the attestation.

COSTS REAL MONEY (Groq agent rollouts + Anthropic net-effect judge — ~$2-3). Run deliberately.

    uv run python scripts/memory/run_net_effect.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import dotenv
import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _groq import groq_chat  # noqa: E402  (robust retry/backoff Groq helper)

from rogue.db.models import Skill, SkillSourceKind, SkillStatus
from rogue.memory.judges import net_effect_judge
from rogue.memory.promotion import (
    PROMOTION_RATE_FLOOR,
    InMemoryVerificationStore,
    evaluate_promotion,
)

_POOL = Path("tests/fixtures/memory/skill_pool.json")
_HELD_OUT = Path("tests/fixtures/memory/held_out_tasks.json")


def _load_skills() -> list[Skill]:
    """Build candidate ``Skill`` objects from the fixture, preserving the original ids.

    The held-out tasks reference skills by their fixture ``skill_id`` (``skill-NNN``), so
    we construct the ORM objects directly (rather than via ``SkillPool.load_fixture``,
    which assigns fresh uuids) to keep that mapping. No embedding is set — the gate reads
    only ``skill_id`` / ``skill_md`` / ``status``.
    """
    records = json.loads(_POOL.read_text())
    skills: list[Skill] = []
    for rec in records:
        skills.append(
            Skill(
                skill_id=rec["skill_id"],
                org_id="org-trusted-team",
                cohort_id="trusted-team",
                trust_domain="trusted-team",
                skill_md=rec["skill_md"],
                embedding=None,
                status=SkillStatus.CANDIDATE,
                applicability_condition=rec.get("applicability_condition") or {},
                source_kind=SkillSourceKind(rec["source_kind"]),
            )
        )
    return skills


def _load_held_out() -> list[dict[str, Any]]:
    return json.loads(_HELD_OUT.read_text())


def build_held_out_sets(
    skills: list[Skill], tasks: list[dict[str, Any]], *, min_tasks: int
) -> dict[str, list[dict[str, Any]]]:
    """Per-skill held-out set = tasks whose ``applicable_skill_ids`` name that skill.

    Returns only the skills that clear ``min_tasks`` (so the bootstrap CI is meaningful),
    keyed by ``skill_id`` and in fixture order within each set.
    """
    by_skill: dict[str, list[dict[str, Any]]] = defaultdict(list)
    known = {s.skill_id for s in skills}
    for task in tasks:
        for sid in task.get("applicable_skill_ids", []):
            if sid in known:
                by_skill[sid].append(task)
    return {sid: ts for sid, ts in by_skill.items() if len(ts) >= min_tasks}


class GroqRolloutRunner:
    """Rolls one held-out task out twice against a weak Groq agent: WITHOUT vs WITH skill.

    WITHOUT: the agent is asked to do ``instance["task"]`` under a plain assistant system
    prompt. WITH: the same task, but the candidate skill's ``skill_md`` is injected into
    the system prompt as an available team skill. The (without, with) pair is what the
    net-effect judge grades. Mirrors the httpx ``_ask`` pattern from
    ``run_leakage_redteam.py`` — one bad call returns an error string rather than sinking
    the run.
    """

    _PLAIN_SYSTEM = (
        "You are a helpful engineering assistant. Complete the user's task directly "
        "and correctly."
    )

    def __init__(self, api_key: str, model: str) -> None:
        self._key = api_key
        self._model = model
        self._client = httpx.Client(timeout=30)

    def _ask(self, system: str, user: str) -> str:
        return groq_chat(
            self._client, self._key, self._model, system, user,
            max_tokens=180, temperature=0.7, error_tag="rollout-call-error",
        )

    def _with_system(self, skill: Skill) -> str:
        return (
            "You are a helpful engineering assistant. You have this team skill "
            "available, use it if relevant:\n<skill_md>\n"
            f"{skill.skill_md}\n</skill_md>\n\n"
            "Complete the user's task directly and correctly."
        )

    def rollout(self, skill: Skill, instance: dict[str, Any]) -> tuple[str, str]:
        task = instance.get("task", "")
        without_output = self._ask(self._PLAIN_SYSTEM, task)
        with_output = self._ask(self._with_system(skill), task)
        return without_output, with_output


def main() -> int:
    dotenv.load_dotenv(dotenv_path=os.path.join(os.getcwd(), ".env"))
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--agent-model", default="llama-3.1-8b-instant")
    ap.add_argument("--min-tasks", type=int, default=5)
    ap.add_argument("--cohort", default="trusted-team")
    args = ap.parse_args()

    key = os.environ["GROQ_API_KEY"]
    skills = _load_skills()
    skills_by_id = {s.skill_id: s for s in skills}
    tasks = _load_held_out()
    held_out_sets = build_held_out_sets(skills, tasks, min_tasks=args.min_tasks)

    eligible = sorted(held_out_sets)
    print(
        f"loaded {len(skills)} skills, {len(tasks)} held-out tasks; "
        f"{len(eligible)} skills clear --min-tasks={args.min_tasks} "
        f"(net-effect gate floor CI-lb > {PROMOTION_RATE_FLOOR})"
    )
    print(
        f"rolling each held-out task out twice against a {args.agent_model} agent "
        "(WITHOUT vs WITH skill); Anthropic net-effect judge grades each pair…\n"
    )

    runner = GroqRolloutRunner(key, args.agent_model)
    judge = net_effect_judge()

    promoted: list[tuple[str, float, float]] = []  # (skill_id, ci_low, ci_high)
    for sid in eligible:
        skill = skills_by_id[sid]
        held = held_out_sets[sid]
        verification = evaluate_promotion(
            skill,
            cohort_id=args.cohort,
            held_out_set=held,
            runner=runner,
            judge=judge,
            store=InMemoryVerificationStore(),
        )
        decision = "PROMOTE" if verification.verdict.value == "pass" else "REJECT"
        if decision == "PROMOTE":
            promoted.append((sid, verification.ci_low, verification.ci_high))
        print(
            f"  {sid:<14} tasks={verification.held_out_n:>2}  "
            f"repairs={verification.repairs:>2} regressions={verification.regressions:>2} "
            f"neutrals={verification.held_out_n - verification.repairs - verification.regressions:>2}  "
            f"net_effect={int(verification.net_effect):>+3}  "
            f"repair-frac CI=[{verification.ci_low:.2f}, {verification.ci_high:.2f}]  "
            f"-> {decision}"
        )

    print("\n=== VERIFIED-PROMOTION RESULT (real net-effect run) ===")
    print(
        f"{len(promoted)} of {len(eligible)} skills verified net-positive "
        f"(CI-lb > {PROMOTION_RATE_FLOOR})"
    )
    if promoted:
        print("promoted skill_ids + repair-fraction CIs:")
        for sid, lo, hi in promoted:
            print(f"  {sid}: CI=[{lo:.2f}, {hi:.2f}]")
    else:
        print("no skills cleared the gate on this held-out set.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
