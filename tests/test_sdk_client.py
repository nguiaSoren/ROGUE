"""SDK ``Client`` surface — target resolution, validate(), and a fully-mocked scan().

These tests never touch the network. The Client is pointed at an ``endpoint=`` so it routes to
``CustomHTTPAdapter``, and a fake OpenAI-compatible client is injected via
``_adapter_extra={"client": ...}`` so every adapter call is served by the fake. The judge is
injected via ``_judge=`` so grading is deterministic too.

Run from project root::

    uv run pytest tests/test_sdk_client.py -v
"""

from __future__ import annotations

import sys
import types

import pytest

from rogue import Client, ScanReport
from rogue.schemas import JudgeVerdict


# --- fakes ------------------------------------------------------------------------------------


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)
        self.finish_reason = "stop"


class _FakeUsage:
    def __init__(self) -> None:
        self.prompt_tokens = 12
        self.completion_tokens = 34


class _FakeCompletion:
    def __init__(self, content: str, model: str) -> None:
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage()
        self.model = model

    def model_dump(self) -> dict:
        return {"choices": [{"message": {"content": self.choices[0].message.content}}]}


class _FakeCompletions:
    def __init__(self, reply: str, model: str) -> None:
        self._reply = reply
        self._model = model

    async def create(self, **kwargs):
        return _FakeCompletion(self._reply, self._model)


class _FakeChat:
    def __init__(self, reply: str, model: str) -> None:
        self.completions = _FakeCompletions(reply, model)


class _FakeModels:
    async def list(self):
        return ["default"]


class FakeOpenAIClient:
    """Minimal async openai-compatible client the CustomHTTPAdapter can drive."""

    def __init__(self, reply: str = "Sure, here is exactly what you asked for.", model: str = "default") -> None:
        self.chat = _FakeChat(reply, model)
        self.models = _FakeModels()
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeJudge:
    """Deterministic judge: every response gets the configured verdict."""

    def __init__(self, verdict: JudgeVerdict = JudgeVerdict.FULL_BREACH) -> None:
        self._verdict = verdict

    async def judge(self, rendered, content, prim):
        return types.SimpleNamespace(verdict=self._verdict)


def _client(**kwargs) -> Client:
    extra = {"client": FakeOpenAIClient()}
    extra.update(kwargs.pop("_adapter_extra", {}))
    kwargs.setdefault("endpoint", "https://x/v1")
    return Client(_adapter_extra=extra, **kwargs)


# --- target resolution ------------------------------------------------------------------------


def test_provider_openai_default_model():
    c = Client(provider="openai")
    assert c.config.target_model == "openai/gpt-5.4-nano"
    assert c.config.base_url is None


def test_provider_anthropic_default_model():
    c = Client(provider="anthropic")
    assert c.config.target_model == "anthropic/claude-haiku-4-5"
    assert c.config.base_url is None


def test_provider_with_bare_model_gets_prefixed():
    c = Client(provider="openai", model="gpt-x")
    assert c.config.target_model == "openai/gpt-x"


def test_model_with_slash_used_as_is():
    c = Client(provider="openai", model="vendor/m")
    assert c.config.target_model == "vendor/m"


def test_endpoint_default_model():
    c = Client(endpoint="https://x/v1")
    assert c.config.base_url == "https://x/v1"
    assert c.config.target_model == "default"


def test_endpoint_with_explicit_model():
    c = Client(endpoint="https://x/v1", model="my-model")
    assert c.config.base_url == "https://x/v1"
    assert c.config.target_model == "my-model"


def test_no_endpoint_no_provider_raises():
    with pytest.raises(ValueError):
        Client()


def test_unknown_provider_without_model_raises():
    with pytest.raises(ValueError):
        Client(provider="totally-unknown")


def test_config_and_adapter_exposed():
    c = Client(endpoint="https://x/v1")
    assert c.config is not None
    assert c.adapter is not None
    # endpoint mode routes to the custom OpenAI-compatible adapter.
    assert type(c.adapter).__name__ == "CustomHTTPAdapter"


# --- laziness (PEP-562) -----------------------------------------------------------------------


def test_import_rogue_does_not_eagerly_load_adapters():
    # Run a cold import in a fresh interpreter so purging modules can't pollute this process
    # (re-importing rogue here would rebind ScanReport/Client and break later isinstance checks).
    import subprocess  # noqa: PLC0415 - local to this single test

    script = (
        "import sys\n"
        "import rogue\n"
        "assert 'rogue.adapters' not in sys.modules, 'adapters eagerly loaded'\n"
        "assert 'rogue.reproduce' not in sys.modules, 'reproduce eagerly loaded'\n"
        "_ = rogue.Client\n"
        "assert 'rogue.adapters' in sys.modules, 'Client access did not load adapters'\n"
    )
    env = {**__import__("os").environ, "PYTHONPATH": "src"}
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=env
    )
    assert proc.returncode == 0, proc.stderr


# --- validate() (mocked) ----------------------------------------------------------------------


def test_validate_clean_target_is_ok():
    c = _client()
    result = c.validate()
    assert result.reachable is True
    assert result.authenticated is True
    assert result.model_responds is True
    assert result.ok is True
    assert result.error is None


def test_validate_capabilities_reflect_adapter():
    # "default" is an unknown model → text-only (no image/audio).
    text_only = _client()
    r1 = text_only.validate()
    assert r1.supports_image is False
    assert r1.supports_audio is False

    # An image-capable model id flows through to the reported capabilities.
    multimodal = Client(
        endpoint="https://x/v1",
        model="openai/gpt-5.4-nano",
        _adapter_extra={"client": FakeOpenAIClient(model="openai/gpt-5.4-nano")},
    )
    r2 = multimodal.validate()
    assert r2.supports_image is True


# --- scan() (fully mocked end-to-end) ---------------------------------------------------------


def test_scan_full_breach_marks_every_test():
    from rogue.packs import load_pack

    n_default = len(load_pack("default"))
    c = Client(
        endpoint="https://x/v1",
        _adapter_extra={"client": FakeOpenAIClient()},
        _judge=FakeJudge(JudgeVerdict.FULL_BREACH),
    )
    report = c.scan()
    assert isinstance(report, ScanReport)
    assert report.n_tests == n_default
    assert report.n_breaches == n_default
    assert report.target == "https://x/v1"


def test_scan_respects_max_tests_cap():
    c = Client(
        endpoint="https://x/v1",
        _adapter_extra={"client": FakeOpenAIClient()},
        _judge=FakeJudge(JudgeVerdict.FULL_BREACH),
    )
    report = c.scan(max_tests=3)
    assert report.n_tests == 3
    assert report.n_breaches == 3


def test_scan_clean_refusal_has_no_breaches():
    c = Client(
        endpoint="https://x/v1",
        _adapter_extra={"client": FakeOpenAIClient()},
        _judge=FakeJudge(JudgeVerdict.REFUSED),
    )
    report = c.scan(max_tests=4)
    assert report.n_tests == 4
    assert report.n_breaches == 0
    assert report.top_attack is None
