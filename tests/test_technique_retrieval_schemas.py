"""Round-trip tests for TechniqueProfile and TargetFingerprint.

Verifies:
- Importable from rogue.schemas (the public surface).
- Construct with minimal fields; defaults are correct.
- Construct with all fields; values survive a round-trip through model_dump /
  model_validate.
- model_dump() / model_validate() are inverse operations.

No DB required.
"""

from __future__ import annotations

import pytest

from rogue.schemas import TargetFingerprint, TechniqueProfile


# ---------------------------------------------------------------------------
# TechniqueProfile
# ---------------------------------------------------------------------------


class TestTechniqueProfileMinimal:
    """Construct with only the required (non-defaulted) fields."""

    def test_construct(self):
        tp = TechniqueProfile(label="crescendo", name="Crescendo", family="multi_turn")
        assert tp.label == "crescendo"
        assert tp.name == "Crescendo"
        assert tp.family == "multi_turn"

    def test_defaults(self):
        tp = TechniqueProfile(label="crescendo", name="Crescendo", family="multi_turn")
        assert tp.technique_id == ""
        assert tp.description == ""
        assert tp.principle == ""
        assert tp.steps == []
        assert tp.modalities == []
        assert tp.historical_targets == []
        assert tp.origin == "arms"
        assert tp.tier == ""

    def test_mutable_defaults_are_independent(self):
        tp1 = TechniqueProfile(label="a", name="A", family="f")
        tp2 = TechniqueProfile(label="b", name="B", family="f")
        tp1.steps.append("step1")
        assert tp2.steps == [], "mutable defaults must not be shared between instances"

    def test_round_trip(self):
        tp = TechniqueProfile(label="crescendo", name="Crescendo", family="multi_turn")
        dumped = tp.model_dump()
        restored = TechniqueProfile.model_validate(dumped)
        assert restored == tp


class TestTechniqueProfileFull:
    """Construct with all fields set and verify round-trip."""

    @pytest.fixture()
    def full_profile(self) -> TechniqueProfile:
        return TechniqueProfile(
            label="image:mml:wr",
            technique_id="01HXYZ1234567890ABCDEF",
            name="Multi-Modal Word Render",
            family="renderer_tier",
            description="Renders the harmful text as an image to bypass text filters.",
            principle="Vision models parse images that text classifiers never see.",
            steps=["Compose prompt text", "Render to image", "Send as vision input"],
            modalities=["image"],
            historical_targets=["anthropic/haiku", "openai/gpt-4o"],
            origin="tier",
            tier="image",
        )

    def test_all_fields_set(self, full_profile: TechniqueProfile):
        assert full_profile.label == "image:mml:wr"
        assert full_profile.technique_id == "01HXYZ1234567890ABCDEF"
        assert full_profile.name == "Multi-Modal Word Render"
        assert full_profile.family == "renderer_tier"
        assert full_profile.description == "Renders the harmful text as an image to bypass text filters."
        assert full_profile.principle == "Vision models parse images that text classifiers never see."
        assert full_profile.steps == [
            "Compose prompt text",
            "Render to image",
            "Send as vision input",
        ]
        assert full_profile.modalities == ["image"]
        assert full_profile.historical_targets == ["anthropic/haiku", "openai/gpt-4o"]
        assert full_profile.origin == "tier"
        assert full_profile.tier == "image"

    def test_round_trip(self, full_profile: TechniqueProfile):
        dumped = full_profile.model_dump()
        restored = TechniqueProfile.model_validate(dumped)
        assert restored == full_profile

    def test_model_dump_keys(self, full_profile: TechniqueProfile):
        keys = set(full_profile.model_dump().keys())
        expected = {
            "label",
            "technique_id",
            "name",
            "family",
            "description",
            "principle",
            "steps",
            "modalities",
            "historical_targets",
            "origin",
            "tier",
        }
        assert keys == expected

    def test_harvested_origin(self):
        tp = TechniqueProfile(label="h1", name="Harvested One", family="harvested_method", origin="harvested")
        assert tp.origin == "harvested"

    def test_free_string_family(self):
        """family accepts any string — not bound to the AttackFamily enum."""
        for family_str in ("arms_pattern", "renderer_tier", "harvested_method", "custom_xyz"):
            tp = TechniqueProfile(label="x", name="X", family=family_str)
            assert tp.family == family_str


# ---------------------------------------------------------------------------
# TargetFingerprint
# ---------------------------------------------------------------------------


class TestTargetFingerprintMinimal:
    """Construct with only the required fields."""

    def test_construct(self):
        tf = TargetFingerprint(
            target_key="anthropic/claude-haiku-4-5",
            vendor="anthropic",
            model_family="claude-haiku",
        )
        assert tf.target_key == "anthropic/claude-haiku-4-5"
        assert tf.vendor == "anthropic"
        assert tf.model_family == "claude-haiku"

    def test_defaults(self):
        tf = TargetFingerprint(
            target_key="openai/gpt-4o",
            vendor="openai",
            model_family="gpt-4o",
        )
        assert tf.supports_images is False
        assert tf.supports_audio is False
        assert tf.context_length is None
        assert tf.reasoning_model is False
        assert tf.known_successes == []

    def test_mutable_defaults_are_independent(self):
        tf1 = TargetFingerprint(target_key="a", vendor="v", model_family="f")
        tf2 = TargetFingerprint(target_key="b", vendor="v", model_family="f")
        tf1.known_successes.append("technique-x")
        assert tf2.known_successes == [], "mutable defaults must not be shared between instances"

    def test_round_trip(self):
        tf = TargetFingerprint(
            target_key="anthropic/claude-haiku-4-5",
            vendor="anthropic",
            model_family="claude-haiku",
        )
        dumped = tf.model_dump()
        restored = TargetFingerprint.model_validate(dumped)
        assert restored == tf


class TestTargetFingerprintFull:
    """Construct with all fields set and verify round-trip."""

    @pytest.fixture()
    def full_fingerprint(self) -> TargetFingerprint:
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

    def test_all_fields_set(self, full_fingerprint: TargetFingerprint):
        assert full_fingerprint.target_key == "openai/gpt-4o"
        assert full_fingerprint.vendor == "openai"
        assert full_fingerprint.model_family == "gpt-4o"
        assert full_fingerprint.supports_images is True
        assert full_fingerprint.supports_audio is True
        assert full_fingerprint.context_length == 128_000
        assert full_fingerprint.reasoning_model is False
        assert full_fingerprint.known_successes == ["crescendo", "image:mml:wr"]

    def test_round_trip(self, full_fingerprint: TargetFingerprint):
        dumped = full_fingerprint.model_dump()
        restored = TargetFingerprint.model_validate(dumped)
        assert restored == full_fingerprint

    def test_model_dump_keys(self, full_fingerprint: TargetFingerprint):
        keys = set(full_fingerprint.model_dump().keys())
        expected = {
            "target_key",
            "vendor",
            "model_family",
            "supports_images",
            "supports_audio",
            "context_length",
            "reasoning_model",
            "known_successes",
        }
        assert keys == expected

    def test_context_length_none(self):
        tf = TargetFingerprint(
            target_key="x/y",
            vendor="x",
            model_family="y",
            context_length=None,
        )
        assert tf.context_length is None

    def test_reasoning_model_flag(self):
        tf = TargetFingerprint(
            target_key="openai/o3",
            vendor="openai",
            model_family="o3",
            reasoning_model=True,
        )
        assert tf.reasoning_model is True


# ---------------------------------------------------------------------------
# Public import surface
# ---------------------------------------------------------------------------


class TestPublicImport:
    """Both types must be importable directly from rogue.schemas."""

    def test_technique_profile_importable(self):
        from rogue.schemas import TechniqueProfile as TP  # noqa: PLC0415
        assert TP is TechniqueProfile

    def test_target_fingerprint_importable(self):
        from rogue.schemas import TargetFingerprint as TF  # noqa: PLC0415
        assert TF is TargetFingerprint

    def test_in_all(self):
        import rogue.schemas as s  # noqa: PLC0415
        assert "TechniqueProfile" in s.__all__
        assert "TargetFingerprint" in s.__all__
