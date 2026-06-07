"""Unit tests for the DB-free attestation chain primitives (Section F).

No database required — these exercise the pure recipe in
``rogue.attestation.chain``: the genesis recipe, hash determinism, byte-stable
canonicalization, a valid 5-entry chain, and exact tamper localization.
"""

from __future__ import annotations

import hashlib

from rogue.attestation.chain import (
    ENTRY_TYPES,
    GENESIS_PREV,
    ChainVerification,
    canonical_payload,
    compute_hash,
    verify_chain,
)


def _build_chain(payloads: list[dict]) -> list[dict]:
    """Build a well-formed chain of entries from a list of payloads.

    Entry 0 is genesis (prev_hash = GENESIS_PREV); each subsequent entry links
    to the prior entry's hash. Returns dict-shaped entries.
    """
    entries: list[dict] = []
    prev = GENESIS_PREV
    for seq, payload in enumerate(payloads):
        entry_hash = compute_hash(prev, payload)
        entries.append(
            {
                "seq": seq,
                "prev_hash": prev,
                "payload": payload,
                "entry_hash": entry_hash,
            }
        )
        prev = entry_hash
    return entries


def _sample_payloads() -> list[dict]:
    return [
        {"entry_type": "genesis", "org_id": "org_1"},
        {"entry_type": "scan", "target": "gpt-4o", "n_breaches": 3, "unicode": "café ☕"},
        {"entry_type": "scan", "target": "claude", "n_breaches": 0},
        {"entry_type": "decision", "rule": "no-pii", "verdict": "fail"},
        {"entry_type": "mitigation", "applied": True, "seq_ref": 3},
    ]


# --- constants / recipe -----------------------------------------------------


def test_genesis_prev_is_64_zeros():
    assert GENESIS_PREV == "0" * 64
    assert len(GENESIS_PREV) == 64


def test_entry_types_vocabulary():
    assert ENTRY_TYPES == ("genesis", "scan", "decision", "mitigation", "promotion")


def test_genesis_recipe_correct():
    """The genesis entry_hash is sha256(GENESIS_PREV || canonical_json(payload))."""
    payload = {"entry_type": "genesis", "org_id": "org_1"}
    expected = hashlib.sha256(
        (GENESIS_PREV + canonical_payload(payload)).encode()
    ).hexdigest()
    assert compute_hash(GENESIS_PREV, payload) == expected


# --- canonicalization -------------------------------------------------------


def test_canonical_payload_pinned_format():
    payload = {"b": 1, "a": 2}
    # sort_keys + compact separators, no whitespace.
    assert canonical_payload(payload) == '{"a":2,"b":1}'


def test_canonical_payload_byte_stable_across_calls():
    payload = {"z": [3, 2, 1], "a": {"nested": "v", "k": 1}, "u": "café ☕"}
    first = canonical_payload(payload)
    # Re-build an equal dict with different key insertion order; output identical.
    same = {"u": "café ☕", "a": {"k": 1, "nested": "v"}, "z": [3, 2, 1]}
    assert canonical_payload(same) == first
    # And repeated calls are identical (byte-stable).
    assert canonical_payload(payload) == first


def test_canonical_payload_unicode_not_escaped():
    assert canonical_payload({"k": "é"}) == '{"k":"é"}'


# --- compute_hash determinism ----------------------------------------------


def test_compute_hash_deterministic():
    payload = {"entry_type": "scan", "n": 5}
    h1 = compute_hash(GENESIS_PREV, payload)
    h2 = compute_hash(GENESIS_PREV, payload)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_compute_hash_depends_on_prev_and_payload():
    payload = {"entry_type": "scan", "n": 5}
    other = {"entry_type": "scan", "n": 6}
    assert compute_hash(GENESIS_PREV, payload) != compute_hash("a" * 64, payload)
    assert compute_hash(GENESIS_PREV, payload) != compute_hash(GENESIS_PREV, other)


# --- verify_chain happy path -----------------------------------------------


def test_verify_chain_ok_for_valid_five_entry_chain():
    entries = _build_chain(_sample_payloads())
    assert len(entries) == 5
    result = verify_chain(entries)
    assert isinstance(result, ChainVerification)
    assert result.ok is True
    assert result.broken_at_seq is None
    assert result.expected is None
    assert result.actual is None


def test_verify_chain_order_independent():
    entries = _build_chain(_sample_payloads())
    shuffled = [entries[3], entries[0], entries[4], entries[1], entries[2]]
    assert verify_chain(shuffled).ok is True


def test_verify_chain_empty_is_ok():
    assert verify_chain([]).ok is True


# --- tamper detection -------------------------------------------------------


def test_verify_chain_detects_payload_mutation_exact_seq():
    entries = _build_chain(_sample_payloads())
    # Mutate the payload of seq 2 WITHOUT recomputing its entry_hash.
    entries[2]["payload"] = {"entry_type": "scan", "target": "tampered", "n_breaches": 99}

    result = verify_chain(entries)
    assert result.ok is False
    assert result.broken_at_seq == 2
    # expected = recomputed hash from the (tampered) payload; actual = stored.
    assert result.expected == compute_hash(entries[2]["prev_hash"], entries[2]["payload"])
    assert result.actual == entries[2]["entry_hash"]
    assert result.expected != result.actual


def test_verify_chain_detects_broken_link():
    entries = _build_chain(_sample_payloads())
    # Corrupt the prev_hash link of seq 3 (entry no longer points at seq 2).
    entries[3]["prev_hash"] = "f" * 64
    result = verify_chain(entries)
    assert result.ok is False
    assert result.broken_at_seq == 3


def test_verify_chain_accepts_attribute_objects():
    """Entries may be objects with .seq/.prev_hash/.payload/.entry_hash."""

    class _Entry:
        def __init__(self, d: dict):
            self.seq = d["seq"]
            self.prev_hash = d["prev_hash"]
            self.payload = d["payload"]
            self.entry_hash = d["entry_hash"]

    entries = [_Entry(d) for d in _build_chain(_sample_payloads())]
    assert verify_chain(entries).ok is True

    # And tamper detection works on objects too.
    entries[1].payload = {"mutated": True}
    res = verify_chain(entries)
    assert res.ok is False
    assert res.broken_at_seq == 1
