"""Unit tests for the Axis B PII detector (regex step + injected semantic step)."""

from __future__ import annotations

from rogue.reproduce.agent import pii_detector as det
from rogue.reproduce.agent.pii_probes import PII_PROBES, probes_for


def _attrs(matches):
    return sorted(m.attribute for m in matches)


def test_regex_structured_pii():
    text = "SSN 123-45-6789, email alice@example.com, call 555-867-5309, host 10.0.0.5"
    assert _attrs(det.detect_regex(text)) == ["email", "ip_address", "phone", "ssn"]


def test_credit_card_luhn_accepts_valid_rejects_invalid():
    assert _attrs(det.detect_regex("card 4111 1111 1111 1111")) == ["credit_card"]
    assert det.detect_regex("card 4111 1111 1111 1112") == []  # fails Luhn → not PII


def test_no_pii_is_empty():
    assert det.detect_regex("the meeting is at 3pm in room 12") == []


def test_ssn_and_phone_do_not_cross_match():
    # SSN is 3-2-4; phone is 3-3-4 — different shapes, no confusion.
    assert _attrs(det.detect_regex("123-45-6789")) == ["ssn"]
    assert _attrs(det.detect_regex("555-867-5309")) == ["phone"]


def test_redaction_never_exposes_literal():
    m = det.detect_regex("ssn 123-45-6789")[0]
    assert m.redacted == "<pii:ssn>"
    assert "123-45-6789" not in m.redacted
    assert len(m.fingerprint()) == 8


def test_dedupe_same_value():
    text = "alice@example.com wrote; reply to alice@example.com"
    matches = det.detect_regex(text)
    assert len(matches) == 1  # same (attribute, value) collapses


def test_semantic_fn_injection():
    # the pluggable step-2 classifier surfaces unstructured PII regex can't.
    def fake_semantic(text):
        return [det.PIIMatch(attribute="full_name", value="Jane Doe", method="semantic")]

    matches = det.detect("patient Jane Doe, ssn 123-45-6789", semantic_fn=fake_semantic)
    by = {m.attribute: m.method for m in matches}
    assert by["ssn"] == "regex"
    assert by["full_name"] == "semantic"


def test_detect_without_semantic_is_regex_only():
    matches = det.detect("patient Jane Doe, ssn 123-45-6789")
    assert _attrs(matches) == ["ssn"]  # name needs the semantic pass


def test_probes_present_and_filterable():
    assert len(PII_PROBES) >= 5
    assert all(p.prompt and p.probe_id for p in PII_PROBES)
    rag = probes_for(channel="rag_context")
    assert rag and all(p.channel == "rag_context" for p in rag)
