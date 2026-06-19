"""Featherless OSS-model sweep runner — with Slack notifications so nobody has to babysit it.

Runs ``scripts/reproduce/scan_endpoint.py`` against the Featherless OpenAI-compatible endpoint for one
or more models. It ALWAYS pings Slack (``SLACK_WEBHOOK_URL``) at start, after each model, on
completion, AND on any crash — so a silent stall or error can't go unnoticed for hours. The same
runner does the cheap smoke and the full overnight sweep; only the flags change.

Featherless is flat-fee/unmetered (the constraint is concurrency, not tokens), so cost lives in the
JUDGE calls. The smoke uses ``--corpus fixtures`` (3 golden primitives) → ~n_trials×3 judge calls.

Smoke (cheap, stateless, no DB writes):
    uv run python scripts/sweep/run_featherless_sweep.py --smoke

Full sweep (per-model, persisted to the leaderboard DB):
    uv run python scripts/sweep/run_featherless_sweep.py \
        --models mistralai/Mistral-7B-Instruct-v0.3 Qwen/Qwen2.5-72B-Instruct ... \
        --corpus db --limit 100 --n-trials 3 --persist

Notifications: set ``SLACK_WEBHOOK_URL`` in ``.env``. Without it, messages print to stdout instead
(so the runner never hard-fails on a missing webhook).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

_FL_BASE = "https://api.featherless.ai/v1"
_SCAN = _ROOT / "scripts" / "reproduce" / "scan_endpoint.py"
# Notification channels. The webhook in .env was a dead PLACEHOLDER (`.../services/...`) — pings to it
# 404'd silently. The bot token (xoxb-, chat.postMessage) is the verified-working channel, so we
# PREFER it; the webhook is only a fallback when it's a real URL (not the placeholder).
_SLACK_BOT = os.environ.get("SLACK_BOT_TOKEN", "").strip().strip('"').strip("'")
_SLACK_CHANNEL = os.environ.get("SLACK_ALERT_CHANNEL", "#security").strip() or "#security"
_SLACK = os.environ.get("SLACK_WEBHOOK_URL", "").strip().strip('"').strip("'")
_WEBHOOK_OK = _SLACK.startswith("https://hooks.slack.com/services/") and "..." not in _SLACK
_FL_KEY = os.environ.get("FEATHERLESS_API_KEY", "").strip()

# A safe smoke default: a small, recognizable, official 8B verified to serve 200s on Featherless
# (Mistral-7B-Instruct-v0.3 is in the catalog + "available_on_current_plan" but 400s on every call —
# a Featherless-side quirk — so don't use it).
_SMOKE_MODELS = ["meta-llama/Meta-Llama-3.1-8B-Instruct"]


def _target_call_health(stderr: str) -> tuple[int, int]:
    """(ok, err) counts of TARGET (Featherless) chat-completions calls, parsed from httpx logs.

    The pipeline SKIPS errored trials, so a scan where every target call 400/500s still prints
    "0/N breached (0%)" — a fake success. Counting the actual HTTP statuses lets the runner catch
    that 'all calls errored' case and alert instead of reporting green."""
    lines = [ln for ln in stderr.splitlines() if "featherless.ai" in ln and "chat/completions" in ln]
    ok = sum(1 for ln in lines if 'HTTP/1.1 2' in ln)
    err = sum(1 for ln in lines if 'HTTP/1.1 4' in ln or 'HTTP/1.1 5' in ln)
    return ok, err


def slack(text: str) -> None:
    """Deliver one alert. Prefers the Slack BOT TOKEN (chat.postMessage → #security), which is the
    verified-working channel; falls back to the webhook only if it's a real URL. Never raises. If NO
    channel works it prints `[NO WORKING SLACK CHANNEL]` loudly — a notify failure must be visible,
    not silent (a silent webhook is exactly how alerts get lost)."""
    if _SLACK_BOT.startswith("xox"):
        try:
            req = urllib.request.Request(
                "https://slack.com/api/chat.postMessage",
                data=json.dumps({"channel": _SLACK_CHANNEL, "text": text}).encode("utf-8"),
                headers={"Authorization": f"Bearer {_SLACK_BOT}", "Content-Type": "application/json"},
            )
            resp = json.loads(urllib.request.urlopen(req, timeout=10).read())  # noqa: S310
            if resp.get("ok"):
                return
            print(f"[slack chat.postMessage NOT ok: {resp.get('error')}] {text}", flush=True)
        except Exception as e:  # pragma: no cover - best-effort notify
            print(f"[slack bot failed: {e}] {text}", flush=True)
    if _WEBHOOK_OK:
        try:
            req = urllib.request.Request(
                _SLACK,
                data=json.dumps({"text": text}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=10).read()  # noqa: S310
            return
        except Exception as e:  # pragma: no cover
            print(f"[slack webhook failed: {e}] {text}", flush=True)
    print(f"[NO WORKING SLACK CHANNEL] {text}", flush=True)


def _breach_line(stdout: str) -> str:
    """Pull the human breach-rate summary line out of scan_endpoint's stdout (best-effort)."""
    for ln in reversed(stdout.splitlines()):
        low = ln.lower()
        if "breach" in low and "%" in ln:
            return ln.strip()[:300]
    # fall back to the report's "Scanned ... : N% breach" summary
    for ln in reversed(stdout.splitlines()):
        if "scanned" in ln.lower():
            return ln.strip()[:300]
    return ""


def run_one(
    model: str, corpus: str, n_trials: int, limit: int, persist: bool, timeout_s: int,
    deep_flags: list[str] | None = None, pack: str | None = None,
) -> tuple[int, str, str, float]:
    cmd = [
        sys.executable, str(_SCAN), _FL_BASE,
        "--model", model, "--api-key", _FL_KEY,
        "--corpus", corpus, "--n-trials", str(n_trials),
    ]
    if pack:
        cmd += ["--pack", pack, "--limit", str(limit)]
    elif corpus == "db":
        cmd += ["--limit", str(limit)]
    if persist:
        cmd += ["--persist", "--config-name", f"fl-{model.split('/')[-1]}"]
    if deep_flags:
        cmd += deep_flags
    t0 = time.time()
    try:
        proc = subprocess.run(  # noqa: S603
            cmd, capture_output=True, text=True, cwd=str(_ROOT), timeout=timeout_s
        )
        return proc.returncode, proc.stdout, proc.stderr, time.time() - t0
    except subprocess.TimeoutExpired as e:
        # A hung model emits no completion event, so the loop would stall forever and never notify.
        # Kill it, surface a non-zero rc + a clear timeout marker (the rc!=0 branch alerts Slack).
        out = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode("utf-8", "replace")
        err = e.stderr if isinstance(e.stderr, str) else (e.stderr or b"").decode("utf-8", "replace")
        return 124, out, err + f"\n[TIMEOUT after {timeout_s}s — model killed]", time.time() - t0


def main() -> None:
    ap = argparse.ArgumentParser(description="Featherless OSS-model sweep with Slack notifications.")
    ap.add_argument("--smoke", action="store_true", help="1 model, fixtures corpus, no DB writes")
    ap.add_argument("--models", nargs="*", default=None, help="Featherless model ids")
    ap.add_argument("--corpus", default=None, choices=("db", "fixtures"))
    ap.add_argument("--n-trials", type=int, default=None)
    ap.add_argument("--limit", type=int, default=100, help="max primitives when --corpus db")
    ap.add_argument("--persist", action="store_true", help="write results into the leaderboard DB")
    ap.add_argument("--timeout", type=int, default=7200, help="per-model timeout in seconds (default 2h)")
    ap.add_argument("--models-file", default=None, help="JSON file of [{model:...}] to sweep (e.g. featherless_models.json)")
    ap.add_argument("--pack", default=None, help="bundled attack pack (default/aggressive/compliance) — the right corpus for bare models")
    ap.add_argument("--deep", action="store_true", help="deep scan (persona + multi-turn; +PAIR/escalation unless capped)")
    ap.add_argument("--pair-max-iters", type=int, default=3, help="PAIR cap under --deep (0 disables PAIR)")
    ap.add_argument("--no-escalate", action="store_true", help="under --deep, skip the escalation ladder")
    args = ap.parse_args()

    if args.smoke:
        models = args.models or _SMOKE_MODELS
        corpus = args.corpus or "fixtures"
        n_trials = args.n_trials or 3
        persist = False
    else:
        models = args.models
        corpus = args.corpus or "db"
        n_trials = args.n_trials or 3
        persist = args.persist

    # Load the verified model list from a JSON file ([{"model": "..."}], e.g. featherless_models.json).
    if not models and args.models_file:
        entries = json.loads(Path(args.models_file).read_text(encoding="utf-8"))
        models = [e["model"] if isinstance(e, dict) else e for e in entries]

    deep_flags: list[str] = []
    if args.deep:
        deep_flags = ["--deep", "--pair-max-iters", str(args.pair_max_iters)]
        if args.no_escalate:
            deep_flags.append("--no-escalate")

    if not models:
        print("no --models given (or use --smoke / --models-file)", file=sys.stderr)
        sys.exit(2)
    if not _FL_KEY:
        slack(":x: ROGUE Featherless sweep: FEATHERLESS_API_KEY missing — aborted before any calls.")
        sys.exit(2)

    label = "SMOKE" if args.smoke else "sweep"
    depth = "deep" if args.deep else "single-shot+multi-turn"
    slack(
        f":hourglass_flowing_sand: ROGUE Featherless {label} started — "
        f"{len(models)} model(s) · corpus={corpus} · n_trials={n_trials} · {depth}"
        f"{' · persist' if persist else ''}"
    )

    results: list[tuple[str, str]] = []
    try:
        for i, model in enumerate(models, 1):
            rc, out, err, dt = run_one(
                model, corpus, n_trials, args.limit, persist, args.timeout, deep_flags, args.pack
            )
            ok_calls, err_calls = _target_call_health(err)
            all_errored = ok_calls == 0 and err_calls > 0  # every target call 4xx/5xx → fake "0%"
            if rc != 0 or all_errored:
                if all_errored:
                    reason = (
                        f"all {err_calls} target calls errored (HTTP 4xx/5xx) — the '0% breach' is "
                        f"FAKE; model likely unservable/misconfigured on Featherless"
                    )
                    tail = err[-900:]
                else:
                    reason = f"rc={rc}"
                    tail = (err or out)[-1100:]
                slack(f":x: [{i}/{len(models)}] *{model}* FAILED ({dt:.0f}s) — {reason}\n```{tail}```")
                results.append((model, "FAILED"))
            else:
                summary = _breach_line(out) or "completed (no breach line parsed)"
                health = f" · {ok_calls} ok/{err_calls} err calls" if err_calls else ""
                slack(f":white_check_mark: [{i}/{len(models)}] *{model}* ({dt:.0f}s) — {summary}{health}")
                results.append((model, summary))
            # Echo to the runner's own stdout/log too (for the agent / `check progress`).
            print(f"\n===== {model} · rc={rc} · {dt:.0f}s =====", flush=True)
            print(out[-2500:], flush=True)
            if err.strip():
                print("--- stderr tail ---\n" + err[-800:], flush=True)

        ok = sum(1 for _, s in results if s != "FAILED")
        fails = [m for m, s in results if s == "FAILED"]
        msg = f":checkered_flag: ROGUE Featherless {label} complete — {ok}/{len(models)} ok"
        if fails:
            msg += "\nfailed: " + ", ".join(fails)
        slack(msg)
        sys.exit(0 if not fails else 1)
    except Exception:
        tb = traceback.format_exc()
        slack(f":rotating_light: ROGUE Featherless {label} CRASHED (the runner itself)\n```{tb[-1500:]}```")
        print(tb, file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
