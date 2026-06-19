"""Tests for local pre-network validation helpers."""

from __future__ import annotations

import pytest

from rogue.exceptions import RogueConfigError, ValidationError
from rogue.utils.validation import (
    validate_api_key,
    validate_base_url,
    validate_deployment,
    validate_model_id,
)

# --- validate_api_key -----------------------------------------------------------------------------


def test_api_key_valid_stripped():
    assert validate_api_key("  sk-test  ") == "sk-test"


@pytest.mark.parametrize("bad", ["", "   ", None, 123, [], {}])
def test_api_key_rejects_bad(bad):
    with pytest.raises(RogueConfigError):
        validate_api_key(bad)


# --- validate_base_url ----------------------------------------------------------------------------


def test_base_url_valid_normalizes_trailing_slash():
    assert validate_base_url("https://api.example.com/") == "https://api.example.com"


def test_base_url_http_ok():
    assert validate_base_url("http://localhost:8000") == "http://localhost:8000"


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "ftp://example.com", "not-a-url", "https://", "//example.com", None, 42],
)
def test_base_url_rejects_bad(bad):
    with pytest.raises(RogueConfigError):
        validate_base_url(bad)


# --- validate_model_id ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model",
    ["gpt-5", "openai/gpt-5", "anthropic/claude-opus-4-8", "gpt-4.1", "model_v2", "ab"],
)
def test_model_id_valid(model):
    assert validate_model_id(model) == model


def test_model_id_strips():
    assert validate_model_id("  gpt-5  ") == "gpt-5"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        " ",
        "a",  # too short (<2)
        "/gpt-5",  # leading slash
        "openai//gpt-5",  # double slash
        "a/b/c",  # two prefixes
        "has space",
        "weird$char",
        None,
        123,
    ],
)
def test_model_id_rejects_bad(bad):
    with pytest.raises(ValidationError):
        validate_model_id(bad)


def test_model_id_too_long_rejected():
    with pytest.raises(ValidationError):
        validate_model_id("x" * 101)


def test_model_id_field_carried():
    with pytest.raises(ValidationError) as ei:
        validate_model_id("", field="model")
    assert ei.value.field == "model"


# --- validate_deployment --------------------------------------------------------------------------


def test_deployment_valid_no_raise():
    validate_deployment(name="Bot", model="gpt-5", system_prompt="sp", tools=["t"], forbidden_topics=["x"])


def test_deployment_aggregates_multiple_bad_fields():
    with pytest.raises(ValidationError) as ei:
        validate_deployment(name="", model="!!bad!!", tools="notalist")
    fields = set(ei.value.fields)
    assert {"name", "model", "tools"} <= fields


def test_deployment_missing_name():
    with pytest.raises(ValidationError) as ei:
        validate_deployment(name="", model="gpt-5")
    assert "name" in ei.value.fields


def test_deployment_name_too_long():
    with pytest.raises(ValidationError) as ei:
        validate_deployment(name="x" * 101, model="gpt-5")
    assert "name" in ei.value.fields


def test_deployment_bad_model():
    with pytest.raises(ValidationError) as ei:
        validate_deployment(name="Bot", model="")
    assert "model" in ei.value.fields


def test_deployment_system_prompt_must_be_str():
    with pytest.raises(ValidationError) as ei:
        validate_deployment(name="Bot", model="gpt-5", system_prompt=123)
    assert "system_prompt" in ei.value.fields


def test_deployment_system_prompt_too_long():
    with pytest.raises(ValidationError) as ei:
        validate_deployment(name="Bot", model="gpt-5", system_prompt="x" * 10_001)
    assert "system_prompt" in ei.value.fields


def test_deployment_tools_must_be_list_of_strings():
    with pytest.raises(ValidationError) as ei:
        validate_deployment(name="Bot", model="gpt-5", tools=[1, 2, 3])
    assert "tools" in ei.value.fields


def test_deployment_forbidden_topics_must_be_list_of_strings():
    with pytest.raises(ValidationError) as ei:
        validate_deployment(name="Bot", model="gpt-5", forbidden_topics="notalist")
    assert "forbidden_topics" in ei.value.fields


def test_deployment_none_optionals_ok():
    validate_deployment(name="Bot", model="gpt-5", system_prompt=None, tools=None, forbidden_topics=None)


def test_deployment_tuple_tools_ok():
    validate_deployment(name="Bot", model="gpt-5", tools=("a", "b"))
