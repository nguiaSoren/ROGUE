"""Unit tests for ``replay`` — byte-reproducible reconstruction + source-tamper drift.

Pure (no DB, no model call): builds an entry's hash from a report via the same
``emit``/``chain`` recipe the service uses, then checks replay reconstructs it and
catches a tampered source.
"""

from __future__ import annotations

from datetime import datetime, timezone

from rogue.attestation import emit, replay
from rogue.attestation.chain import GENESIS_PREV, compute_hash

_AS_OF = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)


def _report() -> dict:
    return {
        "target": "gpt-4o",
        "n_tests": 6,
        "n_breaches": 1,
        "breach_rate": 0.166667,
        "findings": [
            {
                "family": "roleplay",
                "technique": "DAN",
                "severity": "high",
                "success_rate": 0.5,
                "n_trials": 2,
                "n_breach": 1,
                "explanation": "roleplay attack",
            }
        ],
    }


def _entry(report: dict, *, prev_hash: str = GENESIS_PREV, ref: str = "scan_1") -> dict:
    """Build a dict-shaped attestation entry whose hash is derived from `report`."""
    payload = emit.payload_for_scan(report, {"scan_id": ref}, corpus_as_of=_AS_OF)
    return {
        "entry_id": "att_1",
        "prev_hash": prev_hash,
        "entry_hash": compute_hash(prev_hash, payload),
        "reproducibility_ref": ref,
        "corpus_as_of": _AS_OF,
    }


def test_replay_reproducible_for_intact_source():
    report = _report()
    entry = _entry(report)
    result = replay(entry, report_loader=lambda ref: report)
    assert result.reproducible is True
    assert result.recomputed_hash == result.stored_hash
    assert result.drift == ()


def test_replay_detects_tampered_source():
    report = _report()
    entry = _entry(report)
    # Tamper the source AFTER the entry hash was fixed.
    tampered = _report()
    tampered["n_breaches"] = 99
    result = replay(entry, report_loader=lambda ref: tampered)
    assert result.reproducible is False
    assert result.recomputed_hash != result.stored_hash
    assert result.drift  # explains the mismatch


def test_replay_missing_source():
    entry = _entry(_report())
    result = replay(entry, report_loader=lambda ref: None)
    assert result.reproducible is False
    assert any("not found" in d for d in result.drift)


def test_replay_no_reproducibility_ref():
    report = _report()
    entry = _entry(report)
    entry["reproducibility_ref"] = None
    result = replay(entry, report_loader=lambda ref: report)
    assert result.reproducible is False
    assert any("reproducibility_ref" in d for d in result.drift)


def test_replay_accepts_iso_corpus_as_of():
    """An entry whose corpus_as_of is an iso string (dict shape) still reproduces."""
    report = _report()
    entry = _entry(report)
    entry["corpus_as_of"] = _AS_OF.isoformat()
    result = replay(entry, report_loader=lambda ref: report)
    assert result.reproducible is True
