"""Shared fixtures for the ROGUE SDK core test suite.

Every fixture here keeps tests hermetic and offline: a sandboxed config dir, cleared ``ROGUE_*``
env vars, and a ``MockTransport``-backed :class:`Rogue` so nothing touches the network or the real
home directory.
"""

from __future__ import annotations

import pytest

from rogue import Deployment, MockTransport, Rogue

_ROGUE_ENV_VARS = (
    "ROGUE_API_KEY",
    "ROGUE_BASE_URL",
    "ROGUE_TELEMETRY",
    "ROGUE_TELEMETRY_ENDPOINT",
    "DO_NOT_TRACK",
    "ROGUE_DO_NOT_TRACK",
)


@pytest.fixture(autouse=True)
def _sandbox(monkeypatch, tmp_path):
    """Sandbox ``ROGUE_CONFIG_DIR`` to a tmp dir and clear ROGUE_* env vars for isolation."""
    monkeypatch.setenv("ROGUE_CONFIG_DIR", str(tmp_path))
    for name in _ROGUE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    yield


@pytest.fixture
def mock() -> MockTransport:
    """A fresh in-memory transport (scans complete instantly)."""
    return MockTransport()


@pytest.fixture
def client(mock: MockTransport) -> Rogue:
    """A Rogue client backed by the shared mock transport."""
    return Rogue(api_key="demo", transport=mock)


@pytest.fixture
def registered_deployment(client: Rogue) -> Deployment:
    """A deployment already registered against the mock backend."""
    return client.register(name="Support Bot", model="gpt-5", system_prompt="You are helpful.")
