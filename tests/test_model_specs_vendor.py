"""Tests for the vendor/family extraction helpers in adapters.model_specs.

Covers every canonical target_model string ROGUE uses, plus the fail-safe paths
(unknown vendor, no-slash) and the groq-vs-meta-llama collapse to "llama".
"""

import pytest

from rogue.adapters.model_specs import extract_model_family, extract_vendor


@pytest.mark.parametrize(
    "target_model, expected_vendor",
    [
        ("anthropic/claude-haiku-4-5", "anthropic"),
        ("anthropic/claude-sonnet-4-6", "anthropic"),
        ("anthropic/claude-opus-4-8", "anthropic"),
        ("openai/gpt-5.4-nano", "openai"),
        ("openai/gpt-5.4", "openai"),
        ("openai/gpt-audio-mini", "openai"),
        ("google/gemini-3.1-flash-lite", "google"),
        ("meta-llama/llama-3.1-8b-instruct", "meta-llama"),
        ("mistralai/mistral-small-2603", "mistralai"),
        ("mistralai/voxtral-small-24b-2507", "mistralai"),
        ("groq/llama-3.1-8b-instant", "groq"),
    ],
)
def test_extract_vendor_known(target_model, expected_vendor):
    assert extract_vendor(target_model) == expected_vendor


@pytest.mark.parametrize(
    "target_model",
    [
        "cohere/command-r-plus",  # unknown vendor, has slash
        "deepseek/deepseek-chat",  # unknown vendor, has slash
        "gpt-5.4-nano",  # no slash at all
        "",  # empty
        "openrouter/anything",  # backend name is NOT a vendor
    ],
)
def test_extract_vendor_unknown(target_model):
    assert extract_vendor(target_model) == "unknown"


@pytest.mark.parametrize(
    "target_model, expected_family",
    [
        ("anthropic/claude-haiku-4-5", "claude"),
        ("anthropic/claude-sonnet-4-6", "claude"),
        ("anthropic/claude-opus-4-8", "claude"),
        ("openai/gpt-5.4-nano", "gpt"),
        ("openai/gpt-5.4", "gpt"),
        ("google/gemini-3.1-flash-lite", "gemini"),
        ("mistralai/mistral-small-2603", "mistral"),
        # both llama variants collapse to "llama" regardless of vendor
        ("meta-llama/llama-3.1-8b-instruct", "llama"),
        ("groq/llama-3.1-8b-instant", "llama"),
    ],
)
def test_extract_model_family_known(target_model, expected_family):
    assert extract_model_family(target_model) == expected_family


def test_groq_and_meta_llama_both_map_to_llama():
    """The headline cross-vendor case: distinct vendors, same family."""
    a = "groq/llama-3.1-8b-instant"
    b = "meta-llama/llama-3.1-8b-instruct"
    assert extract_vendor(a) != extract_vendor(b)  # groq vs meta-llama
    assert extract_model_family(a) == extract_model_family(b) == "llama"


@pytest.mark.parametrize(
    "target_model",
    [
        "openai/o3-mini",  # unknown family ("o3"), known vendor
        "mistralai/voxtral-small-24b-2507",  # voxtral is not a known family token
        "anthropic/claude-haiku-4-5",  # control handled elsewhere; not here
        "claude-haiku-4-5",  # no slash
        "",  # empty
    ],
)
def test_extract_model_family_unknown_or_noslash(target_model):
    fam = extract_model_family(target_model)
    if target_model == "anthropic/claude-haiku-4-5":
        assert fam == "claude"
    else:
        assert fam == "unknown"
