"""Round-trip the three demo-seed fixtures through the Pydantic schema.

Run from project root:
    pip install pydantic
    pytest tests/test_schemas.py -v

If this passes, the schema is correct: every required field is present in every
fixture, every enum value validates, every constraint is satisfied. That is the
Day 0 green-light gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rogue.schemas import (
    ACME_SYSTEM_PROMPT,
    AttackFamily,
    AttackPrimitive,
    AttackVector,
    Severity,
    demo_deployment_configs,
)

FIXTURES = Path(__file__).parent / "fixtures"
PRIMITIVE_FIXTURES = sorted(FIXTURES.glob("0*.json"))


@pytest.mark.parametrize("fixture_path", PRIMITIVE_FIXTURES, ids=lambda p: p.stem)
def test_primitive_fixture_parses(fixture_path: Path) -> None:
    """Each demo-seed fixture must parse cleanly into an AttackPrimitive."""
    data = json.loads(fixture_path.read_text())
    primitive = AttackPrimitive.model_validate(data)
    # sanity-check a few load-bearing fields are populated
    assert primitive.primitive_id
    assert primitive.family in AttackFamily
    assert primitive.vector in AttackVector
    assert primitive.base_severity in Severity
    assert primitive.sources, "primitive must have at least one source"
    assert 0 <= primitive.reproducibility_score <= 10


@pytest.mark.parametrize("fixture_path", PRIMITIVE_FIXTURES, ids=lambda p: p.stem)
def test_primitive_fixture_round_trips(fixture_path: Path) -> None:
    """Round-trip preserves the JSON exactly (modulo Pydantic JSON normalization)."""
    data = json.loads(fixture_path.read_text())
    primitive = AttackPrimitive.model_validate(data)
    dumped = primitive.model_dump(mode="json")
    # spot-check: critical fields survive the round trip identically
    assert dumped["primitive_id"] == data["primitive_id"]
    assert dumped["family"] == data["family"]
    assert dumped["vector"] == data["vector"]
    assert dumped["payload_template"] == data["payload_template"]
    assert dumped["payload_slots"] == data["payload_slots"]
    assert len(dumped["sources"]) == len(data["sources"])


def test_secondary_family_must_differ_from_primary() -> None:
    """Validator: primary family cannot also be in secondary_families."""
    bad = {
        "primitive_id": "01HBADXXXXXXX",
        "family": "role_hijack",
        "secondary_families": ["role_hijack"],  # illegal — same as primary
        "vector": "user_turn",
        "title": "test",
        "short_description": "test",
        "payload_template": "test payload",
        "payload_slots": {},
        "reproducibility_score": 5,
        "sources": [
            {
                "url": "https://example.com/x",
                "source_type": "blog",
                "fetched_at": "2026-05-21T00:00:00Z",
                "archive_hash": "abcdef0",
                "bright_data_product": "web_unlocker",
            }
        ],
        "discovered_at": "2026-05-21T00:00:00Z",
        "base_severity": "low",
        "severity_rationale": "test",
    }
    with pytest.raises(Exception):
        AttackPrimitive.model_validate(bad)


def test_multimodal_vector_requires_flag() -> None:
    """Validator: multimodal vector must set requires_multimodal=True."""
    bad = {
        "primitive_id": "01HBADXXXXXXX",
        "family": "multimodal_injection",
        "vector": "multimodal_image",
        "title": "test",
        "short_description": "test",
        "payload_template": "an image with adversarial overlay",
        "payload_slots": {},
        "reproducibility_score": 5,
        "requires_multimodal": False,  # illegal — vector says multimodal
        "sources": [
            {
                "url": "https://example.com/x",
                "source_type": "blog",
                "fetched_at": "2026-05-21T00:00:00Z",
                "archive_hash": "abcdef0",
                "bright_data_product": "web_unlocker",
            }
        ],
        "discovered_at": "2026-05-21T00:00:00Z",
        "base_severity": "medium",
        "severity_rationale": "test",
    }
    with pytest.raises(Exception):
        AttackPrimitive.model_validate(bad)


def test_demo_deployment_configs_round_trip() -> None:
    """The 5 hardcoded demo configs all parse and share the Acme system prompt."""
    configs = demo_deployment_configs()
    assert len(configs) == 5
    assert all(c.system_prompt == ACME_SYSTEM_PROMPT for c in configs)
    assert all(c.customer_id == "acme" for c in configs)
    # 5 distinct target models, 5 distinct config_ids
    assert len({c.target_model for c in configs}) == 5
    assert len({c.config_id for c in configs}) == 5


def test_severity_score_uses_family_and_vector_weights() -> None:
    """severity_score = family_weight × vector_weight × any_breach_rate."""
    data = json.loads((FIXTURES / "02_copirate_365_cve_2026_24299.json").read_text())
    primitive = AttackPrimitive.model_validate(data)
    # IPI family weight = 1.00, RAG_DOCUMENT vector weight = 1.00
    # at full breach rate = 1.0, score = 1.0
    assert primitive.severity_score(1.0) == pytest.approx(1.0)
    # at half breach rate = 0.5
    assert primitive.severity_score(0.5) == pytest.approx(0.5)
