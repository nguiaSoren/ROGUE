"""Real round-trip extraction tests on the 4 demo-seed source-document fixtures.

Per ROGUE_PLAN §5.6, the 4 files in ``tests/fixtures/`` (multilingual_paper.html,
multilingual_paper.pdf, copirate_365.html, etr_index.html) are the demo-seed
fallback corpus — if any live Bright Data fetch fails during the Day-4 demo
recording, the pipeline is meant to extract attacks from these local copies
instead. Until now that fallback path has been UNVERIFIED — only the
post-extraction JSON primitives were exercised by tests; the upstream HTML /
PDF was never fed through :class:`ExtractionAgent`.

These tests close that gap by simulating "BD just returned this HTML/PDF" —
read the fixture verbatim, pass through :meth:`ExtractionAgent.extract`,
assert the returned :class:`AttackPrimitive` matches the family / vector /
slot shape documented in the matching golden JSON fixture under
``tests/fixtures/0[123]_*.json``.

Gated on ``ANTHROPIC_API_KEY`` because each test issues one real Anthropic
extraction call (~$0.005). When the key is absent the tests skip cleanly so
CI without secrets still passes; locally the ``.env`` autoloads it via
``dotenv``. Run with::

    uv run pytest tests/test_extraction_fixtures.py -v
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from dotenv import load_dotenv

from rogue.extract.extraction_agent import ExtractionAgent
from rogue.schemas import AttackPrimitive


# Autoload .env so ANTHROPIC_API_KEY is visible to `os.environ.get(...)` at
# test-collection time. dotenv is a no-op if no .env exists (e.g. on CI).
load_dotenv()


FIXTURES_DIR = Path(__file__).parent / "fixtures"
SKIP_REASON = "real LLM call — needs ANTHROPIC_API_KEY"


def _skip_unless_anthropic_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip(SKIP_REASON)


def _read_pdf_as_text(path: Path) -> str:
    """Extract text from a PDF via pypdf (already a harvest-layer dep)."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_multilingual_paper_html_roundtrip() -> None:
    """multilingual_paper.html (arXiv 2605.18239v1, Marx & Dunaiski 2026-05-18).

    Expected per the matching golden ``01_multilingual_african_languages.json``:
      * family = ``language_switching`` (multi-turn jailbreak via translation
        into low-resource African languages)
      * vector ∈ {``user_multi_turn``, ``user_turn``}
      * payload_template uses the ``{language}`` slot
    """
    _skip_unless_anthropic_key()
    html = (FIXTURES_DIR / "multilingual_paper.html").read_text(encoding="utf-8")
    agent = ExtractionAgent()

    primitive = await agent.extract(
        raw_document=html,
        source_url="https://arxiv.org/abs/2605.18239",
        source_type="arxiv",
        fetched_at=datetime.now(timezone.utc),
        bright_data_product="web_unlocker",
    )

    assert primitive is not None, "extraction returned None — expected an attack disclosure"
    assert isinstance(primitive, AttackPrimitive)
    assert primitive.family == "language_switching", (
        f"expected family=language_switching, got {primitive.family!r}"
    )
    assert primitive.vector in ("user_multi_turn", "user_turn"), (
        f"unexpected vector {primitive.vector!r}"
    )
    assert primitive.payload_template
    assert "{language}" in primitive.payload_template, (
        "payload_template must reference the {language} slot — this is the "
        "defining slot for the language_switching family"
    )


@pytest.mark.asyncio
async def test_extract_multilingual_paper_pdf_roundtrip() -> None:
    """multilingual_paper.pdf — same expected attack as the HTML form.

    Proves ROGUE's PDF-extraction robustness for arXiv listings, vendor white
    papers, MITRE ATLAS technical reports. PDF→text via pypdf (harvest-layer
    dep already in pyproject).
    """
    _skip_unless_anthropic_key()
    text = _read_pdf_as_text(FIXTURES_DIR / "multilingual_paper.pdf")
    assert len(text) > 1000, (
        f"pypdf extracted only {len(text)} chars from multilingual_paper.pdf — "
        "fixture may be malformed or empty"
    )
    agent = ExtractionAgent()

    primitive = await agent.extract(
        raw_document=text,
        source_url="https://arxiv.org/pdf/2605.18239v1.pdf",
        source_type="arxiv",
        fetched_at=datetime.now(timezone.utc),
        bright_data_product="web_unlocker",
    )

    assert primitive is not None
    assert primitive.family == "language_switching"
    assert primitive.payload_template


@pytest.mark.asyncio
async def test_extract_copirate_365_html_roundtrip() -> None:
    """copirate_365.html (ETR blog, CVE-2026-24299, Wunderwuzzi 2026-05-04).

    Expected per ``02_copirate_365_cve_2026_24299.json``:
      * family = ``indirect_prompt_injection`` (instructions hidden in Word
        document; secondary = ``tool_use_hijack`` for email-tool invocation)
      * vector = ``rag_document``
      * payload_template references {exfil_destination} or similar exfil slot
    """
    _skip_unless_anthropic_key()
    html = (FIXTURES_DIR / "copirate_365.html").read_text(encoding="utf-8")
    agent = ExtractionAgent()

    primitive = await agent.extract(
        raw_document=html,
        source_url="https://embracethered.com/blog/posts/2026/copirate-365/",
        source_type="blog",
        fetched_at=datetime.now(timezone.utc),
        bright_data_product="web_unlocker",
    )

    assert primitive is not None
    assert primitive.family == "indirect_prompt_injection", (
        f"expected indirect_prompt_injection, got {primitive.family!r}"
    )
    assert primitive.vector in ("rag_document", "tool_output"), (
        f"unexpected vector {primitive.vector!r}"
    )
    # Secondary family is often tool_use_hijack on this attack — accept that or empty
    assert all(
        sf in ("tool_use_hijack", "system_prompt_leak", "training_data_extraction")
        for sf in primitive.secondary_families
    ), f"unexpected secondary_families {primitive.secondary_families!r}"
    assert primitive.payload_template


@pytest.mark.asyncio
async def test_extract_etr_index_html_roundtrip() -> None:
    """etr_index.html (ETR blog index — list of posts, not a single attack).

    An index page is a valid ``is_attack=false`` outcome per the §"What does
    NOT count" rules in the extraction prompt — but the LLM may also choose to
    extract the most prominent attack featured on the index. Either is
    acceptable; this test verifies the extraction COMPLETES cleanly (the
    Day-4 demo never crashes on an index page) and any extracted primitive is
    well-shaped.
    """
    _skip_unless_anthropic_key()
    html = (FIXTURES_DIR / "etr_index.html").read_text(encoding="utf-8")
    agent = ExtractionAgent()

    primitive = await agent.extract(
        raw_document=html,
        source_url="https://embracethered.com/blog/",
        source_type="blog",
        fetched_at=datetime.now(timezone.utc),
        bright_data_product="web_unlocker",
    )

    if primitive is None:
        # is_attack=false path — index page treated as commentary. Valid outcome.
        return

    # If the LLM did extract something, sanity-check the shape against the
    # families ETR is known for. No hard family assertion because an index
    # page is ambiguous by design.
    assert primitive.family in {
        "indirect_prompt_injection",
        "tool_use_hijack",
        "system_prompt_leak",
        "training_data_extraction",
        "multi_turn_gradient",
        "direct_instruction_override",
        "chain_of_thought_hijack",
    }, f"unexpected family from ETR index {primitive.family!r}"
    assert primitive.payload_template
