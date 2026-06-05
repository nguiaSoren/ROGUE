"""Tests for the exception hierarchy and attribute contracts."""

from __future__ import annotations

from rogue.exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    RateLimitError,
    RogueConfigError,
    RogueError,
    ScanError,
    ScanFailedError,
    ScanTimeoutError,
    ValidationError,
)

# --- hierarchy ------------------------------------------------------------------------------------


def test_everything_derives_from_rogue_error():
    for exc in (
        RogueConfigError,
        ValidationError,
        APIError,
        AuthenticationError,
        AuthorizationError,
        NotFoundError,
        ConflictError,
        RateLimitError,
        APIConnectionError,
        ScanError,
        ScanFailedError,
        ScanTimeoutError,
    ):
        assert issubclass(exc, RogueError)


def test_api_subclasses_derive_from_api_error():
    for exc in (AuthenticationError, AuthorizationError, NotFoundError, ConflictError, RateLimitError):
        assert issubclass(exc, APIError)


def test_connection_error_not_api_error():
    # APIConnectionError is a transport reach failure, not an answered request
    assert not issubclass(APIConnectionError, APIError)
    assert issubclass(APIConnectionError, RogueError)


def test_scan_errors_derive_from_scan_error():
    assert issubclass(ScanFailedError, ScanError)
    assert issubclass(ScanTimeoutError, ScanError)


# --- ValidationError attributes -------------------------------------------------------------------


def test_validation_error_single_field():
    e = ValidationError("bad", field="model")
    assert e.field == "model"
    assert e.fields == ["model"]


def test_validation_error_multiple_fields():
    e = ValidationError("bad", fields=["a", "b"])
    assert e.fields == ["a", "b"]
    assert e.field is None


def test_validation_error_no_fields():
    e = ValidationError("bad")
    assert e.fields == []


# --- APIError attributes --------------------------------------------------------------------------


def test_api_error_attributes_default():
    e = APIError("oops")
    assert e.status_code is None
    assert e.code is None
    assert e.details == {}
    assert e.request_id is None


def test_api_error_attributes_set():
    e = APIError("oops", status_code=500, code="server_error", details={"k": "v"}, request_id="r1")
    assert e.status_code == 500
    assert e.code == "server_error"
    assert e.details == {"k": "v"}
    assert e.request_id == "r1"


def test_api_error_str_includes_code_and_status():
    e = APIError("failed", status_code=500, code="server_error")
    s = str(e)
    assert "failed" in s
    assert "server_error" in s
    assert "HTTP 500" in s


def test_api_error_str_bare_message():
    assert str(APIError("just a message")) == "just a message"


# --- RateLimitError -------------------------------------------------------------------------------


def test_rate_limit_retry_after():
    e = RateLimitError("slow down", retry_after=30.0, status_code=429, code="rate_limited")
    assert e.retry_after == 30.0
    assert e.status_code == 429
    assert e.code == "rate_limited"


def test_rate_limit_default_retry_after_none():
    assert RateLimitError("slow").retry_after is None


# --- Scan errors carry the scan ----------------------------------------------------------------


def test_scan_failed_carries_scan():
    sentinel = object()
    e = ScanFailedError("failed", scan=sentinel)
    assert e.scan is sentinel


def test_scan_timeout_carries_scan():
    sentinel = object()
    e = ScanTimeoutError("timed out", scan=sentinel)
    assert e.scan is sentinel


def test_scan_errors_default_scan_none():
    assert ScanFailedError("x").scan is None
    assert ScanTimeoutError("x").scan is None
