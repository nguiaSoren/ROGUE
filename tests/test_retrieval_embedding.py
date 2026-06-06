"""Tests for the embedding infrastructure (Engineer 3 / E3).

Covers:
- build_technique_embedding_text: non-empty, deterministic, contains key fields.
- build_target_embedding_text: non-empty, deterministic, contains key fields.
- deterministic_embed_fn: correct dimension, unit-norm, same→identical, diff→different,
  cosine(self)≈1.
- default_embed_fn: importable without OPENAI_API_KEY (lazy construction); not called.

No DB, no network, no paid API calls.
"""

from __future__ import annotations

import math
from typing import Callable

import pytest

from rogue.retrieval.embed import EmbedFn, default_embed_fn, deterministic_embed_fn
from rogue.retrieval.embedding_text import (
    build_target_embedding_text,
    build_technique_embedding_text,
)
from rogue.schemas import TargetFingerprint, TechniqueProfile

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DIM = 1536


@pytest.fixture()
def minimal_profile() -> TechniqueProfile:
    return TechniqueProfile(
        label="crescendo",
        name="Crescendo",
        family="crescendo",
    )


@pytest.fixture()
def full_profile() -> TechniqueProfile:
    return TechniqueProfile(
        label="image:mml:wr",
        technique_id="01HZ1234567890ABCDEFGHIJKL",
        name="Multi-modal word-replacement",
        family="renderer_tier",
        description="Encodes sensitive tokens as image OCR targets.",
        principle="Vision encoders leak information across the safety boundary.",
        steps=["Render target tokens as images.", "Attach images in user turn.", "Collect model completion."],
        modalities=["image", "text"],
        historical_targets=["anthropic/haiku", "openai/gpt-4o"],
        origin="tier",
        tier="image",
    )


@pytest.fixture()
def minimal_fingerprint() -> TargetFingerprint:
    return TargetFingerprint(
        target_key="anthropic/claude-haiku-4-5",
        vendor="anthropic",
        model_family="claude-haiku",
    )


@pytest.fixture()
def full_fingerprint() -> TargetFingerprint:
    return TargetFingerprint(
        target_key="openai/gpt-4o",
        vendor="openai",
        model_family="gpt-4o",
        supports_images=True,
        supports_audio=True,
        context_length=128_000,
        reasoning_model=False,
        known_successes=["crescendo", "image:mml:wr"],
    )


# ---------------------------------------------------------------------------
# build_technique_embedding_text
# ---------------------------------------------------------------------------


class TestBuildTechniqueEmbeddingText:
    def test_returns_nonempty_string(self, minimal_profile: TechniqueProfile) -> None:
        text = build_technique_embedding_text(minimal_profile)
        assert isinstance(text, str)
        assert len(text) > 0

    def test_contains_name(self, full_profile: TechniqueProfile) -> None:
        text = build_technique_embedding_text(full_profile)
        assert full_profile.name in text

    def test_contains_family(self, full_profile: TechniqueProfile) -> None:
        text = build_technique_embedding_text(full_profile)
        assert full_profile.family in text

    def test_contains_principle(self, full_profile: TechniqueProfile) -> None:
        text = build_technique_embedding_text(full_profile)
        assert full_profile.principle in text

    def test_contains_steps(self, full_profile: TechniqueProfile) -> None:
        text = build_technique_embedding_text(full_profile)
        for step in full_profile.steps:
            assert step in text

    def test_contains_modalities(self, full_profile: TechniqueProfile) -> None:
        text = build_technique_embedding_text(full_profile)
        for modality in full_profile.modalities:
            assert modality in text

    def test_contains_historical_targets(self, full_profile: TechniqueProfile) -> None:
        text = build_technique_embedding_text(full_profile)
        for target in full_profile.historical_targets:
            assert target in text

    def test_deterministic(self, full_profile: TechniqueProfile) -> None:
        text1 = build_technique_embedding_text(full_profile)
        text2 = build_technique_embedding_text(full_profile)
        assert text1 == text2

    def test_minimal_profile_nonempty(self, minimal_profile: TechniqueProfile) -> None:
        text = build_technique_embedding_text(minimal_profile)
        assert minimal_profile.name in text
        assert minimal_profile.family in text
        assert minimal_profile.label in text


# ---------------------------------------------------------------------------
# build_target_embedding_text
# ---------------------------------------------------------------------------


class TestBuildTargetEmbeddingText:
    def test_returns_nonempty_string(self, minimal_fingerprint: TargetFingerprint) -> None:
        text = build_target_embedding_text(minimal_fingerprint)
        assert isinstance(text, str)
        assert len(text) > 0

    def test_contains_vendor(self, full_fingerprint: TargetFingerprint) -> None:
        text = build_target_embedding_text(full_fingerprint)
        assert full_fingerprint.vendor in text

    def test_contains_model_family(self, full_fingerprint: TargetFingerprint) -> None:
        text = build_target_embedding_text(full_fingerprint)
        assert full_fingerprint.model_family in text

    def test_contains_target_key(self, full_fingerprint: TargetFingerprint) -> None:
        text = build_target_embedding_text(full_fingerprint)
        assert full_fingerprint.target_key in text

    def test_image_modality_present_when_supported(self, full_fingerprint: TargetFingerprint) -> None:
        text = build_target_embedding_text(full_fingerprint)
        assert "image" in text

    def test_audio_modality_present_when_supported(self, full_fingerprint: TargetFingerprint) -> None:
        text = build_target_embedding_text(full_fingerprint)
        assert "audio" in text

    def test_context_length_present(self, full_fingerprint: TargetFingerprint) -> None:
        text = build_target_embedding_text(full_fingerprint)
        assert "128000" in text

    def test_known_successes_present(self, full_fingerprint: TargetFingerprint) -> None:
        text = build_target_embedding_text(full_fingerprint)
        for label in full_fingerprint.known_successes:
            assert label in text

    def test_deterministic(self, full_fingerprint: TargetFingerprint) -> None:
        text1 = build_target_embedding_text(full_fingerprint)
        text2 = build_target_embedding_text(full_fingerprint)
        assert text1 == text2

    def test_minimal_fingerprint_nonempty(self, minimal_fingerprint: TargetFingerprint) -> None:
        text = build_target_embedding_text(minimal_fingerprint)
        assert minimal_fingerprint.vendor in text
        assert minimal_fingerprint.model_family in text


# ---------------------------------------------------------------------------
# deterministic_embed_fn
# ---------------------------------------------------------------------------


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


class TestDeterministicEmbedFn:
    @pytest.fixture(autouse=True)
    def fn(self) -> Callable[[str], list[float]]:
        self._fn = deterministic_embed_fn(dim=DIM)
        return self._fn

    def test_returns_list_of_floats(self) -> None:
        vec = self._fn("hello world")
        assert isinstance(vec, list)
        assert all(isinstance(x, float) for x in vec)

    def test_correct_dimension(self) -> None:
        vec = self._fn("hello world")
        assert len(vec) == DIM

    def test_unit_norm(self) -> None:
        vec = self._fn("a sample technique description")
        magnitude = math.sqrt(sum(x * x for x in vec))
        assert abs(magnitude - 1.0) < 1e-6, f"magnitude={magnitude} not ≈ 1"

    def test_cosine_self_approx_one(self) -> None:
        vec = self._fn("deterministic embedding test")
        cos = _cosine(vec, vec)
        assert abs(cos - 1.0) < 1e-6

    def test_same_text_identical_vector(self) -> None:
        text = "crescendo attack technique family escalation"
        vec1 = self._fn(text)
        vec2 = self._fn(text)
        assert vec1 == vec2

    def test_different_text_different_vector(self) -> None:
        vec_a = self._fn("technique: crescendo")
        vec_b = self._fn("technique: jailbreak via role play")
        # Vectors should differ — collision is astronomically unlikely.
        assert vec_a != vec_b

    def test_custom_dimension(self) -> None:
        fn_small = deterministic_embed_fn(dim=64)
        vec = fn_small("short dim test")
        assert len(vec) == 64
        magnitude = math.sqrt(sum(x * x for x in vec))
        assert abs(magnitude - 1.0) < 1e-6

    def test_empty_string_returns_unit_vector(self) -> None:
        vec = self._fn("")
        assert len(vec) == DIM
        magnitude = math.sqrt(sum(x * x for x in vec))
        assert abs(magnitude - 1.0) < 1e-6

    def test_cross_process_determinism(self) -> None:
        """Same text → same vector via two independent fn instances."""
        fn2 = deterministic_embed_fn(dim=DIM)
        text = "cross-process determinism check"
        assert self._fn(text) == fn2(text)


# ---------------------------------------------------------------------------
# default_embed_fn — importability only; do NOT call it
# ---------------------------------------------------------------------------


class TestDefaultEmbedFn:
    def test_importable_without_api_key(self) -> None:
        """Importing and calling default_embed_fn() must not raise — lazy client."""
        import os

        # Temporarily remove the key to verify no eager construction.
        saved = os.environ.pop("OPENAI_API_KEY", None)
        try:
            fn = default_embed_fn()
            # The callable is constructed; the client is NOT built yet.
            assert callable(fn)
        finally:
            if saved is not None:
                os.environ["OPENAI_API_KEY"] = saved

    def test_returns_callable(self) -> None:
        fn = default_embed_fn()
        assert callable(fn)

    def test_custom_model_accepted(self) -> None:
        fn = default_embed_fn(model="text-embedding-3-large")
        assert callable(fn)

    def test_embed_fn_type_alias_is_callable(self) -> None:
        # EmbedFn is a type alias — verify it's accessible from the module.
        assert EmbedFn is not None
