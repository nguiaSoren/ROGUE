"""``rogue`` CLI entry point (Deliverable 9).

Pure stdlib argparse over the public SDK. Each subcommand resolves to a small handler that takes
the parsed args and a ready :class:`rogue.Rogue` client. The client is built once from the global
flags (``--api-key`` / ``--base-url`` / ``--mock``); when a ``transport`` is injected (tests),
that transport is used and ``--mock`` / ``--base-url`` are ignored.

Exit codes: ``0`` ok, ``1`` a :class:`RogueError` (printed as ``error: <msg>`` to stderr, never a
traceback), ``2`` argparse usage error.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from typing import Any

from .. import API_VERSION, MockTransport, Rogue, __version__
from ..client.rogue import DEFAULT_BASE_URL
from ..exceptions import RogueError
from ..transport.base import Transport
from ..utils import config

# --- small helpers --------------------------------------------------------------------------------


def _split_csv(value: str | None) -> list[str] | None:
    """Parse a ``a,b,c`` flag into a list, dropping blanks. ``None``/empty -> ``None``."""
    if not value:
        return None
    items = [piece.strip() for piece in value.split(",") if piece.strip()]
    return items or None


def _emit_json(obj: Any) -> None:
    """Print ``obj`` as JSON. Pydantic models are dumped in JSON mode; dicts/lists pass through."""
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump(mode="json")
    elif isinstance(obj, list):
        obj = [o.model_dump(mode="json") if hasattr(o, "model_dump") else o for o in obj]
    print(json.dumps(obj, indent=2, default=str))


def _build_client(args: argparse.Namespace, transport: Transport | None) -> Rogue:
    """Construct the single ``Rogue`` instance for this invocation from the global flags."""
    if transport is not None:
        return Rogue(api_key=args.api_key, transport=transport)
    if args.mock:
        return Rogue(api_key=args.api_key or "demo", transport=MockTransport())
    return Rogue(api_key=args.api_key, base_url=args.base_url)


# --- command handlers -----------------------------------------------------------------------------


def _cmd_login(args: argparse.Namespace, transport: Transport | None) -> int:
    key = args.api_key
    if not key:
        # Prefer a hidden prompt; fall back to a plain stdin read for non-tty/piped input.
        try:
            key = getpass.getpass("ROGUE API key: ")
        except (EOFError, KeyboardInterrupt):
            key = ""
        if not key:
            key = sys.stdin.readline().strip()
    if not key:
        raise RogueError("no API key provided")

    # Validate by actually authenticating (against the mock when --mock / injected transport).
    if transport is not None:
        client = Rogue(api_key=key, transport=transport)
    elif args.mock:
        client = Rogue(api_key=key, transport=MockTransport())
    else:
        client = Rogue(api_key=key, base_url=args.base_url)
    client.login()

    path = config.save_api_key(key, base_url=args.base_url)
    if args.json:
        _emit_json({"saved": True, "path": str(path)})
    else:
        print(f"Logged in. Credentials saved to {path}")
    return 0


def _cmd_logout(args: argparse.Namespace, transport: Transport | None) -> int:
    removed = config.clear_credentials()
    if args.json:
        _emit_json({"logged_out": True, "removed": removed})
    elif removed:
        print(f"Logged out. Removed {config.credentials_path()}")
    else:
        print("No stored credentials to remove.")
    return 0


def _cmd_status(args: argparse.Namespace, transport: Transport | None) -> int:
    # Status must work with no API key configured — it reports config, it doesn't authenticate.
    has_key = (args.api_key or os.environ.get("ROGUE_API_KEY") or config.load_api_key()) is not None
    if transport is not None:
        base_url = getattr(transport, "base_url", None)
    elif args.mock:
        base_url = "mock://in-memory"
    else:
        base_url = (
            args.base_url
            or os.environ.get("ROGUE_BASE_URL")
            or config.load_base_url()
            or DEFAULT_BASE_URL
        )
    info = {
        "sdk_version": __version__,
        "api_version": API_VERSION,
        "base_url": base_url,
        "api_key_configured": has_key,
    }
    if args.json:
        _emit_json(info)
    else:
        print(f"sdk_version:        {info['sdk_version']}")
        print(f"api_version:        {info['api_version']}")
        print(f"base_url:           {info['base_url']}")
        print(f"api_key_configured: {'yes' if has_key else 'no'}")
    return 0


def _cmd_deployment_create(args: argparse.Namespace, transport: Transport | None) -> int:
    client = _build_client(args, transport)
    dep = client.register(
        name=args.name,
        model=args.model,
        system_prompt=args.system_prompt,
        tools=_split_csv(args.tools),
        forbidden_topics=_split_csv(args.forbidden_topics),
    )
    if args.json:
        _emit_json(dep)
    else:
        print(f"Created deployment {dep.id}  ({dep.name} · {dep.model})")
    return 0


def _cmd_deployment_list(args: argparse.Namespace, transport: Transport | None) -> int:
    client = _build_client(args, transport)
    deployments = client.deployments.list()
    if args.json:
        _emit_json(deployments)
    elif not deployments:
        print("No deployments.")
    else:
        for dep in deployments:
            print(f"{dep.id}  {dep.name}  ({dep.model})")
    return 0


def _cmd_deployment_get(args: argparse.Namespace, transport: Transport | None) -> int:
    client = _build_client(args, transport)
    dep = client.deployments.get(args.id)
    if args.json:
        _emit_json(dep)
    else:
        print(f"id:      {dep.id}")
        print(f"name:    {dep.name}")
        print(f"model:   {dep.model}")
        if dep.system_prompt:
            print(f"system:  {dep.system_prompt}")
        if dep.tools:
            print(f"tools:   {', '.join(dep.tools)}")
        if dep.forbidden_topics:
            print(f"forbidden: {', '.join(dep.forbidden_topics)}")
    return 0


def _cmd_scan_start(args: argparse.Namespace, transport: Transport | None) -> int:
    client = _build_client(args, transport)
    scan = client.scan_async(args.deployment, n_trials=args.n_trials)
    if not args.wait:
        if args.json:
            _emit_json(scan)
        else:
            print(f"Started scan {scan.id}  status={scan.status.value}")
        return 0

    # --wait: poll to completion, then surface the report. Mock advances per-poll, so poll_interval
    # 0 keeps it instant; a real API needs a real interval.
    poll_interval = 0.0 if (args.mock or transport is not None) else 3.0
    scan.wait(poll_interval=poll_interval)
    report = scan.report()
    if args.json:
        _emit_json(report)
    else:
        print(f"Scan {scan.id} completed.")
        print(f"Risk score: {report.risk_score}/100 ({report.risk_level.value})")
        print(report.summary())
    return 0


def _cmd_scan_status(args: argparse.Namespace, transport: Transport | None) -> int:
    client = _build_client(args, transport)
    scan = client.scans.get(args.id)
    if args.json:
        _emit_json(scan)
    else:
        pct = round(scan.progress * 100)
        print(f"Scan {scan.id}  status={scan.status.value}  progress={pct}%")
    return 0


def _cmd_report_open(args: argparse.Namespace, transport: Transport | None) -> int:
    client = _build_client(args, transport)
    if args.scan:
        report = client.reports.for_scan(args.scan)
    elif args.id:
        report = client.reports.get(args.id)
    else:
        raise RogueError("provide a report id or --scan SCANID")

    fmt = args.format
    if fmt == "pdf" and not args.output:
        raise RogueError("pdf format requires --output PATH")

    if args.json or fmt == "json":
        if args.output:
            report.export_json(args.output)
            print(f"Wrote JSON report to {args.output}")
        else:
            _emit_json(report) if args.json else print(report.export_json())
        return 0

    if fmt == "pdf":
        path = report.export_pdf(args.output)
        print(f"Wrote PDF report to {path}")
        return 0

    # markdown (default)
    if args.output:
        report.export_markdown(args.output)
        print(f"Wrote Markdown report to {args.output}")
    else:
        print(report.export_markdown())
    return 0


# --- parser ---------------------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rogue", description="ROGUE red-team CLI.")
    parser.add_argument("--api-key", default=None, help="ROGUE API key (overrides stored/env).")
    parser.add_argument("--base-url", default=None, help="Hosted API base URL.")
    parser.add_argument(
        "--mock", action="store_true", help="Use an in-memory mock backend (offline/demo)."
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_login = sub.add_parser("login", help="Authenticate and store credentials.")
    # default=SUPPRESS so a subcommand-level flag doesn't clobber the global --api-key/--base-url
    # when omitted (argparse otherwise resets the parent's value to the subparser default).
    p_login.add_argument(
        "--api-key", default=argparse.SUPPRESS, help="API key (else prompted)."
    )
    p_login.add_argument(
        "--base-url", default=argparse.SUPPRESS, help="Hosted API base URL to store."
    )
    p_login.set_defaults(func=_cmd_login)

    p_logout = sub.add_parser("logout", help="Remove stored credentials.")
    p_logout.set_defaults(func=_cmd_logout)

    for name in ("status", "whoami"):
        p_status = sub.add_parser(name, help="Show SDK / API version and auth state.")
        p_status.set_defaults(func=_cmd_status)

    p_dep = sub.add_parser("deployment", help="Manage deployments.")
    dep_sub = p_dep.add_subparsers(dest="dep_command", metavar="<action>")

    p_dep_create = dep_sub.add_parser("create", help="Register a deployment.")
    p_dep_create.add_argument("--name", required=True, help="Human label.")
    p_dep_create.add_argument("--model", required=True, help="Model identifier.")
    p_dep_create.add_argument("--system-prompt", default=None, help="Deployed system prompt.")
    p_dep_create.add_argument("--tools", default=None, help="Comma-separated tool names.")
    p_dep_create.add_argument(
        "--forbidden-topics", default=None, help="Comma-separated forbidden topics."
    )
    p_dep_create.set_defaults(func=_cmd_deployment_create)

    p_dep_list = dep_sub.add_parser("list", help="List deployments.")
    p_dep_list.set_defaults(func=_cmd_deployment_list)

    p_dep_get = dep_sub.add_parser("get", help="Show one deployment.")
    p_dep_get.add_argument("id", help="Deployment id.")
    p_dep_get.set_defaults(func=_cmd_deployment_get)

    p_scan = sub.add_parser("scan", help="Start and inspect scans.")
    scan_sub = p_scan.add_subparsers(dest="scan_command", metavar="<action>")

    p_scan_start = scan_sub.add_parser("start", help="Start a red-team scan.")
    p_scan_start.add_argument("--deployment", required=True, help="Deployment id to scan.")
    p_scan_start.add_argument("--n-trials", type=int, default=5, help="Trials per attack.")
    p_scan_start.add_argument(
        "--wait", action="store_true", help="Block until done, then print the report."
    )
    p_scan_start.set_defaults(func=_cmd_scan_start)

    p_scan_status = scan_sub.add_parser("status", help="Show a scan's status.")
    p_scan_status.add_argument("id", help="Scan id.")
    p_scan_status.set_defaults(func=_cmd_scan_status)

    p_report = sub.add_parser("report", help="Fetch and export reports.")
    report_sub = p_report.add_subparsers(dest="report_command", metavar="<action>")

    p_report_open = report_sub.add_parser("open", help="Fetch a report (by id or --scan).")
    p_report_open.add_argument("id", nargs="?", default=None, help="Report id.")
    p_report_open.add_argument("--scan", default=None, help="Resolve via scan id instead.")
    p_report_open.add_argument(
        "--format", choices=("md", "json", "pdf"), default="md", help="Output format."
    )
    p_report_open.add_argument("--output", default=None, help="Write to this path.")
    p_report_open.set_defaults(func=_cmd_report_open)

    return parser


# --- entry point ----------------------------------------------------------------------------------


def main(argv: list[str] | None = None, *, transport: Transport | None = None) -> int:
    """Run the ``rogue`` CLI. Returns an exit code (0 ok, 1 RogueError, 2 usage)."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "func", None) is None:
        parser.print_help(sys.stderr)
        return 2

    try:
        return args.func(args, transport)
    except RogueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
