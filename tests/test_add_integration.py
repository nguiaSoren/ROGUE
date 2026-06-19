"""Offline tests for the `add_integration` registration core — in-memory store, no real/prod DB.

Drives the testable core directly against `InMemoryIntegrationStore`, verifying the per-kind shaping
contract: a Slack integration stores the webhook as its secret; a Jira integration round-trips its
non-secret config (base_url / project / email) alongside the token secret; and `store.list(org)`
surfaces only {kind, name} — never secrets.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from rogue.platform.integration_store import InMemoryIntegrationStore

# Load the script by path (scripts/ is not an importable package).
_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ops" / "add_integration.py"
_spec = importlib.util.spec_from_file_location("add_integration", _SCRIPT)
add_integration_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(add_integration_mod)
add_integration = add_integration_mod.add_integration


def test_slack_stores_webhook_as_secret():
    store = InMemoryIntegrationStore()
    iid = add_integration(store, org_id="o1", kind="slack", name="slack-sec", config={}, secret="https://hooks/x")

    assert iid  # an integration id is returned
    resolved = store.get("o1", "slack-sec")
    assert resolved is not None
    assert resolved.kind == "slack"
    assert resolved.name == "slack-sec"
    assert resolved.secret == "https://hooks/x"
    assert resolved.config == {}


def test_jira_round_trips_config_and_token():
    store = InMemoryIntegrationStore()
    config = {"base_url": "https://acme.atlassian.net", "project_key": "SEC", "email": "ops@acme.com"}
    add_integration(store, org_id="o1", kind="jira", name="jira-prod", config=config, secret="tok-123")

    resolved = store.get("o1", "jira-prod")
    assert resolved is not None
    assert resolved.kind == "jira"
    assert resolved.config == config
    assert resolved.secret == "tok-123"


def test_list_shows_names_without_secrets():
    store = InMemoryIntegrationStore()
    add_integration(store, org_id="o1", kind="slack", name="slack-sec", config={}, secret="https://hooks/x")
    add_integration(
        store,
        org_id="o1",
        kind="jira",
        name="jira-prod",
        config={"base_url": "https://acme.atlassian.net", "project_key": "SEC", "email": "ops@acme.com"},
        secret="tok-123",
    )

    listed = store.list("o1")
    assert {(e["kind"], e["name"]) for e in listed} == {("slack", "slack-sec"), ("jira", "jira-prod")}
    # No secret leaks through the listing surface.
    for entry in listed:
        assert set(entry.keys()) == {"kind", "name"}
    blob = repr(listed)
    assert "https://hooks/x" not in blob
    assert "tok-123" not in blob


def test_other_org_does_not_see_integration():
    store = InMemoryIntegrationStore()
    add_integration(store, org_id="o1", kind="slack", name="slack-sec", config={}, secret="https://hooks/x")

    assert store.get("o2", "slack-sec") is None
    assert store.list("o2") == []
