"""The ``rogue`` command-line interface — a thin shell over the SDK :class:`~rogue.Client`.

Everything the CLI does is delegated to the (synchronous) ``Client``: ``rogue validate`` /
``rogue scan`` / ``rogue benchmark`` build a client from flags + an optional config file and call the
matching method, then render the returned report object. ``rogue report`` re-renders a previously
saved scan JSON without re-scanning.

Target/output flags are global (accepted on every subcommand)::

    rogue validate   --provider openai
    rogue scan       --endpoint https://gw/v1 --api-key sk-... --budget 10 --output report.html
    rogue benchmark  --provider anthropic --dataset advbench_100 --max-goals 25
    rogue report     scan.json --output scan.html

Config file (``--config PATH``, else ``./rogue.yaml`` or ``./rogue.toml`` if present)::

    target:
      endpoint: https://...
      api_key: ...
      provider: openai
      model: ...
    scan:
      budget: 10
      max_tests: 50
      pack: default

Explicit CLI flags override config-file values. Supported formats: YAML (``.yaml``) and TOML
(``.toml``); YAML is parsed with PyYAML when available, else a tiny built-in reader handles the
simple two-level ``section:\n  key: value`` shape documented above.

Persist to the dashboard DB (opt-in)::

    rogue scan --endpoint https://gw/v1 --model my-model --persist --config-name "my-bot"

With ``--persist`` every judged trial is written to the dashboard DB (``$DATABASE_URL`` or the local
dev Postgres), so ``/matrix``, ``/feed``, and ``/brief`` populate with YOUR data.
``--config-name`` is required when ``--persist`` is set; the subcommand then routes through
``scan_endpoint`` directly rather than the SDK ``Client.scan`` path.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path
from typing import Any

from rogue import Client

_DEFAULT_CONFIG_NAMES = ("rogue.yaml", "rogue.toml")


# --- config-file loading ----------------------------------------------------------------------


def _coerce(key: str, value: Any) -> Any:
    """Coerce ``budget``/``max_tests`` from the hand-rolled string reader to numbers."""
    if not isinstance(value, str):
        return value
    if key in ("budget",):
        try:
            return float(value)
        except ValueError:
            return value
    if key in ("max_tests", "n_trials", "max_goals"):
        try:
            return int(value)
        except ValueError:
            return value
    return value


def _parse_simple_yaml(text: str) -> dict[str, dict[str, Any]]:
    """Parse the documented two-level ``section:\\n  key: value`` shape (no PyYAML available).

    Only the documented config shape is supported: top-level sections, two-space-indented
    ``key: value`` pairs, ``#`` comments, surrounding quotes stripped.
    """
    out: dict[str, dict[str, Any]] = {}
    section: str | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line[0].isspace():
            # top-level "section:"
            name = line.strip().rstrip(":").strip()
            section = name
            out.setdefault(section, {})
        else:
            if section is None or ":" not in line:
                continue
            key, _, value = line.strip().partition(":")
            key = key.strip()
            value = value.strip().strip("'\"")
            out[section][key] = _coerce(key, value)
    return out


def _load_config(explicit: str | None) -> dict[str, dict[str, Any]]:
    """Load a config file. ``explicit`` wins; else the first present default in cwd; else ``{}``."""
    path: Path | None = None
    if explicit:
        path = Path(explicit)
        if not path.exists():
            raise FileNotFoundError(f"config file not found: {explicit}")
    else:
        for name in _DEFAULT_CONFIG_NAMES:
            cand = Path(name)
            if cand.exists():
                path = cand
                break
    if path is None:
        return {}

    text = path.read_text(encoding="utf-8")
    if path.suffix == ".toml":
        return tomllib.loads(text)
    # .yaml / .yml / anything else → YAML
    try:
        import yaml  # type: ignore
    except ImportError:
        return _parse_simple_yaml(text)
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"config file {path} did not parse to a mapping")
    return data


# --- client construction ----------------------------------------------------------------------


def _build_client(args: argparse.Namespace) -> Client:
    """Build a :class:`Client` from CLI flags, falling back to the config-file ``target`` section."""
    cfg = _load_config(getattr(args, "config", None))
    target = cfg.get("target", {}) if isinstance(cfg.get("target"), dict) else {}

    endpoint = args.endpoint if args.endpoint is not None else target.get("endpoint")
    api_key = args.api_key if args.api_key is not None else target.get("api_key")
    provider = args.provider if args.provider is not None else target.get("provider")
    model = args.model if args.model is not None else target.get("model")

    # Stash the resolved scan section so scan() can read its defaults.
    args._scan_cfg = cfg.get("scan", {}) if isinstance(cfg.get("scan"), dict) else {}

    return Client(endpoint=endpoint, api_key=api_key, provider=provider, model=model)


def _scan_default(args: argparse.Namespace, key: str, fallback: Any) -> Any:
    """Resolve a scan parameter: explicit CLI value wins, else config ``scan.<key>``, else fallback."""
    cli_val = getattr(args, key, None)
    if cli_val is not None:
        return cli_val
    cfg = getattr(args, "_scan_cfg", {}) or {}
    if key in cfg:
        return _coerce(key, cfg[key])
    return fallback


# --- output helpers ---------------------------------------------------------------------------


def _write_output(report: Any, output: str) -> None:
    """Write a report to ``output`` choosing renderer by file extension (.html → HTML, else JSON)."""
    suffix = Path(output).suffix.lower()
    if suffix in (".html", ".htm"):
        report.to_html(output)
    else:
        report.to_json(output)


def _emit(report: Any, *, as_json: bool, out: Any) -> None:
    """Print a report to stdout — machine JSON with ``--json`` else the human summary."""
    print(report.to_json() if as_json else report.summary(), file=out)


# --- subcommand handlers ----------------------------------------------------------------------


def _cmd_validate(args: argparse.Namespace, out: Any) -> int:
    client = _build_client(args)
    result = client.validate()
    _emit(result, as_json=args.json, out=out)
    return 0


def _cmd_scan(args: argparse.Namespace, out: Any) -> int:
    persist = getattr(args, "persist", False)
    config_name = getattr(args, "config_name", None)

    if persist:
        # Persist path: route directly through scan_endpoint so every judged trial lands in
        # breach_results and /matrix /feed /brief populate with the user's own data.
        # Client.scan goes through the SDK's run_scan, which has no persistence hook, so we
        # bypass it here and call scan_endpoint directly with the pack primitives.
        import asyncio
        import os
        import re

        from rogue.packs import filter_attacks, load_pack
        from rogue.reproduce.endpoint_scan import scan_endpoint

        if not config_name:
            print("error: --config-name NAME is required when --persist is set", file=sys.stderr)
            return 1

        cfg = _load_config(getattr(args, "config", None))
        target = cfg.get("target", {}) if isinstance(cfg.get("target"), dict) else {}
        endpoint = args.endpoint if args.endpoint is not None else target.get("endpoint")
        api_key = args.api_key if args.api_key is not None else target.get("api_key")
        model = args.model if args.model is not None else target.get("model") or "default"

        if not endpoint:
            print("error: --endpoint is required for --persist scans", file=sys.stderr)
            return 1

        args._scan_cfg = cfg.get("scan", {}) if isinstance(cfg.get("scan"), dict) else {}
        pack = _scan_default(args, "pack", "default")
        max_tests = _scan_default(args, "max_tests", 100)
        n_trials = _scan_default(args, "n_trials", 1)
        attacks = [a.strip() for a in args.attacks.split(",") if a.strip()] if args.attacks else None
        primitives = filter_attacks(load_pack(pack), attacks)[:max_tests]

        database_url = os.environ.get("DATABASE_URL", "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue")
        slug = re.sub(r"[^a-z0-9]+", "-", config_name.lower()).strip("-")[:80] or "endpoint-scan"

        report = asyncio.run(
            scan_endpoint(
                endpoint,
                model,
                primitives,
                api_key=api_key,
                n_trials=n_trials,
                persist=True,
                database_url=database_url,
                config_id=slug,
                config_name=config_name,
            )
        )
        if args.output:
            Path(args.output).write_text(report.to_markdown(), encoding="utf-8")
        _emit(report, as_json=args.json, out=out)
        return 0

    # Non-persist path: delegate to Client.scan (stateless, no DB write).
    client = _build_client(args)
    attacks = [a.strip() for a in args.attacks.split(",") if a.strip()] if args.attacks else None
    report = client.scan(
        attacks=attacks,
        max_tests=_scan_default(args, "max_tests", 100),
        budget=_scan_default(args, "budget", None),
        pack=_scan_default(args, "pack", "default"),
        n_trials=_scan_default(args, "n_trials", 1),
    )
    if args.output:
        _write_output(report, args.output)
    _emit(report, as_json=args.json, out=out)
    return 0


def _cmd_benchmark(args: argparse.Namespace, out: Any) -> int:
    client = _build_client(args)
    report = client.benchmark(
        dataset=args.dataset,
        max_goals=args.max_goals,
    )
    _emit(report, as_json=args.json, out=out)
    return 0


def _cmd_report(args: argparse.Namespace, out: Any) -> int:
    import json
    from dataclasses import fields as _dc_fields

    from rogue.report import Finding, ScanReport

    data = json.loads(Path(args.path).read_text(encoding="utf-8"))
    # `to_dict()` emits render-time extras (e.g. `remediation`) beyond the Finding dataclass fields;
    # keep only the real fields so reconstruction tolerates a richer serialized report.
    _fkeys = {f.name for f in _dc_fields(Finding)}
    findings = [Finding(**{k: v for k, v in f.items() if k in _fkeys}) for f in data.get("findings", [])]
    report = ScanReport(
        target=data["target"],
        n_tests=data["n_tests"],
        n_breaches=data["n_breaches"],
        cost_usd=data["cost_usd"],
        findings=findings,
    )
    if args.output:
        _write_output(report, args.output)
    _emit(report, as_json=args.json, out=out)
    return 0


# --- argument parser --------------------------------------------------------------------------


def _add_target_flags(p: argparse.ArgumentParser) -> None:
    """Global target/output flags, accepted on every subcommand."""
    p.add_argument("--endpoint", default=None, help="OpenAI-compatible target endpoint URL")
    p.add_argument("--api-key", dest="api_key", default=None, help="API key (else provider env var)")
    p.add_argument("--provider", default=None, help="known provider: openai/anthropic/openrouter/gemini/groq")
    p.add_argument("--model", default=None, help="target model (optional)")
    p.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="config file (YAML or TOML); default ./rogue.yaml or ./rogue.toml if present",
    )
    p.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of a summary")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rogue", description="ROGUE red-team SDK command-line interface.")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_validate = sub.add_parser("validate", help="cheap pre-flight: is the target reachable/authed?")
    _add_target_flags(p_validate)
    p_validate.set_defaults(func=_cmd_validate)

    p_scan = sub.add_parser("scan", help="run an attack pack against the target")
    _add_target_flags(p_scan)
    p_scan.add_argument("--attacks", default=None, help="comma-separated attack families/names")
    p_scan.add_argument("--max-tests", dest="max_tests", type=int, default=None, help="cap on attacks run")
    p_scan.add_argument("--budget", type=float, default=None, help="stop after this many USD of target-call cost")
    p_scan.add_argument("--pack", default=None, help="bundled attack pack (default: default)")
    p_scan.add_argument("--n-trials", dest="n_trials", type=int, default=None, help="trials per attack")
    p_scan.add_argument("--output", default=None, metavar="PATH", help="write report to .html or .json")
    p_scan.add_argument(
        "--persist",
        action="store_true",
        default=False,
        help="write judged trial rows to the dashboard DB so /matrix /feed /brief show YOUR data",
    )
    p_scan.add_argument(
        "--config-name",
        dest="config_name",
        default=None,
        metavar="NAME",
        help="human-readable deployment label (required with --persist); slugified to a stable config_id",
    )
    p_scan.set_defaults(func=_cmd_scan)

    p_bench = sub.add_parser("benchmark", help="attack-success-rate against a standard dataset")
    _add_target_flags(p_bench)
    p_bench.add_argument("--dataset", default="advbench_100", help="benchmark dataset (default: advbench_100)")
    p_bench.add_argument("--max-goals", dest="max_goals", type=int, default=25, help="number of goals (default: 25)")
    p_bench.set_defaults(func=_cmd_benchmark)

    p_report = sub.add_parser("report", help="re-render a previously saved scan JSON")
    p_report.add_argument("path", help="path to a saved ScanReport JSON file")
    p_report.add_argument("--output", default=None, metavar="PATH", help="write to .html or .json (else print)")
    p_report.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of a summary")
    p_report.set_defaults(func=_cmd_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``rogue`` console script. Returns an exit code (0 ok, 1 error, 2 usage)."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help(sys.stderr)
        return 2

    try:
        return args.func(args, sys.stdout)
    except SystemExit:  # pragma: no cover - argparse already handled it
        raise
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
