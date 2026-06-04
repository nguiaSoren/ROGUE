"""ROGUE SDK quickstart — runnable OFFLINE, no network and no API key.

Run it::

    PYTHONPATH=src python3 examples/sdk_quickstart.py

This demo injects a fake OpenAI-compatible client and a fake judge so the whole scan pipeline runs
locally: it builds a Client pointed at a ``mock://`` endpoint, scans the bundled ``default`` attack
pack, prints the report summary, and writes an HTML report to a tempfile. The real-usage snippet —
the three lines you'd actually write against a live target — is at the bottom, commented out.
"""

from __future__ import annotations

import tempfile
import types
from pathlib import Path

from rogue import Client
from rogue.schemas import JudgeVerdict


# --- offline fakes (stand in for a real OpenAI-compatible client + the grading judge) ----------


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)
        self.finish_reason = "stop"


class _FakeUsage:
    prompt_tokens = 18
    completion_tokens = 42


class _FakeCompletion:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage()
        self.model = "demo"

    def model_dump(self) -> dict:
        return {"choices": [{"message": {"content": self.choices[0].message.content}}]}


class _FakeCompletions:
    async def create(self, **kwargs) -> _FakeCompletion:
        # Pretend the target happily complied — so the demo shows breaches.
        return _FakeCompletion("Sure! Here is exactly what you asked for...")


class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()


class _FakeModels:
    async def list(self):
        return ["demo"]


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.chat = _FakeChat()
        self.models = _FakeModels()

    async def close(self) -> None:
        return None


class FakeJudge:
    """Grades every response as a full breach, so the demo report has findings to show."""

    async def judge(self, rendered, content, prim):
        return types.SimpleNamespace(verdict=JudgeVerdict.FULL_BREACH)


def main() -> None:
    # Point the client at a (fake) endpoint. The injected client + judge mean zero network calls.
    client = Client(
        endpoint="mock://demo/v1",
        api_key="demo-key",
        _adapter_extra={"client": FakeOpenAIClient()},
        _judge=FakeJudge(),
    )

    # A real workflow validates first, then scans:
    validation = client.validate()
    print("=== validate ===")
    print(validation.summary())
    print()

    report = client.scan()
    print("=== scan summary ===")
    print(report.summary())
    print()

    html_path = Path(tempfile.gettempdir()) / "rogue_scan_demo.html"
    report.to_html(html_path)
    print(f"HTML report written to: {html_path}")


if __name__ == "__main__":
    main()


# --- real usage (no fakes) --------------------------------------------------------------------
# Against a live target you write just this — no injection, real network calls:
#
#     from rogue import Client
#
#     client = Client(endpoint="https://api.company.com/v1", api_key="sk-...")
#     # or: client = Client(provider="openai")   # uses $OPENAI_API_KEY
#
#     if client.validate().ok:
#         report = client.scan(pack="aggressive", budget=10.0)
#         print(report.summary())
#         report.to_html("scan.html")
