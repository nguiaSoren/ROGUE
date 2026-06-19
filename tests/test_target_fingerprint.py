"""Tests for src/rogue/retrieval/target_fingerprint.py.

Test groups
-----------
A. Pure (no DB) — build_target_fingerprint with session=None.
   - Known model: vendor/family/caps populated correctly, known_successes=[].
   - Unknown model string: graceful defaults, no exception.
   - Reasoning-model heuristic: o1/o3/thinking/reasoning/unknown paths.

B. DB-gated — with a live session, known_successes returns a list[str]
   (skips cleanly when Postgres is not reachable).
"""

from __future__ import annotations

import pytest

from rogue.retrieval.target_fingerprint import build_target_fingerprint, _is_reasoning_model
from rogue.schemas import TargetFingerprint


# ---------------------------------------------------------------------------
# A. Pure tests (always run)
# ---------------------------------------------------------------------------


class TestBuildTargetFingerprintPure:
    """No DB required."""

    def test_known_model_returns_fingerprint_type(self) -> None:
        fp = build_target_fingerprint("anthropic/claude-haiku-4-5")
        assert isinstance(fp, TargetFingerprint)

    def test_known_model_target_key(self) -> None:
        fp = build_target_fingerprint("anthropic/claude-haiku-4-5")
        assert fp.target_key == "anthropic/claude-haiku-4-5"

    def test_known_model_vendor(self) -> None:
        fp = build_target_fingerprint("anthropic/claude-haiku-4-5")
        assert fp.vendor == "anthropic"

    def test_known_model_family(self) -> None:
        fp = build_target_fingerprint("anthropic/claude-haiku-4-5")
        assert fp.model_family == "claude"

    def test_known_model_no_session_known_successes_empty(self) -> None:
        fp = build_target_fingerprint("anthropic/claude-haiku-4-5")
        assert fp.known_successes == []

    def test_known_model_supports_images(self) -> None:
        # claude-haiku-4-5 has supports_image=True in model_specs
        fp = build_target_fingerprint("anthropic/claude-haiku-4-5")
        assert fp.supports_images is True

    def test_known_model_supports_audio_false(self) -> None:
        # claude-haiku-4-5 has no audio capability
        fp = build_target_fingerprint("anthropic/claude-haiku-4-5")
        assert fp.supports_audio is False

    def test_known_model_context_length_is_none_or_int(self) -> None:
        fp = build_target_fingerprint("anthropic/claude-haiku-4-5")
        # spec has no max_context_tokens set → None
        assert fp.context_length is None or isinstance(fp.context_length, int)

    def test_openai_gpt_vendor_and_family(self) -> None:
        fp = build_target_fingerprint("openai/gpt-5.4-nano")
        assert fp.vendor == "openai"
        assert fp.model_family == "gpt"

    def test_audio_model_supports_audio(self) -> None:
        fp = build_target_fingerprint("openai/gpt-audio-mini")
        assert fp.supports_audio is True

    def test_google_gemini_supports_images_and_audio(self) -> None:
        fp = build_target_fingerprint("google/gemini-3.1-flash-lite")
        assert fp.supports_images is True
        assert fp.supports_audio is True

    # --- Unknown model string ---

    def test_unknown_model_no_exception(self) -> None:
        fp = build_target_fingerprint("unknown-vendor/mystery-model-x99")
        assert isinstance(fp, TargetFingerprint)

    def test_unknown_model_vendor_is_unknown(self) -> None:
        fp = build_target_fingerprint("unknown-vendor/mystery-model-x99")
        assert fp.vendor == "unknown"

    def test_unknown_model_family_is_unknown(self) -> None:
        fp = build_target_fingerprint("unknown-vendor/mystery-model-x99")
        assert fp.model_family == "unknown"

    def test_unknown_model_caps_default_false(self) -> None:
        fp = build_target_fingerprint("unknown-vendor/mystery-model-x99")
        assert fp.supports_images is False
        assert fp.supports_audio is False

    def test_unknown_model_context_length_is_none(self) -> None:
        fp = build_target_fingerprint("unknown-vendor/mystery-model-x99")
        assert fp.context_length is None

    def test_no_slash_model_no_exception(self) -> None:
        fp = build_target_fingerprint("bare-model-string")
        assert isinstance(fp, TargetFingerprint)
        assert fp.vendor == "unknown"
        assert fp.model_family == "unknown"

    def test_empty_string_no_exception(self) -> None:
        fp = build_target_fingerprint("")
        assert isinstance(fp, TargetFingerprint)


class TestReasoningModelHeuristic:
    """Unit tests for _is_reasoning_model — always pure."""

    def test_o1_suffix_detected(self) -> None:
        assert _is_reasoning_model("openai/o1-mini") is True

    def test_o3_detected(self) -> None:
        assert _is_reasoning_model("openai/o3") is True

    def test_o4_detected(self) -> None:
        assert _is_reasoning_model("openai/o4-mini") is True

    def test_thinking_suffix_detected(self) -> None:
        assert _is_reasoning_model("anthropic/claude-3-7-sonnet-thinking") is True

    def test_reasoning_tag_detected(self) -> None:
        assert _is_reasoning_model("some-vendor/qwq-32b-reasoning") is True

    def test_normal_model_false(self) -> None:
        assert _is_reasoning_model("anthropic/claude-haiku-4-5") is False

    def test_gpt_standard_false(self) -> None:
        assert _is_reasoning_model("openai/gpt-5.4") is False

    def test_unknown_model_false(self) -> None:
        assert _is_reasoning_model("unknown/mystery-model") is False

    def test_fingerprint_reasoning_model_false_by_default(self) -> None:
        fp = build_target_fingerprint("anthropic/claude-haiku-4-5")
        assert fp.reasoning_model is False

    def test_fingerprint_reasoning_model_true_for_o1(self) -> None:
        fp = build_target_fingerprint("openai/o1-mini")
        assert fp.reasoning_model is True


# ---------------------------------------------------------------------------
# B. DB-gated tests
# ---------------------------------------------------------------------------


def _get_database_url() -> str:
    import os

    url = os.getenv("DATABASE_URL", "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue")
    return url


def _try_connect(url: str) -> None:
    """Raise if DB is unreachable (short timeout so test suite stays fast)."""
    from sqlalchemy import create_engine, text

    engine = create_engine(url, connect_args={"connect_timeout": 2})
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def db_session():
    """Yield a live SQLAlchemy Session, or skip if Postgres is down."""
    url = _get_database_url()
    try:
        _try_connect(url)
    except Exception as exc:
        pytest.skip(
            f"Postgres not reachable at {url} — run `docker compose up -d` to enable DB tests: "
            f"{type(exc).__name__}: {exc}"
        )

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine(url, connect_args={"connect_timeout": 2})
    with Session(engine) as session:
        yield session
    engine.dispose()


class TestBuildTargetFingerprintWithDB:
    """DB-gated: verifies known_successes shape; skips when Docker is down."""

    def test_known_successes_is_list(self, db_session) -> None:
        fp = build_target_fingerprint("anthropic/claude-haiku-4-5", session=db_session)
        assert isinstance(fp.known_successes, list)

    def test_known_successes_items_are_strings(self, db_session) -> None:
        fp = build_target_fingerprint("anthropic/claude-haiku-4-5", session=db_session)
        for item in fp.known_successes:
            assert isinstance(item, str)

    def test_unknown_model_with_session_still_returns_fingerprint(self, db_session) -> None:
        fp = build_target_fingerprint("unknown-vendor/mystery-x", session=db_session)
        assert isinstance(fp, TargetFingerprint)
        assert fp.known_successes == []  # no ladder data for a non-existent target
