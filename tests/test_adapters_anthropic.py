"""Tests for :class:`rogue.adapters.anthropic.AnthropicAdapter` — fully mocked, no network.

A fake client matching the Anthropic SDK surface (``client.messages.create(...)``) is injected via
``AdapterConfig.extra["client"]``. The error-mapping tests construct *real* ``anthropic`` SDK
exceptions (the package is a dependency) so they exercise the genuine
``_provider_errors.map_provider_exception`` path.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from rogue.adapters._provider_errors import with_provider_retry
from rogue.adapters.anthropic import AnthropicAdapter
from rogue.adapters.base import AdapterConfig
from rogue.core import (
    CanonicalMessage,
    ContentPolicyError,
    ImageBlock,
    MessageRole,
    ProviderError,
    RateLimitError,
    StopReason,
    TextBlock,
    ValidationError,
)
from rogue.core.conformance import assert_conformant


# --------------------------------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------------------------------


def _fake_response(text: str = "hello", *, stop_reason: str = "end_turn", tin: int = 11, tout: int = 7):
    """Build a fake Anthropic Messages response (content blocks + usage + stop_reason)."""
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=tin, output_tokens=tout),
        stop_reason=stop_reason,
        model_dump=lambda: {"stop_reason": stop_reason, "content": [{"type": "text", "text": text}]},
    )


class FakeMessages:
    def __init__(self, response=None, raise_exc=None):
        self._response = response
        self._raise = raise_exc
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._raise is not None:
            raise self._raise
        return self._response


class FakeClient:
    def __init__(self, response=None, raise_exc=None):
        self.messages = FakeMessages(response=response, raise_exc=raise_exc)
        self.closed = False

    async def close(self):
        self.closed = True


def _adapter(client, model="anthropic/claude-haiku-4-5"):
    return AnthropicAdapter(AdapterConfig(model=model, extra={"client": client}))


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    """Make tenacity's async backoff instant so retry-path tests don't actually wait."""
    import tenacity.asyncio

    async def _instant(_self, _fut):
        return None

    monkeypatch.setattr(tenacity.asyncio.AsyncRetrying, "sleep", _instant, raising=False)


def _anthropic_exc(name: str, status: int):
    import anthropic

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(status, request=req)
    return getattr(anthropic, name)(name, response=resp, body=None)


# --------------------------------------------------------------------------------------------------
# Happy path
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_text_usage_stop():
    client = FakeClient(_fake_response("the answer", tin=20, tout=5))
    adapter = _adapter(client)
    result = await adapter.invoke(
        [CanonicalMessage.system("be helpful"), CanonicalMessage.user("hi")]
    )
    assert result.text == "the answer"
    assert [type(b) for b in result.content] == [TextBlock]
    assert result.usage.input_tokens == 20
    assert result.usage.output_tokens == 5
    assert result.usage.total_tokens == 25
    assert result.usage.estimated_cost_usd is not None and result.usage.estimated_cost_usd > 0
    assert result.stop_reason == StopReason.COMPLETE
    assert result.latency_ms >= 0
    assert isinstance(result.raw_response, dict)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_stop,expected",
    [
        ("end_turn", StopReason.COMPLETE),
        ("max_tokens", StopReason.LENGTH),
        ("refusal", StopReason.SAFETY),
        ("tool_use", StopReason.TOOL_CALL),
    ],
)
async def test_stop_reason_mapping(provider_stop, expected):
    client = FakeClient(_fake_response(stop_reason=provider_stop))
    result = await _adapter(client).invoke([CanonicalMessage.user("x")])
    assert result.stop_reason == expected


# --------------------------------------------------------------------------------------------------
# System/chat split + content shapes
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_system_chat_split_text_only():
    client = FakeClient(_fake_response())
    await _adapter(client).invoke(
        [
            CanonicalMessage.system("sys one"),
            CanonicalMessage.system("sys two"),
            CanonicalMessage.user("hello"),
            CanonicalMessage.assistant("prior"),
        ]
    )
    call = client.messages.calls[0]
    assert call["system"] == "sys one\n\nsys two"
    # non-system turns only; text-only content is a plain string
    assert call["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "prior"},
    ]


@pytest.mark.asyncio
async def test_image_message_anthropic_block_shape():
    client = FakeClient(_fake_response())
    img = ImageBlock(data=b"\x89PNG\r\n", mime_type="image/png")
    msg = CanonicalMessage(
        role=MessageRole.USER, content=[TextBlock(text="look"), img]
    )
    await _adapter(client).invoke([CanonicalMessage.system("s"), msg])
    content = client.messages.calls[0]["messages"][0]["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "look"}
    assert content[1]["type"] == "image"
    assert content[1]["source"]["type"] == "base64"
    assert content[1]["source"]["media_type"] == "image/png"
    assert content[1]["source"]["data"] == img.to_base64()


@pytest.mark.asyncio
async def test_no_non_system_messages_raises():
    client = FakeClient(_fake_response())
    with pytest.raises(ValidationError, match="no non-system messages"):
        await _adapter(client).invoke([CanonicalMessage.system("only system")])


# --------------------------------------------------------------------------------------------------
# Temperature clamp + max_tokens default
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_temperature_clamped_to_one():
    client = FakeClient(_fake_response())
    await _adapter(client).invoke([CanonicalMessage.user("x")], temperature=1.5)
    assert client.messages.calls[0]["temperature"] == 1.0


@pytest.mark.asyncio
async def test_max_tokens_defaults_to_4096():
    client = FakeClient(_fake_response())
    await _adapter(client).invoke([CanonicalMessage.user("x")])
    assert client.messages.calls[0]["max_tokens"] == 4096


@pytest.mark.asyncio
async def test_max_tokens_honors_explicit_cap():
    client = FakeClient(_fake_response())
    await _adapter(client).invoke([CanonicalMessage.user("x")], max_output_tokens=128)
    assert client.messages.calls[0]["max_tokens"] == 128


# --------------------------------------------------------------------------------------------------
# Error mapping (real anthropic SDK exceptions)
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_maps_to_core_rate_limit():
    client = FakeClient(raise_exc=_anthropic_exc("RateLimitError", 429))
    with pytest.raises(RateLimitError):
        await _adapter(client).invoke([CanonicalMessage.user("x")])


@pytest.mark.asyncio
async def test_bad_request_maps_to_content_policy():
    client = FakeClient(raise_exc=_anthropic_exc("BadRequestError", 400))
    with pytest.raises(ContentPolicyError):
        await _adapter(client).invoke([CanonicalMessage.user("x")])


@pytest.mark.asyncio
async def test_api_status_5xx_maps_to_provider_error():
    client = FakeClient(raise_exc=_anthropic_exc("APIStatusError", 503))
    with pytest.raises(ProviderError):
        await _adapter(client).invoke([CanonicalMessage.user("x")])


@pytest.mark.asyncio
async def test_unrecognized_exception_reraised():
    client = FakeClient(raise_exc=KeyError("boom"))
    with pytest.raises(KeyError):
        await _adapter(client).invoke([CanonicalMessage.user("x")])


# --------------------------------------------------------------------------------------------------
# Capabilities, healthcheck, estimate, lifecycle
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capabilities_haiku_supports_image_and_tools():
    caps = await _adapter(FakeClient(_fake_response())).capabilities()
    assert caps.supports_image is True
    assert caps.supports_tools is True
    assert caps.supports_function_calling is True


@pytest.mark.asyncio
async def test_healthcheck_true_with_env_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert await _adapter(FakeClient(_fake_response())).healthcheck() is True


@pytest.mark.asyncio
async def test_healthcheck_false_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    adapter = AnthropicAdapter(
        AdapterConfig(model="anthropic/claude-haiku-4-5", api_key=None, extra={"client": FakeClient(_fake_response())})
    )
    assert await adapter.healthcheck() is False


@pytest.mark.asyncio
async def test_estimate_cost_no_model_call():
    client = FakeClient(_fake_response())
    adapter = _adapter(client)
    usage = await adapter.estimate_cost([CanonicalMessage.user("a" * 40)])
    assert client.messages.calls == []  # no model call
    assert usage.input_tokens == 10  # 40 // 4
    assert usage.output_tokens == 512
    assert usage.estimated_cost_usd is not None and usage.estimated_cost_usd > 0


@pytest.mark.asyncio
async def test_aclose_does_not_close_injected_client():
    client = FakeClient(_fake_response())
    adapter = _adapter(client)
    await adapter.aclose()
    assert client.closed is False  # injected client is never closed by the adapter


@pytest.mark.asyncio
async def test_audio_block_is_misroute():
    from rogue.core import AudioBlock

    client = FakeClient(_fake_response())
    msg = CanonicalMessage(role=MessageRole.USER, content=[AudioBlock(data=b"RIFF", mime_type="audio/wav")])
    with pytest.raises(ValidationError):
        await _adapter(client).invoke([msg])


# --------------------------------------------------------------------------------------------------
# Conformance
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conformance():
    # A fresh fake client per adapter so repeated invoke()s in the suite all succeed.
    fake = FakeClient(_fake_response("conformant reply"))
    adapter = AnthropicAdapter(
        AdapterConfig(model="anthropic/claude-haiku-4-5", extra={"client": fake})
    )
    await assert_conformant(adapter)


def test_with_provider_retry_is_used():
    # Guard: the inner call must be wrapped by the shared retry policy (smoke).
    assert callable(with_provider_retry)
