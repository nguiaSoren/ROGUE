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
import time
import tomllib
from pathlib import Path
from typing import Any

from rogue import Client

_DEFAULT_CONFIG_NAMES = ("rogue.yaml", "rogue.toml")

# Bundled, committed fixtures for the keyless `rogue try` demo (see _cmd_try).
_DATA_DIR = Path(__file__).resolve().parent / "data"
_TRY_PACK_PATH = _DATA_DIR / "demo_try_pack.json"
_DEMO_STATS_PATH = _DATA_DIR / "demo_stats.json"

# Locked brand colors (VIRAL_LAUNCH_SPEC) for the terminal demo. ANSI, since `rich` is not a dep.
_C_GREEN = "\033[38;2;0;255;136m"  # #00ff88 — defended
_C_RED = "\033[38;2;255;0;60m"  # #ff003c — breach
_C_DIM = "\033[2m"
_C_BOLD = "\033[1m"
_C_RESET = "\033[0m"


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


def _resolve_system_prompt(args: argparse.Namespace, target: dict) -> str:
    """The target system prompt: ``--system-prompt`` > ``--system-prompt-file`` > config > ``""``."""
    sp = getattr(args, "system_prompt", None)
    if sp is not None:
        return sp
    spf = getattr(args, "system_prompt_file", None)
    if spf:
        return Path(spf).read_text(encoding="utf-8")
    return target.get("system_prompt", "") if isinstance(target, dict) else ""


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

    return Client(
        endpoint=endpoint,
        api_key=api_key,
        provider=provider,
        model=model,
        system_prompt=_resolve_system_prompt(args, target),
    )


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


def _emit_scan_card(report: Any, args: argparse.Namespace, out: Any) -> None:
    """Drop the shareable breach card for a real scan (same artifact as ``rogue try``).

    Skipped on ``--no-card`` or ``--json`` (machine output). Never fails the scan — a card-render
    error is reported but swallowed. ``tier`` reflects the judge used (heuristic→quick, calibrated)."""
    if getattr(args, "no_card", False) or getattr(args, "json", False):
        return
    try:
        from datetime import datetime, timezone

        from rogue.report_card import render_breach_card

        top = getattr(report, "top_attack", None)
        top = top() if callable(top) else top
        fams = getattr(report, "families_covered", None)
        fams = list(fams()) if callable(fams) else []
        card = {
            "model_label": getattr(report, "target", None) or "scanned-model",
            "breach_rate": float(getattr(report, "breach_rate", 0.0) or 0.0),
            "trials": int(getattr(report, "n_tests", 0) or 0),
            "breaches": int(getattr(report, "n_breaches", 0) or 0),
            "top_attack": top or "",
            "families": fams,
            "verdict_counts": {},
            "tier": "calibrated" if getattr(args, "judge", "") == "calibrated" else "quick",
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
        out_dir = Path(getattr(args, "out_dir", None) or "rogue-scan")
        paths = render_breach_card(card, out_dir)
        print("\n  shareable card saved:", file=out)
        for k in ("svg", "png", "html"):
            if paths.get(k):
                print(f"    {paths[k]}", file=out)
    except Exception as exc:  # noqa: BLE001 — a card-render failure must never fail the scan
        print(f"  (shareable card not generated: {exc})", file=out)


# --- subcommand handlers ----------------------------------------------------------------------


def _cmd_validate(args: argparse.Namespace, out: Any) -> int:
    client = _build_client(args)
    result = client.validate()
    _emit(result, as_json=args.json, out=out)
    return 0


def _resolve_judge(args: argparse.Namespace, out: Any) -> Any:
    """The judge object for a scan, per ``--judge`` (default ``heuristic``).

    ``heuristic`` → the keyless :class:`HeuristicJudge` (no key, network-free). ``calibrated`` →
    ``None``, which lets the scan path build the calibrated LLM ``JudgeAgent`` (today's behavior).
    On the keyless default with no judge key present, prints a one-line upgrade hint.
    """
    import os

    judge_choice = getattr(args, "judge", "heuristic") or "heuristic"
    if judge_choice == "calibrated":
        return None  # scan path builds the calibrated v3 JudgeAgent (unchanged behavior)
    from rogue.reproduce.heuristic_judge import HeuristicJudge

    # Friendly note only when running keyless (no judge/openai key) — don't nag a configured user.
    # Goes to stderr so it never pollutes `--json` machine output on stdout.
    if not (os.environ.get("OPENAI_API_KEY") or os.environ.get("JUDGE_API_KEY")):
        print(
            f"{_C_DIM}quick scan (keyless heuristic judge) — add a judge key + "
            f"`--judge calibrated` for the calibrated v3 judge{_C_RESET}",
            file=sys.stderr,
        )
    return HeuristicJudge()


def _cmd_scan(args: argparse.Namespace, out: Any) -> int:
    persist = getattr(args, "persist", False)
    config_name = getattr(args, "config_name", None)
    deep = getattr(args, "deep", False)

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
                system_prompt=_resolve_system_prompt(args, target),
                n_trials=n_trials,
                judge=_resolve_judge(args, out),
                deep=deep,
                persist=True,
                database_url=database_url,
                config_id=slug,
                config_name=config_name,
            )
        )
        if args.output:
            Path(args.output).write_text(report.to_markdown(), encoding="utf-8")
        _emit(report, as_json=args.json, out=out)
        _emit_scan_card(report, args, out)
        return 0

    # Non-persist path: delegate to Client.scan (stateless, no DB write).
    client = _build_client(args)
    # Tiered judge: heuristic (keyless, default) or the calibrated v3 JudgeAgent. The Client passes
    # `_judge` straight to run_scan; None means run_scan builds the calibrated JudgeAgent itself.
    client._judge = _resolve_judge(args, out)
    attacks = [a.strip() for a in args.attacks.split(",") if a.strip()] if args.attacks else None
    if deep:
        # Deep scan threads `deep=True` into run_scan (persona-wrap + the multi-turn/escalation
        # seams). Client.scan has no deep flag, so call run_scan directly with the client's resolved
        # config/judge — same stateless path, just with the extra stages enabled.
        import asyncio

        from rogue.packs import filter_attacks, load_pack
        from rogue.scan import run_scan

        pack = _scan_default(args, "pack", "default")
        primitives = filter_attacks(load_pack(pack), attacks)[: _scan_default(args, "max_tests", 100)]
        report = asyncio.run(
            run_scan(
                client.config,
                primitives,
                n_trials=_scan_default(args, "n_trials", 1),
                budget=_scan_default(args, "budget", None),
                adapter_extra=client._adapter_extra,
                judge=client._judge,
                judge_model=client._judge_model,
                deep=True,
            )
        )
    else:
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
    _emit_scan_card(report, args, out)
    return 0


# --- `rogue try` — the keyless hero command ----------------------------------------------------


def _color(enabled: bool, code: str, text: str) -> str:
    """Wrap ``text`` in an ANSI ``code`` when color is ``enabled``, else return it plain."""
    return f"{code}{text}{_C_RESET}" if enabled else text


def _verdict_style(verdict_value: str) -> tuple[str, str, bool]:
    """(symbol, color-code, is_breach) for a JudgeVerdict value — green defended / red breach."""
    from rogue.schemas.breach_result import JudgeVerdict

    breach = verdict_value in (JudgeVerdict.PARTIAL_BREACH.value, JudgeVerdict.FULL_BREACH.value)
    if breach:
        return "✗ BREACH", _C_RED, True
    if verdict_value == JudgeVerdict.REFUSED.value:
        return "✓ DEFENDED", _C_GREEN, False
    return "○ EVADED", _C_GREEN, False  # engagement without transfer — held, not breached


def _cmd_try(args: argparse.Namespace, out: Any) -> int:
    """The flagship keyless demo: a real ATTACKER→MODEL→JUDGE pipeline over a BUNDLED mock pack and
    BUNDLED canned responses, graded live by the keyless :class:`HeuristicJudge`, ending by overlaying
    ROGUE's REAL measured per-model breach rates. Zero keys, zero network, ~15s. Emits a share card."""
    import json
    import os

    from rogue.reproduce.heuristic_judge import HeuristicJudge

    color = sys.stdout.isatty() and out is sys.stdout and not os.environ.get("NO_COLOR")
    fast = bool(getattr(args, "fast", False))

    def pause(secs: float) -> None:
        if not fast:
            time.sleep(secs)

    def c(code: str, text: str) -> str:
        return _color(color, code, text)

    pack = json.loads(_TRY_PACK_PATH.read_text(encoding="utf-8"))
    attacks = pack["attacks"]
    target_label = pack.get("target_label", "demo-model (mock)")

    print(file=out)
    print(c(_C_BOLD, "  ROGUE · try") + c(_C_DIM, "   the red-team that never sleeps"), file=out)
    print(
        c(_C_DIM, f"  keyless demo · {len(attacks)} attacks · mock target · live heuristic judge"),
        file=out,
    )
    print(file=out)
    print(c(_C_DIM, f"  ATTACKER  →  MODEL ({target_label})  →  JUDGE"), file=out)
    print(file=out)

    judge = HeuristicJudge()
    findings: list[dict] = []
    families: list[str] = []
    n_breach = 0
    for i, atk in enumerate(attacks, 1):
        family = atk["family"]
        title = atk.get("title", family)
        families.append(family)
        # ATTACKER: send the attack.
        print(f"  [{i}/{len(attacks)}] {c(_C_BOLD, title)}", file=out)
        print(c(_C_DIM, f"      → {_one_line(atk['attack_prompt'], 72)}"), file=out)
        pause(0.35)
        # MODEL: canned response (the mock target).
        print(c(_C_DIM, "      … model responding"), file=out)
        pause(0.45)
        # JUDGE: real keyless grading of the (attack, response, goal) triple.
        result = judge.judge_sync(atk["attack_prompt"], atk["model_response"], goal=atk.get("goal"))
        symbol, code, is_breach = _verdict_style(result.verdict.value)
        if is_breach:
            n_breach += 1
        print(f"      {c(code, symbol)}  {c(_C_DIM, '· ' + _one_line(result.rationale, 64))}", file=out)
        print(file=out)
        findings.append({"family": family, "title": title, "verdict": result.verdict.value, "breach": is_breach})
        pause(0.2)

    n = len(attacks)
    rate = n_breach / n if n else 0.0
    bar = _breach_bar(rate, color)
    rate_code = _C_RED if rate > 0 else _C_GREEN
    print(c(_C_BOLD, "  ── RESULT ──"), file=out)
    print(
        f"  {c(rate_code, f'{n_breach}/{n} BREACHED')}  {bar}  {c(rate_code, f'{round(rate * 100)}%')}",
        file=out,
    )
    top = next((f["title"] for f in findings if f["breach"]), None)
    print(c(_C_DIM, f"  top attack: {top or '— none breached'}"), file=out)
    print(file=out)

    # --- the overlay: ROGUE's REAL measured per-model breach rates ----------------------------
    _print_real_stats(out, color)

    # --- emit the shareable card --------------------------------------------------------------
    card_paths: dict[str, Any] = {}
    if not getattr(args, "no_card", False):
        from datetime import datetime, timezone

        from rogue.report_card import render_breach_card

        verdict_counts: dict[str, int] = {}
        for f in findings:
            verdict_counts[f["verdict"]] = verdict_counts.get(f["verdict"], 0) + 1
        card = {
            "model_label": target_label,
            "breach_rate": rate,
            "trials": n,
            "breaches": n_breach,
            "top_attack": top,
            "families": families,
            "verdict_counts": verdict_counts,
            "tier": "quick",
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
        out_dir = Path(getattr(args, "out_dir", None) or "rogue-try")
        try:
            card_paths = render_breach_card(card, out_dir)
            print(c(_C_BOLD, "  shareable card saved:"), file=out)
            print(c(_C_GREEN, f"    {card_paths['svg']}"), file=out)
            if card_paths.get("png"):
                print(c(_C_GREEN, f"    {card_paths['png']}"), file=out)
            print(c(_C_DIM, f"    {card_paths['html']}  (open to screenshot/share)"), file=out)
            print(file=out)
        except Exception as exc:  # never let a render hiccup fail the demo
            print(c(_C_DIM, f"  (card render skipped: {exc})"), file=out)
            print(file=out)

    # --- one-line next step -------------------------------------------------------------------
    print(
        c(_C_BOLD, "  scan your own model: ")
        + c(_C_GREEN, "rogue scan --provider openai --model gpt-5.4-nano"),
        file=out,
    )
    print(file=out)

    if getattr(args, "json", False):
        import json as _j

        print(
            _j.dumps(
                {
                    "target": target_label,
                    "n_tests": n,
                    "n_breaches": n_breach,
                    "breach_rate": round(rate, 4),
                    "top_attack": top,
                    "tier": "quick",
                    "findings": findings,
                    "card": {k: str(v) if v else None for k, v in card_paths.items()},
                },
                indent=2,
            ),
            file=out,
        )
    return 0


def _one_line(text: str, n: int) -> str:
    """Collapse whitespace and clip to ``n`` chars (so a multi-line payload stays one tidy line)."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= n else flat[: n - 1].rstrip() + "…"


def _breach_bar(rate: float, color: bool, width: int = 20) -> str:
    """A small green/red breach-rate bar: red filled to the rate, green for the defended remainder."""
    filled = max(0, min(width, round(rate * width)))
    # With color, red/green carry the split; without it (pipes, CI, plain terminals, screenshots)
    # fall back to distinct glyphs so the proportion stays legible — solid = breached, light = defended.
    red = _color(color, _C_RED, "█" * filled)
    green = _color(color, _C_GREEN, "█" * (width - filled)) if color else "░" * (width - filled)
    return f"[{red}{green}]"


def _print_real_stats(out: Any, color: bool) -> None:
    """Overlay ROGUE's REAL measured per-model breach rates from the bundled fixture — the
    "here's what this looks like against 8 real models" close."""
    import json

    def c(code: str, text: str) -> str:
        return _color(color, code, text)

    stats = json.loads(_DEMO_STATS_PATH.read_text(encoding="utf-8"))
    models = stats.get("models", [])
    total = stats.get("total_trials", sum(m.get("n_trials", 0) for m in models))
    print(
        c(_C_BOLD, f"  ── ROGUE vs {len(models)} REAL models ──")
        + c(_C_DIM, f"   {total:,} calibrated-judge trials"),
        file=out,
    )
    print(c(_C_DIM, "  the same families, measured live against production models:"), file=out)
    print(file=out)
    for m in models:
        rate = float(m.get("mean_breach_rate", 0.0))
        bar = _breach_bar(rate, color, width=16)
        code = _C_RED if rate >= 0.1 else _C_GREEN
        label = m.get("model_label", "?")
        trials = int(m.get("n_trials", 0))
        print(
            f"    {label:<26.26s} {bar} {c(code, f'{round(rate * 100):>3d}%')}"
            f"  {c(_C_DIM, f'n={trials:,}')}",
            file=out,
        )
    print(file=out)
    print(
        c(_C_DIM, f"  source: {stats.get('source', 'ROGUE all-time matrix')} · {stats.get('judge', 'calibrated v3 judge')}"),
        file=out,
    )
    print(c(_C_DIM, "  full board → rogue-eosin.vercel.app/leaderboard"), file=out)
    print(file=out)


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
        "--system-prompt",
        dest="system_prompt",
        default=None,
        metavar="TEXT",
        help="the target's system prompt — red-team YOUR exact deployment, not a bare model",
    )
    p.add_argument(
        "--system-prompt-file",
        dest="system_prompt_file",
        default=None,
        metavar="PATH",
        help="read the system prompt from a file (alternative to --system-prompt)",
    )
    p.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="config file (YAML or TOML); default ./rogue.yaml or ./rogue.toml if present",
    )
    p.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of a summary")


def _cmd_setup(args: argparse.Namespace, out: Any) -> int:
    """Install the best free scraper on demand: crawl4ai + its Chromium (and --pdf for local PDF).

    Keeps the base ``pip install rogue-live-redteam`` lean — crawl4ai pulls ~37 deps + needs a Chromium
    download that pip can't do, so it's an opt-in one-command upgrade instead of a core dependency.
    """
    import shutil
    import subprocess

    pip_pkgs = ["crawl4ai"]
    if args.pdf:
        pip_pkgs.append("pymupdf4llm")

    pip_cmd = [sys.executable, "-m", "pip", "install", *pip_pkgs]
    browser_cmd: list[str] | None = None
    if not args.no_browser:
        setup_bin = shutil.which("crawl4ai-setup")
        browser_cmd = [setup_bin] if setup_bin else [sys.executable, "-m", "playwright", "install", "chromium"]

    if args.dry_run:
        print("# rogue setup would run:", file=out)
        print("#   " + " ".join(pip_cmd), file=out)
        if browser_cmd:
            print("#   " + " ".join(browser_cmd) + "   (download Chromium for crawl4ai)", file=out)
        return 0

    print(f"[rogue setup] installing {', '.join(pip_pkgs)} …", file=out)
    if subprocess.run(pip_cmd).returncode != 0:
        print("[rogue setup] pip install failed — see output above.", file=out)
        return 1

    if browser_cmd:
        print("[rogue setup] downloading Chromium for crawl4ai …", file=out)
        if subprocess.run(browser_cmd).returncode != 0:
            print("[rogue setup] browser download failed — run `crawl4ai-setup` manually.", file=out)

    try:
        from rogue.harvest.fetchers.crawl4ai import Crawl4AIFetcher

        if Crawl4AIFetcher.is_available():
            print("[rogue setup] crawl4ai ready ✓ — it now leads UNLOCK/BROWSER in the harvest.", file=out)
        else:
            print("[rogue setup] crawl4ai installed; browser not detected — run `crawl4ai-setup`.", file=out)
    except Exception:  # noqa: BLE001
        print("[rogue setup] crawl4ai installed (restart your shell, then `rogue try`).", file=out)
    return 0


def _cmd_harvest(args: argparse.Namespace, out: Any) -> int:
    """Run the open-web harvest (scrape → extract → dedupe → persist).

    The harvest *orchestrator* lives in ``scripts/harvest/harvest_once.py``, which is NOT bundled in
    the pip wheel (only ``src/rogue`` ships). So this command runs the pipeline when invoked from a
    repo clone, and — honestly — tells a pip-only user to clone the repo otherwise, rather than
    pretending to harvest. Scraping is free/keyless; extraction calls an LLM you choose
    (``--extraction-model``), so set the matching provider key (e.g. ``OPENAI_API_KEY``).
    """
    import os
    import subprocess

    repo_root = Path(__file__).resolve().parents[2]  # src/rogue/cli.py → repo root
    script = repo_root / "scripts" / "harvest" / "harvest_once.py"
    if not script.exists():
        print(
            "rogue harvest: the open-web harvest pipeline isn't bundled in the pip package "
            "(only the scan/try engine is). Run it from a repo clone:\n"
            "  git clone https://github.com/nguiaSoren/ROGUE && cd ROGUE\n"
            "  rogue harvest --since 1d --extraction-model openai/gpt-5.4-nano\n"
            "Scraping is free/keyless; extraction needs an LLM key for the provider you pick.",
            file=out,
        )
        return 2

    cmd = [sys.executable, str(script), "--since", args.since]
    if args.extraction_model:
        cmd += ["--extraction-model", args.extraction_model]
    if args.database_url:
        cmd += ["--database-url", args.database_url]
    if args.x_only:
        cmd += ["--x-only"]
    if args.multimodal_only:
        cmd += ["--multimodal-only"]

    # The script may import sibling `scripts.*` modules — put the repo root on PYTHONPATH and run
    # from there, the same contract as `uv run python scripts/harvest/harvest_once.py`.
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root) + os.pathsep + env.get("PYTHONPATH", "")
    print(f"[rogue harvest] {' '.join(cmd[1:])}", file=out)
    return subprocess.call(cmd, cwd=str(repo_root), env=env)


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
    p_scan.add_argument(
        "--judge",
        choices=("heuristic", "calibrated"),
        default="heuristic",
        help="grader: 'heuristic' (keyless, default) or 'calibrated' (LLM v3 judge — needs a key)",
    )
    p_scan.add_argument(
        "--deep",
        action="store_true",
        default=False,
        help=(
            "opt-in deep scan: adds persona-wrap (a persuasion frame per attack) on top of true "
            "multi-turn back-and-forth, plus the PAIR + escalation seams. COSTS MORE — many more "
            "model calls (and an LLM persona-wrap call per attack) than the default fast scan"
        ),
    )
    p_scan.add_argument("--output", default=None, metavar="PATH", help="write report to .html or .json")
    p_scan.add_argument("--no-card", dest="no_card", action="store_true", help="skip the shareable breach card")
    p_scan.add_argument("--out-dir", dest="out_dir", default=None, metavar="DIR", help="where to write the breach card (default: ./rogue-scan)")
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

    p_try = sub.add_parser(
        "try",
        help="keyless ~15s demo: run a mock attack pipeline, then show ROGUE's real 8-model stats",
    )
    p_try.add_argument(
        "--out-dir",
        dest="out_dir",
        default=None,
        metavar="DIR",
        help="where to write the shareable breach card (default: ./rogue-try)",
    )
    p_try.add_argument("--no-card", dest="no_card", action="store_true", help="skip writing the share card")
    p_try.add_argument("--fast", action="store_true", help="no inter-step delays (for tests/CI)")
    p_try.add_argument("--json", action="store_true", help="emit a machine-readable JSON summary at the end")
    p_try.set_defaults(func=_cmd_try)

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

    p_setup = sub.add_parser(
        "setup",
        help="install the best free scraper: crawl4ai + its Chromium (one command; keeps base install lean)",
    )
    p_setup.add_argument("--pdf", action="store_true", help="also install local PDF parsing (pymupdf4llm)")
    p_setup.add_argument("--no-browser", dest="no_browser", action="store_true", help="skip the one-time Chromium download")
    p_setup.add_argument("--dry-run", dest="dry_run", action="store_true", help="print the commands without running them")
    p_setup.set_defaults(func=_cmd_setup)

    p_harvest = sub.add_parser(
        "harvest",
        help="run the open-web harvest (scrape → extract → dedupe → persist) — needs a repo clone + an LLM extraction key",
    )
    p_harvest.add_argument("--since", default="1d", help="time window to harvest (e.g. '1d', '14d', '6h'). Default: 1d.")
    p_harvest.add_argument("--extraction-model", default=None,
                           help="provider-prefixed extraction model, e.g. 'openai/gpt-5.4-nano' (default: anthropic/claude-haiku-4-5)")
    p_harvest.add_argument("--database-url", default=None, help="SQLAlchemy URL (default: $DATABASE_URL)")
    p_harvest.add_argument("--x-only", action="store_true", help="harvest only X/Twitter handles")
    p_harvest.add_argument("--multimodal-only", action="store_true", help="harvest only the multimodal SERP arms")
    p_harvest.set_defaults(func=_cmd_harvest)

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
