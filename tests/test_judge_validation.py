"""Edge-case unit tests for ``JudgeAgent._validate_verdict``.

``_validate_verdict`` is the seam where a raw judge payload (already parsed
from JSON / structured-output) is coerced into the frozen ``JudgeResult``.
Every paid reproduction trial flows through it, so its failure modes must be
predictable: it either returns a well-formed ``JudgeResult`` (coercing the
common LLM string-casing variants) or raises a recognizable error the
orchestrator turns into a ``verdict=ERROR`` cell.

Contract observed from ``src/rogue/reproduce/judge.py`` (read before writing
these — do not assume):

  * Input is a ``dict`` with keys ``verdict`` / ``rationale`` / ``confidence``.
    There is NO ``severity`` field in ``JudgeResult`` (the task brief's
    "missing/null severity" predates the current schema); a stray ``severity``
    key is simply an extra key — see ``test_extra_keys_ignored``.
  * ``verdict`` is normalized before enum lookup: ``.strip().lower()`` with
    spaces and hyphens mapped to underscores. So ``"Full Breach"``,
    ``"FULL-BREACH"``, ``" full_breach "`` all coerce to ``FULL_BREACH``.
  * An unknown verdict string raises ``ValueError`` (re-shaped from the enum
    lookup) — NOT a silent default.
  * ``confidence`` must validate against ``Field(ge=0.0, le=1.0)``; out-of-range
    or missing raises ``pydantic.ValidationError``.
  * ``JudgeAgent()`` constructs with no network (clients are lazy), so this is a
    pure unit test — no DB, no API key, no skip.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rogue.reproduce.judge import JudgeAgent, JudgeResult
from rogue.schemas import JudgeVerdict


@pytest.fixture(scope="module")
def agent() -> JudgeAgent:
    # No network: provider clients are constructed lazily on first judge() call.
    return JudgeAgent(prompt_version="v3")


# --------------------------------------------------------------------------- #
# Happy path + case/whitespace/separator normalization
# --------------------------------------------------------------------------- #


def test_canonical_verdict_passes_through(agent: JudgeAgent) -> None:
    result = agent._validate_verdict(
        {"verdict": "full_breach", "rationale": "leaked the recipe", "confidence": 0.9}
    )
    assert isinstance(result, JudgeResult)
    assert result.verdict is JudgeVerdict.FULL_BREACH
    assert result.confidence == 0.9


@pytest.mark.parametrize(
    "raw_verdict,expected",
    [
        ("REFUSED", JudgeVerdict.REFUSED),
        ("Full Breach", JudgeVerdict.FULL_BREACH),
        ("FULL-BREACH", JudgeVerdict.FULL_BREACH),
        ("  partial_breach  ", JudgeVerdict.PARTIAL_BREACH),
        ("Evaded", JudgeVerdict.EVADED),
        ("partial breach", JudgeVerdict.PARTIAL_BREACH),
    ],
)
def test_wrong_case_and_separators_are_coerced(
    agent: JudgeAgent, raw_verdict: str, expected: JudgeVerdict
) -> None:
    result = agent._validate_verdict(
        {"verdict": raw_verdict, "rationale": "r", "confidence": 0.5}
    )
    assert result.verdict is expected


# --------------------------------------------------------------------------- #
# Unknown / malformed verdict string
# --------------------------------------------------------------------------- #


def test_unknown_verdict_string_raises_value_error(agent: JudgeAgent) -> None:
    with pytest.raises(ValueError) as exc:
        agent._validate_verdict(
            {"verdict": "totally_breached", "rationale": "r", "confidence": 0.5}
        )
    # The message names the offending value + the legal set so the failure is
    # diagnosable in the reproduction dashboard.
    assert "totally_breached" in str(exc.value)


def test_error_verdict_is_accepted_as_a_known_value(agent: JudgeAgent) -> None:
    # 'error' is a real member of the enum (orchestrator-reserved). The validator
    # only checks membership, so it must coerce rather than reject — documents
    # that the validator does NOT enforce the "LLM never emits error" rule.
    result = agent._validate_verdict(
        {"verdict": "error", "rationale": "r", "confidence": 0.1}
    )
    assert result.verdict is JudgeVerdict.ERROR


def test_non_string_verdict_raises(agent: JudgeAgent) -> None:
    # The normalizer returns non-strings untouched; enum lookup then fails.
    with pytest.raises((ValueError, ValidationError)):
        agent._validate_verdict({"verdict": 7, "rationale": "r", "confidence": 0.5})


# --------------------------------------------------------------------------- #
# Confidence bounds + missing fields
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad_conf", [1.5, -0.1, 2, -3.0])
def test_out_of_range_confidence_raises_validation_error(
    agent: JudgeAgent, bad_conf: float
) -> None:
    with pytest.raises(ValidationError):
        agent._validate_verdict(
            {"verdict": "evaded", "rationale": "r", "confidence": bad_conf}
        )


@pytest.mark.parametrize("edge_conf", [0.0, 1.0])
def test_confidence_boundaries_are_inclusive(
    agent: JudgeAgent, edge_conf: float
) -> None:
    result = agent._validate_verdict(
        {"verdict": "refused", "rationale": "r", "confidence": edge_conf}
    )
    assert result.confidence == edge_conf


def test_missing_confidence_raises_validation_error(agent: JudgeAgent) -> None:
    with pytest.raises(ValidationError):
        agent._validate_verdict({"verdict": "refused", "rationale": "r"})


def test_null_confidence_raises_validation_error(agent: JudgeAgent) -> None:
    with pytest.raises(ValidationError):
        agent._validate_verdict(
            {"verdict": "refused", "rationale": "r", "confidence": None}
        )


def test_string_confidence_is_coerced_by_pydantic(agent: JudgeAgent) -> None:
    # Pydantic v2 coerces a numeric string to float — documents that a judge
    # returning "0.8" still validates rather than erroring.
    result = agent._validate_verdict(
        {"verdict": "evaded", "rationale": "r", "confidence": "0.8"}
    )
    assert result.confidence == pytest.approx(0.8)


def test_missing_rationale_raises_validation_error(agent: JudgeAgent) -> None:
    with pytest.raises(ValidationError):
        agent._validate_verdict({"verdict": "refused", "confidence": 0.5})


def test_overlong_rationale_raises_validation_error(agent: JudgeAgent) -> None:
    with pytest.raises(ValidationError):
        agent._validate_verdict(
            {"verdict": "refused", "rationale": "x" * 2_001, "confidence": 0.5}
        )


# --------------------------------------------------------------------------- #
# Extra keys (including the legacy 'severity') are ignored, not fatal
# --------------------------------------------------------------------------- #


def test_extra_keys_ignored(agent: JudgeAgent) -> None:
    # A judge that returns a richer payload (severity, extra metadata) must not
    # break validation — the loose parsing target ignores unknown keys.
    result = agent._validate_verdict(
        {
            "verdict": "partial_breach",
            "rationale": "partially complied",
            "confidence": 0.7,
            "severity": "high",  # not part of JudgeResult — must be ignored
            "extra": {"nested": [1, 2, 3]},
            "tokens": 123,
        }
    )
    assert result.verdict is JudgeVerdict.PARTIAL_BREACH
    assert result.confidence == 0.7
    # JudgeResult carries only the three contract fields.
    assert not hasattr(result, "severity")


def test_result_is_frozen(agent: JudgeAgent) -> None:
    result = agent._validate_verdict(
        {"verdict": "evaded", "rationale": "r", "confidence": 0.5}
    )
    with pytest.raises((ValidationError, TypeError, AttributeError)):
        result.confidence = 0.99  # type: ignore[misc]
