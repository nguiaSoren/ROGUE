"""Offline QA for the public, DB-free ``POST /api/public-scan`` endpoint.

Everything here is offline — no network, no DB, no real LLM/target calls. Two layers:

* **SSRF guard** (:func:`rogue.api._ssrf.validate_public_endpoint`): a public literal IP passes; every
  blocked category (loopback / private / link-local incl. 169.254.169.254 / IPv6 ::1 / IPv6-mapped
  metadata) rejects; a non-http(s) scheme rejects; a hostname is resolved and ALL records must pass.
* **Route** (``TestClient`` mounting just the router on a bare app, mirroring
  tests/integrations/slack/test_inbound.py): input validation (422), the happy path with
  ``scan_endpoint`` + ``render_breach_card`` monkeypatched (200 with base64 + summary), the
  keyless↔calibrated-v3 ``judge`` flip, an SSRF block (400), and the concurrency cap (429).

The two external seams we control: ``scan_endpoint`` (the money-spending scan) and ``render_breach_card``
(the Pillow/SVG render) are patched to fakes, and ``getaddrinfo`` is patched for hostname SSRF cases so
the suite never touches DNS or the network.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import rogue.api.public_scan as ps
from rogue.api._ssrf import SsrfBlocked, validate_public_endpoint


# ------------------------------------------------------------------------------------------------ #
# Fakes
# ------------------------------------------------------------------------------------------------ #


@dataclass
class _FakeFinding:
    family: str
    breached: bool


@dataclass
class _FakeReport:
    """Stands in for EndpointScanReport — only the fields the route reads."""

    n_primitives: int = 6
    n_breached: int = 2
    findings: list = field(default_factory=list)

    @property
    def breach_rate(self) -> float:
        return self.n_breached / self.n_primitives if self.n_primitives else 0.0


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(ps.router)
    if ps._limiter is not None:
        # Mount the limiter's state so the SlowAPI-decorated route can find it, then disable it so the
        # per-IP cap (5/hour) doesn't bleed across tests sharing the TestClient IP. The cap itself is
        # covered by the dedicated 429 concurrency test + the limiter's own suite.
        app.state.limiter = ps._limiter
        ps._limiter.enabled = False
    return app


@pytest.fixture(autouse=True)
def _disable_rate_limit():
    """Keep the per-IP rate limiter off for the route tests (re-enabled state isn't shared)."""
    if ps._limiter is not None:
        ps._limiter.enabled = False
    yield


@pytest.fixture
def patched(monkeypatch):
    """Patch the scan + render seams and the SSRF resolver so the route runs fully offline.

    Returns a dict whose ``calls`` captures the kwargs scan_endpoint was invoked with (so a test can
    assert the judge object / caps / DB-free flags) and ``card`` captures the card dict rendered.
    """
    captured: dict = {"calls": [], "card": None}

    async def fake_scan_endpoint(base_url, model, primitives, **kwargs):
        captured["calls"].append(
            {
                "base_url": base_url,
                "model": model,
                "n_primitives": len(primitives),
                "kwargs": kwargs,
            }
        )
        report = _FakeReport(
            n_primitives=len(primitives),
            n_breached=1,
            findings=[_FakeFinding("dan_persona", True), _FakeFinding("obfuscation_encoding", False)],
        )
        return report

    def fake_render(card, out_dir):
        captured["card"] = card
        svg = out_dir / "breach-card.svg"
        png = out_dir / "breach-card.png"
        svg.write_text("<svg>breach</svg>", encoding="utf-8")
        png.write_bytes(b"\x89PNG\r\n_fake_png_bytes")
        return {"svg": svg, "png": png, "html": out_dir / "breach-card.html"}

    # The route imports these lazily from their home modules; patch at the source.
    monkeypatch.setattr("rogue.reproduce.endpoint_scan.scan_endpoint", fake_scan_endpoint)
    monkeypatch.setattr("rogue.report_card.render_breach_card", fake_render)
    # Make any hostname resolve to a public IP so the SSRF gate passes on the happy path.
    monkeypatch.setattr(
        "rogue.api._ssrf.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))],
    )
    return captured


# ------------------------------------------------------------------------------------------------ #
# SSRF guard
# ------------------------------------------------------------------------------------------------ #


def test_ssrf_allows_public_literal_ip():
    assert validate_public_endpoint("https://8.8.8.8/v1") == "https://8.8.8.8/v1"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/v1",
        "http://10.0.0.1/v1",
        "http://172.16.0.1/v1",
        "http://192.168.1.1/v1",
        "http://169.254.169.254/latest/meta-data",  # cloud metadata
        "http://100.100.100.200/",  # alibaba metadata (carrier-grade NAT space)
        "http://[::1]/v1",  # IPv6 loopback
        "http://[fe80::1]/v1",  # IPv6 link-local
        "http://[::ffff:169.254.169.254]/",  # IPv4-mapped IPv6 metadata bypass
        "http://0.0.0.0/v1",  # unspecified
        "http://224.0.0.1/v1",  # multicast
    ],
)
def test_ssrf_blocks_non_public_literals(url):
    with pytest.raises(SsrfBlocked):
        validate_public_endpoint(url)


@pytest.mark.parametrize("url", ["ftp://example.com/", "file:///etc/passwd", "gopher://x/", "//noscheme"])
def test_ssrf_blocks_bad_scheme(url):
    with pytest.raises(SsrfBlocked):
        validate_public_endpoint(url)


def test_ssrf_localhost_hostname_blocked():
    # 'localhost' resolves to loopback via getaddrinfo — must reject.
    with pytest.raises(SsrfBlocked):
        validate_public_endpoint("http://localhost:8000/v1")


def test_ssrf_hostname_resolving_to_private_blocked(monkeypatch):
    monkeypatch.setattr(
        "rogue.api._ssrf.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("10.1.2.3", 443))],
    )
    with pytest.raises(SsrfBlocked):
        validate_public_endpoint("https://evil.example.com/v1")


def test_ssrf_hostname_one_private_record_blocked(monkeypatch):
    # A host with BOTH a public and a private record must be rejected (all records checked).
    monkeypatch.setattr(
        "rogue.api._ssrf.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("203.0.113.5", 443)), (2, 1, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(SsrfBlocked):
        validate_public_endpoint("https://mixed.example.com/v1")


def test_ssrf_unresolvable_host_blocked(monkeypatch):
    import socket as _socket

    def _boom(*a, **k):
        raise _socket.gaierror("nope")

    monkeypatch.setattr("rogue.api._ssrf.socket.getaddrinfo", _boom)
    with pytest.raises(SsrfBlocked):
        validate_public_endpoint("https://nx.example.com/v1")


# ------------------------------------------------------------------------------------------------ #
# Route — validation
# ------------------------------------------------------------------------------------------------ #


@pytest.mark.parametrize(
    "body",
    [
        {"model": "m", "api_key": "k"},  # missing endpoint
        {"endpoint": "https://x.example/v1", "api_key": "k"},  # missing model
        {"endpoint": "https://x.example/v1", "model": "m"},  # missing api_key
        {"endpoint": "https://x.example/v1", "model": "m", "api_key": ""},  # empty api_key
    ],
)
def test_validation_422(body):
    client = TestClient(_make_app())
    resp = client.post("/api/public-scan", json=body)
    assert resp.status_code == 422


def test_ssrf_block_returns_400(patched):
    client = TestClient(_make_app())
    resp = client.post(
        "/api/public-scan",
        json={"endpoint": "http://127.0.0.1/v1", "model": "m", "api_key": "secret-key"},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "public address" in detail
    assert "secret-key" not in detail  # key never echoed


def test_bad_pack_returns_400(patched):
    client = TestClient(_make_app())
    resp = client.post(
        "/api/public-scan",
        json={"endpoint": "https://x.example/v1", "model": "m", "api_key": "k", "pack": "nonsense"},
    )
    assert resp.status_code == 400


# ------------------------------------------------------------------------------------------------ #
# Route — happy path + judge selection
# ------------------------------------------------------------------------------------------------ #


def test_happy_path_keyless(patched):
    client = TestClient(_make_app())
    resp = client.post(
        "/api/public-scan",
        json={"endpoint": "https://api.example.com/v1", "model": "gpt-x", "api_key": "sk-target"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # base64 PNG round-trips to the fake bytes; SVG text passed through.
    assert base64.b64decode(data["card_png_base64"]) == b"\x89PNG\r\n_fake_png_bytes"
    assert data["card_svg"] == "<svg>breach</svg>"

    summ = data["summary"]
    assert summ["model_label"] == "gpt-x"
    assert summ["judge"] == "keyless"
    assert summ["trials"] == 6  # default pack capped to 6 primitives
    assert summ["breached"] == 1
    assert summ["rate"] == pytest.approx(1 / 6)

    # The scan was invoked DB-free, with the caps and a HeuristicJudge.
    from rogue.reproduce.heuristic_judge import HeuristicJudge

    call = patched["calls"][0]
    assert call["model"] == "gpt-x"
    assert call["n_primitives"] <= ps.MAX_PRIMITIVES
    assert call["kwargs"]["persist"] is False
    assert call["kwargs"]["database_url"] is None
    assert call["kwargs"]["n_trials"] <= ps.MAX_TRIALS
    assert call["kwargs"]["api_key"] == "sk-target"
    assert isinstance(call["kwargs"]["judge"], HeuristicJudge)

    # The card tier reflects the keyless judge.
    assert patched["card"]["tier"] == "quick"


def test_happy_path_calibrated_v3_flips_judge(patched, monkeypatch):
    # Avoid constructing a real provider client: stub the calibrated-judge builder to a sentinel.
    sentinel = object()
    monkeypatch.setattr(ps, "_build_calibrated_judge", lambda key, model: sentinel)

    client = TestClient(_make_app())
    resp = client.post(
        "/api/public-scan",
        json={
            "endpoint": "https://api.example.com/v1",
            "model": "gpt-x",
            "api_key": "sk-target",
            "judge_key": "sk-judge",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["summary"]["judge"] == "calibrated-v3"

    call = patched["calls"][0]
    assert call["kwargs"]["judge"] is sentinel  # the calibrated judge was wired in
    assert patched["card"]["tier"] == "calibrated"


def test_aggressive_pack_still_capped(patched):
    client = TestClient(_make_app())
    resp = client.post(
        "/api/public-scan",
        json={
            "endpoint": "https://api.example.com/v1",
            "model": "m",
            "api_key": "k",
            "pack": "aggressive",
        },
    )
    assert resp.status_code == 200, resp.text
    assert patched["calls"][0]["n_primitives"] <= ps.MAX_PRIMITIVES
    assert patched["calls"][0]["kwargs"]["n_trials"] <= ps.MAX_TRIALS


# ------------------------------------------------------------------------------------------------ #
# Route — error mapping + concurrency
# ------------------------------------------------------------------------------------------------ #


def test_target_unreachable_returns_502(patched, monkeypatch):
    async def boom(*a, **k):
        raise ConnectionError("refused")

    monkeypatch.setattr("rogue.reproduce.endpoint_scan.scan_endpoint", boom)
    client = TestClient(_make_app())
    resp = client.post(
        "/api/public-scan",
        json={"endpoint": "https://api.example.com/v1", "model": "m", "api_key": "k"},
    )
    assert resp.status_code == 502
    assert "k" not in resp.json()["detail"] or "unreachable" in resp.json()["detail"]


def test_concurrency_cap_returns_429(patched, monkeypatch):
    # Drain the semaphore so the route's acquire times out → 429. Restore after.
    sem = asyncio.Semaphore(0)
    monkeypatch.setattr(ps, "_semaphore", sem)
    client = TestClient(_make_app())
    resp = client.post(
        "/api/public-scan",
        json={"endpoint": "https://api.example.com/v1", "model": "m", "api_key": "k"},
    )
    assert resp.status_code == 429
