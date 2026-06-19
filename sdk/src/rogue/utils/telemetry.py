"""Opt-in, anonymous usage telemetry for the ROGUE SDK (Deliverable 12).

Telemetry is **disabled by default** and only activates when the customer
explicitly opts in — either by calling ``Rogue.enable_telemetry()`` or by
setting the ``ROGUE_TELEMETRY`` environment variable to a truthy value.

Privacy guarantees (enforced in code, see ``_sanitize``):

* **Anonymous.** The only stable identifier is ``client_id`` — a random
  per-machine UUID with no link to any account, API key, or customer identity.
* **No customer data, ever.** A payload may contain ONLY: ``event``,
  ``sdk_version``, ``python_version``, ``os``, ``client_id``, ``ts``, and the
  caller-supplied ``**fields`` after sanitization. ``_sanitize`` drops any value
  that is not a plain scalar (``int``/``float``/``str``/``bool``) and any key
  whose name resembles a secret or content field (contains ``key``, ``token``,
  ``secret``, ``prompt``, ``password``, ``credential``, ``authorization``).
  Long strings are truncated to 120 chars. Prompts, system prompts, API keys,
  deployment content, model responses, and secret-bearing URLs can therefore
  never reach the wire.
* **Best-effort & crash-proof.** ``emit`` never raises and never blocks a
  customer call: it returns immediately and the network POST happens on a daemon
  thread with a short timeout, swallowing every exception. When disabled, ``emit``
  is a pure no-op (no thread, no import of ``httpx``).
* **Kill-switches honored.** ``ROGUE_TELEMETRY=0/false/off`` and the de-facto
  standard ``DO_NOT_TRACK=1`` / ``ROGUE_DO_NOT_TRACK=1`` force telemetry off,
  even if another variable would have enabled it.
"""

from __future__ import annotations

import os
import platform
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from . import config

DEFAULT_ENDPOINT = "https://telemetry.rogue.dev/v1/events"

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}

# Substrings that mark a field key as sensitive (content or secret) — dropped.
_SENSITIVE_KEY_PARTS = (
    "key",
    "token",
    "secret",
    "prompt",
    "password",
    "credential",
    "authorization",
)

_MAX_STR_LEN = 120
_CLIENT_ID_KEY = "telemetry_client_id"
_POST_TIMEOUT = 2.0


def _env_truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in _TRUTHY


def _env_falsy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in _FALSY


def _sanitize(fields: dict[str, Any]) -> dict[str, Any]:
    """Keep only safe scalars under safe key names. Never lets customer data through.

    Drops: non-scalar values, sensitive-looking keys, and the reserved payload
    keys. Truncates long strings to ``_MAX_STR_LEN`` chars.
    """
    reserved = {"event", "sdk_version", "python_version", "os", "client_id", "ts"}
    clean: dict[str, Any] = {}
    for key, value in fields.items():
        if not isinstance(key, str):
            continue
        if key in reserved:
            continue
        lowered = key.lower()
        if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
            continue
        # bool must be checked before int (bool is a subclass of int).
        if isinstance(value, bool):
            clean[key] = value
        elif isinstance(value, (int, float)):
            clean[key] = value
        elif isinstance(value, str):
            clean[key] = value[:_MAX_STR_LEN]
        # everything else (dict/list/bytes/objects/None) is dropped.
    return clean


def _persisted_client_id() -> str | None:
    """Read the stable client_id from credentials.json, or None."""
    try:
        value = config.load_credentials().get(_CLIENT_ID_KEY)
        return value if isinstance(value, str) and value else None
    except Exception:  # pragma: no cover - defensive
        return None


def _persist_client_id(client_id: str) -> None:
    """Best-effort persist of the client_id alongside other credentials.

    Reuses ``config.config_dir()`` / ``credentials.json`` so the id is stable
    per machine. Any failure is swallowed (the caller falls back to ephemeral).
    """
    import json
    import stat

    d = config.config_dir()
    d.mkdir(parents=True, exist_ok=True)
    data = config.load_credentials()
    data[_CLIENT_ID_KEY] = client_id
    path = config.credentials_path()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:  # pragma: no cover - non-POSIX
        pass


def _resolve_client_id() -> str:
    """Return a stable per-machine anonymous id, persisting a fresh one if needed.

    Never raises: on any persistence failure, returns an ephemeral per-process id.
    """
    existing = _persisted_client_id()
    if existing:
        return existing
    new_id = uuid.uuid4().hex
    try:
        _persist_client_id(new_id)
    except Exception:
        # Could not persist — still return a usable (ephemeral) id this process.
        pass
    return new_id


def _default_sender(endpoint: str) -> Callable[[dict[str, Any]], None]:
    """Build a sender that POSTs a payload to ``endpoint`` via lazy-imported httpx."""

    def _send(payload: dict[str, Any]) -> None:
        try:
            import httpx  # lazy: never imported on the disabled / no-op path

            httpx.post(endpoint, json=payload, timeout=_POST_TIMEOUT)
        except Exception:  # network, import, anything — telemetry is best-effort
            pass

    return _send


class Telemetry:
    """Anonymous, opt-in, best-effort telemetry emitter.

    See module docstring for the privacy guarantees. ``emit`` never raises and
    never blocks; when ``enabled`` is False it is a pure no-op.
    """

    def __init__(
        self,
        enabled: bool,
        *,
        endpoint: str | None = None,
        sdk_version: str = "",
        client_id: str | None = None,
        sender: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.endpoint = endpoint or DEFAULT_ENDPOINT
        self.sdk_version = sdk_version
        self._sender = sender
        # Only resolve/persist a client_id when telemetry is actually on, so a
        # disabled instance has zero side effects.
        if not self.enabled:
            self.client_id = client_id
        elif client_id:
            self.client_id = client_id
        else:
            try:
                self.client_id = _resolve_client_id()
            except Exception:  # pragma: no cover - defensive
                self.client_id = uuid.uuid4().hex

    @classmethod
    def from_env(cls, *, sdk_version: str = "") -> Telemetry:
        """Construct from environment. Disabled unless explicitly opted in.

        Enabled iff ``ROGUE_TELEMETRY`` is truthy AND no kill-switch is set.
        Kill-switches: ``ROGUE_TELEMETRY`` falsy, ``DO_NOT_TRACK``,
        ``ROGUE_DO_NOT_TRACK``.
        """
        env = os.environ
        rogue_telemetry = env.get("ROGUE_TELEMETRY")
        do_not_track = _env_truthy(env.get("DO_NOT_TRACK")) or _env_truthy(
            env.get("ROGUE_DO_NOT_TRACK")
        )
        enabled = (
            _env_truthy(rogue_telemetry)
            and not _env_falsy(rogue_telemetry)
            and not do_not_track
        )
        endpoint = env.get("ROGUE_TELEMETRY_ENDPOINT") or None
        return cls(enabled=enabled, endpoint=endpoint, sdk_version=sdk_version)

    def emit(self, event: str, **fields: Any) -> None:
        """Fire an event. Best-effort: returns immediately, never raises.

        No-op when disabled (no thread spawned, no httpx import).
        """
        if not self.enabled:
            return
        try:
            payload = self._build_payload(event, fields)
            sender = self._sender
            if sender is not None:
                # Injected sender (tests / custom) runs synchronously.
                sender(payload)
            else:
                self._dispatch_async(payload)
        except Exception:  # telemetry must NEVER break a customer call
            pass

    def _build_payload(self, event: str, fields: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event": str(event),
            "sdk_version": self.sdk_version,
            "python_version": platform.python_version(),
            "os": platform.system(),
            "client_id": self.client_id,
            "ts": datetime.now(UTC).isoformat(),
        }
        payload.update(_sanitize(fields))
        return payload

    def _dispatch_async(self, payload: dict[str, Any]) -> None:
        import threading

        sender = _default_sender(self.endpoint)
        thread = threading.Thread(
            target=sender, args=(payload,), name="rogue-telemetry", daemon=True
        )
        thread.start()


__all__ = ["Telemetry"]
