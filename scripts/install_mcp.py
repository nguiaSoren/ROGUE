"""One-command installer: register ROGUE's MCP server with an MCP client.

The manual path — hand-editing ``claude_desktop_config.json`` — is fiddly and
error-prone (a single missing comma silently disables the whole file). This
script does it safely and idempotently:

  * detects the client's config path for the current OS,
  * reads the existing config (preserving every other key + server),
  * merges in the ``rogue`` server entry pointing at THIS checkout,
  * backs up the old file before writing,
  * is a no-op if the entry is already present and correct.

Usage:

    uv run python scripts/install_mcp.py                 # Claude Desktop, stdio
    uv run python scripts/install_mcp.py --dry-run        # show, don't write
    uv run python scripts/install_mcp.py --client cursor  # Cursor instead

Then fully restart the client so it re-reads its config.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SERVER_NAME = "rogue"
REPO_ROOT = Path(__file__).resolve().parents[1]

# Per-client config locations. Each value is a callable returning the path for
# the current platform (None when that client has no known path on this OS).
# Cursor / Windsurf use the same `mcpServers` schema as Claude Desktop, so the
# merge logic is identical — only the file location differs.


def _claude_desktop_config() -> Path | None:
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        return Path(appdata) / "Claude/claude_desktop_config.json" if appdata else None
    # Linux / other
    return Path.home() / ".config/Claude/claude_desktop_config.json"


def _cursor_config() -> Path | None:
    # Cursor reads a global MCP config from the user home dir on every OS.
    return Path.home() / ".cursor/mcp.json"


def _windsurf_config() -> Path | None:
    return Path.home() / ".codeium/windsurf/mcp_config.json"


CLIENTS = {
    "claude-desktop": _claude_desktop_config,
    "cursor": _cursor_config,
    "windsurf": _windsurf_config,
}


def _server_entry() -> dict:
    """The mcpServers["rogue"] block — runs THIS checkout over stdio via uv."""
    return {
        "command": "uv",
        "args": [
            "--directory",
            str(REPO_ROOT),
            "run",
            "python",
            "-m",
            "rogue.mcp_server.server",
        ],
    }


def install(config_path: Path, *, dry_run: bool = False) -> int:
    entry = _server_entry()

    # Load existing config (preserve everything). Refuse to clobber a file we
    # can't parse — back off and tell the user rather than destroy their config.
    existing: dict = {}
    if config_path.exists():
        raw = config_path.read_text(encoding="utf-8").strip()
        if raw:
            try:
                existing = json.loads(raw)
            except json.JSONDecodeError as exc:
                print(
                    f"!! {config_path} exists but is not valid JSON ({exc}).\n"
                    "   Fix or remove it first — refusing to overwrite a config "
                    "I can't safely merge into.",
                    file=sys.stderr,
                )
                return 2
        if not isinstance(existing, dict):
            print(f"!! {config_path} is not a JSON object — refusing to merge.", file=sys.stderr)
            return 2

    servers = existing.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        print("!! existing 'mcpServers' is not an object — refusing to merge.", file=sys.stderr)
        return 2

    if servers.get(SERVER_NAME) == entry:
        print(f"✓ '{SERVER_NAME}' already registered in {config_path} — nothing to do.")
        return 0

    action = "update" if SERVER_NAME in servers else "add"
    servers[SERVER_NAME] = entry
    rendered = json.dumps(existing, indent=2)

    if dry_run:
        print(f"# dry-run: would {action} '{SERVER_NAME}' in {config_path}:\n")
        print(rendered)
        return 0

    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup = config_path.with_suffix(config_path.suffix + f".bak-{stamp}")
        backup.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"• backed up existing config → {backup}")

    config_path.write_text(rendered + "\n", encoding="utf-8")
    print(f"✓ {action}ed '{SERVER_NAME}' → {config_path}")
    print("→ Fully quit and reopen the client so it re-reads the config.")
    return 0


def uninstall(config_path: Path, *, dry_run: bool = False) -> int:
    """Remove the `rogue` entry from a client config (the inverse of install).

    Config-file MCP servers can't always be deleted from the client's UI — they
    live in this file — so this is how you remove the local `rogue` server.
    Leaves every other key/server untouched; no-op if it isn't present.
    """
    if not config_path.exists():
        print(f"✓ {config_path} doesn't exist — nothing to remove.")
        return 0
    raw = config_path.read_text(encoding="utf-8").strip()
    try:
        existing = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        print(f"!! {config_path} is not valid JSON ({exc}) — fix it first.", file=sys.stderr)
        return 2
    servers = existing.get("mcpServers")
    if not isinstance(servers, dict) or SERVER_NAME not in servers:
        print(f"✓ '{SERVER_NAME}' not in {config_path} — nothing to remove.")
        return 0

    del servers[SERVER_NAME]
    rendered = json.dumps(existing, indent=2)
    if dry_run:
        print(f"# dry-run: would remove '{SERVER_NAME}' from {config_path}:\n")
        print(rendered)
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = config_path.with_suffix(config_path.suffix + f".bak-{stamp}")
    backup.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"• backed up existing config → {backup}")
    config_path.write_text(rendered + "\n", encoding="utf-8")
    print(f"✓ removed '{SERVER_NAME}' → {config_path}")
    print("→ Fully quit and reopen the client so it drops the server.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client",
        choices=sorted(CLIENTS),
        default="claude-desktop",
        help="Which MCP client to register with (default: claude-desktop).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Override the config file path (mostly for testing).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resulting config instead of writing it.",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove the 'rogue' server from the client config instead of adding it.",
    )
    args = parser.parse_args()

    config_path = args.config or CLIENTS[args.client]()
    if config_path is None:
        print(f"!! no known {args.client} config path for this OS.", file=sys.stderr)
        return 2

    if args.uninstall:
        return uninstall(config_path, dry_run=args.dry_run)
    return install(config_path, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
