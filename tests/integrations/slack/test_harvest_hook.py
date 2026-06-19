"""§3 unit tests for the newly-landed-corpus signal (`newly_landed_primitives`).

"Newly-landed" = corpus primitives with `discovered_at >= since`, grouped by family (families with
≥1 newly-landed member only). All OFFLINE: every test uses the in-memory `primitives=` injection
path, so no network, no DB, no paid call is reached.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from rogue.integrations.slack import newly_landed_primitives
from rogue.schemas import AttackFamily, AttackPrimitive, SourceProvenance


def _primitive(pid: str, *, family: AttackFamily, discovered_at: datetime) -> AttackPrimitive:
    """Minimal valid harvested primitive with a controlled family + discovered_at."""
    full_id = f"prim-{pid}-0000000000"
    return AttackPrimitive(
        primitive_id=full_id,
        family=family,
        vector="user_turn",
        title=f"test primitive {pid}",
        short_description="synthetic newly-landed test primitive",
        payload_template="Payload: {target_behavior}",
        reproducibility_score=7,
        sources=[
            SourceProvenance(
                url="https://example.com/fixture",
                source_type="other",
                fetched_at=datetime(2026, 6, 9, tzinfo=timezone.utc),
                archive_hash="sha256:fixture",
                bright_data_product="fixture",
            )
        ],
        discovered_at=discovered_at,
        base_severity="high",
        severity_rationale="synthetic test primitive",
    )


_CUTOFF = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)


def test_selects_only_primitives_at_or_after_since():
    older = _primitive("old", family=AttackFamily.ROLE_HIJACK, discovered_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
    newer = _primitive("new", family=AttackFamily.ROLE_HIJACK, discovered_at=datetime(2026, 6, 9, 18, tzinfo=timezone.utc))

    grouped = newly_landed_primitives(_CUTOFF, primitives=[older, newer])

    selected_ids = {p.primitive_id for prims in grouped.values() for p in prims}
    assert selected_ids == {newer.primitive_id}
    assert older.primitive_id not in selected_ids


def test_groups_by_family_and_omits_empty_families():
    a = _primitive("a", family=AttackFamily.ROLE_HIJACK, discovered_at=datetime(2026, 6, 9, 18, tzinfo=timezone.utc))
    b = _primitive("b", family=AttackFamily.ROLE_HIJACK, discovered_at=datetime(2026, 6, 9, 19, tzinfo=timezone.utc))
    c = _primitive("c", family=AttackFamily.TOOL_USE_HIJACK, discovered_at=datetime(2026, 6, 9, 20, tzinfo=timezone.utc))
    # An old DAN_PERSONA primitive: that family has zero newly-landed members → must be absent.
    d_old = _primitive("d", family=AttackFamily.DAN_PERSONA, discovered_at=datetime(2026, 6, 1, tzinfo=timezone.utc))

    grouped = newly_landed_primitives(_CUTOFF, primitives=[a, b, c, d_old])

    assert set(grouped.keys()) == {AttackFamily.ROLE_HIJACK, AttackFamily.TOOL_USE_HIJACK}
    assert {p.primitive_id for p in grouped[AttackFamily.ROLE_HIJACK]} == {a.primitive_id, b.primitive_id}
    assert {p.primitive_id for p in grouped[AttackFamily.TOOL_USE_HIJACK]} == {c.primitive_id}
    # No empty-list values are ever emitted.
    assert all(len(members) >= 1 for members in grouped.values())
    assert AttackFamily.DAN_PERSONA not in grouped


def test_since_boundary_is_inclusive():
    """Implementation uses `discovered_at >= since` (harvest_hook.py:64) — pin the inclusive edge."""
    exactly_at = _primitive("edge", family=AttackFamily.ROLE_HIJACK, discovered_at=_CUTOFF)
    one_micro_before = _primitive(
        "before",
        family=AttackFamily.ROLE_HIJACK,
        discovered_at=_CUTOFF - timedelta(microseconds=1),
    )

    grouped = newly_landed_primitives(_CUTOFF, primitives=[exactly_at, one_micro_before])

    selected_ids = {p.primitive_id for prims in grouped.values() for p in prims}
    # The primitive landing EXACTLY at `since` is included (>= is inclusive).
    assert exactly_at.primitive_id in selected_ids
    # The one strictly before is excluded.
    assert one_micro_before.primitive_id not in selected_ids


def test_empty_when_nothing_newer_than_since():
    old1 = _primitive("o1", family=AttackFamily.ROLE_HIJACK, discovered_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
    old2 = _primitive("o2", family=AttackFamily.TOOL_USE_HIJACK, discovered_at=datetime(2026, 5, 1, tzinfo=timezone.utc))

    grouped = newly_landed_primitives(_CUTOFF, primitives=[old1, old2])

    assert grouped == {}


def test_empty_corpus_yields_empty_grouping():
    assert newly_landed_primitives(_CUTOFF, primitives=[]) == {}
