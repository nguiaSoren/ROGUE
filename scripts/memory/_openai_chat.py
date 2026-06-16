"""Provider-agnostic OpenAI-compatible chat helper for the §08 memory red-team.

Generalizes ``_groq.py`` to any OpenAI-shaped ``/chat/completions`` endpoint (Groq,
Featherless, …) and — crucially for the reasoning-trace leak-surface measurement — keeps the
*answer channel* and the *reasoning channel* SEPARATE instead of collapsing them into one
string. The original ``groq_chat`` returned ``content or reasoning``; that collapse is exactly
what made the qwen3-32b leakage rate "leak-in-reasoning-or-answer" and not answer-comparable to
the others. Here we return both, plus the inline ``<think>…</think>`` split, so a caller can
score answer-only vs reasoning-inclusive (paper Item 2).

Same robustness contract as ``_groq.py``: retry/backoff on 429/5xx/missing-choices, an
inter-call pace, and an honest error marker only after exhausting retries (a dead call must be
visibly tagged, never a silent ''— which would fake a 0% leak).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import httpx

# OpenAI-compatible base URLs (the path /chat/completions is appended).
PROVIDER_BASE_URLS = {
    "featherless": "https://api.featherless.ai/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",  # warm/fast routing for popular models
}

_THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)


@dataclass
class ChatResult:
    """One completion, with the answer and reasoning channels kept apart.

    - ``answer``: the content channel with any inline ``<think>…</think>`` removed — what a
      consumer sees as the model's reply (answer-only scoring).
    - ``reasoning``: the separate reasoning field (``reasoning`` / ``reasoning_content``) plus
      any inline ``<think>`` blocks lifted out of content — the visible chain-of-thought.
    - ``visible``: the raw content channel as returned (inline think included) — reproduces the
      original harness's scored field exactly.
    - ``reasoning_inclusive``: answer + reasoning — everything visible anywhere.
    - ``error``: set iff the call failed after retries; ``visible`` then carries the tag.
    """

    answer: str
    reasoning: str
    visible: str
    error: str | None

    @property
    def reasoning_inclusive(self) -> str:
        return (self.answer + "\n" + self.reasoning).strip()

    @property
    def is_error(self) -> bool:
        return self.error is not None


def _split_channels(content: str, reasoning_field: str) -> tuple[str, str, str]:
    """Return (answer, reasoning, visible) from a raw content + separate reasoning field."""
    visible = (content or "").strip()
    think_blocks = _THINK_RE.findall(visible)
    answer = _THINK_RE.sub("", visible).strip()
    reasoning = "\n".join(
        part.strip() for part in ([reasoning_field or ""] + think_blocks) if part and part.strip()
    ).strip()
    return answer, reasoning, visible


def openai_chat(
    client: httpx.Client,
    base_url: str,
    api_key: str,
    model: str,
    system: str,
    user: str,
    *,
    max_tokens: int = 512,
    temperature: float = 0.7,
    max_retries: int = 5,
    base_pace_s: float = 0.4,
    error_tag: str = "call-error",
) -> ChatResult:
    """One chat completion against an OpenAI-compatible endpoint, channels kept separate.

    ``base_pace_s`` defaults lower than the Groq helper's 1.5s because Featherless is a
    flat-rate dedicated-throughput provider, not a free-tier RPM bucket; the retry/backoff still
    handles any 429.
    """
    url = base_url.rstrip("/") + "/chat/completions"
    time.sleep(base_pace_s)
    last = "unknown"
    for attempt in range(max_retries):
        try:
            r = client.post(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            if r.status_code == 429 or r.status_code >= 500:
                last = f"http {r.status_code}"
                retry_after = r.headers.get("retry-after")
                wait = float(retry_after) if retry_after else min(2.0 ** attempt, 10.0)
                time.sleep(wait)
                continue
            if r.status_code >= 400:
                # 4xx other than 429 (e.g. 400 on a decommissioned model) is terminal — surface it
                # so the liveness guard aborts rather than scoring a dead target as a clean 0%.
                last = f"http {r.status_code}: {r.text[:120]}"
                break
            data = r.json()
            if "choices" in data and data["choices"]:
                msg = data["choices"][0].get("message", {})
                reasoning_field = msg.get("reasoning") or msg.get("reasoning_content") or ""
                answer, reasoning, visible = _split_channels(msg.get("content") or "", reasoning_field)
                if visible or reasoning:
                    return ChatResult(answer=answer, reasoning=reasoning,
                                      visible=visible or reasoning, error=None)
                last = "empty content+reasoning"  # a failed call, NOT a silent '' (would fake a 0% leak)
            else:
                last = f"no-choices: {str(data)[:120]}"
            time.sleep(min(2.0 ** attempt, 10.0))
        except Exception as exc:  # network blip etc.
            last = str(exc)
            time.sleep(min(2.0 ** attempt, 10.0))
    tag = f"[{error_tag}: exhausted {max_retries} retries — {last}]"
    return ChatResult(answer="", reasoning="", visible=tag, error=last)
