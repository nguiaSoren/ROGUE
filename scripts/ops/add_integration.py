"""Ops/admin CLI: register an org's Slack/Jira integration once (secret stored encrypted).

Onboards a stored Integration so MCP tools reference it by NAME and the agent never handles the
raw credential. The secret (Slack webhook URL / Jira API token) is encrypted into the `secrets`
table via the `SecretStore`; the non-secret config (Jira base_url / project / email) is stored in
plaintext on the `integrations` row. Thereafter `send_slack_alert(scan_id, integration="slack-sec")`
/ `create_jira_ticket(scan_id, integration="jira-prod")` resolve the config + decrypt the secret
server-side — the LLM only ever sees the integration's NAME.

Run from the repo root against the target deployment's `DATABASE_URL`::

    # Slack: the webhook IS the secret.
    uv run python scripts/ops/add_integration.py --org org_123 --kind slack \
        --name slack-sec --webhook https://hooks.slack.com/services/XXX/YYY/ZZZ

    # Jira: base_url/project/email are config; the API token is the secret.
    uv run python scripts/ops/add_integration.py --org org_123 --kind jira \
        --name jira-prod --base-url https://acme.atlassian.net \
        --project SEC --email ops@acme.com --token <api-token>

Requires `SECRET_ENCRYPTION_KEY` (see `src/rogue/platform/secrets.py`) — without it there is no
encryption to store the secret behind, and the command refuses to run.

This connects to a real database ONLY when a human runs `main()` against `DATABASE_URL`. Importing
the module (or calling `add_integration` with a test store) opens no connection.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Defensive `src/` insert so the script runs even without the editable install on path.
_SRC = str(Path(__file__).resolve().parents[2] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import os  # noqa: E402

from rogue.platform.integration_store import build_postgres_integration_store  # noqa: E402
from rogue.platform.secrets import build_postgres_secret_store  # noqa: E402

DEFAULT_DATABASE_URL = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"


def add_integration(store, *, org_id: str, kind: str, name: str, config: dict, secret: str | None) -> str:
    """Register one stored integration; return its integration id.

    Thin core over `IntegrationStore.put`: the secret (if any) is encrypted via the store's
    `SecretStore`; `config` holds only non-secret fields. Re-registering the same `(org_id, name)`
    updates it in place (see `PostgresIntegrationStore.put`).
    """
    return store.put(org_id=org_id, kind=kind, name=name, config=config, secret=secret)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Register an org's Slack/Jira integration once (secret stored encrypted, never echoed)."
    )
    parser.add_argument("--org", required=True, help="Organization id that owns this integration.")
    parser.add_argument("--kind", required=True, choices=["slack", "jira"], help="Integration kind.")
    parser.add_argument("--name", required=True, help="Integration name MCP tools reference (e.g. slack-sec).")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        help="SQLAlchemy URL for the target deployment (default: $DATABASE_URL).",
    )
    # slack
    parser.add_argument("--webhook", default=None, help="[slack] Incoming-webhook URL (the secret).")
    # jira
    parser.add_argument("--base-url", default=None, help="[jira] Jira base URL (config).")
    parser.add_argument("--project", default=None, help="[jira] Jira project key (config).")
    parser.add_argument("--email", default=None, help="[jira] Jira account email (config).")
    parser.add_argument("--token", default=None, help="[jira] Jira API token (the secret).")
    args = parser.parse_args(argv)

    # Per-kind validation + (config, secret) shaping. Done before touching the DB so a bad invocation
    # fails fast and never leaves a half-built integration.
    if args.kind == "slack":
        if not args.webhook:
            parser.error("slack integrations require --webhook (the incoming-webhook URL)")
        config: dict = {}
        secret: str | None = args.webhook
    else:  # jira
        missing = [
            flag
            for flag, val in (
                ("--base-url", args.base_url),
                ("--project", args.project),
                ("--email", args.email),
                ("--token", args.token),
            )
            if not val
        ]
        if missing:
            parser.error("jira integrations require " + ", ".join(missing))
        # Key is `project_key` to match what create_jira_ticket reads from the resolved config.
        config = {"base_url": args.base_url, "project_key": args.project, "email": args.email}
        secret = args.token

    secret_store = build_postgres_secret_store()
    if secret_store is None:
        print("error: set SECRET_ENCRYPTION_KEY to store integration secrets", file=sys.stderr)
        return 1

    store = build_postgres_integration_store(secret_store, database_url=args.database_url)
    if store is None:  # only reached if the secret store vanished between the two builds
        print("error: set SECRET_ENCRYPTION_KEY to store integration secrets", file=sys.stderr)
        return 1

    iid = add_integration(store, org_id=args.org, kind=args.kind, name=args.name, config=config, secret=secret)

    print()
    print("=" * 72)
    print(f"  integration_id:  {iid}")
    print(f"  org:             {args.org}")
    print(f"  kind:            {args.kind}")
    print(f"  name:            {args.name}")
    print("  secret stored encrypted (not shown)")
    print("=" * 72)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
