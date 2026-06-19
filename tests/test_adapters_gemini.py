"""Tests for :class:`rogue.adapters.gemini.GeminiAdapter` — fully mocked, no network, no SDK.

The ``google-genai`` SDK is NOT installed; the adapter imports it lazily inside its client builder, so
this test file imports cleanly. A fake client matching the async surface the adapter codes to —
``client.aio.models.generate_content(model=, contents=, config=)`` — is injected via
``AdapterConfig.extra["client"]``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from rogue.adapters.base import AdapterConfig
from rogue.adapters.gemini import GeminiAdapter
from rogue.core import (
    CanonicalMessage,
    ImageBlock,
    MessageRole,
    ProviderError,
    StopReason,
    TextBlock,
)
from rogue.core.conformance import assert_conformant


# --------------------------------------------------------------------------------------------------
# Fakes — match google-genai's async surface: client.aio.models.generate_content(...)
# --------------------------------------------------------------------------------------------------


def _fake_response(text: str = "hello", *, finish: str = "STOP", tin: int = 12, tout: int = 8):
    return SimpleNamespace(
        text=text,
        usage_metadata=SimpleNamespace(prompt_token_count=tin, candidates_token_count=tout),
        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name=finish))],
        model_dump=lambda: {"text": text, "finish_reason": finish},
    )


class FakeModels:
    def __init__(self, response=None, raise_exc=None):
        self._response = response
        self._raise = raise_exc
        self.calls: list[dict] = []

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self._raise is not None:
            raise self._raise
        return self._response


class FakeAio:
    def __init__(self, models):
        self.models = models


class FakeClient:
    def __init__(self, response=None, raise_exc=None):
        self.models = FakeModels(response=response, raise_exc=raise_exc)
        self.aio = FakeAio(self.models)


def _adapter(client, model="google/gemini-3.1-flash-lite"):
    return GeminiAdapter(AdapterConfig(model=model, extra={"client": client}))


# --------------------------------------------------------------------------------------------------
# Happy path
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_text_usage_stop():
    client = FakeClient(_fake_response("gemini reply", finish="STOP", tin=30, tout=10))
    result = await _adapter(client).invoke(
        [CanonicalMessage.system("be terse"), CanonicalMessage.user("hi")]
    )
    assert result.text == "gemini reply"
    assert [type(b) for b in result.content] == [TextBlock]
    assert result.usage.input_tokens == 30
    assert result.usage.output_tokens == 10
    assert result.usage.total_tokens == 40
    assert result.usage.estimated_cost_usd is not None and result.usage.estimated_cost_usd > 0
    assert result.stop_reason == StopReason.COMPLETE
    assert isinstance(result.raw_response, dict)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "finish,expected",
    [
        ("STOP", StopReason.COMPLETE),
        ("MAX_TOKENS", StopReason.LENGTH),
        ("SAFETY", StopReason.SAFETY),
    ],
)
async def test_finish_reason_mapping(finish, expected):
    result = await _adapter(FakeClient(_fake_response(finish=finish))).invoke(
        [CanonicalMessage.user("x")]
    )
    assert result.stop_reason == expected


# --------------------------------------------------------------------------------------------------
# Message mapping: roles, system_instruction, image parts
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_role_mapping_and_system_instruction():
    client = FakeClient(_fake_response())
    await _adapter(client).invoke(
        [
            CanonicalMessage.system("sys a"),
            CanonicalMessage.system("sys b"),
            CanonicalMessage.user("hello"),
            CanonicalMessage.assistant("prior"),
        ]
    )
    call = client.models.calls[0]
    assert call["model"] == "gemini-3.1-flash-lite"  # google/ prefix stripped
    assert call["config"]["system_instruction"] == "sys a\n\nsys b"
    assert call["contents"] == [
        {"role": "user", "parts": [{"text": "hello"}]},
        {"role": "model", "parts": [{"text": "prior"}]},  # ASSISTANT -> "model"
    ]


@pytest.mark.asyncio
async def test_image_inline_data_part():
    client = FakeClient(_fake_response())
    img = ImageBlock(data=b"\x89PNG\r\n", mime_type="image/png")
    msg = CanonicalMessage(role=MessageRole.USER, content=[TextBlock(text="see"), img])
    await _adapter(client).invoke([msg])
    parts = client.models.calls[0]["contents"][0]["parts"]
    assert parts[0] == {"text": "see"}
    assert parts[1]["inline_data"]["mime_type"] == "image/png"
    assert parts[1]["inline_data"]["data"] == img.to_base64()


@pytest.mark.asyncio
async def test_no_system_instruction_when_no_system_msg():
    client = FakeClient(_fake_response())
    await _adapter(client).invoke([CanonicalMessage.user("x")], max_output_tokens=64, temperature=0.3)
    cfg = client.models.calls[0]["config"]
    assert "system_instruction" not in cfg
    assert cfg["max_output_tokens"] == 64
    assert cfg["temperature"] == 0.3


# --------------------------------------------------------------------------------------------------
# Response parsing fallbacks
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_text_falls_back_to_candidate_parts():
    resp = SimpleNamespace(
        text=None,
        usage_metadata=None,
        candidates=[
            SimpleNamespace(
                finish_reason="STOP",
                content=SimpleNamespace(parts=[SimpleNamespace(text="part1"), SimpleNamespace(text="part2")]),
            )
        ],
    )
    result = await _adapter(FakeClient(resp)).invoke([CanonicalMessage.user("x")])
    assert result.text == "part1part2"
    assert result.usage.input_tokens == 0  # no usage_metadata -> 0
    assert result.usage.total_tokens == 0
    assert isinstance(result.raw_response, dict)  # no model_dump -> {}


# --------------------------------------------------------------------------------------------------
# Error wrapping
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_native_error_wrapped_as_provider_error():
    # A google-genai-native error is not recognized by map_provider_exception -> wrapped ProviderError.
    class FakeGenAIError(Exception):
        pass

    client = FakeClient(raise_exc=FakeGenAIError("quota exceeded"))
    with pytest.raises(ProviderError, match="quota exceeded"):
        await _adapter(client).invoke([CanonicalMessage.user("x")])


# --------------------------------------------------------------------------------------------------
# Capabilities / healthcheck / estimate
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capabilities_spec_model_supports_image_audio():
    caps = await _adapter(FakeClient(_fake_response())).capabilities()
    assert caps.supports_image is True
    assert caps.supports_audio is True


@pytest.mark.asyncio
async def test_capabilities_unknown_gemini_id_text_only():
    adapter = _adapter(FakeClient(_fake_response()), model="gemini/gemini-experimental")
    caps = await adapter.capabilities()
    assert caps.supports_text is True
    assert caps.supports_image is False
    assert caps.supports_audio is False


@pytest.mark.asyncio
async def test_wire_model_strips_gemini_prefix():
    client = FakeClient(_fake_response())
    await _adapter(client, model="gemini/gemini-experimental").invoke([CanonicalMessage.user("x")])
    assert client.models.calls[0]["model"] == "gemini-experimental"


@pytest.mark.asyncio
async def test_healthcheck_true_with_env_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert await _adapter(FakeClient(_fake_response())).healthcheck() is True


@pytest.mark.asyncio
async def test_healthcheck_false_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    adapter = GeminiAdapter(
        AdapterConfig(model="google/gemini-3.1-flash-lite", api_key=None, extra={"client": FakeClient(_fake_response())})
    )
    assert await adapter.healthcheck() is False


@pytest.mark.asyncio
async def test_estimate_cost_no_model_call():
    client = FakeClient(_fake_response())
    usage = await _adapter(client).estimate_cost([CanonicalMessage.user("a" * 40)])
    assert client.models.calls == []
    assert usage.input_tokens == 10
    assert usage.output_tokens == 512
    assert usage.estimated_cost_usd is not None and usage.estimated_cost_usd > 0


# --------------------------------------------------------------------------------------------------
# Conformance
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conformance():
    fake = FakeClient(_fake_response("conformant reply"))
    adapter = GeminiAdapter(
        AdapterConfig(model="google/gemini-3.1-flash-lite", extra={"client": fake})
    )
    await assert_conformant(adapter)
