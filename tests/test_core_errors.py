"""Unit tests for :mod:`rogue.core.errors` — the canonical adapter error hierarchy."""

from __future__ import annotations

import pytest

from rogue.core.errors import (
    AdapterError,
    AuthenticationError,
    ContentPolicyError,
    ProviderError,
    RateLimitError,
    TimeoutError,
    ValidationError,
    from_http_status,
    is_retryable,
)


# ---- hierarchy + retryable flags ---------------------------------------------------------------


def test_all_subclass_adapter_error():
    for cls in (
        AuthenticationError,
        RateLimitError,
        TimeoutError,
        ProviderError,
        ValidationError,
        ContentPolicyError,
    ):
        assert issubclass(cls, AdapterError)


def test_content_policy_is_provider_error_subclass():
    assert issubclass(ContentPolicyError, ProviderError)


def test_base_default_not_retryable():
    assert AdapterError.retryable is False


@pytest.mark.parametrize(
    "cls, expected",
    [
        (AuthenticationError, False),
        (RateLimitError, True),
        (TimeoutError, True),
        (ProviderError, True),
        (ValidationError, False),
        (ContentPolicyError, False),
    ],
)
def test_class_retryable_flags(cls, expected):
    assert cls.retryable is expected
    assert cls("msg").retryable is expected


def test_content_policy_overrides_parent_retryable():
    # ProviderError is retryable; its ContentPolicyError child is not.
    assert ProviderError("x").retryable is True
    assert ContentPolicyError("x").retryable is False


# ---- constructor fields ------------------------------------------------------------------------


def test_constructor_stores_fields():
    e = AdapterError(
        "boom",
        provider="mock",
        status_code=500,
        retry_after=2.5,
        raw={"k": "v"},
    )
    assert e.message == "boom"
    assert e.provider == "mock"
    assert e.status_code == 500
    assert e.retry_after == 2.5
    assert e.raw == {"k": "v"}
    assert str(e).startswith("boom")


def test_retryable_override_true():
    e = AuthenticationError("x", retryable=True)
    assert e.retryable is True


def test_retryable_override_false():
    e = RateLimitError("x", retryable=False)
    assert e.retryable is False


def test_retryable_none_uses_class_default():
    e = RateLimitError("x", retryable=None)
    assert e.retryable is True


# ---- from_http_status mapping ------------------------------------------------------------------


@pytest.mark.parametrize(
    "code, cls",
    [
        (401, AuthenticationError),
        (403, AuthenticationError),
        (408, TimeoutError),
        (429, RateLimitError),
        (400, ValidationError),
        (500, ProviderError),
        (502, ProviderError),
        (503, ProviderError),
        (599, ProviderError),
        (418, ProviderError),  # other → ProviderError
        (404, ProviderError),
    ],
)
def test_from_http_status_mapping(code, cls):
    e = from_http_status(code)
    assert type(e) is cls
    assert e.status_code == code


def test_from_http_status_429_sets_retry_after():
    e = from_http_status(429, retry_after=12.0)
    assert isinstance(e, RateLimitError)
    assert e.retry_after == 12.0


def test_from_http_status_passes_provider_and_raw():
    e = from_http_status(500, provider="openai", raw={"err": "x"})
    assert e.provider == "openai"
    assert e.raw == {"err": "x"}


def test_from_http_status_default_message():
    e = from_http_status(503)
    assert "503" in e.message


def test_from_http_status_custom_message():
    e = from_http_status(503, message="custom")
    assert e.message == "custom"


# ---- is_retryable ------------------------------------------------------------------------------


def test_is_retryable_on_retryable_adapter_error():
    assert is_retryable(RateLimitError("x")) is True
    assert is_retryable(TimeoutError("x")) is True
    assert is_retryable(ProviderError("x")) is True


def test_is_retryable_on_non_retryable_adapter_error():
    assert is_retryable(AuthenticationError("x")) is False
    assert is_retryable(ValidationError("x")) is False
    assert is_retryable(ContentPolicyError("x")) is False


def test_is_retryable_on_builtin_exception():
    assert is_retryable(ValueError("not an adapter error")) is False
    assert is_retryable(RuntimeError("x")) is False


def test_is_retryable_respects_instance_override():
    assert is_retryable(AuthenticationError("x", retryable=True)) is True
    assert is_retryable(RateLimitError("x", retryable=False)) is False
