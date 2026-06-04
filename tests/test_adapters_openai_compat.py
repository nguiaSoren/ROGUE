"""Tests for the OpenAI-compatible target adapters (Week-2 migration).

A fake injected client (``AdapterConfig(extra={'client': fake})``) stands in for ``AsyncOpenAI`` so
nothing touches the network. The fake records what ``chat.completions.create`` received so we can
assert the exact wire format the adapter built. Retryable error paths (429 / 5xx) monkeypatch
``asyncio.sleep`` to keep tenacity's backoff instant.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from rogue.adapters.base import AdapterConfig
from rogue.adapters.custom import CustomHTTPAdapter
from rogue.adapters.openai import GroqAdapter, OpenAIAdapter
from rogue.adapters.openrouter import OpenRouterAdapter
from rogue.core import (
    AudioBlock,
    CanonicalMessage,
    ImageBlock,
    MessageRole,
    StopReason,
    TextBlock,
)
from rogue.core.conformance import assert_conformant
from rogue.core.errors import (
    ContentPolicyError,
    ProviderError,
    RateLimitError,
    ValidationError,
)

PRICED_MODEL = "openai/gpt-5.4-nano"


# --------------------------------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------------------------------


class _FakeMessage:
    def __init__(self, content: str | None):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str | None, finish_reason: str | None):
        self.message = _FakeMessage(content)
        self.finish_reason = finish_reason


class _FakeUsage:
    def __init__(self, prompt_tokens: int, completion_tokens: int):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeResponse:
    def __init__(self, content="hello world", finish_reason="stop", tin=11, tout=7):
        self.choices = [_FakeChoice(content, finish_reason)]
        self.usage = _FakeUsage(tin, tout)
        self._dump = {"id": "resp_1", "choices": [{"message": {"content": content}}]}

    def model_dump(self) -> dict:
        return self._dump


class _FakeCompletions:
    def __init__(self, parent: "FakeClient"):
        self._parent = parent

    async def create(self, **kwargs):
        self._parent.last_create_kwargs = kwargs
        if self._parent.raises is not None:
            raise self._parent.raises
        return self._parent.response


class _FakeChat:
    def __init__(self, parent: "FakeClient"):
        self.completions = _FakeCompletions(parent)


class _FakeModels:
    def __init__(self, parent: "FakeClient"):
        self._parent = parent

    async def list(self):
        if self._parent.models_raises is not None:
            raise self._parent.models_raises
        return {"data": []}


class FakeClient:
    """Minimal stand-in for AsyncOpenAI exposing chat.completions.create + models.list."""

    def __init__(self, response: _FakeResponse | None = None, raises: Exception | None = None):
        self.response = response if response is not None else _FakeResponse()
        self.raises = raises
        self.models_raises: Exception | None = None
        self.last_create_kwargs: dict | None = None
        self.chat = _FakeChat(self)
        self.models = _FakeModels(self)


def _cfg(model: str = PRICED_MODEL, fake: FakeClient | None = None, **extra) -> AdapterConfig:
    client = fake if fake is not None else FakeClient()
    return AdapterConfig(model=model, extra={"client": client, **extra})


def _httpx_status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    response = httpx.Response(status_code=status, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


@pytest.fixture
def _no_backoff(monkeypatch):
    """Make tenacity's async backoff instant so retryable-error tests don't sleep for seconds."""

    async def _instant(_delay):
        return None

    monkeypatch.setattr(asyncio, "sleep", _instant)


# --------------------------------------------------------------------------------------------------
# invoke — happy path
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invoke_happy_path():
    fake = FakeClient(_FakeResponse(content="ack", finish_reason="stop", tin=20, tout=10))
    adapter = OpenAIAdapter(_cfg(fake=fake))
    result = await adapter.invoke([CanonicalMessage.user("hi")])

    assert result.text == "ack"
    assert result.usage.input_tokens == 20
    assert result.usage.output_tokens == 10
    assert result.usage.total_tokens == 30
    assert result.usage.estimated_cost_usd is not None and result.usage.estimated_cost_usd > 0
    assert result.stop_reason == StopReason.COMPLETE
    assert isinstance(result.latency_ms, int) and result.latency_ms >= 0
    assert isinstance(result.raw_response, dict) and result.raw_response.get("id") == "resp_1"


@pytest.mark.asyncio
async def test_invoke_maps_finish_reason():
    fake = FakeClient(_FakeResponse(finish_reason="length"))
    adapter = OpenAIAdapter(_cfg(fake=fake))
    result = await adapter.invoke([CanonicalMessage.user("hi")])
    assert result.stop_reason == StopReason.LENGTH


@pytest.mark.asyncio
async def test_invoke_no_usage_defaults_zero():
    resp = _FakeResponse()
    resp.usage = None
    fake = FakeClient(resp)
    adapter = OpenAIAdapter(_cfg(fake=fake))
    result = await adapter.invoke([CanonicalMessage.user("hi")])
    assert result.usage.input_tokens == 0
    assert result.usage.output_tokens == 0


# --------------------------------------------------------------------------------------------------
# Wire-format translation
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_text_only_content_is_string():
    fake = FakeClient()
    adapter = OpenAIAdapter(_cfg(fake=fake))
    await adapter.invoke(
        [CanonicalMessage.system("be brief"), CanonicalMessage.user("hello there")]
    )
    msgs = fake.last_create_kwargs["messages"]
    assert msgs == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hello there"},
    ]
    # Each text-only content is a plain str, not a list.
    assert all(isinstance(m["content"], str) for m in msgs)


@pytest.mark.asyncio
async def test_image_message_is_list_with_text_then_image_url():
    fake = FakeClient()
    adapter = OpenAIAdapter(_cfg(fake=fake))
    msg = CanonicalMessage(
        role=MessageRole.USER,
        content=[
            TextBlock(text="describe this"),
            ImageBlock(data=b"\x89PNG", mime_type="image/png"),
        ],
    )
    await adapter.invoke([msg])
    content = fake.last_create_kwargs["messages"][0]["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "describe this"}
    assert content[1]["type"] == "image_url"
    url = content[1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_image_url_block_passes_url_through():
    fake = FakeClient()
    adapter = OpenAIAdapter(_cfg(fake=fake))
    msg = CanonicalMessage(
        role=MessageRole.USER,
        content=[ImageBlock(url="https://img.test/x.png", mime_type="image/png")],
    )
    await adapter.invoke([msg])
    content = fake.last_create_kwargs["messages"][0]["content"]
    # No text part (no TextBlock); first part is the image_url with the raw URL.
    assert content == [
        {"type": "image_url", "image_url": {"url": "https://img.test/x.png"}}
    ]


@pytest.mark.asyncio
async def test_audio_message_input_audio_format():
    fake = FakeClient()
    adapter = OpenAIAdapter(_cfg(fake=fake))
    msg = CanonicalMessage(
        role=MessageRole.USER,
        content=[
            TextBlock(text="transcribe"),
            AudioBlock(data=b"RIFFdata", mime_type="audio/wav"),
        ],
    )
    await adapter.invoke([msg])
    content = fake.last_create_kwargs["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "transcribe"}
    assert content[1]["type"] == "input_audio"
    assert content[1]["input_audio"]["format"] == "wav"
    assert content[1]["input_audio"]["data"]  # base64 string present


@pytest.mark.asyncio
async def test_audio_mpeg_maps_to_mp3():
    fake = FakeClient()
    adapter = OpenAIAdapter(_cfg(fake=fake))
    msg = CanonicalMessage(
        role=MessageRole.USER,
        content=[AudioBlock(data=b"\xff\xfbmp3", mime_type="audio/mpeg")],
    )
    await adapter.invoke([msg])
    content = fake.last_create_kwargs["messages"][0]["content"]
    assert content[0]["input_audio"]["format"] == "mp3"


# --------------------------------------------------------------------------------------------------
# Wire model id per provider
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_strips_prefix():
    fake = FakeClient()
    adapter = OpenAIAdapter(_cfg(model="openai/gpt-5.4-nano", fake=fake))
    await adapter.invoke([CanonicalMessage.user("hi")])
    assert fake.last_create_kwargs["model"] == "gpt-5.4-nano"


@pytest.mark.asyncio
async def test_groq_strips_prefix():
    fake = FakeClient()
    adapter = GroqAdapter(_cfg(model="groq/llama-3.1-8b-instant", fake=fake))
    await adapter.invoke([CanonicalMessage.user("hi")])
    assert fake.last_create_kwargs["model"] == "llama-3.1-8b-instant"
    assert adapter.provider == "groq"


@pytest.mark.asyncio
async def test_openrouter_keeps_full_model():
    fake = FakeClient()
    adapter = OpenRouterAdapter(_cfg(model="mistralai/mistral-small-2603", fake=fake))
    await adapter.invoke([CanonicalMessage.user("hi")])
    assert fake.last_create_kwargs["model"] == "mistralai/mistral-small-2603"
    assert adapter.provider == "mistralai"


# --------------------------------------------------------------------------------------------------
# max_output_tokens handling
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_tokens_omitted_when_none():
    fake = FakeClient()
    adapter = OpenAIAdapter(_cfg(fake=fake))
    await adapter.invoke([CanonicalMessage.user("hi")])
    assert "max_tokens" not in fake.last_create_kwargs


@pytest.mark.asyncio
async def test_max_tokens_passed_when_set():
    fake = FakeClient()
    adapter = OpenAIAdapter(_cfg(fake=fake))
    await adapter.invoke([CanonicalMessage.user("hi")], max_output_tokens=64)
    assert fake.last_create_kwargs["max_tokens"] == 64


# --------------------------------------------------------------------------------------------------
# Error mapping
# --------------------------------------------------------------------------------------------------


def _openai_exc(cls, status: int):
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(status_code=status, request=request)
    return cls("provider error", response=response, body=None)


@pytest.mark.asyncio
async def test_rate_limit_error_maps(_no_backoff):
    from openai import RateLimitError as OARateLimit

    fake = FakeClient(raises=_openai_exc(OARateLimit, 429))
    adapter = OpenAIAdapter(_cfg(fake=fake))
    with pytest.raises(RateLimitError):
        await adapter.invoke([CanonicalMessage.user("hi")])


@pytest.mark.asyncio
async def test_bad_request_maps_to_content_policy():
    from openai import BadRequestError as OABadRequest

    fake = FakeClient(raises=_openai_exc(OABadRequest, 400))
    adapter = OpenAIAdapter(_cfg(fake=fake))
    with pytest.raises(ContentPolicyError):
        await adapter.invoke([CanonicalMessage.user("hi")])


@pytest.mark.asyncio
async def test_api_status_error_maps_to_provider(_no_backoff):
    from openai import APIStatusError as OAStatus

    fake = FakeClient(raises=_openai_exc(OAStatus, 500))
    adapter = OpenAIAdapter(_cfg(fake=fake))
    with pytest.raises(ProviderError):
        await adapter.invoke([CanonicalMessage.user("hi")])


@pytest.mark.asyncio
async def test_httpx_429_maps_to_rate_limit(_no_backoff):
    fake = FakeClient(raises=_httpx_status_error(429))
    adapter = OpenAIAdapter(_cfg(fake=fake))
    with pytest.raises(RateLimitError):
        await adapter.invoke([CanonicalMessage.user("hi")])


@pytest.mark.asyncio
async def test_httpx_500_maps_to_provider(_no_backoff):
    fake = FakeClient(raises=_httpx_status_error(500))
    adapter = OpenAIAdapter(_cfg(fake=fake))
    with pytest.raises(ProviderError):
        await adapter.invoke([CanonicalMessage.user("hi")])


# --------------------------------------------------------------------------------------------------
# CustomHTTPAdapter
# --------------------------------------------------------------------------------------------------


def test_custom_requires_base_url():
    with pytest.raises(ValidationError):
        CustomHTTPAdapter(AdapterConfig(model="my-model", extra={"client": FakeClient()}))


@pytest.mark.asyncio
async def test_custom_with_base_url_works():
    fake = FakeClient()
    adapter = CustomHTTPAdapter(
        AdapterConfig(model="my-model", base_url="https://gw.test/v1", extra={"client": fake})
    )
    result = await adapter.invoke([CanonicalMessage.user("hi")])
    assert result.text == "hello world"
    assert fake.last_create_kwargs["model"] == "my-model"
    assert adapter.provider == "custom"


# --------------------------------------------------------------------------------------------------
# capabilities + healthcheck
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capabilities_reflect_model_specs():
    adapter = OpenAIAdapter(_cfg(model="openai/gpt-5.4-nano"))
    caps = await adapter.capabilities()
    assert caps.supports_image is True
    assert caps.supports_audio is False
    assert caps.supports_tools is True


@pytest.mark.asyncio
async def test_healthcheck_true_then_false():
    fake = FakeClient()
    adapter = OpenAIAdapter(_cfg(fake=fake))
    assert await adapter.healthcheck() is True
    fake.models_raises = RuntimeError("network down")
    assert await adapter.healthcheck() is False


# --------------------------------------------------------------------------------------------------
# Conformance — every adapter passes the provider-agnostic suite
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conformance_openai():
    await assert_conformant(OpenAIAdapter(_cfg(model="openai/gpt-5.4-nano")))


@pytest.mark.asyncio
async def test_conformance_groq():
    await assert_conformant(GroqAdapter(_cfg(model="groq/llama-3.1-8b-instant")))


@pytest.mark.asyncio
async def test_conformance_openrouter():
    await assert_conformant(OpenRouterAdapter(_cfg(model="mistralai/mistral-small-2603")))


@pytest.mark.asyncio
async def test_conformance_custom():
    fake = FakeClient()
    await assert_conformant(
        CustomHTTPAdapter(
            AdapterConfig(model="my-model", base_url="https://gw.test/v1", extra={"client": fake})
        )
    )
