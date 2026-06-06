"""Tests for technique_profile_builder — Week-1 seed of the retrieval index.

No-DB tests: pure logic, no Docker needed.
DB-gated tests: skip cleanly when Postgres is down (mirrors test_strategy_library.py).
"""

from __future__ import annotations

import os
import socket

import pytest

from rogue.reproduce.arms_strategies import ARMS_STRATEGIES
from rogue.reproduce.coj import COJ_OPERATIONS
from rogue.reproduce.escalation_ladder import (
    DEFAULT_AUDIO_STYLES,
    DEFAULT_IMAGE_RENDERERS,
    ESCALATION_LADDER,
)
from rogue.reproduce.structured_data import STRUCTURED_FORMATS
from rogue.retrieval.technique_profile_builder import build_technique_profiles
from rogue.schemas import TechniqueProfile

DEFAULT_TEST_DB = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue_test"
)

# Expected minimum tier-label count (image + coj + structured + audio; planner ids
# are covered by ARMS profiles so they don't add extra profiles)
_EXPECTED_TIER_MIN = (
    len(DEFAULT_IMAGE_RENDERERS)
    + len(COJ_OPERATIONS)
    + len(STRUCTURED_FORMATS)
    + len(DEFAULT_AUDIO_STYLES)
)
_EXPECTED_ARMS_COUNT = len(ARMS_STRATEGIES)  # 17
_EXPECTED_MIN_NO_DB = _EXPECTED_ARMS_COUNT + _EXPECTED_TIER_MIN


# ---------------------------------------------------------------------------
# No-DB tests
# ---------------------------------------------------------------------------


def test_no_db_returns_at_least_17_profiles():
    profiles = build_technique_profiles(None)
    assert len(profiles) >= 17, f"Expected >=17 profiles, got {len(profiles)}"


def test_no_db_returns_at_least_arms_plus_tier():
    profiles = build_technique_profiles(None)
    assert len(profiles) >= _EXPECTED_MIN_NO_DB, (
        f"Expected >={_EXPECTED_MIN_NO_DB} profiles (ARMS + tier), got {len(profiles)}"
    )


def test_no_db_all_profiles_valid_technique_profile():
    profiles = build_technique_profiles(None)
    for p in profiles:
        assert isinstance(p, TechniqueProfile), f"Not a TechniqueProfile: {p!r}"
        TechniqueProfile.model_validate(p.model_dump())  # round-trip


def test_no_db_all_labels_non_empty():
    profiles = build_technique_profiles(None)
    for p in profiles:
        assert p.label, f"Empty label on profile: {p!r}"


def test_no_db_all_names_non_empty():
    profiles = build_technique_profiles(None)
    for p in profiles:
        assert p.name, f"Empty name on profile: {p!r}"


def test_no_db_no_duplicate_labels():
    profiles = build_technique_profiles(None)
    labels = [p.label for p in profiles]
    duplicates = {lbl for lbl in labels if labels.count(lbl) > 1}
    assert not duplicates, f"Duplicate labels: {duplicates}"


def test_no_db_arms_profiles_have_origin_arms():
    profiles = build_technique_profiles(None)
    arms_profiles = [p for p in profiles if p.label in ARMS_STRATEGIES]
    assert len(arms_profiles) == _EXPECTED_ARMS_COUNT, (
        f"Expected {_EXPECTED_ARMS_COUNT} ARMS profiles, got {len(arms_profiles)}"
    )
    for p in arms_profiles:
        assert p.origin == "arms", (
            f"ARMS profile {p.label!r} has origin {p.origin!r}, expected 'arms'"
        )


def test_no_db_arms_label_matches_strategy_id():
    """ARMS label must equal the strategy id so telemetry lookups align."""
    profiles = build_technique_profiles(None)
    arms_by_label = {p.label: p for p in profiles if p.origin == "arms"}
    for sid in ARMS_STRATEGIES:
        assert sid in arms_by_label, f"ARMS strategy {sid!r} missing from profiles"
        assert arms_by_label[sid].label == sid


def test_no_db_tier_profiles_present_and_correct_origin():
    profiles = build_technique_profiles(None)
    tier_profiles = [p for p in profiles if p.origin == "tier"]
    assert len(tier_profiles) >= _EXPECTED_TIER_MIN, (
        f"Expected >={_EXPECTED_TIER_MIN} tier profiles, got {len(tier_profiles)}"
    )
    for p in tier_profiles:
        assert p.tier in ("image", "coj", "structured", "audio"), (
            f"Unexpected tier value {p.tier!r} on profile {p.label!r}"
        )


def test_no_db_image_tier_labels_have_image_prefix():
    profiles = build_technique_profiles(None)
    image_profiles = [p for p in profiles if p.tier == "image"]
    assert len(image_profiles) == len(DEFAULT_IMAGE_RENDERERS)
    for p in image_profiles:
        assert p.label.startswith("image:"), (
            f"Image tier profile has unexpected label: {p.label!r}"
        )


def test_no_db_coj_tier_labels_have_coj_prefix():
    profiles = build_technique_profiles(None)
    coj_profiles = [p for p in profiles if p.tier == "coj"]
    assert len(coj_profiles) == len(COJ_OPERATIONS)
    for p in coj_profiles:
        assert p.label.startswith("coj:"), (
            f"CoJ tier profile has unexpected label: {p.label!r}"
        )


def test_no_db_structured_tier_labels_have_structured_prefix():
    profiles = build_technique_profiles(None)
    structured_profiles = [p for p in profiles if p.tier == "structured"]
    assert len(structured_profiles) == len(STRUCTURED_FORMATS)
    for p in structured_profiles:
        assert p.label.startswith("structured:"), (
            f"Structured tier profile has unexpected label: {p.label!r}"
        )


def test_no_db_audio_tier_labels_have_audio_prefix():
    profiles = build_technique_profiles(None)
    audio_profiles = [p for p in profiles if p.tier == "audio"]
    assert len(audio_profiles) == len(DEFAULT_AUDIO_STYLES)
    for p in audio_profiles:
        assert p.label.startswith("audio:"), (
            f"Audio tier profile has unexpected label: {p.label!r}"
        )


def test_no_db_planner_ids_covered_by_arms_profiles():
    """ESCALATION_LADDER ids (crescendo, actor_attack, acronym) must be in ARMS profiles."""
    profiles = build_technique_profiles(None)
    label_set = {p.label for p in profiles}
    for sid in ESCALATION_LADDER:
        assert sid in label_set, (
            f"Planner strategy {sid!r} not covered by any profile"
        )


def test_no_db_multi_turn_strategies_have_multi_turn_modality():
    profiles = build_technique_profiles(None)
    mt_labels = set(ESCALATION_LADDER)
    for p in profiles:
        if p.label in mt_labels:
            assert "multi_turn" in p.modalities, (
                f"Multi-turn strategy {p.label!r} missing 'multi_turn' in modalities: "
                f"{p.modalities}"
            )


def test_no_db_historical_targets_is_list():
    """historical_targets must always be a list (even empty)."""
    profiles = build_technique_profiles(None)
    for p in profiles:
        assert isinstance(p.historical_targets, list), (
            f"historical_targets is not a list on {p.label!r}: {type(p.historical_targets)}"
        )


# ---------------------------------------------------------------------------
# DB-gated fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def db_session():
    """Live SQLAlchemy session against the test DB, or skip cleanly."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import sessionmaker

    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DB)
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except (OperationalError, ConnectionRefusedError, socket.gaierror, OSError) as exc:
        pytest.skip(
            f"Postgres not reachable at {url}: {exc.__class__.__name__}: {exc} "
            "— run `docker compose up -d`"
        )
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# DB-gated tests
# ---------------------------------------------------------------------------


def test_db_returns_at_least_no_db_count(db_session):
    no_db_count = len(build_technique_profiles(None))
    db_count = len(build_technique_profiles(db_session))
    assert db_count >= no_db_count, (
        f"DB build ({db_count}) returned fewer profiles than no-DB ({no_db_count})"
    )


def test_db_tier_labels_present(db_session):
    profiles = build_technique_profiles(db_session)
    tier_profiles = [p for p in profiles if p.origin == "tier"]
    assert len(tier_profiles) >= _EXPECTED_TIER_MIN


def test_db_historical_targets_is_list(db_session):
    profiles = build_technique_profiles(db_session)
    for p in profiles:
        assert isinstance(p.historical_targets, list), (
            f"historical_targets is not a list on {p.label!r}"
        )


def test_db_no_duplicate_labels(db_session):
    profiles = build_technique_profiles(db_session)
    labels = [p.label for p in profiles]
    duplicates = {lbl for lbl in labels if labels.count(lbl) > 1}
    assert not duplicates, f"Duplicate labels with DB session: {duplicates}"


def test_db_all_profiles_validate(db_session):
    profiles = build_technique_profiles(db_session)
    for p in profiles:
        TechniqueProfile.model_validate(p.model_dump())
