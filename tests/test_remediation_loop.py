"""Whole-area offline exit gate for Surface 1b (build-05 §7 + the §0 area exit gate).

The remediation loop end-to-end with a FAKE panel + FAKE judge (no network, no spend): a breach →
generate → re-test → accept/iterate. Covers the clean accept (breach↓ + over-block≈0), the
over-block REJECTION (the on-brand half — a fix that closes the breach but blocks legitimate
traffic is NOT accepted), the honest architecture fallback on exhaustion, and reverify's regression
flag. One judge object is reused across passes (ADR-0010: no second model).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from rogue.remediation import RemediationLoop, RemediationTask
from rogue.schemas import AttackPrimitive, JudgeVerdict, demo_deployment_configs
from rogue.schemas.governance import ClientPolicy
from rogue.schemas.remediation import CONFIG_APPLICABLE, MitigationType

_FIX = Path("tests/fixtures/governance")


def _rule(rule_id: str):
    pol = ClientPolicy.model_validate_json((_FIX / "sample_policy.json").read_text())
    return next(r for r in pol.rules if r.rule_id == rule_id)


def _attacks(start: int = 0, end: int = 2) -> list[AttackPrimitive]:
    raw = json.loads((_FIX / "mini_corpus.json").read_text())
    rows = raw["primitives"] if isinstance(raw, dict) and "primitives" in raw else raw
    return [AttackPrimitive.model_validate(r) for r in rows[start:end]]


class _Verdict:
    def __init__(self, v):
        self.verdict = v
        self.rationale = "fake"
        self.confidence = 1.0


class _ScenarioJudge:
    """Returns ``attack_verdict`` for the task's attack primitives and ``legit_verdict`` for the
    legitimate probes (distinguished by primitive_id). One object reused across both passes."""

    def __init__(self, attack_ids, *, attack_verdict, legit_verdict):
        self._attack_ids = set(attack_ids)
        self._av, self._lv = attack_verdict, legit_verdict

    async def judge(self, rendered, model_response, primitive, context=None):
        v = self._av if primitive.primitive_id in self._attack_ids else self._lv
        return _Verdict(v)


class _FakeResp:
    def __init__(self, content: str = "ok"):
        self.content = content
        self.cost_usd = 0.0


class _FakePanel:
    async def run_attack(self, rendered, config, temperature: float = 0.7, n_trials: int = 5):
        return [_FakeResp() for _ in range(n_trials)]


def _fake_complete(prompt: str) -> str:
    return "MITIGATION: never disclose a protected value outside an authorized, retrieved context."


def _loop(attacks, *, attack_v, legit_v):
    judge = _ScenarioJudge([p.primitive_id for p in attacks], attack_verdict=attack_v, legit_verdict=legit_v)
    return RemediationLoop(panel=_FakePanel(), judge=judge, complete=_fake_complete, n_trials=3)


def _task(attacks):
    return RemediationTask(rule=_rule("R1"), config=demo_deployment_configs()[0],
                           primitives=attacks, transcripts=["...the salary figure was disclosed..."],
                           pre_breach_rate=1.0)


def test_loop_accepts_a_clean_fix():
    attacks = _attacks()
    # attacks now resisted (REFUSED → post-breach 0); legit engaged (FULL_BREACH → 0 false-blocks)
    res = asyncio.run(_loop(attacks, attack_v=JudgeVerdict.REFUSED, legit_v=JudgeVerdict.FULL_BREACH)
                      .run(_task(attacks)))
    assert res.accepted and res.verified_by == "rescan"
    assert res.candidate.mitigation_type in CONFIG_APPLICABLE
    assert res.post_breach_rate < res.pre_breach_rate == 1.0
    assert res.over_block is not None and res.over_block.over_block_rate <= 0.05
    assert res.breach_reduced


def test_loop_rejects_on_over_block_then_architecture():
    attacks = _attacks()
    # breach closes (attacks REFUSED) BUT the fix also blocks legit traffic (legit REFUSED) → reject
    res = asyncio.run(_loop(attacks, attack_v=JudgeVerdict.REFUSED, legit_v=JudgeVerdict.REFUSED)
                      .run(_task(attacks)))
    assert res.candidate.mitigation_type == MitigationType.ARCHITECTURE_RECOMMENDATION
    assert res.verified_by == "by_construction_out_of_band" and res.accepted
    assert res.rejected_candidates  # the over-blocking patch is retained


def test_loop_architecture_when_breach_not_reduced():
    attacks = _attacks()
    res = asyncio.run(_loop(attacks, attack_v=JudgeVerdict.FULL_BREACH, legit_v=JudgeVerdict.FULL_BREACH)
                      .run(_task(attacks)))
    assert res.candidate.mitigation_type == MitigationType.ARCHITECTURE_RECOMMENDATION
    assert not res.breach_reduced


def test_reverify_flags_regression():
    attacks = _attacks(0, 2)
    res = asyncio.run(_loop(attacks, attack_v=JudgeVerdict.REFUSED, legit_v=JudgeVerdict.FULL_BREACH)
                      .run(_task(attacks)))
    assert res.accepted and res.candidate.mitigation_type in CONFIG_APPLICABLE
    # new harvested variants now breach the accepted mitigation → regression
    new = _attacks(2, 4)
    loop2 = _loop(new, attack_v=JudgeVerdict.FULL_BREACH, legit_v=JudgeVerdict.FULL_BREACH)
    out = asyncio.run(loop2.reverify(res, new, task=_task(attacks)))
    assert out["reverified"] and out["regressed"]
    assert out["new_breach_rate"] > res.post_breach_rate
