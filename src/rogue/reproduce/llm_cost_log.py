"""Append-only CSV cost log for Anthropic LLM calls outside the target panel.

Sister of ``target_panel._estimate_cost`` (which logs panel costs as
``BreachResult.cost_usd``) and ``BrightDataCostLog`` (the DB table for BD
spend). This module covers the §10.7 augmentation LLM calls — persona wraps
and escalation plans — that don't have a natural row in either of the two
existing accounting surfaces:

  - panel cost ⇒ ``BreachResult.cost_usd``           (per-trial)
  - bright_data ⇒ ``BrightDataCostLog`` table         (per-fetch)
  - judge cost ⇒ ``_JUDGE_COST_ESTIMATE_PER_CALL_USD`` constant (per-call estimate)
  - **§10.7 wrap/plan ⇒ this CSV**                   (per-call exact, from
                                                     Anthropic's usage block)

Why CSV at the repo root (per CLAUDE.md's "Output" section): consistent with
the existing ``bright_data_cost_log.csv`` + ``llm_cost_log.csv`` pattern; the
file is .gitignored; a fresh run starts from an empty file. A spreadsheet/
duckdb/jq invocation can verify the augmentation-LLM total against an
Anthropic invoice in seconds.

Accuracy contract:
  - Per-call ``input_tokens`` / ``output_tokens`` come straight from the
    Anthropic API response's ``usage`` block — the same values Anthropic
    bills on. Cost is ``(in_tok × in_price + out_tok × out_price) / 1e6``
    with the published per-million-token prices below.
  - We log ONLY when the SDK returned a response object (i.e. tokens were
    actually consumed). Exceptions caught upstream (BadRequestError /
    APIStatusError) abort before we ever see token counts and are NOT logged
    — they typically aren't billed either.
  - We DO log refusals (short-stub responses) and JSON-parse failures — both
    consume tokens.
  - We do NOT account for Anthropic prompt-cache discounts (90% off cache
    reads). If your account has automatic caching enabled, the logged total
    can OVER-state actual spend by up to ~80% for the planner (which sends
    the same long system prompt repeatedly within ~5 min). Conservative
    direction — actual invoice ≤ logged total.

Schema (one row per real API call):

    timestamp_utc, module, operation, model, subject_id,
    input_tokens, output_tokens, cost_usd, refused, notes

Concurrency: ``append_row`` opens in ``'a'`` mode and writes one CSV line
per call. POSIX guarantees atomicity for single ``write()`` calls under
PIPE_BUF (4 KB) — our lines are well under that.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "ANTHROPIC_PRICE_PER_MILLION",
    "DEFAULT_LOG_PATH",
    "CSV_HEADER",
    "anthropic_call_cost_usd",
    "append_row",
    "log_anthropic_response",
]

_log = logging.getLogger(__name__)


# USD per 1,000,000 tokens. Pricing for the panel models also lives in
# `rogue.adapters.model_specs` (the canonical source since the Week-2 provider
# migration) — keep these in sync when Anthropic re-prices.
ANTHROPIC_PRICE_PER_MILLION: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    # Stretch / debug models (rare but used by demo overrides):
    "claude-opus-4-8": (15.00, 75.00),
}

# At repo root, .gitignored per `.gitignore` line 51 (matches CLAUDE.md's
# stated convention for `llm_cost_log.csv`).
DEFAULT_LOG_PATH = Path("llm_cost_log.csv")

CSV_HEADER = (
    "timestamp_utc",
    "module",
    "operation",
    "model",
    "subject_id",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "refused",
    "notes",
)


def anthropic_call_cost_usd(
    model: str, input_tokens: int, output_tokens: int,
) -> float:
    """Return USD cost for one Anthropic call. Unknown model ⇒ 0.0 + warn.

    Same "log and return zero" stance as `target_panel._estimate_cost`: an
    unknown model id (e.g. a stretch model used for a one-off demo) doesn't
    crash the run — the line just shows $0 in the log and an operator notices
    from the WARNING.
    """
    prices = ANTHROPIC_PRICE_PER_MILLION.get(model)
    if prices is None:
        _log.warning(
            "anthropic_call_cost_usd: no price entry for model %r — logging $0",
            model,
        )
        return 0.0
    in_price, out_price = prices
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000


def append_row(
    *,
    module: str,
    operation: str,
    model: str,
    subject_id: str,
    input_tokens: int,
    output_tokens: int,
    refused: bool,
    notes: str = "",
    path: Path = DEFAULT_LOG_PATH,
) -> None:
    """Append one row to the CSV log. Writes the header iff file is new.

    Safe to call from concurrent async tasks — single-write append is atomic
    on POSIX up to PIPE_BUF (4 KB), and our row size is well under that.
    Failures bubble up only as logged warnings — never raise into the caller
    (cost logging must never crash a reproduction run).
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not path.exists()
        cost_usd = anthropic_call_cost_usd(model, input_tokens, output_tokens)
        row = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "module": module,
            "operation": operation,
            "model": model,
            "subject_id": subject_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": f"{cost_usd:.6f}",
            "refused": "true" if refused else "false",
            "notes": notes,
        }
        with path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
            if write_header:
                writer.writeheader()
            writer.writerow(row)
    except OSError as exc:
        _log.warning("llm_cost_log append failed (%s): %s", path, exc)


def log_anthropic_response(
    response: Any,
    *,
    module: str,
    operation: str,
    model: str,
    subject_id: str,
    refused: bool,
    notes: str = "",
    path: Path = DEFAULT_LOG_PATH,
) -> tuple[int, int]:
    """Extract ``usage.input_tokens`` + ``usage.output_tokens`` from an Anthropic
    response and append a log row. Returns ``(input_tokens, output_tokens)``.

    Tolerant of a missing or empty ``usage`` block — defaults to (0, 0) and
    still writes the row so refusal-without-usage cases are visible in the
    log (they show as $0). Never raises.
    """
    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
    append_row(
        module=module,
        operation=operation,
        model=model,
        subject_id=subject_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        refused=refused,
        notes=notes,
        path=path,
    )
    return input_tokens, output_tokens
