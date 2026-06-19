"""Tests for the Rogue client: construction/auth resolution, deployment CRUD, scan lifecycle
(sync + async), report retrieval, provider registration, and transparent token refresh.

All against MockTransport — no network, poll_interval=0 to avoid real sleeps.
"""

from __future__ import annotations

import pytest

from rogue import (
    Deployment,
    MockTransport,
    Report,
    Rogue,
    Scan,
    ScanStatus,
    __version__,
)
from rogue.exceptions import (
    AuthenticationError,
    RogueConfigError,
    ScanFailedError,
    ScanTimeoutError,
    ValidationError,
)

# --- construction ---------------------------------------------------------------------------------


def test_mock_transport_defaults_api_key_demo():
    r = Rogue(transport=MockTransport())
    assert r._auth.api_key == "demo"


def test_versions():
    r = Rogue(transport=MockTransport())
    assert r.api_version == "v1"
    assert r.sdk_version == __version__


def test_base_url_from_transport():
    r = Rogue(transport=MockTransport())
    # MockTransport has no base_url attribute
    assert r.base_url is None


def test_real_transport_requires_api_key():
    with pytest.raises(RogueConfigError):
        Rogue(api_key=None, base_url="https://api.example.com")


def test_real_transport_validates_base_url():
    with pytest.raises(RogueConfigError):
        Rogue(api_key="k", base_url="not-a-url")


def test_real_transport_constructs_with_key_and_url():
    r = Rogue(api_key="k", base_url="https://api.example.com/")
    assert r.base_url == "https://api.example.com"


def test_api_key_from_env(monkeypatch):
    monkeypatch.setenv("ROGUE_API_KEY", "env-key")
    r = Rogue(transport=MockTransport())
    assert r._auth.api_key == "env-key"


def test_context_manager_closes():
    mt = MockTransport()
    with Rogue(transport=mt) as r:
        assert r is not None


# --- auth -----------------------------------------------------------------------------------------


def test_login_sets_authenticated(client):
    assert not client.is_authenticated
    client.login()
    assert client.is_authenticated


def test_logout_clears_tokens(client):
    client.login()
    client.logout()
    assert not client.is_authenticated


def test_lazy_login_on_first_request(client):
    # no explicit login; a deployment call authenticates lazily
    client.register(name="x", model="gpt-5")
    assert client.is_authenticated


def test_bad_api_key_raises_on_use():
    r = Rogue(api_key="invalid", transport=MockTransport())
    with pytest.raises(AuthenticationError):
        r.login()


def test_transparent_refresh_on_token_expiry(client, mock):
    # authenticate, then expire the issued tokens; the next request should refresh transparently
    client.login()
    mock.expire_tokens()
    dep = client.register(name="x", model="gpt-5")
    assert dep.is_registered


# --- deployments ----------------------------------------------------------------------------------


def test_register_returns_registered_deployment(client):
    dep = client.register(name="Bot", model="gpt-5", system_prompt="sp")
    assert isinstance(dep, Deployment)
    assert dep.is_registered
    assert dep.name == "Bot"
    assert dep.model == "gpt-5"


def test_register_local_validation_aggregates(client):
    with pytest.raises(ValidationError) as ei:
        client.register(name="", model="")
    assert "name" in ei.value.fields
    assert "model" in ei.value.fields


def test_register_with_prebuilt_deployment(client):
    dep = Deployment(name="Bot", model="anthropic/claude-opus-4-8", tools=["search"])
    out = client.register(deployment=dep)
    assert out.is_registered
    assert out.tools == ["search"]


def test_register_prebuilt_still_validated(client):
    bad = Deployment(name="", model="x")
    with pytest.raises(ValidationError):
        client.register(deployment=bad)


def test_get_deployment(client, registered_deployment):
    fetched = client.deployments.get(registered_deployment.id)
    assert fetched.id == registered_deployment.id


def test_get_missing_deployment_404(client):
    from rogue.exceptions import NotFoundError

    client.login()
    with pytest.raises(NotFoundError):
        client.deployments.get("dep_does_not_exist")


def test_list_deployments(client):
    client.register(name="A", model="gpt-5")
    client.register(name="B", model="gpt-4")
    deps = client.deployments.list()
    assert len(deps) == 2
    assert all(isinstance(d, Deployment) for d in deps)


def test_update_deployment_field(client, registered_deployment):
    updated = client.update(registered_deployment, system_prompt="new prompt")
    assert updated.system_prompt == "new prompt"


def test_update_by_id(client, registered_deployment):
    updated = client.update(registered_deployment.id, name="Renamed")
    assert updated.name == "Renamed"


def test_update_unregistered_raises(client):
    dep = Deployment(name="x", model="gpt-5")  # no id
    with pytest.raises(ValidationError):
        client.update(dep, name="y")


def test_update_no_changes_sends_current_payload(client, registered_deployment):
    registered_deployment.name = "Mutated"
    updated = client.update(registered_deployment)
    assert updated.name == "Mutated"


def test_update_by_id_no_changes_raises(client, registered_deployment):
    with pytest.raises(ValidationError):
        client.update(registered_deployment.id)


def test_delete_deployment(client, registered_deployment):
    from rogue.exceptions import NotFoundError

    client.deployments.delete(registered_deployment)
    with pytest.raises(NotFoundError):
        client.deployments.get(registered_deployment.id)


def test_delete_unregistered_raises(client):
    dep = Deployment(name="x", model="gpt-5")
    with pytest.raises(ValidationError):
        client.deployments.delete(dep)


# --- scan (sync) ----------------------------------------------------------------------------------


def test_scan_blocking_returns_report(client, registered_deployment):
    report = client.scan(registered_deployment, poll_interval=0)
    assert isinstance(report, Report)
    assert report.deployment_id == registered_deployment.id
    assert report.stats.n_findings >= 1


def test_scan_by_deployment_id(client, registered_deployment):
    report = client.scan(deployment_id=registered_deployment.id, poll_interval=0)
    assert isinstance(report, Report)


def test_scan_unregistered_deployment_raises(client):
    dep = Deployment(name="x", model="gpt-5")
    with pytest.raises(ValidationError):
        client.scan(dep, poll_interval=0)


def test_scan_no_target_raises(client):
    with pytest.raises(ValidationError):
        client.scan(poll_interval=0)


def test_scan_with_polling(registered_deployment):
    # client wired to a transport that needs 2 polls
    mt = MockTransport(complete_after_polls=2)
    r = Rogue(transport=mt)
    dep = r.register(name="Bot", model="gpt-5")
    report = r.scan(dep, poll_interval=0)
    assert isinstance(report, Report)


# --- scan (async) ---------------------------------------------------------------------------------


def test_scan_async_returns_scan_handle(client, registered_deployment):
    job = client.scan_async(registered_deployment)
    assert isinstance(job, Scan)
    assert job.deployment_id == registered_deployment.id


def test_scan_async_instant_completion(client, registered_deployment):
    job = client.scan_async(registered_deployment)
    # complete_after_polls=0 => already completed on creation
    assert job.status == ScanStatus.COMPLETED
    assert job.done


def test_scan_handle_report(client, registered_deployment):
    job = client.scan_async(registered_deployment)
    report = job.report()
    assert isinstance(report, Report)


def test_scan_wait_then_report_with_polling():
    mt = MockTransport(complete_after_polls=2)
    r = Rogue(transport=mt)
    dep = r.register(name="Bot", model="gpt-5")
    job = r.scan_async(dep)
    assert job.status == ScanStatus.RUNNING
    job.wait(poll_interval=0)
    assert job.succeeded
    assert isinstance(job.report(), Report)


def test_scan_refresh_updates_in_place():
    mt = MockTransport(complete_after_polls=1)
    r = Rogue(transport=mt)
    dep = r.register(name="Bot", model="gpt-5")
    job = r.scan_async(dep)
    assert job.status == ScanStatus.RUNNING
    job.refresh()
    assert job.status == ScanStatus.COMPLETED


def test_scan_wait_timeout_raises():
    # never completes within budget; timeout immediately
    mt = MockTransport(complete_after_polls=999)
    r = Rogue(transport=mt)
    dep = r.register(name="Bot", model="gpt-5")
    job = r.scan_async(dep)
    with pytest.raises(ScanTimeoutError) as ei:
        job.wait(timeout=0.0, poll_interval=0)
    assert ei.value.scan is job


def test_scan_cancel():
    mt = MockTransport(complete_after_polls=999)
    r = Rogue(transport=mt)
    dep = r.register(name="Bot", model="gpt-5")
    job = r.scan_async(dep)
    job.cancel()
    assert job.status == ScanStatus.CANCELED


def test_scans_list(client, registered_deployment):
    client.scan_async(registered_deployment)
    client.scan_async(registered_deployment)
    scans = client.scans.list()
    assert len(scans) == 2


def test_scans_list_filtered_by_deployment(client, registered_deployment):
    other = client.register(name="Other", model="gpt-4")
    client.scan_async(registered_deployment)
    client.scan_async(other)
    only = client.scans.list(deployment_id=registered_deployment.id)
    assert len(only) == 1
    assert only[0].deployment_id == registered_deployment.id


def test_scan_failed_raises_scan_failed_error(client, registered_deployment, monkeypatch):
    # simulate a failed terminal state by patching the scan refresh path
    job = client.scan_async(registered_deployment)
    # force a failed state and re-run wait's terminal check
    from rogue.models.common import ScanStatus as SS

    object.__setattr__(job, "status", SS.FAILED)
    object.__setattr__(job, "error", "boom")
    with pytest.raises(ScanFailedError) as ei:
        job.wait(poll_interval=0)
    assert "boom" in str(ei.value)


# --- providers ------------------------------------------------------------------------------------


def test_register_provider_generic(client):
    rec = client.register_provider("openai", api_key="sk-test")
    assert rec["provider"] == "openai"
    assert "_credentials" not in rec  # secrets never returned


def test_register_openai_helper(client):
    rec = client.register_openai("sk-test", label="prod")
    assert rec["provider"] == "openai"
    assert rec["label"] == "prod"


def test_register_anthropic_helper(client):
    rec = client.register_anthropic("sk-ant")
    assert rec["provider"] == "anthropic"


def test_register_vertex_helper(client):
    rec = client.register_vertex(project="my-proj", location="us-central1")
    assert rec["provider"] == "vertex"


def test_register_vertex_missing_fields_raises(client):
    with pytest.raises(ValidationError):
        client.register_provider("vertex")


def test_register_custom_helper(client):
    rec = client.register_custom(base_url="https://my-endpoint")
    assert rec["provider"] == "custom"


def test_providers_list(client):
    client.register_openai("sk-test")
    provs = client.providers()
    assert any(p["provider"] == "openai" for p in provs)
    assert all("_credentials" not in p for p in provs)
