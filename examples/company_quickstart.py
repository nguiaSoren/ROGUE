"""ROGUE SDK company quickstart — self-serve / local mode.

Run it (offline, no keys, no network — this is what executes by default)::

    PYTHONPATH=src python3 examples/company_quickstart.py

This file shows BOTH halves of the company workflow:

  1. ``run_real()`` — the three lines a company actually writes against its OWN live
     target. It is guarded behind an env check (``TARGET_ENDPOINT``) so it never runs
     without credentials. It needs TWO credentials: the target endpoint + key, AND a
     judge model + that provider's key (the judge grades the responses independently).

  2. the offline demo in ``main()`` — injects a fake OpenAI-compatible client and a fake
     judge so the whole scan pipeline runs locally with zero network calls. This is what
     runs by default (and in CI): it scans the bundled ``default`` pack, prints the report
     summary, and writes an HTML report to a tempfile.
"""

from __future__ import annotations

import os
import tempfile
import types
from pathlib import Path

from rogue import Client
from rogue.schemas import JudgeVerdict


# --- real company usage (needs TWO creds: target endpoint+key AND a judge key) -----------------
# Guarded behind an env check so importing/running this file never spends money or hits the
# network. To run it for real, export the four vars below and call run_real() (or set
# TARGET_ENDPOINT and run this file — main() will dispatch here automatically):
#
#     export TARGET_ENDPOINT="https://api.company.com/v1"   # your OpenAI-compatible target
#     export TARGET_API_KEY="sk-..."                        # key for THAT target
#     export JUDGE_MODEL="openai/gpt-5.4-nano"              # independent grading model
#     export OPENAI_API_KEY="sk-..."                        # key for the JUDGE's provider
#
# The target key and the judge key are two SEPARATE credentials — the judge is an
# independent model that grades the target's responses, so it has its own provider/key.


def run_real() -> None:
    """Scan a company's own live target. Requires TARGET_ENDPOINT + TARGET_API_KEY and a judge."""
    client = Client(
        endpoint=os.environ["TARGET_ENDPOINT"],
        api_key=os.environ["TARGET_API_KEY"],
        # JUDGE_MODEL picks the independent grading model; its provider key (e.g. OPENAI_API_KEY)
        # is read from the environment by the judge itself.
        judge_model=os.environ.get("JUDGE_MODEL"),
    )

    # Cheap one-call pre-flight: is the target reachable, authed, responding?
    validation = client.validate()
    print(validation.summary())
    if not validation.ok:
        print(f"target not ready: {validation.error}")
        return

    report = client.scan(max_tests=10)
    print(report.summary())
    report.to_html("report.html")
    print("HTML report written to: report.html")


# --- offline demo (no keys, no network) --------------------------------------------------------
# Fakes that stand in for a real OpenAI-compatible client + the grading judge, so the entire
# scan pipeline runs locally. Injected via _adapter_extra={"client": ...} and _judge=...


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)
        self.finish_reason = "stop"


class _FakeUsage:
    prompt_tokens = 23
    completion_tokens = 57


class _FakeCompletion:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage()
        self.model = "demo"

    def model_dump(self) -> dict:
        return {"choices": [{"message": {"content": self.choices[0].message.content}}]}


class _FakeCompletions:
    async def create(self, **kwargs) -> _FakeCompletion:
        # Pretend the target complied — so the demo report has responses to grade.
        return _FakeCompletion("Sure! Here is exactly what you asked for...")


class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()


class _FakeModels:
    async def list(self):
        return ["demo"]


class FakeOpenAIClient:
    """Minimal async OpenAI-compatible stub: .chat.completions.create / .models.list / .close."""

    def __init__(self) -> None:
        self.chat = _FakeChat()
        self.models = _FakeModels()

    async def close(self) -> None:
        return None


# Families we let "break through" in the demo so the report shows real findings.
_BREACH_FAMILIES = {"dan_persona", "system_prompt_leak"}


class FakeJudge:
    """Grades a couple of families as breaches and refuses the rest — a realistic mixed report."""

    async def judge(self, rendered, content, prim):
        family = getattr(prim, "family", None)
        family = getattr(family, "value", family)
        verdict = JudgeVerdict.FULL_BREACH if family in _BREACH_FAMILIES else JudgeVerdict.REFUSED
        return types.SimpleNamespace(verdict=verdict)


def main() -> None:
    # If a real target is configured, run the real path instead of the offline demo.
    if os.environ.get("TARGET_ENDPOINT"):
        run_real()
        return

    # Point the client at a (fake) endpoint. The injected client + judge mean zero network calls.
    client = Client(
        endpoint="mock://demo",
        api_key="demo",
        _adapter_extra={"client": FakeOpenAIClient()},
        _judge=FakeJudge(),
    )

    report = client.scan(max_tests=10)
    print("=== scan summary ===")
    print(report.summary())
    print()

    html_path = Path(tempfile.gettempdir()) / "rogue_company_quickstart.html"
    report.to_html(html_path)
    print(f"HTML report written to: {html_path}")


if __name__ == "__main__":
    main()
