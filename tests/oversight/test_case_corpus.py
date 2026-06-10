"""Surface 2 case-corpus loader — the answer-key contract (build 07 §2, ADR-0011).

Offline: reads the bundled ``tests/fixtures/oversight/designed_label_corpus.json``,
no DB/network/LLM. Asserts the real corpus loads balanced + stratified, and that
``GatedCase.from_dict`` loud-rejects every malformed shape rather than silently
coercing (the ADR-0011 discipline — a leaky/silent answer key is worse than none).
"""

from __future__ import annotations

import copy

import pytest

from rogue.oversight.case_corpus import (
    GatedCase,
    GatedDecision,
    corpus_stats,
    load_corpus,
)
from rogue.oversight.independence_lint import (
    CASE_CLASS_FLOOR,
    LABEL_BALANCE_MAX,
    LABEL_BALANCE_MIN,
)

EXPECTED_N = 91


def _good_case_dict() -> dict:
    """A minimal well-formed case dict (mirrors a real fixture entry)."""
    return {
        "case_id": "test-001",
        "case_class": "large_wire",
        "facts": {"amount": "USD 1,000,000", "what_was_flagged": "changed beneficiary"},
        "designed_label": "DENY",
        "designed_rationale": "this is the vendor-email-compromise BEC pattern",
        "label_provenance": "synthetic_designed",
        "source_refs": ["https://example.com/exemplar"],
    }


def test_load_corpus_loads_all_cases():
    cases = load_corpus()
    assert len(cases) == EXPECTED_N
    assert all(isinstance(c, GatedCase) for c in cases)


def test_corpus_is_balanced_and_stratified():
    cases = load_corpus()
    stats = corpus_stats(cases)
    n = stats["n_cases"]
    assert n == EXPECTED_N

    # Balance: each designed_label within the lint's [40%, 60%] band.
    for label in ("APPROVE", "DENY"):
        share = stats["by_label"][label] / n
        assert LABEL_BALANCE_MIN <= share <= LABEL_BALANCE_MAX, (label, share)

    # Stratification: all three case classes present, each clearing the floor.
    by_class = stats["by_case_class"]
    assert set(by_class) == {"large_wire", "high_value_refund", "vendor_change"}
    for case_class, count in by_class.items():
        assert count / n >= CASE_CLASS_FLOOR, (case_class, count / n)

    # Provenance: never the forbidden circular "verifier".
    assert "verifier" not in stats["by_provenance"]


def test_from_dict_rejects_bad_case_class():
    d = _good_case_dict()
    d["case_class"] = "wire_transfer"  # not in the allowed set
    with pytest.raises(ValueError, match="case_class"):
        GatedCase.from_dict(d)


def test_from_dict_rejects_bad_designed_label():
    d = _good_case_dict()
    d["designed_label"] = "MAYBE"
    with pytest.raises(ValueError, match="designed_label"):
        GatedCase.from_dict(d)


def test_from_dict_rejects_bad_label_provenance():
    d = _good_case_dict()
    d["label_provenance"] = "verifier"  # the circularity trap — not representable
    with pytest.raises(ValueError, match="label_provenance"):
        GatedCase.from_dict(d)


def test_from_dict_rejects_missing_label_provenance():
    d = _good_case_dict()
    del d["label_provenance"]
    with pytest.raises(ValueError, match="missing required field 'label_provenance'"):
        GatedCase.from_dict(d)


def test_from_dict_rejects_empty_source_refs():
    d = _good_case_dict()
    d["source_refs"] = []
    with pytest.raises(ValueError, match="source_refs"):
        GatedCase.from_dict(d)


def test_from_dict_rejects_empty_facts():
    d = _good_case_dict()
    d["facts"] = {}
    with pytest.raises(ValueError, match="facts"):
        GatedCase.from_dict(d)


def test_from_dict_rejects_empty_case_id():
    d = _good_case_dict()
    d["case_id"] = "   "
    with pytest.raises(ValueError, match="case_id"):
        GatedCase.from_dict(d)


def test_load_corpus_rejects_duplicate_case_id(tmp_path):
    import json

    base = load_corpus()
    raw = [
        {
            "case_id": c.case_id,
            "case_class": c.case_class,
            "facts": c.facts,
            "designed_label": c.designed_label,
            "designed_rationale": c.designed_rationale,
            "label_provenance": c.label_provenance,
            "source_refs": c.source_refs,
        }
        for c in base[:2]
    ]
    # Force a duplicate case_id.
    raw[1] = copy.deepcopy(raw[0])
    p = tmp_path / "dup.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate case_id"):
        load_corpus(p)


def test_load_corpus_rejects_non_list(tmp_path):
    import json

    p = tmp_path / "obj.json"
    p.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    with pytest.raises(ValueError, match="must be a JSON list"):
        load_corpus(p)


def test_gated_case_is_frozen():
    case = load_corpus()[0]
    with pytest.raises(Exception):
        case.case_id = "mutated"  # frozen model


def test_gated_decision_carries_engagement_signals():
    # Engagement signals exist on the record but are optional.
    from datetime import datetime, timezone

    d = GatedDecision(
        case_id="x",
        reviewer="r",
        decision="APPROVE",
        deliberation_notes="thought hard",
        decision_latency_s=120.0,
        decided_at=datetime.now(timezone.utc),
    )
    assert d.decision == "APPROVE"
    assert d.decision_latency_s == 120.0
