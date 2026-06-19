"""Tests for provider adapters and the adapter registry."""

from __future__ import annotations

import pytest

from rogue.adapters import (
    AnthropicAdapter,
    CustomAdapter,
    OpenAIAdapter,
    VertexAdapter,
    get_adapter,
    registered_providers,
)
from rogue.exceptions import ValidationError

# --- registry -------------------------------------------------------------------------------------


def test_registered_providers_includes_builtins():
    provs = registered_providers()
    assert {"openai", "anthropic", "vertex", "custom"} <= set(provs)


def test_registered_providers_sorted():
    provs = registered_providers()
    assert provs == sorted(provs)


def test_get_adapter_returns_registered():
    assert isinstance(get_adapter("openai"), OpenAIAdapter)
    assert isinstance(get_adapter("anthropic"), AnthropicAdapter)
    assert isinstance(get_adapter("vertex"), VertexAdapter)
    assert isinstance(get_adapter("custom"), CustomAdapter)


def test_get_adapter_unknown_returns_generic_requiring_api_key():
    adapter = get_adapter("mystery")
    assert adapter.provider == "mystery"
    # generic requires api_key
    with pytest.raises(ValidationError):
        adapter.to_payload()
    payload = adapter.to_payload(api_key="k")
    assert payload["provider"] == "mystery"


# --- to_payload shape -----------------------------------------------------------------------------


def test_openai_to_payload_shape():
    payload = get_adapter("openai").to_payload(label="x", api_key="sk-test")
    assert payload == {
        "provider": "openai",
        "label": "x",
        "credentials": {"api_key": "sk-test"},
    }


def test_to_payload_default_label():
    payload = get_adapter("openai").to_payload(api_key="sk-test")
    assert payload["label"] == "default"


def test_openai_optional_fields_allowed():
    payload = get_adapter("openai").to_payload(api_key="k", organization="org", base_url="https://x")
    assert payload["credentials"]["organization"] == "org"
    assert payload["credentials"]["base_url"] == "https://x"


def test_anthropic_to_payload_shape():
    payload = get_adapter("anthropic").to_payload(api_key="sk-ant")
    assert payload["provider"] == "anthropic"
    assert payload["credentials"] == {"api_key": "sk-ant"}


# --- required-field enforcement -------------------------------------------------------------------


def test_openai_missing_api_key_raises():
    with pytest.raises(ValidationError) as ei:
        get_adapter("openai").to_payload()
    assert "api_key" in ei.value.fields


def test_vertex_requires_project_and_location():
    with pytest.raises(ValidationError) as ei:
        get_adapter("vertex").to_payload()
    assert "project" in ei.value.fields
    assert "location" in ei.value.fields


def test_vertex_partial_missing_location():
    with pytest.raises(ValidationError) as ei:
        get_adapter("vertex").to_payload(project="p")
    assert "location" in ei.value.fields
    assert "project" not in ei.value.fields


def test_vertex_valid_payload():
    payload = get_adapter("vertex").to_payload(project="p", location="us-central1")
    assert payload["credentials"] == {"project": "p", "location": "us-central1"}


def test_vertex_optional_credentials_json():
    payload = get_adapter("vertex").to_payload(
        project="p", location="loc", credentials_json="{...}"
    )
    assert payload["credentials"]["credentials_json"] == "{...}"


def test_custom_requires_base_url():
    with pytest.raises(ValidationError) as ei:
        get_adapter("custom").to_payload()
    assert "base_url" in ei.value.fields


def test_custom_valid_with_optional_api_key():
    payload = get_adapter("custom").to_payload(base_url="https://x", api_key="k")
    assert payload["credentials"]["base_url"] == "https://x"
    assert payload["credentials"]["api_key"] == "k"


# --- unknown-field rejection ----------------------------------------------------------------------


def test_unknown_credential_field_rejected():
    with pytest.raises(ValidationError) as ei:
        get_adapter("openai").to_payload(api_key="k", bogus="nope")
    assert "bogus" in ei.value.fields


def test_anthropic_unknown_field_rejected():
    with pytest.raises(ValidationError):
        get_adapter("anthropic").to_payload(api_key="k", project="x")


# --- normalize_model ------------------------------------------------------------------------------


def test_openai_normalize_strips_prefix():
    assert OpenAIAdapter().normalize_model("openai/gpt-5") == "gpt-5"
    assert OpenAIAdapter().normalize_model("gpt-5") == "gpt-5"


def test_anthropic_normalize_strips_prefix():
    assert AnthropicAdapter().normalize_model("anthropic/claude-opus-4-8") == "claude-opus-4-8"
    assert AnthropicAdapter().normalize_model("claude-opus-4-8") == "claude-opus-4-8"


def test_vertex_normalize_strips_prefix():
    assert VertexAdapter().normalize_model("vertex/gemini-2") == "gemini-2"
    assert VertexAdapter().normalize_model("gemini-2") == "gemini-2"


def test_normalize_does_not_strip_foreign_prefix():
    # OpenAI adapter only strips "openai/" prefixes
    assert OpenAIAdapter().normalize_model("anthropic/claude") == "anthropic/claude"


# --- None values dropped --------------------------------------------------------------------------


def test_none_credentials_dropped():
    payload = get_adapter("openai").to_payload(api_key="k", organization=None)
    assert "organization" not in payload["credentials"]
