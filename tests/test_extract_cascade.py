"""Local-first extraction cascade (Q17) — deterministic, $0 (no live model).

Proves the cascade routing/gate logic with stubbed local + fallback tiers, the
env resolver's off-by-default contract, and the harvest seam's byte-identical
off-path. No network: the tiers are fakes.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from rogue.extract.cascade import (
    CascadeConfig,
    CascadeExtractionAgent,
    CascadeStats,
    maybe_build_cascade_extractor,
    resolve_cascade_config,
)
from rogue.schemas import AttackPrimitive, RawDocument, TechniqueSpec

FIXTURES = Path(__file__).parent / "fixtures"


def _raw_doc(content: str) -> RawDocument:
    return RawDocument(
        url="https://example.com/doc",
        source_type="blog",
        bright_data_product="web_unlocker",
        fetched_at=datetime.now(timezone.utc),
        raw_content=content,
        content_format="text",
        archive_hash=hashlib.sha256(content.encode()).hexdigest(),
        http_status=200,
    )


def _prim(payload_template: str) -> AttackPrimitive:
    g = json.loads((FIXTURES / "02_copirate_365_cve_2026_24299.json").read_text())
    base = {k: v for k, v in g.items() if k != "is_attack"}
    base["payload_template"] = payload_template
    return AttackPrimitive.model_validate(base)


class _FakeLocal:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    async def extract_from_raw_document(self, raw_doc, images=None):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _FakeFallback:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    async def extract_any_from_raw_document(self, raw_doc, images=None):
        self.calls += 1
        return self.result


def _cascade(local_result, fallback_result) -> CascadeExtractionAgent:
    c = CascadeExtractionAgent(CascadeConfig(enabled=True))
    c.local = _FakeLocal(local_result)
    c.fallback = _FakeFallback(fallback_result)
    return c


# --------------------------------------------------------------------------- #
# env resolver / off-by-default
# --------------------------------------------------------------------------- #

def test_off_by_default(monkeypatch) -> None:
    monkeypatch.delenv("ROGUE_EXTRACT_CASCADE", raising=False)
    assert resolve_cascade_config().enabled is False
    assert maybe_build_cascade_extractor() is None


def test_on_when_flag_truthy(monkeypatch) -> None:
    monkeypatch.setenv("ROGUE_EXTRACT_CASCADE", "on")
    assert resolve_cascade_config().enabled is True
    agent = maybe_build_cascade_extractor(fallback_model="anthropic/claude-haiku-4-5")
    assert isinstance(agent, CascadeExtractionAgent)
    assert agent.config.fallback_model == "anthropic/claude-haiku-4-5"


def test_stats_math() -> None:
    s = CascadeStats(
        n_docs=10,
        n_local_accepted=4,
        n_escalated_abstain=3,
        n_escalated_ungrounded=2,
        n_escalated_error=1,
    )
    assert s.n_escalated == 6
    assert s.local_save_rate == pytest.approx(0.4)
    d = s.to_dict()
    assert d["n_escalated"] == 6 and d["local_save_rate"] == 0.4


# --------------------------------------------------------------------------- #
# routing / acceptance gate
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_grounded_local_accepted_no_escalation() -> None:
    doc = _raw_doc("here is the verbatim injection payload override system now")
    prim = _prim("verbatim injection payload override system")  # tokens in doc
    c = _cascade(local_result=prim, fallback_result=None)
    out = await c.extract_any_from_raw_document(doc)
    assert out is prim
    assert c.fallback.calls == 0  # Haiku never called — the saving
    assert c.stats.n_local_accepted == 1 and c.stats.n_escalated == 0


@pytest.mark.asyncio
async def test_local_abstain_escalates() -> None:
    doc = _raw_doc("some attack document text about payload override")
    fb = _prim("payload override text")
    c = _cascade(local_result=None, fallback_result=fb)
    out = await c.extract_any_from_raw_document(doc)
    assert out is fb
    assert c.fallback.calls == 1
    assert c.stats.n_escalated_abstain == 1


@pytest.mark.asyncio
async def test_ungrounded_local_escalates() -> None:
    doc = _raw_doc("a document with entirely different words about cats and dogs")
    ungrounded = _prim("zzzz qqqq wwww vvvv nonsense fabricated")  # no doc overlap
    fb = _prim("cats dogs document different")
    c = _cascade(local_result=ungrounded, fallback_result=fb)
    out = await c.extract_any_from_raw_document(doc)
    assert out is fb
    assert c.stats.n_escalated_ungrounded == 1


@pytest.mark.asyncio
async def test_local_error_escalates() -> None:
    doc = _raw_doc("attack document override payload text")
    fb = _prim("override payload text")
    c = _cascade(local_result=RuntimeError("endpoint down"), fallback_result=fb)
    out = await c.extract_any_from_raw_document(doc)
    assert out is fb
    assert c.stats.n_escalated_error == 1


@pytest.mark.asyncio
async def test_extract_from_raw_document_projects_technique_to_none() -> None:
    doc = _raw_doc("a technique document describing a method")
    tech = TechniqueSpec(
        technique_id="01HTECHNIQUE0000000000000",
        name="some method",
        modality="text",
        principle="because it works",
        source_url="https://example.com/doc",
    )
    c = _cascade(local_result=None, fallback_result=tech)
    # extract_any surfaces the technique; extract_from_raw_document projects to None.
    assert await c.extract_any_from_raw_document(doc) is tech
    c2 = _cascade(local_result=None, fallback_result=tech)
    assert await c2.extract_from_raw_document(doc) is None
