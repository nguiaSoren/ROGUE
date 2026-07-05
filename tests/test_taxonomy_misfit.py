"""Taxonomy-misfit flag — schema round-trip, tool-schema exposure, parse survival.

The extraction agent is enum-locked (Anthropic ``tool_choice`` on the frozen
``AttackFamily`` / ``AttackVector`` enums), so a genuinely novel technique gets
shoehorned into the nearest slot silently. The ``taxonomy_fit`` /
``taxonomy_fit_note`` fields surface those misfits for human review without ever
mutating the frozen taxonomy. These tests lock:

  (a) the two fields round-trip through model_dump → model_validate;
  (b) both appear in the ``extract_attack_primitive`` tool schema properties
      (they are derived from the Pydantic model, not hand-added);
  (c) a synthetic tool-call dict carrying ``taxonomy_fit`` survives the
      server-side validation path into the returned primitive (no LLM call), and
      a weak/novel fit emits the human-review warning.

No network / DB. Mirrors the mock-free surface of test_extraction.py.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from rogue.extract.extraction_agent import _EXTRACTION_TOOL_SCHEMA, ExtractionAgent
from rogue.schemas import AttackPrimitive

_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "01_multilingual_african_languages.json"
)


def _golden_primitive_dict() -> dict[str, Any]:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# (a) round-trip
# --------------------------------------------------------------------------- #


def test_taxonomy_fit_round_trips() -> None:
    """taxonomy_fit='novel' + a note survive model_dump → model_validate."""
    data = _golden_primitive_dict()
    data["taxonomy_fit"] = "novel"
    data["taxonomy_fit_note"] = "delivery channel (browser extension DOM) has no matching vector"

    primitive = AttackPrimitive.model_validate(data)
    assert primitive.taxonomy_fit == "novel"
    assert primitive.taxonomy_fit_note is not None

    reloaded = AttackPrimitive.model_validate(primitive.model_dump(mode="json"))
    assert reloaded.taxonomy_fit == "novel"
    assert reloaded.taxonomy_fit_note == primitive.taxonomy_fit_note


def test_taxonomy_fit_defaults_to_clear() -> None:
    """Absent from the payload → 'clear' (the additive no-op path)."""
    data = _golden_primitive_dict()
    data.pop("taxonomy_fit", None)
    data.pop("taxonomy_fit_note", None)

    primitive = AttackPrimitive.model_validate(data)
    assert primitive.taxonomy_fit == "clear"
    assert primitive.taxonomy_fit_note is None


# --------------------------------------------------------------------------- #
# (b) tool-schema exposure
# --------------------------------------------------------------------------- #


def test_taxonomy_fields_in_tool_schema() -> None:
    """Both fields are offered to the extraction LLM, with enum + descriptions."""
    props = _EXTRACTION_TOOL_SCHEMA["properties"]
    assert "taxonomy_fit" in props
    assert "taxonomy_fit_note" in props
    assert props["taxonomy_fit"]["enum"] == ["clear", "weak", "novel"]
    # Not required — older callers/fixtures must still validate.
    assert "taxonomy_fit" not in _EXTRACTION_TOOL_SCHEMA.get("required", [])


# --------------------------------------------------------------------------- #
# (c) parse-path survival + human-review warning
# --------------------------------------------------------------------------- #


def test_taxonomy_fit_survives_validation_path(caplog) -> None:
    """A synthetic tool-call dict with taxonomy_fit='weak' reaches the primitive
    and emits the taxonomy-misfit warning (no LLM / network)."""
    agent = ExtractionAgent(prompt_version="v4")
    data = _golden_primitive_dict()
    data["is_attack"] = True
    data["taxonomy_fit"] = "weak"
    data["taxonomy_fit_note"] = "mechanism half-matches obfuscation_encoding"

    with caplog.at_level(logging.WARNING, logger="rogue.extract.extraction_agent"):
        primitive = agent._validate_or_none(data)

    assert primitive is not None
    assert primitive.taxonomy_fit == "weak"
    assert primitive.taxonomy_fit_note == "mechanism half-matches obfuscation_encoding"
    assert any("taxonomy_fit=weak" in rec.message for rec in caplog.records)


def test_clear_fit_emits_no_warning(caplog) -> None:
    """The default 'clear' path stays silent (additive no-op)."""
    agent = ExtractionAgent(prompt_version="v4")
    data = _golden_primitive_dict()
    data["is_attack"] = True
    data.pop("taxonomy_fit", None)

    with caplog.at_level(logging.WARNING, logger="rogue.extract.extraction_agent"):
        primitive = agent._validate_or_none(data)

    assert primitive is not None
    assert primitive.taxonomy_fit == "clear"
    assert not any("taxonomy_fit" in rec.message for rec in caplog.records)
