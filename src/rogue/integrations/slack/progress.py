"""`progress` / `status` Slack command — an on-demand pipeline snapshot posted back to the channel.

This is the *interactive* counterpart to the advisory path (:mod:`rogue.integrations.slack.inbound`):
where that one watches consented sandbox channels and pushes Tripwire/RedlineGuard advisories, this
one answers a direct operator question ("progress" / "status") in whatever channel it was asked —
typically the ops `#security` channel — with a compact read-only snapshot of the live pipeline:

  * corpus size (primitives / trials / breached trials),
  * harvest freshness (newest primitive ``discovered_at``), and
  * the open-source (``fl-*``) leaderboard extremes — most-permissive / most-resistant models, at the
    SAME primitive-level any-breach rate the public ``/leaderboard`` reports.

Two pieces, both side-effect-free at import:

  * :func:`is_progress_command` — a pure matcher (also tolerates a leading ``<@bot>`` mention), and
  * :func:`build_progress_report` — a synchronous psycopg READ that returns a Slack message payload.

The report is read-only (``select`` only) and never raises for an empty DB — it degrades to a "no
data yet" line. The FastAPI route schedules it on a background task (off the request path) and runs
the blocking query in a thread, so this module stays HTTP- and asyncio-agnostic.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

__all__ = ["is_progress_command", "build_progress_report"]

# Stats shape passed from the DB read to the pure formatter:
#   {"n_prim": int, "n_trials": int, "n_breached": int,
#    "latest": datetime | None,
#    "fl": [{"model": str, "np": int, "brp": int}, ...]}  # one per fl-* config

# Accept "progress" / "status" optionally prefixed by a bot mention ("<@U123> progress") and
# surrounded by whitespace. Deliberately strict (exact word) so normal chatter never triggers it.
_PROGRESS_RE = re.compile(r"^\s*(?:<@[A-Z0-9]+>\s*)?(?:progress|status)\b[\s.!?]*$", re.IGNORECASE)

_BREACH = ("partial_breach", "full_breach")


def is_progress_command(text: str) -> bool:
    """True iff ``text`` is the bare ``progress``/``status`` command (mention-prefix tolerated)."""
    return bool(_PROGRESS_RE.match(text or ""))


def _fmt_pct(x: float) -> str:
    return f"{round(x * 100):d}%"


def _query_stats(database_url: str) -> dict:
    """Read-only (``select`` only) pipeline snapshot from the DB. Synchronous (psycopg). Returns the
    stats dict the pure :func:`_format_report` consumes. On a hard connection error the exception
    propagates to the best-effort dispatcher, which logs and swallows it."""
    import psycopg

    url = database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url, connect_timeout=20) as conn:
        n_prim = conn.execute("select count(*) from attack_primitives").fetchone()[0]
        n_trials = conn.execute("select count(*) from breach_results").fetchone()[0]
        n_breached = conn.execute(
            "select count(*) from breach_results where verdict = any(%s)", (list(_BREACH),)
        ).fetchone()[0]
        latest = conn.execute("select max(discovered_at) from attack_primitives").fetchone()[0]
        # Primitive-level any-breach per fl-* (open-source) config — matches the public leaderboard:
        # a primitive counts as breached if ANY of its trials breached.
        fl = conn.execute(
            "select dc.target_model, "
            "count(distinct br.primitive_id) as np, "
            "count(distinct br.primitive_id) filter (where br.verdict = any(%s)) as brp "
            "from deployment_configs dc "
            "join breach_results br on br.deployment_config_id = dc.config_id "
            "where dc.config_id like 'fl-%%' "
            "group by dc.target_model "
            "having count(distinct br.primitive_id) > 0",
            (list(_BREACH),),
        ).fetchall()
    return {
        "n_prim": n_prim,
        "n_trials": n_trials,
        "n_breached": n_breached,
        "latest": latest,
        "fl": [{"model": tm.split("/")[-1], "np": np, "brp": brp} for tm, np, brp in fl],
    }


def _format_report(stats: dict) -> dict:
    """Pure formatter — turn a :func:`_query_stats` snapshot into a Slack ``chat.postMessage``
    payload. No I/O, so the layout (corpus line, harvest freshness, OSS extremes) is unit-testable
    offline. Degrades gracefully when there's no harvest yet / no fl-* results."""
    lines = ["📊 *ROGUE progress*"]
    lines.append(
        f"• Corpus: *{stats['n_prim']:,}* primitives · *{stats['n_trials']:,}* trials · "
        f"*{stats['n_breached']:,}* breached"
    )
    latest = stats.get("latest")
    if latest is not None:
        lines.append(f"• Latest harvest: *{latest:%Y-%m-%d %H:%M} UTC*")
    else:
        lines.append("• Latest harvest: _none yet_")

    fl = stats.get("fl") or []
    if fl:
        ranked = sorted(
            ({"model": r["model"], "rate": r["brp"] / r["np"]} for r in fl if r["np"] > 0),
            key=lambda r: r["rate"],
        )
        lines.append(
            f"• Open-source models scanned: *{len(ranked)}* (single-shot pack, primitive-level)"
        )
        most_permissive = ranked[-3:][::-1]
        most_resistant = ranked[:3]
        lines.append(
            "   _most permissive:_ "
            + " · ".join(f"{r['model']} {_fmt_pct(r['rate'])}" for r in most_permissive)
        )
        lines.append(
            "   _most resistant:_ "
            + " · ".join(f"{r['model']} {_fmt_pct(r['rate'])}" for r in most_resistant)
        )
    else:
        lines.append("• Open-source sweep: _no fl-* results yet_")

    return {"text": "\n".join(lines)}


def build_progress_report(database_url: str) -> dict:
    """Read a compact pipeline snapshot from the DB and return a Slack ``chat.postMessage`` payload.

    Read-only. Synchronous (psycopg) — the caller runs it in a thread off the event loop. Splits
    into a DB read (:func:`_query_stats`) + a pure formatter (:func:`_format_report`)."""
    return _format_report(_query_stats(database_url))
