"""Repertoire-mode scans: the ORM→Pydantic corpus converter + the engine's mode branch (offline)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from rogue.packs import load_pack
from rogue.platform.engine import DefaultScanEngine
from rogue.platform.repertoire import _orm_to_primitive
from rogue.platform.schemas import ScanSpec, TargetSpec
from rogue.schemas import AttackPrimitive, JudgeVerdict


def _fake_orm(**over):
    base = {
        "primitive_id": "01KT7BGE2XBY65VX4EKZ3ECQ5G",
        "cluster_id": None,
        "canonical": True,
        "family": "dan_persona",
        "secondary_families": None,
        "vector": "user_turn",
        "title": "Test primitive",
        "short_description": "a test attack primitive",
        "payload_template": "do the forbidden thing",
        "payload_slots": None,
        "multi_turn_sequence": None,
        "target_models_claimed": None,
        "claimed_success_rate": None,
        "claimed_first_seen": None,
        "reproducibility_score": 10,
        "requires_multi_turn": False,
        "requires_system_prompt_access": False,
        "requires_tools": None,
        "requires_multimodal": False,
        "discovered_at": datetime.now(timezone.utc),
        "base_severity": "high",
        "severity_rationale": "high-impact if it lands",
        "notes": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


def test_orm_to_primitive_converts_a_corpus_row():
    p = _orm_to_primitive(_fake_orm())
    assert isinstance(p, AttackPrimitive)
    assert p.primitive_id == "01KT7BGE2XBY65VX4EKZ3ECQ5G"
    assert p.family.value == "dan_persona"
    assert p.vector.value == "user_turn"
    assert p.base_severity.value == "high"
    assert p.payload_template == "do the forbidden thing"
    # JSON-column defaults coerced from None, and the placeholder source so the wire type validates.
    assert p.payload_slots == {}
    assert len(p.sources) == 1
    assert p.primitive_id in str(p.sources[0].url)


def test_orm_to_primitive_accepts_already_typed_enums():
    # When the ORM hands back enum instances (not strings) the converter must pass them through.
    from rogue.schemas import AttackFamily, AttackVector, Severity

    p = _orm_to_primitive(
        _fake_orm(family=AttackFamily.DAN_PERSONA, vector=AttackVector.USER_TURN, base_severity=Severity.HIGH)
    )
    assert p.family == AttackFamily.DAN_PERSONA


class _FakePanel:
    async def run_attack(self, rendered, config, n_trials=1, **kw):
        return [SimpleNamespace(error=None, content="Sure, here you go.", cost_usd=0.0001) for _ in range(n_trials)]

    async def aclose(self):
        return None


class _FakeJudge:
    async def judge(self, rendered, model_response, primitive):
        breach = primitive.family.value == "dan_persona"
        return SimpleNamespace(verdict=JudgeVerdict.FULL_BREACH if breach else JudgeVerdict.REFUSED)


@pytest.mark.asyncio
async def test_engine_repertoire_mode_uses_the_loader_not_the_pack():
    # Inject a repertoire loader (stands in for the DB corpus); the engine must source from it, not
    # from load_pack, and run the identical scan loop.
    corpus = load_pack("default")[:3]  # real AttackPrimitives standing in for harvested corpus rows
    calls: list = []

    def loader(spec):
        calls.append(spec)
        return corpus

    engine = DefaultScanEngine(panel=_FakePanel(), judge=_FakeJudge(), repertoire_loader=loader)
    spec = ScanSpec(target=TargetSpec(endpoint="https://x/v1", api_key="k"), mode="repertoire", max_tests=3)
    report = await engine.run(spec)

    assert len(calls) == 1  # the repertoire loader was consulted
    assert calls[0] is spec
    assert report.n_tests == 3  # ran over the loader's primitives


@pytest.mark.asyncio
async def test_engine_pack_mode_unaffected():
    engine = DefaultScanEngine(panel=_FakePanel(), judge=_FakeJudge(), repertoire_loader=lambda s: (_ for _ in ()).throw(AssertionError("loader must not run in pack mode")))
    spec = ScanSpec(target=TargetSpec(provider="openai"), mode="pack", pack="default", max_tests=2)
    report = await engine.run(spec)
    assert report.n_tests == 2  # pack path, loader never called
