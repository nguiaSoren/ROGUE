"""Harvest→generator loop: the extractor can emit a `generator` spec for procedural attacks, and an
unbuildable kind is dropped (kept as an emergent flag) rather than persisted."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from rogue.extract.extraction_agent import _EXTRACTION_TOOL_SCHEMA, ExtractionAgent

_FIXTURE = Path(__file__).parent / "fixtures" / "01_multilingual_african_languages.json"


def _golden() -> dict[str, Any]:
    d = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    d["is_attack"] = True
    return d


def test_generator_field_in_extraction_schema():
    assert "generator" in _EXTRACTION_TOOL_SCHEMA["properties"]
    assert "generator" not in _EXTRACTION_TOOL_SCHEMA.get("required", [])


def test_valid_generator_survives_validation():
    agent = ExtractionAgent(prompt_version="v4")
    data = _golden()
    data["generator"] = {
        "kind": "many_shot",
        "params": {"instruction_style": "secret_role"},
        "sweep_param": "target_tokens",
        "sweep_values": [2000, 8000, 32000],
    }
    prim = agent._validate_or_none(data)
    assert prim is not None
    assert prim.generator is not None
    assert prim.generator.kind == "many_shot"
    assert prim.generator.is_sweep()


def test_unbuildable_generator_kind_is_dropped(caplog):
    agent = ExtractionAgent(prompt_version="v4")
    data = _golden()
    data["generator"] = {"kind": "totally_made_up", "params": {}}
    data["emergent_label"] = "totally_made_up"
    with caplog.at_level(logging.WARNING, logger="rogue.extract.extraction_agent"):
        prim = agent._validate_or_none(data)
    assert prim is not None
    assert prim.generator is None  # dropped — not persisted
    assert prim.emergent_label == "totally_made_up"  # flag kept for a human
    assert any("unbuildable generator" in rec.message for rec in caplog.records)
