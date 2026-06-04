"""TargetPanel ⇄ adapter migration (Week 2): routing, error projection, ModelResponse mapping.

After the migration the panel keeps its public contract (``run_attack`` → ``list[ModelResponse]``,
``ModelResponse``, ``supports_image``/``supports_audio``) but dispatches through the adapter registry.
These tests pin: (a) the prefix→provider routing, (b) the high-fidelity path end-to-end via a real
``AsyncOpenAI`` over a mocked httpx transport injected through the panel's ``adapter_extra`` seam, and
(c) the exact legacy error tags the panel projects from typed ``AdapterError``s. No network.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from rogue.core.errors import (
    AuthenticationError,
    ContentPolicyError,
    ProviderError,
    RateLimitError,
)
from rogue.reproduce.instantiator import RenderedAttack
from rogue.reproduce.target_panel import ModelResponse, TargetPanel, _resolve_provider
from rogue.schemas import demo_deployment_configs


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    """Make tenacity's async retry backoff instant (it sleeps via asyncio.sleep)."""

    async def _instant(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", _instant)


def _rendered() -> RenderedAttack:
    return RenderedAttack(
        messages=[{"role": "user", "content": "hi"}],
        is_multi_turn=False,
        resolved_slots={},
        primitive_id="prim_panel_test",
        deployment_config_id="dc_test",
    )


def _config(target_model: str = "openai/gpt-5.4-nano"):
    return next(c for c in demo_deployment_configs() if c.target_model == target_model)


_CHAT_OK = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "created": 1,
    "model": "gpt-5.4-nano",
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "all good"}, "finish_reason": "stop"}
    ],
    "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
}


def _openai_client_returning(*responses: httpx.Response):
    """A real AsyncOpenAI whose HTTP layer replays the given responses in order over MockTransport."""
    from openai import AsyncOpenAI

    seq = list(responses)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        i = min(calls["n"], len(seq) - 1)
        calls["n"] += 1
        return seq[i]

    client = AsyncOpenAI(
        base_url="https://api.openai.com/v1",
        api_key="test-key",
        max_retries=0,  # disable the SDK's own retry; the adapter's tenacity layer is the only one
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return client, calls


# --- routing --------------------------------------------------------------------------------------


def test_resolve_provider_routes():
    assert _resolve_provider("openai/gpt-5.4-nano") == "openai"
    assert _resolve_provider("anthropic/claude-haiku-4-5") == "anthropic"
    assert _resolve_provider("mistralai/mistral-small-2603") == "openrouter"
    assert _resolve_provider("google/gemini-3.1-flash-lite") == "openrouter"
    assert _resolve_provider("meta-llama/llama-3.1-8b-instruct") == "openrouter"
    assert _resolve_provider("groq/llama-3.1-8b-instant") == "groq"


def test_resolve_provider_unrouted_raises():
    with pytest.raises(NotImplementedError):
        _resolve_provider("unknownvendor/some-model")


# --- high-fidelity success path (real AsyncOpenAI + mocked transport, through the panel) ----------


@pytest.mark.asyncio
async def test_dispatch_one_success_maps_invocation_to_model_response():
    client, _ = _openai_client_returning(httpx.Response(200, json=_CHAT_OK))
    panel = TargetPanel(adapter_extra={"client": client})
    try:
        result = await panel._dispatch_one(_rendered(), _config(), trial_index=0, temperature=0.7)
    finally:
        await panel.aclose()

    assert isinstance(result, ModelResponse)
    assert result.error is None
    assert result.content == "all good"
    assert result.tokens_in == 7
    assert result.tokens_out == 3
    assert result.cost_usd > 0  # priced via model_specs
    assert result.trial_index == 0


@pytest.mark.asyncio
async def test_dispatch_one_retries_503_then_succeeds():
    client, calls = _openai_client_returning(
        httpx.Response(503, json={"error": {"message": "busy"}}),
        httpx.Response(200, json=_CHAT_OK),
    )
    panel = TargetPanel(adapter_extra={"client": client})
    try:
        result = await panel._dispatch_one(_rendered(), _config(), trial_index=0, temperature=0.7)
    finally:
        await panel.aclose()
    assert result.error is None and result.content == "all good"
    assert calls["n"] == 2  # one retried 503 + one 200


@pytest.mark.asyncio
async def test_dispatch_one_content_policy_block_to_model_response():
    client, calls = _openai_client_returning(
        httpx.Response(400, json={"error": {"message": "blocked by safety", "code": "content_filter"}})
    )
    panel = TargetPanel(adapter_extra={"client": client})
    try:
        result = await panel._dispatch_one(_rendered(), _config(), trial_index=0, temperature=0.7)
    finally:
        await panel.aclose()
    assert result.error is not None
    assert result.error.startswith("content_policy_or_bad_request")
    assert result.content == ""
    assert calls["n"] == 1  # 400 is deterministic — not retried


@pytest.mark.asyncio
async def test_dispatch_one_exhausted_rate_limit_to_model_response():
    client, calls = _openai_client_returning(
        httpx.Response(429, json={"error": {"message": "rate limited"}}),
    )
    panel = TargetPanel(adapter_extra={"client": client})
    try:
        result = await panel._dispatch_one(_rendered(), _config(), trial_index=0, temperature=0.7)
    finally:
        await panel.aclose()
    assert result.error is not None
    assert result.error.startswith("rate_limit_exhausted")
    assert calls["n"] == 3  # initial + 2 retries (stop_after_attempt(3))


# --- error projection from typed AdapterErrors (panel's except-clause mapping) --------------------


class _RaisingAdapter:
    """A stand-in adapter whose invoke raises a chosen AdapterError — exercises the panel's mapping."""

    def __init__(self, exc):
        self._exc = exc

    async def invoke(self, *a, **k):
        raise self._exc

    async def aclose(self):
        return None


@pytest.mark.parametrize(
    "exc, expected_prefix",
    [
        (RateLimitError("slow down", status_code=429), "rate_limit_exhausted"),
        (ContentPolicyError("nope", status_code=400), "content_policy_or_bad_request"),
        (ProviderError("upstream 500", status_code=503), "http_status_503"),
        (AuthenticationError("bad key", status_code=401), "http_status_401"),
    ],
)
@pytest.mark.asyncio
async def test_dispatch_one_projects_adapter_errors_to_legacy_tags(monkeypatch, exc, expected_prefix):
    panel = TargetPanel()
    monkeypatch.setattr(
        panel, "_adapter_for", lambda provider, model_id, base_url=None: _RaisingAdapter(exc)
    )
    result = await panel._dispatch_one(_rendered(), _config(), trial_index=2, temperature=0.9)
    assert isinstance(result, ModelResponse)
    assert result.error is not None
    assert result.error.startswith(expected_prefix)
    assert result.content == ""
    assert result.trial_index == 2  # trial bookkeeping preserved on the error path


@pytest.mark.asyncio
async def test_run_attack_orders_trials_and_caches_one_adapter(monkeypatch):
    """run_attack fans out N trials (sorted by trial_index) through a single cached adapter."""
    client, _ = _openai_client_returning(httpx.Response(200, json=_CHAT_OK))
    panel = TargetPanel(adapter_extra={"client": client})
    try:
        responses = await panel.run_attack(_rendered(), _config(), temperature=0.7, n_trials=3)
    finally:
        await panel.aclose()
    assert [r.trial_index for r in responses] == [0, 1, 2]
    assert all(r.content == "all good" for r in responses)
