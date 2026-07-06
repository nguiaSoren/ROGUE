"""Per-config scheduler prior — the SIZE scope. A config borrows strategy order from configs of its
size × context reach (the axis the many-shot / long-context papers tie to ASR). Correlational prior,
validated by measurement."""

from __future__ import annotations

from rogue.reproduce.config_features import ConfigFeatures, derive_config_features
from rogue.reproduce.ladder_priors import (
    BLEND_W_FAMILY,
    BLEND_W_GLOBAL,
    BLEND_W_SIZE,
    BLEND_W_VENDOR,
    VendorFamilyStat,
)


def test_blend_weights_still_sum_to_one():
    assert abs(BLEND_W_GLOBAL + BLEND_W_VENDOR + BLEND_W_FAMILY + BLEND_W_SIZE - 1.0) < 1e-9
    assert BLEND_W_SIZE > 0


def test_size_class_derivation():
    assert derive_config_features("qwen/qwen-2.5-72b-instruct").size_class == "large"
    assert derive_config_features("openai/gpt-5.4-nano").size_class == "small"
    assert derive_config_features("anthropic/claude-opus-4-8").size_class == "large"
    # sibling_key groups on size × context reach
    assert isinstance(derive_config_features("openai/gpt-4o-mini").sibling_key, str)


def test_features_are_comparable_for_pooling():
    a = derive_config_features("qwen/qwen-2.5-72b-instruct")
    b = derive_config_features("meta-llama/llama-3.1-70b-instruct")
    assert isinstance(a, ConfigFeatures)
    assert a.size_class == b.size_class == "large"  # two large models pool together


def test_size_scope_promotes_same_size_winner():
    # A: weak globally, strong against same-size siblings. B: the reverse.
    a = VendorFamilyStat("A", 1, 20, 0, 0, 0, 0, size_breaches=9, size_trials=10)
    b = VendorFamilyStat("B", 1, 20, 0, 0, 0, 0, size_breaches=0, size_trials=10)
    assert a.blend_score() > b.blend_score()  # size evidence lifts A above B


def test_size_scope_cold_start_is_neutral():
    # Unseen size cell (0/0) → size_rate 0.5, so it neither helps nor hurts vs a size-less baseline.
    seen = VendorFamilyStat("x", 2, 10, 0, 0, 0, 0, size_breaches=0, size_trials=0)
    assert abs(seen.size_rate - 0.5) < 1e-9


def test_new_config_inherits_sibling_order():
    """A brand-new large config (no own history) orders strategies by what beat OTHER large configs."""
    # strat_fast: great vs large siblings; strat_slow: poor vs large siblings; both unseen globally
    fast = VendorFamilyStat("fast", 0, 0, 0, 0, 0, 0, size_breaches=8, size_trials=10)
    slow = VendorFamilyStat("slow", 0, 0, 0, 0, 0, 0, size_breaches=1, size_trials=10)
    assert fast.blend_score() > slow.blend_score()
