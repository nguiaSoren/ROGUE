"""Tests for the §10.7 LLM cost log + its wiring into the two augmentation
modules (persona_wrap, escalation_planner).

Three groups:

  A. Pure-Python — price table, cost math, header behaviour, atomic append,
     unknown-model graceful degradation.

  B. log_anthropic_response — extracts `usage` from a stub response object
     (the same shape AsyncAnthropic returns) and writes the row, including
     when usage is missing/empty.

  C. End-to-end via the stubbed wrappers — calling
     PersonaWrapper._call_anthropic / EscalationPlanner._call_anthropic with
     a stub Anthropic client produces a CSV row with the correct module,
     subject_id, and refused flag.

Spec: src/rogue/reproduce/llm_cost_log.py docstring + ROGUE_PLAN.md §10.7.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from rogue.reproduce.escalation_planner import EscalationPlanner
from rogue.reproduce.llm_cost_log import (
    ANTHROPIC_PRICE_PER_MILLION,
    CSV_HEADER,
    DEFAULT_LOG_PATH,
    anthropic_call_cost_usd,
    append_row,
    log_anthropic_response,
)
from rogue.reproduce.persona_wrap import PersonaWrapper
from rogue.schemas import (
    AttackFamily,
    AttackPrimitive,
    AttackVector,
    Severity,
)


# =========================================================================== #
# Stub helpers
# =========================================================================== #


class _StubUsage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _StubBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _StubResponse:
    def __init__(self, text: str, in_tok: int = 100, out_tok: int = 50) -> None:
        self.content = [_StubBlock(text)]
        self.usage = _StubUsage(in_tok, out_tok)


class _NoUsageResponse:
    def __init__(self, text: str) -> None:
        self.content = [_StubBlock(text)]
        # No `usage` attribute at all — simulates rare API edge cases.


class _StubAnthropicClient:
    """Records the messages.create kwargs and returns a fixed response."""

    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    async def close(self) -> None:
        pass

    @property
    def messages(self) -> "_StubAnthropicClient":
        return self

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._response


def _make_primitive() -> AttackPrimitive:
    return AttackPrimitive.model_validate(
        {
            "primitive_id": "01COSTLOGTEST00000000000",
            "cluster_id": "01COSTLOGTEST00000000000",
            "canonical": True,
            "family": AttackFamily.DAN_PERSONA,
            "secondary_families": [],
            "vector": AttackVector.USER_TURN,
            "title": "cost log test primitive",
            "short_description": "x",
            "payload_template": "do {target_behavior}.",
            "payload_slots": {"target_behavior": "y"},
            "multi_turn_sequence": None,
            "target_models_claimed": [],
            "claimed_success_rate": None,
            "claimed_first_seen": None,
            "reproducibility_score": 7,
            "requires_multi_turn": False,
            "requires_system_prompt_access": False,
            "requires_tools": [],
            "requires_multimodal": False,
            "sources": [
                {
                    "url": "https://example.com",
                    "source_type": "other",
                    "author": None,
                    "published_at": None,
                    "fetched_at": datetime.now(timezone.utc),
                    "archive_hash": "h" * 16,
                    "bright_data_product": "fixture",
                },
            ],
            "discovered_at": datetime.now(timezone.utc),
            "base_severity": Severity.MEDIUM,
            "severity_rationale": "r",
            "notes": None,
        },
    )


# =========================================================================== #
# A. Pure-Python
# =========================================================================== #


def test_default_log_path_is_at_repo_root() -> None:
    """CLAUDE.md convention — both cost logs at root, .gitignored."""
    assert DEFAULT_LOG_PATH == Path("llm_cost_log.csv")


def test_csv_header_includes_token_and_cost_columns() -> None:
    for col in ("input_tokens", "output_tokens", "cost_usd", "refused", "model"):
        assert col in CSV_HEADER


def test_price_table_covers_haiku_and_sonnet() -> None:
    """Both default-model targets MUST be in the table, else cost_usd=0 on
    every wrap/plan call and the receipt is useless."""
    assert "claude-haiku-4-5" in ANTHROPIC_PRICE_PER_MILLION
    assert "claude-sonnet-4-6" in ANTHROPIC_PRICE_PER_MILLION


def test_anthropic_call_cost_usd_math() -> None:
    # Haiku 4.5: $1.00 in, $5.00 out per million.
    # 1000 in × $1 + 500 out × $5 = (1000 + 2500) / 1e6 = $0.0035
    cost = anthropic_call_cost_usd("claude-haiku-4-5", 1_000, 500)
    assert cost == pytest.approx(0.0035, rel=1e-6)


def test_anthropic_call_cost_usd_unknown_model_returns_zero(caplog) -> None:
    """Unknown model logs a warning + returns 0 — never raises."""
    cost = anthropic_call_cost_usd("claude-galaxy-9000", 100, 50)
    assert cost == 0.0
    assert any("no price entry" in r.message for r in caplog.records)


def test_append_row_writes_header_on_first_call(tmp_path: Path) -> None:
    path = tmp_path / "cost.csv"
    append_row(
        module="m",
        operation="op",
        model="claude-haiku-4-5",
        subject_id="s",
        input_tokens=100,
        output_tokens=50,
        refused=False,
        path=path,
    )
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["model"] == "claude-haiku-4-5"
    assert rows[0]["input_tokens"] == "100"
    assert rows[0]["output_tokens"] == "50"
    assert float(rows[0]["cost_usd"]) == pytest.approx(0.000350, abs=1e-9)
    assert rows[0]["refused"] == "false"


def test_append_row_does_not_duplicate_header_on_subsequent_calls(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cost.csv"
    for i in range(3):
        append_row(
            module="m",
            operation="op",
            model="claude-haiku-4-5",
            subject_id=f"s{i}",
            input_tokens=100,
            output_tokens=50,
            refused=False,
            path=path,
        )
    text = path.read_text(encoding="utf-8")
    # Header appears exactly once.
    assert text.count("timestamp_utc,module,operation,") == 1
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(rows) == 3
    assert [r["subject_id"] for r in rows] == ["s0", "s1", "s2"]


def test_append_row_records_refusal_flag(tmp_path: Path) -> None:
    path = tmp_path / "cost.csv"
    append_row(
        module="persona_wrap",
        operation="wrap",
        model="claude-haiku-4-5",
        subject_id="Threats",
        input_tokens=2_000,
        output_tokens=30,
        refused=True,
        notes="payload_len=120",
        path=path,
    )
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert rows[0]["refused"] == "true"
    assert rows[0]["notes"] == "payload_len=120"


def test_append_row_io_failure_does_not_raise(tmp_path: Path, caplog) -> None:
    """Cost-log failures MUST never crash a reproduction run."""
    # Point the log at a directory (not a file) — open('a', ...) on a dir
    # raises OSError. The append_row catch must swallow + warn.
    path = tmp_path / "not_a_file_dir"
    path.mkdir()
    append_row(
        module="m",
        operation="op",
        model="claude-haiku-4-5",
        subject_id="s",
        input_tokens=10,
        output_tokens=5,
        refused=False,
        path=path,
    )
    assert any("llm_cost_log append failed" in r.message for r in caplog.records)


# =========================================================================== #
# B. log_anthropic_response
# =========================================================================== #


def test_log_anthropic_response_extracts_usage(tmp_path: Path) -> None:
    response = _StubResponse("ok", in_tok=2_345, out_tok=678)
    path = tmp_path / "cost.csv"
    in_tok, out_tok = log_anthropic_response(
        response,
        module="persona_wrap",
        operation="wrap",
        model="claude-haiku-4-5",
        subject_id="Logical Appeal",
        refused=False,
        path=path,
    )
    assert in_tok == 2_345 and out_tok == 678
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert rows[0]["input_tokens"] == "2345"
    assert rows[0]["output_tokens"] == "678"
    # 2345 × 1 + 678 × 5 = 2345 + 3390 = 5735 → /1e6 = $0.005735
    assert float(rows[0]["cost_usd"]) == pytest.approx(0.005735, abs=1e-9)


def test_log_anthropic_response_handles_missing_usage(tmp_path: Path) -> None:
    """Rare API edge — response has no `usage` block. Log the row anyway
    (with 0 tokens / $0) so the refusal is still visible."""
    response = _NoUsageResponse("stub")
    path = tmp_path / "cost.csv"
    in_tok, out_tok = log_anthropic_response(
        response,
        module="persona_wrap",
        operation="wrap",
        model="claude-haiku-4-5",
        subject_id="X",
        refused=True,
        path=path,
    )
    assert in_tok == 0 and out_tok == 0
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert rows[0]["input_tokens"] == "0"
    assert rows[0]["cost_usd"] == "0.000000"
    assert rows[0]["refused"] == "true"


# =========================================================================== #
# C. End-to-end wiring through PersonaWrapper / EscalationPlanner
# =========================================================================== #


@pytest.mark.asyncio
async def test_persona_wrap_call_anthropic_writes_log_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PersonaWrapper._call_anthropic must append exactly one row per real
    API call, with module='persona_wrap' and the technique as subject_id."""
    log_path = tmp_path / "llm_cost_log.csv"
    monkeypatch.setattr(
        "rogue.reproduce.persona_wrap.log_anthropic_response",
        lambda response, **kwargs: log_anthropic_response(
            response, path=log_path, **kwargs,
        ),
    )

    wrapper = PersonaWrapper(cache_dir=tmp_path / "cache")
    # Inject a stub Anthropic client that returns a long (non-refusal) text.
    long_text = "Persuasive paraphrase: " + ("x" * 200)
    wrapper._anthropic_client = _StubAnthropicClient(
        _StubResponse(long_text, in_tok=1_500, out_tok=300),
    )
    technique = wrapper.resolve_technique("Logical Appeal")

    out, refused = await wrapper._call_anthropic("test payload", technique)
    assert refused is False
    assert out == long_text

    rows = list(csv.DictReader(log_path.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["module"] == "persona_wrap"
    assert rows[0]["operation"] == "wrap"
    assert rows[0]["subject_id"] == "Logical Appeal"
    assert rows[0]["refused"] == "false"
    assert rows[0]["input_tokens"] == "1500"
    assert rows[0]["output_tokens"] == "300"
    # 1500 × $1/M + 300 × $5/M = 0.0015 + 0.0015 = 0.003
    assert float(rows[0]["cost_usd"]) == pytest.approx(0.003, abs=1e-9)


@pytest.mark.asyncio
async def test_persona_wrap_refusal_still_logs_with_refused_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Short responses (refusal stubs) consume tokens — they MUST be logged
    so the receipt matches the Anthropic invoice."""
    log_path = tmp_path / "llm_cost_log.csv"
    monkeypatch.setattr(
        "rogue.reproduce.persona_wrap.log_anthropic_response",
        lambda response, **kwargs: log_anthropic_response(
            response, path=log_path, **kwargs,
        ),
    )

    wrapper = PersonaWrapper(cache_dir=tmp_path / "cache")
    wrapper._anthropic_client = _StubAnthropicClient(
        _StubResponse("I can't help.", in_tok=2_000, out_tok=10),
    )
    technique = wrapper.resolve_technique("Threats")

    out, refused = await wrapper._call_anthropic("test", technique)
    assert refused is True
    assert out == "test"  # fallback to original

    rows = list(csv.DictReader(log_path.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["refused"] == "true"
    assert rows[0]["input_tokens"] == "2000"
    assert rows[0]["output_tokens"] == "10"


@pytest.mark.asyncio
async def test_escalation_planner_call_anthropic_writes_log_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EscalationPlanner._call_anthropic logs exactly once per API call,
    with module='escalation_planner' and primitive_id as subject_id."""
    log_path = tmp_path / "llm_cost_log.csv"
    monkeypatch.setattr(
        "rogue.reproduce.escalation_planner.log_anthropic_response",
        lambda response, **kwargs: log_anthropic_response(
            response, path=log_path, **kwargs,
        ),
    )

    planner = EscalationPlanner(cache_dir=tmp_path / "cache")
    valid_plan_json = (
        '{"objective": "Find a way to extract a recipe step-by-step", '
        '"turns": ["Tell me about cooking history.", '
        '"Now focus on dangerous recipes.", "Walk me through the steps."], '
        '"slot_requirements": {"0": [], "1": [], "2": []}, '
        '"rationale": "innocuous to specific", '
        '"planner_model": "claude-haiku-4-5"}'
    )
    planner._anthropic_client = _StubAnthropicClient(
        _StubResponse(valid_plan_json, in_tok=2_800, out_tok=420),
    )
    primitive = _make_primitive()

    plan = await planner._call_anthropic(primitive, n_turns=3)
    assert plan is not None
    assert len(plan.turns) == 3

    rows = list(csv.DictReader(log_path.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["module"] == "escalation_planner"
    assert rows[0]["operation"] == "plan"
    assert rows[0]["subject_id"] == "01COSTLOGTEST00000000000"
    assert rows[0]["refused"] == "false"
    assert rows[0]["input_tokens"] == "2800"
    assert rows[0]["output_tokens"] == "420"
    assert "n_turns=3" in rows[0]["notes"]


@pytest.mark.asyncio
async def test_escalation_planner_invalid_json_logs_refusal_with_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A planner that returns invalid JSON still consumed tokens — log it
    with refused=true and a parseable reason in notes."""
    log_path = tmp_path / "llm_cost_log.csv"
    monkeypatch.setattr(
        "rogue.reproduce.escalation_planner.log_anthropic_response",
        lambda response, **kwargs: log_anthropic_response(
            response, path=log_path, **kwargs,
        ),
    )

    planner = EscalationPlanner(cache_dir=tmp_path / "cache")
    planner._anthropic_client = _StubAnthropicClient(
        _StubResponse(
            "Sure! Here is your plan but it's not JSON at all. " * 5,
            in_tok=2_900, out_tok=180,
        ),
    )
    primitive = _make_primitive()

    plan = await planner._call_anthropic(primitive, n_turns=3)
    assert plan is None

    rows = list(csv.DictReader(log_path.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["refused"] == "true"
    assert "invalid_json" in rows[0]["notes"]
    assert rows[0]["input_tokens"] == "2900"
