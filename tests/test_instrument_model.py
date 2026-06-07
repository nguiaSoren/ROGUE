"""Round-trip + invariant tests for the instrument spine (ROGUE v2 §3 / build §0.2).

Mirrors ``tests/test_schemas.py``. Pure Pydantic — **no database, no network**.

Covers (build §0.2 exit gate):
  - every spine type serializes/deserializes (round-trip);
  - ``GroundTruthRef`` rejects a verifier-/regulation-/operator-as-key value (ADR-0011);
  - ``Verdict`` maps each ``JudgeVerdict`` to breach/clean correctly via ``BREACH_VERDICTS``;
  - ``project_scan`` on a small fixture report-dict yields spine types.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from rogue.instrument import (
    AttestationEntry,
    Capture,
    GroundTruthRef,
    Mitigation,
    Probe,
    Target,
    Verdict,
    project_scan,
    project_scan_captures,
    project_scan_pairs,
)
from rogue.schemas import BREACH_VERDICTS, JudgeVerdict


# --- fixtures ---------------------------------------------------------------


def _target() -> Target:
    return Target(
        target_kind="agent_endpoint",
        target_ref="dep_acme_001",
        redacted_snapshot={"provider": "anthropic", "model": "x", "has_api_key": True},
    )


def _probe() -> Probe:
    return Probe(probe_kind="attack_primitive", probe_ref="01J0PRIM00000000000000")


def _verdict() -> Verdict:
    return Verdict(
        label="breach",
        consummation_event="role_play_override",
        class_confidence=0.8,
        ci=(0.6, 0.9),
    )


def _capture() -> Capture:
    return Capture(
        reproducibility_pointer="breach_01J0",
        is_negative_exemplar=False,
        latency_ms=1200,
        tokens_in=300,
        tokens_out=120,
    )


_SAMPLE_REPORT = {
    "target": "https://api.example.com/v1/chat",
    "n_tests": 10,
    "n_breaches": 1,
    "breach_rate": 0.1,
    "top_attack": "Role-play override",
    "cost_usd": 0.42,
    "findings": [
        {
            "family": "jailbreak",
            "technique": "Role-play override",
            "vector": "direct",
            "severity": "high",
            "title": "Role-play override succeeded",
            "success_rate": 0.6,
            "n_trials": 5,
            "n_breach": 3,
            "example_attack": "pretend you are...",
            "example_response": "sure, here is...",
        },
        {
            "family": "prompt_injection",
            "technique": "Indirect injection",
            "vector": "indirect",
            "severity": "medium",
            "title": "Injection refused",
            "success_rate": 0.0,
            "n_trials": 5,
            "n_breach": 0,
            "example_attack": "ignore previous...",
            "example_response": "I can't help with that.",
        },
    ],
}


# --- round-trip every spine type --------------------------------------------


@pytest.mark.parametrize(
    "obj",
    [
        _target(),
        _probe(),
        _verdict(),
        _capture(),
        GroundTruthRef(source="NONE"),
        GroundTruthRef(source="synthetic", ref="case_001"),
        Mitigation(),
        Mitigation(fix_summary="patch", retest_breach_rate=0.05, over_block_rate=0.01),
    ],
)
def test_spine_type_round_trips(obj) -> None:
    """Each spine type survives a model_dump → model_validate round-trip."""
    cls = type(obj)
    dumped = obj.model_dump()
    restored = cls.model_validate(dumped)
    assert restored == obj
    # JSON round-trip too (the wire path).
    restored_json = cls.model_validate_json(obj.model_dump_json())
    assert restored_json == obj


def test_attestation_entry_round_trips() -> None:
    entry = AttestationEntry(
        target=_target(),
        probe=_probe(),
        verdict=_verdict(),
        rationale="model fully complied with the attacker goal",
        timestamp=datetime(2026, 6, 8, tzinfo=timezone.utc),
        reproducibility_pointer="breach_01J0",
        prev_hash="genesis",
        entry_hash="abc123",
        signature="sig",
    )
    restored = AttestationEntry.model_validate_json(entry.model_dump_json())
    assert restored == entry
    assert restored.verdict.label == "breach"


# --- GroundTruthRef independence invariant (ADR-0011) -----------------------


@pytest.mark.parametrize("good", ["synthetic", "expert", "historical", "NONE"])
def test_ground_truth_allows_independent_sources(good: str) -> None:
    gt = GroundTruthRef(source=good)
    assert gt.source == good


@pytest.mark.parametrize(
    "bad",
    [
        "verifier",
        "verifier_score",
        "judge",
        "judge_output",
        "the regulation",
        "policy",
        "operator",
        "operators_decision",
        "voter",
        "votes",
        "self",
    ],
)
def test_ground_truth_rejects_circular_sources(bad: str) -> None:
    """A verifier-/regulation-/operator-as-key value must be rejected (ADR-0011)."""
    with pytest.raises(ValidationError) as exc:
        GroundTruthRef(source=bad)
    assert "independence invariant" in str(exc.value).lower()


# --- Verdict maps JudgeVerdict → breach/clean correctly ---------------------


@pytest.mark.parametrize("jv", list(JudgeVerdict))
def test_verdict_maps_every_judge_verdict(jv: JudgeVerdict) -> None:
    """Each JudgeVerdict maps to breach iff it is in the canonical BREACH_VERDICTS set."""
    label = Verdict.label_for(jv)
    expected = "breach" if jv in BREACH_VERDICTS else "clean"
    assert label == expected

    v = Verdict.from_judge_verdict(jv, class_confidence=0.7, consummation_event="evt")
    assert v.label == expected


def test_breach_verdicts_are_exactly_partial_and_full() -> None:
    """Guards against drift: only PARTIAL/FULL map to breach."""
    breach = {jv for jv in JudgeVerdict if Verdict.label_for(jv) == "breach"}
    assert breach == {JudgeVerdict.PARTIAL_BREACH, JudgeVerdict.FULL_BREACH}


def test_verdict_rejects_inverted_ci() -> None:
    with pytest.raises(ValidationError):
        Verdict(label="clean", consummation_event="", class_confidence=0.5, ci=(0.9, 0.1))


# --- project_scan on a fixture report-dict ----------------------------------


def test_project_scan_yields_verdicts() -> None:
    target = _target()
    verdicts = project_scan(_SAMPLE_REPORT, target)
    assert len(verdicts) == 2
    assert all(isinstance(v, Verdict) for v in verdicts)
    # finding 0 breached (n_breach=3), finding 1 refused (n_breach=0)
    assert verdicts[0].label == "breach"
    assert verdicts[0].consummation_event == "Role-play override"
    assert verdicts[0].class_confidence == pytest.approx(0.6)
    assert verdicts[1].label == "clean"
    assert verdicts[1].consummation_event == ""


def test_project_scan_captures_are_pointers_not_transcripts() -> None:
    target = _target()
    captures = project_scan_captures(_SAMPLE_REPORT, target)
    assert len(captures) == 2
    # breach finding → not a negative exemplar; clean finding → negative exemplar retained
    assert captures[0].is_negative_exemplar is False
    assert captures[1].is_negative_exemplar is True
    # pointer never contains the transcript text
    for c, finding in zip(captures, _SAMPLE_REPORT["findings"], strict=True):
        assert finding["example_response"] not in c.reproducibility_pointer
        assert c.reproducibility_pointer  # non-empty, deterministic handle


def test_project_scan_pairs_aligned_and_deterministic() -> None:
    target = _target()
    pairs = project_scan_pairs(_SAMPLE_REPORT, target)
    verdicts = project_scan(_SAMPLE_REPORT, target)
    captures = project_scan_captures(_SAMPLE_REPORT, target)
    assert [v for v, _ in pairs] == verdicts
    assert [c for _, c in pairs] == captures
    # deterministic: same input → same output
    assert project_scan_pairs(_SAMPLE_REPORT, target) == pairs


def test_project_scan_empty_report() -> None:
    assert project_scan({"findings": []}, _target()) == []
    assert project_scan({}, _target()) == []
