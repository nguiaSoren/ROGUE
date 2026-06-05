"""Local credential + config storage (supports `rogue login` and api-key resolution).

Credentials live in ``$ROGUE_CONFIG_DIR`` (default ``~/.config/rogue/credentials.json``), written
with ``0600`` perms. This is the lowest-priority source for the API key — an explicit
``Rogue(api_key=...)`` or ``ROGUE_API_KEY`` env var always wins.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

_CREDENTIALS_FILE = "credentials.json"


def config_dir() -> Path:
    """The ROGUE config directory (``$ROGUE_CONFIG_DIR`` or ``~/.config/rogue``)."""
    override = os.environ.get("ROGUE_CONFIG_DIR")
    return Path(override) if override else Path.home() / ".config" / "rogue"


def credentials_path() -> Path:
    return config_dir() / _CREDENTIALS_FILE


def load_credentials() -> dict:
    """Return the stored credentials dict, or ``{}`` if none / unreadable."""
    path = credentials_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return {}


def save_api_key(api_key: str, *, base_url: str | None = None) -> Path:
    """Persist the API key (and optionally base URL) with ``0600`` perms. Returns the path."""
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    try:
        d.chmod(stat.S_IRWXU)  # 0700
    except OSError:  # pragma: no cover - non-POSIX
        pass
    data = load_credentials()
    data["api_key"] = api_key
    if base_url is not None:
        data["base_url"] = base_url
    path = credentials_path()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:  # pragma: no cover - non-POSIX
        pass
    return path


def load_api_key() -> str | None:
    return load_credentials().get("api_key")


def load_base_url() -> str | None:
    return load_credentials().get("base_url")


def clear_credentials() -> bool:
    """Delete the stored credentials file. Returns True if a file was removed."""
    path = credentials_path()
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


__all__ = [
    "config_dir",
    "credentials_path",
    "load_credentials",
    "save_api_key",
    "load_api_key",
    "load_base_url",
    "clear_credentials",
]
