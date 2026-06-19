"""ExtractionAgent wire-shape tests — Anthropic tool-use + OpenAI parse paths.

Goal: lock the structured-output call shape against mocked provider SDKs so
the Day-1 §9.4 live-network swap is a one-line change (drop the mock,
the SDK calls already go through the right code path).

Strategy: monkeypatch the lazy-init client attributes on a fresh
:class:`ExtractionAgent` instance with `MagicMock` doubles, then assert on
the recorded call kwargs *and* on the returned ``AttackPrimitive``. Mirrors
the ``_FakeBrightDataClient`` pattern from ``tests/test_harvest.py`` but
scoped to the extraction surface.

Reference: ROGUE_PLAN.md §9.4 (Day-1 afternoon — Extraction goes live),
§A.21 (canonical agent shape), §A.8 (prompt spec).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from rogue.extract.extraction_agent import ExtractionAgent
from rogue.schemas import AttackPrimitive, RawDocument


# --------------------------------------------------------------------------- #
# Fixture helpers
# --------------------------------------------------------------------------- #

_FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "01_multilingual_african_languages.json"
)


def _golden_primitive_dict() -> dict[str, Any]:
    """Load the golden AttackPrimitive fixture as a dict (re-usable per test)."""
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


def _make_raw_document(content: str = "Document body about prompt injection.") -> RawDocument:
    """Build a minimal RawDocument for the adapter tests."""
    body = content
    return RawDocument(
        url="https://example.com/post",
        source_type="blog",
        bright_data_product="web_unlocker",
        fetched_at=datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc),
        raw_content=body,
        content_format="markdown",
        archive_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        http_status=200,
        metadata={"test": True},
        discovered_via=None,
    )


# --------------------------------------------------------------------------- #
# A. Anthropic tool-use wire shape
# --------------------------------------------------------------------------- #


def _build_anthropic_tool_use_response(payload: dict[str, Any]) -> MagicMock:
    """Shape-mock the ``messages.create`` response: one ``tool_use`` block.

    The agent iterates ``response.content`` looking for ``block.type ==
    "tool_use"`` and reads ``block.input`` — so we mirror exactly that shape
    on the returned MagicMock.
    """
    block = MagicMock()
    block.type = "tool_use"
    block.input = payload
    response = MagicMock()
    response.content = [block]
    return response


@pytest.mark.asyncio
async def test_anthropic_path_emits_correct_tool_use_payload() -> None:
    """The Anthropic call MUST set ``tool_choice = extract_attack_primitive``
    and supply ``input_schema = AttackPrimitive.model_json_schema()``."""
    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")

    # Mock client whose `messages.create` returns a tool_use block carrying
    # the golden primitive dict + the is_attack flag.
    payload = _golden_primitive_dict()
    payload["is_attack"] = True
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=_build_anthropic_tool_use_response(payload),
    )
    agent._anthropic_client = mock_client

    result = await agent.extract(
        raw_document="A jailbreak technique using African low-resource languages.",
        source_url="https://arxiv.org/abs/2605.18239",
        source_type="arxiv",
    )

    assert isinstance(result, AttackPrimitive)
    # primitive_id is server-side-assigned (fresh ULID), not LLM-supplied —
    # see test_extract_overwrites_llm_primitive_id_with_fresh_ulid for why.
    assert result.primitive_id != payload["primitive_id"]
    assert len(result.primitive_id) == 26

    # --- Verify the wire shape of the call ---
    assert mock_client.messages.create.await_count == 1
    _, kwargs = mock_client.messages.create.call_args
    assert kwargs["model"] == "claude-haiku-4-5", (
        "provider prefix must be stripped before sending to SDK"
    )
    # System prompt is sent as a prompt-cached block (cache_control: ephemeral)
    # so the ~20 KB rubric is charged at ~0.1x after the first call in a window.
    assert isinstance(kwargs["system"], list), "system must be a cache-control block list"
    assert kwargs["system"][0]["text"] == agent.prompt, (
        "system block must carry the loaded extraction prompt"
    )
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}, (
        "extraction system prompt must be prompt-cached"
    )
    tools = kwargs["tools"]
    assert len(tools) == 1
    assert tools[0]["name"] == "extract_attack_primitive"
    # This agent is the default v3 (technique classifier disabled), so the
    # input_schema must be the bare, live AttackPrimitive json schema — NOT the
    # §10.9-widened one (which only ships on prompt v4+). Guarantees taxonomy
    # updates flow through AND that legacy extraction is byte-for-byte unchanged.
    assert tools[0]["input_schema"] == AttackPrimitive.model_json_schema()
    assert kwargs["tool_choice"] == {
        "type": "tool",
        "name": "extract_attack_primitive",
    }


@pytest.mark.asyncio
async def test_anthropic_path_handles_is_attack_false_skip() -> None:
    """``is_attack: false`` from the LLM → :meth:`extract` returns ``None``,
    no Pydantic error raised."""
    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=_build_anthropic_tool_use_response(
            {"is_attack": False, "reason": "commentary only, no payload"}
        ),
    )
    agent._anthropic_client = mock_client

    result = await agent.extract(
        raw_document="Yet another jailbreak appeared today — see X user @foo.",
        source_url="https://news.example.com/post",
        source_type="blog",
    )

    assert result is None


@pytest.mark.asyncio
async def test_anthropic_path_logs_when_no_tool_use_block_returned(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A response with no ``tool_use`` block must (a) NOT crash, (b) log a
    warning, and (c) return ``None`` via the soft-skip branch."""
    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")
    empty_response = MagicMock()
    empty_response.content = []
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=empty_response)
    agent._anthropic_client = mock_client

    with caplog.at_level(logging.WARNING, logger="rogue.extract.extraction_agent"):
        result = await agent.extract(
            raw_document="…",
            source_url="https://example.com/x",
            source_type="blog",
        )

    assert result is None
    assert any(
        "no tool_use block" in rec.getMessage() for rec in caplog.records
    ), f"expected 'no tool_use block' warning, got: {caplog.records}"


# --------------------------------------------------------------------------- #
# B. OpenAI `.parse()` wire shape
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_openai_path_uses_parse_with_attack_primitive_response_format() -> None:
    """OpenAI path must call ``.beta.chat.completions.parse`` with
    ``response_format=AttackPrimitive``."""
    agent = ExtractionAgent(model="openai/gpt-5.4-mini")

    parsed_primitive = AttackPrimitive.model_validate(_golden_primitive_dict())
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.parsed = parsed_primitive

    mock_client = MagicMock()
    mock_client.beta.chat.completions.parse = AsyncMock(return_value=completion)
    agent._openai_client = mock_client

    result = await agent.extract(
        raw_document="A jailbreak technique using African low-resource languages.",
        source_url="https://arxiv.org/abs/2605.18239",
        source_type="arxiv",
    )

    assert isinstance(result, AttackPrimitive)
    # primitive_id is server-side-overwritten with a fresh ULID even on the
    # OpenAI path — see test_extract_overwrites_llm_primitive_id_with_fresh_ulid.
    assert result.primitive_id != parsed_primitive.primitive_id
    assert len(result.primitive_id) == 26

    # --- Wire-shape assertions ---
    assert mock_client.beta.chat.completions.parse.await_count == 1
    _, kwargs = mock_client.beta.chat.completions.parse.call_args
    assert kwargs["model"] == "gpt-5.4-mini"
    assert kwargs["response_format"] is AttackPrimitive
    messages = kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == agent.prompt
    assert messages[1]["role"] == "user"


@pytest.mark.asyncio
async def test_openai_path_returns_none_when_parsed_is_none() -> None:
    """SDK returns ``parsed=None`` on refusal / schema mismatch → ``None``."""
    agent = ExtractionAgent(model="openai/gpt-5.4-mini")
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.parsed = None
    mock_client = MagicMock()
    mock_client.beta.chat.completions.parse = AsyncMock(return_value=completion)
    agent._openai_client = mock_client

    result = await agent.extract(
        raw_document="…",
        source_url="https://example.com/x",
        source_type="blog",
    )

    assert result is None


# --------------------------------------------------------------------------- #
# C. RawDocument adapter (pipeline-facing entry point)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_extract_from_raw_document_routes_fields_correctly() -> None:
    """The adapter must project ``RawDocument`` → :meth:`extract` kwargs
    1:1 (url, source_type, fetched_at, raw_content)."""
    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")
    payload = _golden_primitive_dict()
    payload["is_attack"] = True
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=_build_anthropic_tool_use_response(payload),
    )
    agent._anthropic_client = mock_client

    raw_doc = _make_raw_document(content="A jailbreak in low-resource languages.")
    result = await agent.extract_from_raw_document(raw_doc)

    assert isinstance(result, AttackPrimitive)
    # Verify the user-message rendering pulled fields off the RawDocument.
    _, kwargs = mock_client.messages.create.call_args
    user_msg = kwargs["messages"][0]["content"]
    assert str(raw_doc.url) in user_msg
    assert str(raw_doc.source_type) in user_msg
    assert raw_doc.raw_content in user_msg


@pytest.mark.asyncio
async def test_extract_from_raw_document_logs_and_reraises_on_validation_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ValidationError from the underlying ``extract()`` must be logged with
    the source URL + archive_hash attached, then re-raised so the dedup
    layer can drop the bad row with full provenance."""
    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")
    # is_attack=true with a payload that has payload_template (so the
    # demote-to-skip branch doesn't fire) but has an INVALID enum value
    # for `family` — triggers ValidationError post-normalization. We
    # intentionally bypass every auto-fix the extract() pipeline does.
    bad_payload = _golden_primitive_dict()
    bad_payload["is_attack"] = True
    bad_payload["family"] = "not_a_real_attack_family_enum_value"
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=_build_anthropic_tool_use_response(bad_payload),
    )
    agent._anthropic_client = mock_client

    raw_doc = _make_raw_document()
    with caplog.at_level(logging.ERROR, logger="rogue.extract.extraction_agent"):
        with pytest.raises(ValidationError):
            await agent.extract_from_raw_document(raw_doc)

    log_blob = " ".join(rec.getMessage() for rec in caplog.records)
    assert str(raw_doc.url) in log_blob
    assert raw_doc.archive_hash in log_blob


# --------------------------------------------------------------------------- #
# D. Provider routing
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_extract_synths_sources_when_llm_omits_them() -> None:
    """When the extraction LLM returns a primitive WITHOUT a ``sources`` field,
    ``extract()`` must synth one from the harvest-side fields so validation
    passes — the LLM routinely omits sources on simple docs and we'd lose
    every such primitive otherwise. Source URL, archive_hash, fetched_at,
    bright_data_product must all be present + correct on the synth entry.

    Regression guard for the 2026-05-26 evening crash where every
    extraction-LLM call that omitted ``sources`` killed the surrounding
    harvest_once.py per-doc loop with Pydantic ValidationError.
    """
    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")

    # Build a payload that's missing `sources` entirely — this is the
    # failure mode harvest_once.py saw on Simon Willison's snowflake post.
    payload_no_sources = {
        k: v for k, v in _golden_primitive_dict().items() if k != "sources"
    }
    payload_no_sources["is_attack"] = True
    assert "sources" not in payload_no_sources

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=_build_anthropic_tool_use_response(payload_no_sources),
    )
    agent._anthropic_client = mock_client

    raw_text = "A jailbreak via low-resource African languages"
    fetched_at = datetime(2026, 5, 26, 6, 41, tzinfo=timezone.utc)
    result = await agent.extract(
        raw_document=raw_text,
        source_url="https://simonwillison.net/2026/Mar/18/snowflake-cortex-ai/",
        source_type="blog",
        fetched_at=fetched_at,
        bright_data_product="web_unlocker",
    )

    # Validation passed — the synth-sources fallback kicked in.
    assert isinstance(result, AttackPrimitive)
    assert len(result.sources) == 1
    synth = result.sources[0]
    assert str(synth.url) == "https://simonwillison.net/2026/Mar/18/snowflake-cortex-ai/"
    assert synth.source_type == "blog"
    assert synth.bright_data_product == "web_unlocker"
    assert synth.fetched_at == fetched_at
    # archive_hash must be SHA-256 of the raw text, not a placeholder.
    assert synth.archive_hash == hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


@pytest.mark.asyncio
async def test_extract_preserves_llm_sources_when_present() -> None:
    """When the LLM DOES emit `sources`, the synth fallback must NOT fire —
    the LLM's source list (which may include multiple disclosures) is the
    authoritative one."""
    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")

    payload = _golden_primitive_dict()
    payload["is_attack"] = True
    # Sanity: the golden fixture already has 1+ source entries.
    assert payload["sources"]
    original_source_count = len(payload["sources"])

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=_build_anthropic_tool_use_response(payload),
    )
    agent._anthropic_client = mock_client

    result = await agent.extract(
        raw_document="x",
        source_url="https://different-url.example.com/",
        source_type="blog",
    )

    assert isinstance(result, AttackPrimitive)
    # Synth did NOT prepend a fake source; LLM-emitted list preserved.
    assert len(result.sources) == original_source_count


@pytest.mark.asyncio
async def test_extract_from_raw_document_passes_bright_data_product_through() -> None:
    """The RawDocument adapter must thread `bright_data_product` to extract()
    so a synth source records the correct label (web_scraper_api, scraping_browser,
    etc. — not the default `web_unlocker`)."""
    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")

    payload_no_sources = {
        k: v for k, v in _golden_primitive_dict().items() if k != "sources"
    }
    payload_no_sources["is_attack"] = True

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=_build_anthropic_tool_use_response(payload_no_sources),
    )
    agent._anthropic_client = mock_client

    # Build a RawDocument with bright_data_product='web_scraper_api' (Reddit/X path).
    raw_doc = _make_raw_document(content="reddit-fetched-content")
    # Override to a non-default product so we can verify the threading.
    raw_doc_dict = raw_doc.model_dump()
    raw_doc_dict["bright_data_product"] = "web_scraper_api"
    raw_doc = RawDocument.model_validate(raw_doc_dict)

    result = await agent.extract_from_raw_document(raw_doc)

    assert isinstance(result, AttackPrimitive)
    assert result.sources[0].bright_data_product == "web_scraper_api"


@pytest.mark.asyncio
async def test_extract_overwrites_llm_primitive_id_with_fresh_ulid() -> None:
    """The LLM routinely copies the prompt's example primitive_id across every
    call, causing PK collisions on every save. ``extract()`` must overwrite
    whatever the LLM emits with a fresh ULID so each primitive gets a unique
    ID. Regression guard for the 2026-05-26 evening crash where every doc
    saved with primitive_id=01ARZ3NDEKTSV4RRFFQ69G5FAV and Postgres rejected
    every save after the first."""
    import ulid

    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")

    # Two payloads both copying the SAME bogus ID (mimics LLM behavior).
    bogus_id = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    payload_1 = _golden_primitive_dict()
    payload_1["primitive_id"] = bogus_id
    payload_1["is_attack"] = True
    payload_2 = _golden_primitive_dict()
    payload_2["primitive_id"] = bogus_id  # same — would PK-collide
    payload_2["is_attack"] = True

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        side_effect=[
            _build_anthropic_tool_use_response(payload_1),
            _build_anthropic_tool_use_response(payload_2),
        ],
    )
    agent._anthropic_client = mock_client

    result_1 = await agent.extract("doc1", "https://x.com/1", "blog")
    result_2 = await agent.extract("doc2", "https://x.com/2", "blog")

    assert isinstance(result_1, AttackPrimitive)
    assert isinstance(result_2, AttackPrimitive)
    # Both LLM-supplied IDs were OVERWRITTEN with fresh ULIDs.
    assert result_1.primitive_id != bogus_id
    assert result_2.primitive_id != bogus_id
    # The two primitives have DIFFERENT IDs (no PK-collision possible).
    assert result_1.primitive_id != result_2.primitive_id
    # Both are valid 26-char ULID strings.
    for r in (result_1, result_2):
        assert len(r.primitive_id) == 26
        ulid.from_str(r.primitive_id)  # raises ValueError if not a valid ULID


@pytest.mark.asyncio
async def test_extract_synths_discovered_at_when_llm_omits() -> None:
    """When the LLM omits ``discovered_at``, ``extract()`` must default it
    to ``fetched_at`` so validation passes. Same per-doc-loss-prevention
    pattern as the sources synth."""
    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")

    payload = {
        k: v for k, v in _golden_primitive_dict().items() if k != "discovered_at"
    }
    payload["is_attack"] = True
    assert "discovered_at" not in payload

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=_build_anthropic_tool_use_response(payload),
    )
    agent._anthropic_client = mock_client

    fetched_at = datetime(2026, 5, 26, 7, 0, tzinfo=timezone.utc)
    result = await agent.extract(
        raw_document="x",
        source_url="https://example.com/",
        source_type="blog",
        fetched_at=fetched_at,
    )

    assert isinstance(result, AttackPrimitive)
    assert result.discovered_at == fetched_at


@pytest.mark.asyncio
async def test_extract_strips_json_object_wrapping_from_claimed_first_seen() -> None:
    """Haiku occasionally emits ``claimed_first_seen`` as a JSON-object-literal
    string like ``'{"2026-01-12T00:00:00Z"}'`` — Pydantic's date parser
    rejects the leading `{`. We must strip the wrapper before validation."""
    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")

    payload = _golden_primitive_dict()
    payload["is_attack"] = True
    payload["claimed_first_seen"] = '{"2026-01-12T00:00:00Z"}'  # the bug shape

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=_build_anthropic_tool_use_response(payload),
    )
    agent._anthropic_client = mock_client

    result = await agent.extract("x", "https://example.com/", "blog")
    assert isinstance(result, AttackPrimitive)
    # Date was unwrapped and parsed correctly.
    assert result.claimed_first_seen is not None
    assert result.claimed_first_seen.year == 2026
    assert result.claimed_first_seen.month == 1
    assert result.claimed_first_seen.day == 12


@pytest.mark.asyncio
async def test_extract_drops_unparseable_claimed_first_seen() -> None:
    """If the unwrapped value still isn't a date, we set the (Optional)
    field to None rather than crashing — better to lose one optional field
    than to lose the whole primitive."""
    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")

    payload = _golden_primitive_dict()
    payload["is_attack"] = True
    payload["claimed_first_seen"] = "not even close to a date"

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=_build_anthropic_tool_use_response(payload),
    )
    agent._anthropic_client = mock_client

    result = await agent.extract("x", "https://example.com/", "blog")
    assert isinstance(result, AttackPrimitive)
    assert result.claimed_first_seen is None


@pytest.mark.asyncio
async def test_short_doc_passes_through_extraction_without_truncation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Below the 40K-char threshold, raw_document is sent to the LLM
    unchanged. Verifies the truncation path is OFF for the median doc."""
    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")
    payload = _golden_primitive_dict()
    payload["is_attack"] = True
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=_build_anthropic_tool_use_response(payload),
    )
    agent._anthropic_client = mock_client

    short_doc = "a normal-sized blog post body. " * 200  # ~6000 chars
    assert len(short_doc) < 40_000

    with caplog.at_level(logging.WARNING, logger="rogue.extract.extraction_agent"):
        result = await agent.extract(short_doc, "https://example.com/post", "blog")

    assert isinstance(result, AttackPrimitive)
    # No truncation log line.
    assert not any("truncated content" in r.getMessage() for r in caplog.records)
    # The full short_doc was passed through to the LLM message body.
    _, kwargs = mock_client.messages.create.call_args
    user_msg = kwargs["messages"][0]["content"]
    assert short_doc in user_msg


@pytest.mark.asyncio
async def test_long_doc_truncated_with_head_tail_and_marker(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Above 40K chars (non-Pliny), the LLM input is the head + a clear
    truncation marker + the tail. Original content is preserved for hashing."""
    import hashlib

    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")
    payload = _golden_primitive_dict()
    payload["is_attack"] = True
    # Strip sources so the synth-sources block fires (hashing the ORIGINAL doc).
    payload.pop("sources", None)

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=_build_anthropic_tool_use_response(payload),
    )
    agent._anthropic_client = mock_client

    # 60K chars of distinct head/middle/tail markers so we can verify which
    # parts survived truncation.
    head_section = "HEAD_MARKER " * 1000          # 12K chars
    middle_section = "MIDDLE_MARKER " * 3000      # ~42K chars (should be dropped)
    tail_section = "TAIL_MARKER " * 500           # 6K chars
    long_doc = head_section + middle_section + tail_section
    assert len(long_doc) > 40_000

    with caplog.at_level(logging.WARNING, logger="rogue.extract.extraction_agent"):
        result = await agent.extract(long_doc, "https://example.com/long", "blog")

    assert isinstance(result, AttackPrimitive)

    # --- Truncation log line emitted with sane numbers ---
    truncate_logs = [r for r in caplog.records if "truncated content" in r.getMessage()]
    assert len(truncate_logs) == 1
    msg = truncate_logs[0].getMessage()
    assert "https://example.com/long" in msg
    assert "orig_chars=60000" in msg

    # --- LLM saw head + tail markers, NOT the middle ---
    _, kwargs = mock_client.messages.create.call_args
    user_msg = kwargs["messages"][0]["content"]
    assert "HEAD_MARKER" in user_msg
    assert "TAIL_MARKER" in user_msg
    assert "MIDDLE_MARKER" not in user_msg
    assert "[...content truncated for TPM" in user_msg

    # --- archive_hash on the synth source matches the ORIGINAL doc, not the truncated one ---
    assert len(result.sources) == 1
    expected_hash = hashlib.sha256(long_doc.encode("utf-8")).hexdigest()
    assert result.sources[0].archive_hash == expected_hash


@pytest.mark.asyncio
async def test_pliny_url_exempt_from_truncation_even_when_huge(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """L1B3RT4S / CL4R1T4S URLs are exempt — their content IS the attack
    corpus, so truncation would discard primitives. Verifies the URL-prefix
    bypass."""
    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")
    payload = _golden_primitive_dict()
    payload["is_attack"] = True
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=_build_anthropic_tool_use_response(payload),
    )
    agent._anthropic_client = mock_client

    huge_pliny_doc = "PLINY_PAYLOAD " * 5000  # 70K chars, well above threshold
    pliny_url = (
        "https://raw.githubusercontent.com/elder-plinius/L1B3RT4S/main/ANTHROPIC.mkd"
    )

    with caplog.at_level(logging.WARNING, logger="rogue.extract.extraction_agent"):
        result = await agent.extract(huge_pliny_doc, pliny_url, "github")

    assert isinstance(result, AttackPrimitive)
    # NO truncation logged — Pliny was exempted.
    assert not any("truncated content" in r.getMessage() for r in caplog.records)
    # The full huge_pliny_doc made it into the LLM message.
    _, kwargs = mock_client.messages.create.call_args
    user_msg = kwargs["messages"][0]["content"]
    assert huge_pliny_doc in user_msg


def test_maybe_truncate_helper_behavior() -> None:
    """Direct unit test of the truncation helper. Three cases: short
    pass-through, long head+tail+marker, Pliny exempt."""
    from rogue.extract.extraction_agent import _maybe_truncate_for_extraction

    # Short doc → unchanged.
    short = "x" * 10_000
    out, truncated = _maybe_truncate_for_extraction(short, "https://example.com/")
    assert out == short
    assert truncated is False

    # Long non-Pliny doc → truncated with marker.
    long = "H" * 20_000 + "M" * 50_000 + "T" * 20_000  # 90K chars
    out, truncated = _maybe_truncate_for_extraction(long, "https://example.com/")
    assert truncated is True
    assert "[...content truncated for TPM" in out
    # Default head_chars=12_000, tail_chars=4_000.
    assert out.startswith("H" * 12_000)
    assert out.endswith("T" * 4_000)
    # Middle is gone.
    assert "M" * 100 not in out

    # Long Pliny doc → exempt.
    out, truncated = _maybe_truncate_for_extraction(
        long, "https://raw.githubusercontent.com/elder-plinius/L1B3RT4S/main/X.mkd",
    )
    assert truncated is False
    assert out == long

    # Disable via None threshold.
    out, truncated = _maybe_truncate_for_extraction(
        long, "https://example.com/", threshold_chars=None,
    )
    assert truncated is False
    assert out == long


@pytest.mark.asyncio
async def test_extract_demotes_to_skip_when_payload_template_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The LLM occasionally returns ``is_attack: true`` but omits the actual
    attack content (just classification + description). Without
    ``payload_template`` the primitive is unreproducible; ``extract()`` must
    skip cleanly (return None) rather than crash on validation.

    Regression guard for the 2026-05-26 incident where
    ``embracethered.com/scary-agent-skills/`` consistently extracted with
    ``payload_template`` missing and crashed the per-doc loop.
    """
    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")
    payload = _golden_primitive_dict()
    payload["is_attack"] = True
    # Remove payload_template — mimics the failure mode.
    payload.pop("payload_template", None)

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=_build_anthropic_tool_use_response(payload),
    )
    agent._anthropic_client = mock_client

    with caplog.at_level(logging.WARNING, logger="rogue.extract.extraction_agent"):
        result = await agent.extract(
            raw_document="…",
            source_url="https://embracethered.com/blog/posts/2026/scary-agent-skills/",
            source_type="blog",
        )

    # Clean skip — no AttackPrimitive, no exception.
    assert result is None
    # Warning logged so operator can audit which docs got demoted.
    assert any(
        "missing payload_template" in r.getMessage() for r in caplog.records
    )


@pytest.mark.asyncio
async def test_extract_demotes_to_skip_when_payload_template_empty_string() -> None:
    """Same skip path for empty / whitespace-only payload_template."""
    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")
    payload = _golden_primitive_dict()
    payload["is_attack"] = True
    payload["payload_template"] = "   "  # whitespace only — useless

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=_build_anthropic_tool_use_response(payload),
    )
    agent._anthropic_client = mock_client

    result = await agent.extract(
        raw_document="…",
        source_url="https://example.com/",
        source_type="blog",
    )
    assert result is None


@pytest.mark.asyncio
async def test_extract_parses_list_fields_that_came_back_as_json_strings() -> None:
    """Haiku occasionally serializes list-typed fields as JSON-encoded
    strings (e.g. ``multi_turn_sequence='["turn1", "turn2"]'``) instead of
    actual Python lists. ``extract()`` must `json.loads` them before
    validation. Regression guard for the 2026-05-26 evening incident on
    Pliny's L1B3RT4S/ANTHROPIC.mkd."""
    agent = ExtractionAgent(model="anthropic/claude-haiku-4-5")
    payload = _golden_primitive_dict()
    payload["is_attack"] = True
    # Wire up ALL four list-typed fields as JSON-encoded strings — the
    # failure mode caught in production was multi_turn_sequence, but the
    # normalization should handle every list field defensively.
    payload["multi_turn_sequence"] = '["turn one text", "turn two text"]'
    payload["secondary_families"] = '["role_hijack", "refusal_suppression"]'
    payload["target_models_claimed"] = '["anthropic/claude-opus-4-7"]'
    payload["requires_tools"] = '["bash", "web_fetch"]'

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=_build_anthropic_tool_use_response(payload),
    )
    agent._anthropic_client = mock_client

    result = await agent.extract("doc", "https://example.com/", "blog")

    assert isinstance(result, AttackPrimitive)
    # All four fields parsed into actual lists.
    assert result.multi_turn_sequence == ["turn one text", "turn two text"]
    assert len(result.secondary_families) == 2
    assert result.target_models_claimed == ["anthropic/claude-opus-4-7"]
    assert result.requires_tools == ["bash", "web_fetch"]


# --------------------------------------------------------------------------- #
# Z. Direct unit tests of _normalize_extraction_payload — these run against
#    the function directly (no LLM mock) so we can exercise each rule in
#    isolation + catch regressions when new rules are added.
# --------------------------------------------------------------------------- #


def _norm_call(data: dict, **overrides) -> Any:
    """Thin wrapper: invoke _normalize_extraction_payload with sensible defaults."""
    from rogue.extract.extraction_agent import _normalize_extraction_payload

    defaults = {
        "raw_document": "the harvested document body",
        "source_url": "https://example.com/post",
        "source_type": "blog",
        "fetched_at": datetime(2026, 5, 26, 9, 0, tzinfo=timezone.utc),
        "bright_data_product": "web_unlocker",
    }
    defaults.update(overrides)
    return _normalize_extraction_payload(data, **defaults)


def test_normalizer_skips_when_is_attack_false() -> None:
    """is_attack=false bypasses every rule — pass-through unchanged."""
    out = _norm_call({"is_attack": False, "reason": "commentary"})
    assert out == {"is_attack": False, "reason": "commentary"}


def test_normalizer_skips_when_input_not_dict() -> None:
    """Non-dict input (None, list, etc.) is returned untouched."""
    assert _norm_call(None) is None  # type: ignore[arg-type]


def test_normalizer_R7_clamps_reproducibility_score_above_range(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """reproducibility_score=15 should clamp to 10 with a WARNING."""
    payload = _golden_primitive_dict()
    payload["is_attack"] = True
    payload["reproducibility_score"] = 15
    with caplog.at_level(logging.WARNING, logger="rogue.extract.extraction_agent"):
        out = _norm_call(payload)
    assert out["reproducibility_score"] == 10
    assert any("out of range" in r.getMessage() for r in caplog.records)


def test_normalizer_R7_clamps_reproducibility_score_below_range() -> None:
    """reproducibility_score=0 (or negative) clamps to 1."""
    payload = _golden_primitive_dict()
    payload["is_attack"] = True
    payload["reproducibility_score"] = 0
    out = _norm_call(payload)
    assert out["reproducibility_score"] == 1


def test_normalizer_R4_strips_json_wrap_from_discovered_at() -> None:
    """The same JSON-object-literal noise we patched for claimed_first_seen
    can hit discovered_at too — rule R4 applies to all datetime fields."""
    payload = _golden_primitive_dict()
    payload["is_attack"] = True
    payload["discovered_at"] = '{"2026-05-01T00:00:00Z"}'
    out = _norm_call(payload)
    assert out["discovered_at"] == "2026-05-01T00:00:00Z"


def test_normalizer_R4_defaults_unparseable_discovered_at_to_fetched_at() -> None:
    """Required datetime field with unparseable value falls back to fetched_at
    (not None, because the field is required)."""
    payload = _golden_primitive_dict()
    payload["is_attack"] = True
    payload["discovered_at"] = "totally not a date"
    fetched_at = datetime(2026, 5, 26, 9, 0, tzinfo=timezone.utc)
    out = _norm_call(payload, fetched_at=fetched_at)
    assert out["discovered_at"] == fetched_at.isoformat()


def test_normalizer_R6_wraps_scalar_in_list_for_string_list_fields() -> None:
    """When a list-typed field gets a non-JSON scalar, wrap it in a single-
    element list rather than crashing — e.g. requires_tools='bash' → ['bash']."""
    payload = _golden_primitive_dict()
    payload["is_attack"] = True
    payload["requires_tools"] = "bash"
    payload["target_models_claimed"] = "anthropic/claude-opus-4-7"
    out = _norm_call(payload)
    assert out["requires_tools"] == ["bash"]
    assert out["target_models_claimed"] == ["anthropic/claude-opus-4-7"]


def test_normalizer_R6_handles_secondary_families_loudly_on_non_json_string() -> None:
    """secondary_families is an enum list — a non-JSON string can't be auto-
    wrapped (the wrap would still fail enum validation). Null it out so
    Pydantic raises the actual enum error loudly."""
    payload = _golden_primitive_dict()
    payload["is_attack"] = True
    payload["secondary_families"] = "not_an_enum_value"
    out = _norm_call(payload)
    assert out["secondary_families"] is None


def test_normalizer_R6_empty_string_in_list_field_becomes_empty_list() -> None:
    payload = _golden_primitive_dict()
    payload["is_attack"] = True
    payload["requires_tools"] = ""
    out = _norm_call(payload)
    assert out["requires_tools"] == []


def test_normalizer_R8_overwrites_bright_data_product_with_harvest_truth() -> None:
    """The LLM hallucinates bright_data_product values in source entries
    (caught post-§9.5-PROOF-OF-LIFE — 27 'blog | web_scraper_api' rows
    that should have been 'blog | web_unlocker'). R8 always overwrites
    with the harvest-side truth, same trust-the-server pattern as R1."""
    payload = _golden_primitive_dict()
    payload["is_attack"] = True
    # Tamper with the LLM-emitted source: claim it came from web_scraper_api
    # when the actual harvest path was web_unlocker. R8 must overwrite.
    payload["sources"] = [
        {
            "url": "https://example.com/post",
            "source_type": "blog",
            "author": None,
            "published_at": None,
            "fetched_at": "2026-05-26T09:00:00+00:00",
            "archive_hash": "deadbeefcafe1234567890",
            "bright_data_product": "web_scraper_api",  # ← LLM hallucination
        },
    ]
    out = _norm_call(payload, bright_data_product="web_unlocker")
    assert out["sources"][0]["bright_data_product"] == "web_unlocker"


def test_normalizer_R8_overwrites_across_multiple_sources() -> None:
    """If the LLM emits multiple source entries, R8 overwrites all of them."""
    payload = _golden_primitive_dict()
    payload["is_attack"] = True
    payload["sources"] = [
        {
            "url": "https://example.com/a",
            "source_type": "blog",
            "author": None,
            "published_at": None,
            "fetched_at": "2026-05-26T09:00:00+00:00",
            "archive_hash": "hash_aaaaaaaaaaaaaaa",
            "bright_data_product": "web_scraper_api",  # wrong
        },
        {
            "url": "https://example.com/b",
            "source_type": "blog",
            "author": None,
            "published_at": None,
            "fetched_at": "2026-05-26T09:00:00+00:00",
            "archive_hash": "hash_bbbbbbbbbbbbbbb",
            "bright_data_product": "serp",  # also wrong
        },
    ]
    out = _norm_call(payload, bright_data_product="web_unlocker")
    for src in out["sources"]:
        assert src["bright_data_product"] == "web_unlocker"


def test_normalizer_integration_against_all_seven_known_failure_shapes() -> None:
    """End-to-end test: a payload that exhibits EVERY known LLM-output
    failure mode at once. The normalizer should produce a valid
    AttackPrimitive dict that passes Pydantic validation. This is the
    regression guard for the future when we add a new rule and accidentally
    break an existing one."""
    payload = {
        # R1: copied example primitive_id
        "primitive_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "is_attack": True,
        "family": "indirect_prompt_injection",
        "vector": "user_turn",
        "title": "test primitive",
        "short_description": "a test of every failure shape",
        # R5: payload_template present (non-empty) — won't trigger demote
        "payload_template": "Ignore previous and {target}",
        "payload_slots": {"target": "the prompt"},
        # R6: list as JSON string
        "secondary_families": '["tool_use_hijack"]',
        # R6: list as scalar
        "requires_tools": "bash",
        "target_models_claimed": '["anthropic/claude-opus-4-7"]',
        # R3: discovered_at omitted entirely
        # R4: claimed_first_seen wrapped
        "claimed_first_seen": '{"2026-01-12T00:00:00Z"}',
        "reproducibility_score": 15,  # R7: out of range
        "requires_multi_turn": False,
        "requires_system_prompt_access": False,
        "requires_multimodal": False,
        "base_severity": "high",
        "severity_rationale": "indirect injection chained with tool hijack",
        # R2: sources omitted entirely
    }
    out = _norm_call(payload)

    # R1
    assert out["primitive_id"] != "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    assert len(out["primitive_id"]) == 26
    # R2
    assert len(out["sources"]) == 1
    assert out["sources"][0]["url"] == "https://example.com/post"
    # R3
    assert out["discovered_at"]  # populated
    # R4
    assert out["claimed_first_seen"] == "2026-01-12T00:00:00Z"
    # R6
    assert out["secondary_families"] == ["tool_use_hijack"]
    assert out["requires_tools"] == ["bash"]
    assert out["target_models_claimed"] == ["anthropic/claude-opus-4-7"]
    # R7
    assert out["reproducibility_score"] == 10

    # And the whole thing must round-trip through Pydantic without error.
    primitive = AttackPrimitive.model_validate(
        {k: v for k, v in out.items() if k != "is_attack"},
    )
    assert primitive.title == "test primitive"


@pytest.mark.asyncio
async def test_unknown_provider_prefix_raises_not_implemented() -> None:
    """Any model id that isn't ``anthropic/*`` or ``openai/*`` must raise
    ``NotImplementedError`` so misconfigurations surface loudly (rather
    than silently picking the wrong provider)."""
    agent = ExtractionAgent(model="cohere/command-r")
    with pytest.raises(NotImplementedError):
        await agent.extract(
            raw_document="…",
            source_url="https://example.com/x",
            source_type="blog",
        )
