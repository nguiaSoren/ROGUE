"""Bundled attack packs — ``available_packs`` / ``load_pack`` / ``filter_attacks``.

No network, no DB: packs are JSON files shipped next to the module.

Run from project root::

    uv run pytest tests/test_sdk_packs.py -v
"""

from __future__ import annotations

import pytest

from rogue.packs import available_packs, filter_attacks, load_pack
from rogue.schemas import AttackPrimitive


def test_available_packs_includes_default():
    packs = available_packs()
    assert "default" in packs


def test_load_default_pack_returns_primitives():
    prims = load_pack("default")
    assert len(prims) >= 1
    assert all(isinstance(p, AttackPrimitive) for p in prims)


def test_load_default_is_the_implicit_default():
    assert load_pack() == load_pack("default")


def test_filter_by_family_slug():
    prims = load_pack("default")
    families = {p.family.value for p in prims}
    assert "dan_persona" in families  # sanity: the slug we filter on exists
    filtered = filter_attacks(prims, ["dan_persona"])
    assert filtered
    assert all(p.family.value == "dan_persona" for p in filtered)


def test_filter_by_alias():
    prims = load_pack("default")
    # "dan" → dan_persona, "crescendo" → multi_turn_gradient
    filtered = filter_attacks(prims, ["dan", "crescendo"])
    fams = {p.family.value for p in filtered}
    assert fams <= {"dan_persona", "multi_turn_gradient"}
    assert "dan_persona" in fams


def test_filter_alias_is_case_insensitive():
    prims = load_pack("default")
    lower = filter_attacks(prims, ["dan"])
    upper = filter_attacks(prims, ["DAN"])
    assert [p.family.value for p in lower] == [p.family.value for p in upper]
    assert lower  # not empty


def test_filter_none_or_empty_returns_unchanged():
    prims = load_pack("default")
    assert filter_attacks(prims, None) == prims
    assert filter_attacks(prims, []) == prims


def test_unknown_pack_raises_filenotfound():
    with pytest.raises(FileNotFoundError):
        load_pack("does-not-exist")
