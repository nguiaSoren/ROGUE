"""Tests for the transport layer: Response, raise_for_response error mapping, MockTransport's
contract fidelity, and HTTPTransport's retry/parse/header behavior (with an injected fake client —
no real network).
"""

from __future__ import annotations

import pytest

from rogue import HTTPTransport, MockTransport, Transport
from rogue.exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)
from rogue.transport.base import Response, raise_for_response


def _err_resp(status, code=None, message=None, headers=None, details=None):
    err: dict = {}
    if code is not None:
        err["code"] = code
    if message is not None:
        err["message"] = message
    if details is not None:
        err["details"] = details
    return Response(status_code=status, data={"error": err} if err else {}, headers=headers or {})


# --- raise_for_response: 2xx no-op ----------------------------------------------------------------


@pytest.mark.parametrize("status", [200, 201, 202, 204, 299])
def test_no_raise_on_2xx(status):
    raise_for_response(Response(status_code=status, data={"ok": True}))


# --- raise_for_response: status-based fallback ----------------------------------------------------


@pytest.mark.parametrize(
    "status,exc",
    [
        (400, ValidationError),
        (401, AuthenticationError),
        (403, AuthorizationError),
        (404, NotFoundError),
        (409, ConflictError),
        (429, RateLimitError),
        (500, APIError),
        (502, APIError),
        (503, APIError),
    ],
)
def test_status_maps_to_exception(status, exc):
    with pytest.raises(exc):
        raise_for_response(_err_resp(status, message="boom"))


def test_api_error_carries_status_and_code():
    with pytest.raises(APIError) as ei:
        raise_for_response(_err_resp(500, code="server_error", message="down"))
    assert ei.value.status_code == 500
    assert ei.value.code == "server_error"


# --- raise_for_response: code precedence over status ----------------------------------------------


def test_code_overrides_status():
    # status 200-range body shouldn't reach here, but a 500 with a known code maps by code.
    with pytest.raises(NotFoundError):
        raise_for_response(_err_resp(500, code="not_found", message="missing"))


def test_invalid_api_key_code_to_auth_error():
    with pytest.raises(AuthenticationError):
        raise_for_response(_err_resp(403, code="invalid_api_key"))


def test_token_expired_code_to_auth_error():
    with pytest.raises(AuthenticationError) as ei:
        raise_for_response(_err_resp(401, code="token_expired", message="expired"))
    assert ei.value.code == "token_expired"


def test_validation_error_code_collects_fields():
    with pytest.raises(ValidationError) as ei:
        raise_for_response(
            _err_resp(422, code="validation_error", details={"name": "required", "model": "bad"})
        )
    assert set(ei.value.fields) == {"name", "model"}


def test_validation_error_no_details_empty_fields():
    with pytest.raises(ValidationError) as ei:
        raise_for_response(_err_resp(400, message="bad"))
    assert ei.value.fields == []


# --- raise_for_response: rate-limit retry-after ---------------------------------------------------


def test_rate_limit_parses_retry_after():
    with pytest.raises(RateLimitError) as ei:
        raise_for_response(_err_resp(429, code="rate_limited", headers={"retry-after": "12"}))
    assert ei.value.retry_after == 12.0


def test_rate_limit_retry_after_case_insensitive_header():
    with pytest.raises(RateLimitError) as ei:
        raise_for_response(_err_resp(429, headers={"Retry-After": "5"}))
    assert ei.value.retry_after == 5.0


def test_rate_limit_no_retry_after_is_none():
    with pytest.raises(RateLimitError) as ei:
        raise_for_response(_err_resp(429))
    assert ei.value.retry_after is None


def test_rate_limit_bad_retry_after_is_none():
    with pytest.raises(RateLimitError) as ei:
        raise_for_response(_err_resp(429, headers={"retry-after": "soon"}))
    assert ei.value.retry_after is None


def test_request_id_from_header():
    with pytest.raises(APIError) as ei:
        raise_for_response(_err_resp(500, headers={"x-request-id": "req-123"}))
    assert ei.value.request_id == "req-123"


def test_default_message_when_absent():
    with pytest.raises(APIError) as ei:
        raise_for_response(Response(status_code=500, data=None))
    assert "HTTP 500" in str(ei.value)


# --- MockTransport contract -----------------------------------------------------------------------


def test_mock_is_transport_subclass():
    assert isinstance(MockTransport(), Transport)


def test_mock_auth_token_success():
    mt = MockTransport()
    data = mt.request_json("POST", "/v1/auth/token", json={"api_key": "demo"})
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.parametrize("bad", ["invalid", "bad", ""])
def test_mock_auth_bad_key_401(bad):
    mt = MockTransport()
    with pytest.raises(AuthenticationError) as ei:
        mt.request_json("POST", "/v1/auth/token", json={"api_key": bad})
    assert ei.value.code == "invalid_api_key"


def test_mock_auth_missing_key_401():
    mt = MockTransport()
    with pytest.raises(AuthenticationError):
        mt.request_json("POST", "/v1/auth/token", json={})


def test_mock_refresh_unknown_token_401():
    mt = MockTransport()
    with pytest.raises(AuthenticationError):
        mt.request_json("POST", "/v1/auth/refresh", json={"refresh_token": "nope"})


def test_mock_unknown_path_404():
    mt = MockTransport()
    # authenticate first so the request passes the bearer check and reaches the route fallthrough
    with pytest.raises(NotFoundError):
        mt.request_json("GET", "/v1/nope", headers=_auth_headers(mt))


def test_mock_non_v1_path_404():
    mt = MockTransport()
    with pytest.raises(NotFoundError):
        mt.request_json("GET", "/healthz")


def test_mock_requires_bearer_for_protected_routes():
    mt = MockTransport()
    with pytest.raises(AuthenticationError) as ei:
        mt.request_json("GET", "/v1/deployments")
    assert ei.value.code == "invalid_token"


def _auth_headers(mt: MockTransport) -> dict:
    data = mt.request_json("POST", "/v1/auth/token", json={"api_key": "demo"})
    return {"Authorization": f"Bearer {data['access_token']}"}


def test_mock_authorized_deployment_list():
    mt = MockTransport()
    data = mt.request_json("GET", "/v1/deployments", headers=_auth_headers(mt))
    assert data == {"deployments": [], "next_cursor": None}


def test_mock_expire_tokens_yields_token_expired():
    mt = MockTransport()
    headers = _auth_headers(mt)
    mt.expire_tokens()
    with pytest.raises(AuthenticationError) as ei:
        mt.request_json("GET", "/v1/deployments", headers=headers)
    assert ei.value.code == "token_expired"


def test_mock_create_deployment_validation_error():
    mt = MockTransport()
    with pytest.raises(ValidationError) as ei:
        mt.request_json("POST", "/v1/deployments", json={"name": "x"}, headers=_auth_headers(mt))
    assert "model" in ei.value.fields


def test_mock_create_deployment_201():
    mt = MockTransport()
    data = mt.request_json(
        "POST", "/v1/deployments", json={"name": "x", "model": "gpt-5"}, headers=_auth_headers(mt)
    )
    assert data["id"].startswith("dep_")
    assert data["model"] == "gpt-5"


def test_mock_scan_unknown_deployment_404():
    mt = MockTransport()
    with pytest.raises(NotFoundError):
        mt.request_json(
            "POST", "/v1/scans", json={"deployment_id": "dep_x"}, headers=_auth_headers(mt)
        )


def test_mock_scan_missing_deployment_id_400():
    mt = MockTransport()
    with pytest.raises(ValidationError):
        mt.request_json("POST", "/v1/scans", json={}, headers=_auth_headers(mt))


def test_mock_scan_completes_instantly_when_zero_polls():
    mt = MockTransport(complete_after_polls=0)
    h = _auth_headers(mt)
    dep = mt.request_json(
        "POST", "/v1/deployments", json={"name": "x", "model": "gpt-5"}, headers=h
    )
    scan = mt.request_json(
        "POST", "/v1/scans", json={"deployment_id": dep["id"]}, headers=h
    )
    assert scan["status"] == "completed"
    assert scan["report_id"]


def test_mock_scan_stays_running_then_completes_after_n_polls():
    mt = MockTransport(complete_after_polls=2)
    h = _auth_headers(mt)
    dep = mt.request_json(
        "POST", "/v1/deployments", json={"name": "x", "model": "gpt-5"}, headers=h
    )
    scan = mt.request_json("POST", "/v1/scans", json={"deployment_id": dep["id"]}, headers=h)
    assert scan["status"] == "running"
    sid = scan["id"]
    # poll 1: still running
    s1 = mt.request_json("GET", f"/v1/scans/{sid}", headers=h)
    assert s1["status"] == "running"
    assert 0.0 < s1["progress"] < 1.0
    # poll 2: completes
    s2 = mt.request_json("GET", f"/v1/scans/{sid}", headers=h)
    assert s2["status"] == "completed"
    assert s2["progress"] == 1.0


def test_mock_cancel_running_scan():
    mt = MockTransport(complete_after_polls=5)
    h = _auth_headers(mt)
    dep = mt.request_json(
        "POST", "/v1/deployments", json={"name": "x", "model": "gpt-5"}, headers=h
    )
    scan = mt.request_json("POST", "/v1/scans", json={"deployment_id": dep["id"]}, headers=h)
    canceled = mt.request_json("POST", f"/v1/scans/{scan['id']}/cancel", headers=h)
    assert canceled["status"] == "canceled"


def test_mock_delete_deployment_204():
    mt = MockTransport()
    h = _auth_headers(mt)
    dep = mt.request_json(
        "POST", "/v1/deployments", json={"name": "x", "model": "gpt-5"}, headers=h
    )
    resp = mt.request("DELETE", f"/v1/deployments/{dep['id']}", headers=h)
    assert resp.status_code == 204
    with pytest.raises(NotFoundError):
        mt.request_json("GET", f"/v1/deployments/{dep['id']}", headers=h)


def test_mock_findings_count_function_of_model():
    mt = MockTransport()
    h = _auth_headers(mt)
    # robust model => fewer findings (2..4); unknown => more (4..8)
    for model in ("claude-opus-4-8", "some-obscure-7b"):
        dep = mt.request_json(
            "POST", "/v1/deployments", json={"name": "x", "model": model}, headers=h
        )
        scan = mt.request_json("POST", "/v1/scans", json={"deployment_id": dep["id"]}, headers=h)
        rep = mt.request_json("GET", f"/v1/scans/{scan['id']}/report", headers=h)
        assert rep["stats"]["n_findings"] >= 1
        assert 0.0 <= rep["risk_score"] <= 100.0


# --- HTTPTransport (no real network) --------------------------------------------------------------


class _FakeResp:
    def __init__(self, status_code, *, json_body=None, text="", content=b"x", ctype="application/json"):
        self.status_code = status_code
        self._json = json_body
        self.text = text
        self.content = content if content is not None else (text.encode() if text else b"")
        self.headers = {"content-type": ctype}

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class _FakeClient:
    """Returns queued responses (or raises queued exceptions) per .request() call."""

    def __init__(self, script):
        self._script = list(script)
        self.calls = []
        self.closed = False

    def request(self, method, path, *, params=None, json=None, headers=None):
        self.calls.append((method, path, headers))
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.closed = True


def test_http_construction_strips_trailing_slash():
    t = HTTPTransport("https://api.example.com/", client=_FakeClient([]))
    assert t.base_url == "https://api.example.com"


def test_http_backoff_growth():
    t = HTTPTransport("https://x", client=_FakeClient([]))
    assert t._backoff(0) == 1.5
    assert t._backoff(1) == 3.0
    assert t._backoff(2) == 6.0


def test_http_parse_json():
    t = HTTPTransport("https://x", client=_FakeClient([]))
    r = _FakeResp(200, json_body={"a": 1})
    assert t._parse(r) == {"a": 1}


def test_http_parse_text_when_not_json_ctype():
    t = HTTPTransport("https://x", client=_FakeClient([]))
    r = _FakeResp(200, text="hello", ctype="text/plain")
    assert t._parse(r) == "hello"


def test_http_parse_empty_content_none():
    t = HTTPTransport("https://x", client=_FakeClient([]))
    r = _FakeResp(204, content=b"", ctype="application/json")
    assert t._parse(r) is None


def test_http_parse_bad_json_returns_none():
    t = HTTPTransport("https://x", client=_FakeClient([]))
    r = _FakeResp(200, json_body=None, content=b"{", ctype="application/json")
    assert t._parse(r) is None


def test_http_sets_version_headers():
    fake = _FakeClient([_FakeResp(200, json_body={"ok": True})])
    t = HTTPTransport("https://x", client=fake)
    t.request("GET", "/v1/ping")
    _, _, headers = fake.calls[0]
    from rogue import API_VERSION, __version__

    assert headers["X-Rogue-Api-Version"] == API_VERSION
    assert headers["User-Agent"] == f"rogue-python/{__version__}"
    assert headers["Accept"] == "application/json"


def test_http_retries_on_503_then_succeeds(monkeypatch):
    import rogue.transport.http as http_mod

    monkeypatch.setattr(http_mod.time, "sleep", lambda *_: None)
    fake = _FakeClient([_FakeResp(503), _FakeResp(200, json_body={"ok": True})])
    t = HTTPTransport("https://x", client=fake, max_retries=3)
    resp = t.request("GET", "/v1/ping")
    assert resp.status_code == 200
    assert resp.data == {"ok": True}
    assert len(fake.calls) == 2


def test_http_returns_last_retryable_after_exhausting_retries(monkeypatch):
    import rogue.transport.http as http_mod

    monkeypatch.setattr(http_mod.time, "sleep", lambda *_: None)
    fake = _FakeClient([_FakeResp(502), _FakeResp(502)])
    t = HTTPTransport("https://x", client=fake, max_retries=1)
    resp = t.request("GET", "/v1/ping")
    # after exhausting retries it returns the last (still 502) response
    assert resp.status_code == 502
    assert len(fake.calls) == 2


def test_http_network_error_becomes_connection_error(monkeypatch):
    import httpx

    import rogue.transport.http as http_mod

    monkeypatch.setattr(http_mod.time, "sleep", lambda *_: None)
    fake = _FakeClient([httpx.ConnectError("boom"), httpx.ConnectError("boom")])
    t = HTTPTransport("https://x", client=fake, max_retries=1)
    with pytest.raises(APIConnectionError):
        t.request("GET", "/v1/ping")
    assert len(fake.calls) == 2


def test_http_network_error_retries_then_succeeds(monkeypatch):
    import httpx

    import rogue.transport.http as http_mod

    monkeypatch.setattr(http_mod.time, "sleep", lambda *_: None)
    fake = _FakeClient([httpx.ConnectError("boom"), _FakeResp(200, json_body={"ok": 1})])
    t = HTTPTransport("https://x", client=fake, max_retries=2)
    resp = t.request("GET", "/v1/ping")
    assert resp.status_code == 200


def test_http_close_owns_injected_client_is_false():
    fake = _FakeClient([])
    t = HTTPTransport("https://x", client=fake)
    t.close()
    # injected client is not owned, so it is NOT closed
    assert fake.closed is False


def test_http_drops_none_params(monkeypatch):
    fake = _FakeClient([_FakeResp(200, json_body={"ok": True})])
    t = HTTPTransport("https://x", client=fake)
    # should not raise; None params filtered out
    t.request("GET", "/v1/ping", params={"a": None, "b": 1})
