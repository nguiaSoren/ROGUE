"""Local, pre-network validation (Deliverable 10).

Catch the obvious mistakes — missing model, empty prompt, bad API key, malformed base URL —
*locally*, with a precise message, before spending a network round-trip to be told the same thing.
Raises :class:`~rogue.exceptions.ValidationError` (or :class:`RogueConfigError` for client config).
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from ..exceptions import RogueConfigError, ValidationError

# A model id is provider-prefixed or bare: "gpt-5", "openai/gpt-5", "anthropic/claude-opus-4-8".
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]*(/[A-Za-z0-9][A-Za-z0-9._\-]*)?$")


def validate_api_key(api_key: object) -> str:
    """Validate an API key shape. Returns it stripped; raises RogueConfigError otherwise."""
    if not isinstance(api_key, str) or not api_key.strip():
        raise RogueConfigError(
            "No API key. Pass Rogue(api_key=...) or set the ROGUE_API_KEY environment variable."
        )
    return api_key.strip()


def validate_base_url(base_url: object) -> str:
    """Validate a base URL is http(s) with a host. Returns it normalized (no trailing slash)."""
    if not isinstance(base_url, str) or not base_url.strip():
        raise RogueConfigError("base_url must be a non-empty string.")
    parsed = urlparse(base_url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise RogueConfigError(f"base_url must be an http(s) URL with a host, got {base_url!r}.")
    return base_url.strip().rstrip("/")


def validate_model_id(model: object, *, field: str = "model") -> str:
    """Validate a model identifier's shape. Returns it; raises ValidationError otherwise."""
    if not isinstance(model, str) or not model.strip():
        raise ValidationError("model is required (e.g. 'gpt-5' or 'anthropic/claude-opus-4-8').",
                              field=field)
    m = model.strip()
    if len(m) < 2 or len(m) > 100 or not _MODEL_RE.match(m):
        raise ValidationError(
            f"model {model!r} is not a valid identifier "
            "(letters/digits/.-_ , optional single 'provider/model' prefix).",
            field=field,
        )
    return m


def validate_deployment(
    *,
    name: object,
    model: object,
    system_prompt: object = None,
    tools: object = None,
    forbidden_topics: object = None,
) -> None:
    """Validate the fields of a deployment-to-register. Aggregates every problem into one error."""
    problems: list[str] = []
    bad_fields: list[str] = []

    if not isinstance(name, str) or not name.strip():
        problems.append("name is required and must be a non-empty string")
        bad_fields.append("name")
    elif len(name) > 100:
        problems.append("name must be at most 100 characters")
        bad_fields.append("name")

    try:
        validate_model_id(model)
    except ValidationError as e:
        problems.append(str(e))
        bad_fields.append("model")

    if system_prompt is not None:
        if not isinstance(system_prompt, str):
            problems.append("system_prompt must be a string")
            bad_fields.append("system_prompt")
        elif len(system_prompt) > 10_000:
            problems.append("system_prompt must be at most 10,000 characters")
            bad_fields.append("system_prompt")

    for fname, val in (("tools", tools), ("forbidden_topics", forbidden_topics)):
        if val is None:
            continue
        if not isinstance(val, (list, tuple)) or not all(isinstance(x, str) for x in val):
            problems.append(f"{fname} must be a list of strings")
            bad_fields.append(fname)

    if problems:
        raise ValidationError("; ".join(problems), fields=bad_fields)


__all__ = [
    "validate_api_key",
    "validate_base_url",
    "validate_model_id",
    "validate_deployment",
]
