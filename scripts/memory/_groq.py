"""Robust Groq chat helper for the §08 memory red-team / rollout scripts.

The earlier scripts POSTed with no retry/backoff; firing dozens-to-hundreds of rapid calls
rate-limited Groq, which returns error JSON with no ``choices``. The old code swallowed that into
a ``[...-call-error]`` string, so ~90% of a sweep silently degenerated (error-vs-error graded
neutral). This helper retries on 429 / 5xx / missing-``choices`` with exponential backoff, paces
calls to stay under the rate limit, and surfaces an honest marker only after exhausting retries.
"""

from __future__ import annotations

import time

import httpx

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def groq_chat(
    client: httpx.Client,
    api_key: str,
    model: str,
    system: str,
    user: str,
    *,
    max_tokens: int = 512,
    temperature: float = 0.7,
    max_retries: int = 5,
    base_pace_s: float = 1.5,
    error_tag: str = "call-error",
) -> str:
    """One chat completion, with retry/backoff on rate-limits + a small inter-call pace.

    Returns the assistant text, or ``[<error_tag>: …]`` only after ``max_retries`` genuine
    failures (so a degenerate call is rare AND visibly tagged, never silently identical-to-its-pair).
    """
    time.sleep(base_pace_s)  # pace: stay under the rate limit on a tight loop
    last = "unknown"
    for attempt in range(max_retries):
        try:
            r = client.post(
                _GROQ_URL,
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
            data = r.json()
            if "choices" in data and data["choices"]:
                msg = data["choices"][0].get("message", {})
                text = (msg.get("content") or "").strip()
                if not text:  # reasoning models (e.g. gpt-oss) put output in 'reasoning'
                    text = (msg.get("reasoning") or "").strip()
                if text:
                    return text
                last = "empty content+reasoning"  # a failed call, NOT a silent '' (would fake a 0% leak)
            else:
                last = f"no-choices: {str(data)[:120]}"
            time.sleep(min(2.0 ** attempt, 10.0))
        except Exception as exc:  # network blip etc.
            last = str(exc)
            time.sleep(min(2.0 ** attempt, 10.0))
    return f"[{error_tag}: exhausted {max_retries} retries — {last}]"
