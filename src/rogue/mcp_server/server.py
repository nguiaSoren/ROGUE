"""ROGUE MCP server — exposes the threat-intelligence DB as a Model Context
Protocol surface that Claude Desktop / Cursor / Windsurf can query directly.

This is the §6.2 / §11.2 "producer-side MCP" differentiator — ROGUE uses MCP
on BOTH sides of the harvest pipeline:

  * **Consumer**: ``DiscoveryAgent`` calls Bright Data's MCP server to
    discover novel attacks (handled in the harvest layer).
  * **Producer (this file)**: ROGUE exposes its OWN MCP server so any
    Claude-Desktop user can ask "what new attacks broke our customer
    support config in the last 24 hours?" and have Claude call our tools
    in-IDE.

Six tools (§6.2 spec, line 1067, + query_worst_attacks):

  query_attacks(family?, vector?, since_days?, limit?)   → list[AttackPrimitive]
  query_diff(date?)                                       → today vs yesterday diff
  query_threat_brief(date?, format?)                      → markdown threat brief
  query_breaches_for_config(deployment_config_id, ...)    → list[BreachResult]
  query_attack_detail(primitive_id)                       → primitive + linked breaches
  query_worst_attacks(model_family?, limit?)              → hardest-breaching attacks

Transport: stdio by default (the standard for Claude Desktop). Run via:

    uv run python -m rogue.mcp_server.server

For remote access (Cursor / Windsurf / a hosted client), serve the same tools
over HTTP on a dedicated port (8001, alongside the FastAPI dashboard on 8000):

    ROGUE_MCP_TRANSPORT=streamable-http uv run python -m rogue.mcp_server.server

(``ROGUE_MCP_TRANSPORT`` accepts ``stdio`` | ``sse`` | ``streamable-http``;
``ROGUE_MCP_PORT`` / ``ROGUE_MCP_HOST`` override the default 127.0.0.1:8001.)

Claude Desktop config (drop into `~/Library/Application Support/Claude/claude_desktop_config.json`):

    {
      "mcpServers": {
        "rogue": {
          "command": "uv",
          "args": ["--directory", "/Users/soren/Desktop/ROGUE",
                   "run", "python", "-m", "rogue.mcp_server.server"]
        }
      }
    }

Spec: ROGUE_PLAN.md §6.2 (tool surface) + §11.2 (Day-3 implementation),
§A.11 (server skeleton).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Load .env BEFORE importing anything that reads provider keys at module-init
# time (Anthropic/OpenAI SDKs). Mirrors `scripts/harvest_once.py`.
load_dotenv()

from mcp.server.fastmcp import FastMCP  # noqa: E402

from rogue.db.models import (  # noqa: E402
    AttackPrimitive as AttackPrimitiveORM,
    BreachResult as BreachResultORM,
)
from sqlalchemy import create_engine, select, text  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

logger = logging.getLogger("rogue.mcp_server")


DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"
)
THREAT_BRIEFS_DIR = Path("data/threat_briefs")


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


_engine = None
_SessionLocal = None


def _get_session() -> Session:
    """Lazy-init engine on first tool call. Keeps `import rogue.mcp_server.server`
    cheap + side-effect-free for tests."""
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_engine(_database_url(), pool_pre_ping=True, pool_recycle=300, pool_timeout=10)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    assert _SessionLocal is not None
    return _SessionLocal()


# --------------------------------------------------------------------------- #
# MCP server instance
# --------------------------------------------------------------------------- #


# `instructions` is the server-level description the MCP `initialize` response
# returns — it's what Claude Desktop / Cursor / VS Code show as the server's
# description (the config schemas themselves have no description field). Keep it
# tight: what ROGUE is, what the data is, and when to reach for each tool.
_INSTRUCTIONS = """\
ROGUE — continuous open-web LLM red-team. This server exposes ROGUE's live
threat-intelligence database: real jailbreak and prompt-injection attacks
harvested from 15+ open-web sources via Bright Data, reproduced against customer
deployment configs (model × system-prompt × tools), and graded by an independent
judge. All tools are READ-ONLY and return live data from the breach matrix.

When to use each tool:
• query_worst_attacks — the fast "am I exposed?" answer: the hardest-breaching
  attacks. When the user asks about "a model like me / you", pass YOUR OWN model
  identity (you know what you are — e.g. Claude Opus 4.8 → "claude-opus-4-8");
  ROGUE scopes results to the closest config, so you never need the user to name
  the model. Omit it for the worst across all configs.
• query_attacks — browse/filter the attack-primitive corpus by family, vector,
  or recency (e.g. "show indirect_prompt_injection attacks from the last 7 days").
• query_diff — what changed today vs yesterday: newly-breaching and newly-defended
  cells, per-severity counts (e.g. "any new critical attacks today?").
• query_threat_brief — the full daily CISO-readable threat brief (markdown/JSON).
• query_breaches_for_config — per-trial breach results for ONE customer deployment,
  with judge rationale + model-response excerpts (e.g. "what broke our support bot?").
• query_attack_detail — one attack's full record + its per-config breach aggregates
  (n_full / n_partial / n_refused / n_evaded).

Attack families follow ROGUE's taxonomy (jailbreak, indirect_prompt_injection,
multimodal_injection, …); breach rates are MAX any-breach over N=5 trials per cell.
"""

mcp = FastMCP(
    "rogue",
    instructions=_INSTRUCTIONS,
    website_url="https://rogue-eosin.vercel.app",
)


# --------------------------------------------------------------------------- #
# Tool 1: query_attacks
# --------------------------------------------------------------------------- #


@mcp.tool()
def query_attacks(
    family: str | None = None,
    vector: str | None = None,
    since_days: int = 7,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Query the ROGUE attack database with optional filters.

    Args:
        family: Optional attack family filter (e.g. "indirect_prompt_injection",
            "jailbreak_persona", "training_data_extraction"). See the 15-family
            ROGUE taxonomy. None = all families.
        vector: Optional injection vector filter (e.g. "user_turn",
            "rag_document", "tool_output", "system_prompt"). None = all vectors.
        since_days: Only return attacks discovered within this many days
            (default 7). Use 999 for "all-time".
        limit: Maximum number of attacks to return (default 20, max 100).

    Returns:
        List of attack primitives, newest first. Each dict has: primitive_id,
        title, family, vector, base_severity, short_description,
        payload_template (truncated to 500 chars), reproducibility_score,
        discovered_at, canonical, sources (list of {url, source_type}).
    """
    limit = max(1, min(100, limit))
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)

    with _get_session() as session:
        stmt = select(AttackPrimitiveORM).where(
            AttackPrimitiveORM.discovered_at >= cutoff
        ).order_by(AttackPrimitiveORM.discovered_at.desc()).limit(limit)
        if family:
            stmt = stmt.where(AttackPrimitiveORM.family == family)
        if vector:
            stmt = stmt.where(AttackPrimitiveORM.vector == vector)

        rows = session.execute(stmt).scalars().all()
        return [_primitive_to_dict(p, include_payload=True) for p in rows]


# --------------------------------------------------------------------------- #
# Tool 2: query_diff
# --------------------------------------------------------------------------- #


@mcp.tool()
def query_diff(date_str: str | None = None) -> dict[str, Any]:
    """Today's threat brief diff vs the day before — what's newly breaching.

    Args:
        date_str: ISO date string ``"YYYY-MM-DD"`` (default = today UTC).
            The diff computes ``breach_set(date) - breach_set(date - 1 day)``.

    Returns:
        Dict shaped like the JSON form of `ThreatBriefBuilder.render_json`:
        {summary: {new_critical, new_high, new_medium, new_low, newly_defended,
        total_today, total_yesterday, net_delta}, new_critical: [...],
        new_high: [...], ...}.
    """
    from rogue.diff.threat_brief import ThreatBriefBuilder

    target_date = _parse_iso_date(date_str)

    with _get_session() as session:
        builder = ThreatBriefBuilder(session=session)
        # Default customer_id = "acme" per the demo deployment configs. If
        # multi-tenancy lands, accept `customer_id` as another tool arg.
        diff = builder.build_diff(customer_id="acme", target_date=target_date)
        return builder.render_json(diff)


# --------------------------------------------------------------------------- #
# Tool 3: query_threat_brief
# --------------------------------------------------------------------------- #


@mcp.tool()
def query_threat_brief(date_str: str | None = None, format: str = "markdown") -> str:
    """Fetch the full threat brief for a date.

    Args:
        date_str: ISO date string ``"YYYY-MM-DD"`` (default = today UTC).
        format: ``"markdown"`` (default) or ``"json"``. Markdown is what a
            human reads; JSON is what downstream agents consume.

    Returns:
        The brief file's content as a string. Falls back to rendering live
        from the DB if the artifact file isn't on disk yet (the harvest
        may not have written today's brief at the moment of query).
    """
    target_date = _parse_iso_date(date_str)
    fmt = format.lower()
    if fmt not in ("markdown", "json"):
        raise ValueError(f"format must be 'markdown' or 'json'; got {format!r}")

    ext = "md" if fmt == "markdown" else "json"
    brief_path = THREAT_BRIEFS_DIR / f"{target_date.isoformat()}.{ext}"
    if brief_path.exists():
        return brief_path.read_text(encoding="utf-8")

    # Fall back to live render — the brief may not exist if today's harvest
    # didn't run yet, or if the operator asked for a different customer.
    from rogue.diff.threat_brief import ThreatBriefBuilder

    with _get_session() as session:
        builder = ThreatBriefBuilder(session=session)
        diff = builder.build_diff(customer_id="acme", target_date=target_date)
        if fmt == "markdown":
            return builder.render_markdown(diff)
        return json.dumps(builder.render_json(diff), indent=2, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# Tool 4: query_breaches_for_config
# --------------------------------------------------------------------------- #


@mcp.tool()
def query_breaches_for_config(
    deployment_config_id: str,
    since_days: int = 7,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List breach results for a specific deployment config (model × system prompt).

    Args:
        deployment_config_id: Config id, e.g. "acme-claudehaiku-20260526" or
            "acme-mistralsm-20260526". Get the full list via the dashboard
            ``/api/configs`` endpoint or by querying `deployment_configs` table.
        since_days: Look back window in days (default 7).
        limit: Max BreachResults to return (default 50, max 200).

    Returns:
        List of breach results (most recent first). Each: breach_id,
        primitive_id, primitive_title, verdict, judge_rationale (truncated
        500), judge_confidence, ran_at, trial_index, model_response (truncated
        500).
    """
    limit = max(1, min(200, limit))
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)

    with _get_session() as session:
        stmt = (
            select(BreachResultORM, AttackPrimitiveORM)
            .join(
                AttackPrimitiveORM,
                AttackPrimitiveORM.primitive_id == BreachResultORM.primitive_id,
            )
            .where(BreachResultORM.deployment_config_id == deployment_config_id)
            .where(BreachResultORM.ran_at >= cutoff)
            .order_by(BreachResultORM.ran_at.desc())
            .limit(limit)
        )
        rows = session.execute(stmt).all()
        return [
            {
                "breach_id": str(br.breach_id),
                "primitive_id": br.primitive_id,
                "primitive_title": ap.title,
                "deployment_config_id": br.deployment_config_id,
                "trial_index": br.trial_index,
                "verdict": _enum_str(br.verdict),
                "judge_confidence": br.judge_confidence,
                "judge_rationale": (br.judge_rationale or "")[:500],
                "model_response_excerpt": (br.model_response or "")[:500],
                "ran_at": br.ran_at.isoformat() if br.ran_at else None,
            }
            for br, ap in rows
        ]


# --------------------------------------------------------------------------- #
# Tool 5: query_attack_detail
# --------------------------------------------------------------------------- #


@mcp.tool()
def query_attack_detail(primitive_id: str) -> dict[str, Any]:
    """Full detail on one attack primitive + linked breach results.

    Args:
        primitive_id: The ULID-shaped attack id (e.g. from `query_attacks`
            results). Returned 1:1 with the harvest-side `primitive_id`.

    Returns:
        Dict: primitive (all fields including full payload_template + slot
        defaults), and `breaches` (per-config aggregate of trials × verdicts
        with mean confidence and most-recent timestamp).
    """
    with _get_session() as session:
        primitive = session.get(AttackPrimitiveORM, primitive_id)
        if primitive is None:
            raise ValueError(f"primitive not found: {primitive_id!r}")

        per_config = session.execute(
            text(
                """
                SELECT
                    br.deployment_config_id,
                    dc.name AS config_name,
                    dc.target_model,
                    COUNT(*) AS n_trials,
                    COUNT(*) FILTER (WHERE br.verdict = 'full_breach') AS n_full,
                    COUNT(*) FILTER (WHERE br.verdict = 'partial_breach') AS n_partial,
                    COUNT(*) FILTER (WHERE br.verdict = 'refused') AS n_refused,
                    COUNT(*) FILTER (WHERE br.verdict = 'evaded') AS n_evaded,
                    COUNT(*) FILTER (WHERE br.verdict = 'error') AS n_error,
                    AVG(br.judge_confidence) FILTER (WHERE br.verdict != 'error') AS avg_confidence,
                    MAX(br.ran_at) AS last_ran_at
                FROM breach_results br
                JOIN deployment_configs dc ON dc.config_id = br.deployment_config_id
                WHERE br.primitive_id = :pid
                GROUP BY br.deployment_config_id, dc.name, dc.target_model
                ORDER BY br.deployment_config_id
                """
            ),
            {"pid": primitive_id},
        ).all()

        return {
            "primitive": _primitive_to_dict(primitive, include_payload=True, truncate_payload=False),
            "breaches": [
                {
                    "deployment_config_id": row.deployment_config_id,
                    "config_name": row.config_name,
                    "target_model": row.target_model,
                    "n_trials": int(row.n_trials),
                    "n_full_breach": int(row.n_full),
                    "n_partial_breach": int(row.n_partial),
                    "n_refused": int(row.n_refused),
                    "n_evaded": int(row.n_evaded),
                    "n_error": int(row.n_error),
                    "avg_confidence": float(row.avg_confidence) if row.avg_confidence is not None else None,
                    "last_ran_at": row.last_ran_at.isoformat() if row.last_ran_at else None,
                }
                for row in per_config
            ],
        }


# --------------------------------------------------------------------------- #
# Tool 6: query_worst_attacks
# --------------------------------------------------------------------------- #

# Tokens scanned (in priority order) inside the caller's model_family string to
# find the substring that identifies the closest config's target_model. Specific
# Claude TIERS (opus/sonnet/haiku) come before the generic "claude"/"anthropic"
# so "claude-opus-4-8" resolves to the Opus config, not whichever Claude is first.
# Substring-scan (not exact-match) so a full id like "claude-opus-4-8", a label
# like "Claude Opus 4.8", or a bare "opus" all resolve correctly.
_MODEL_FAMILY_TOKENS = (
    "opus", "sonnet", "haiku",        # Claude tiers (most specific first)
    "gpt", "nano",                    # OpenAI
    "gemini", "llama", "mistral",     # other model names
    "claude", "anthropic", "openai", "google", "meta",  # provider fallbacks
)


def _resolve_family_token(model_family: str) -> str | None:
    s = model_family.strip().lower()
    return next((t for t in _MODEL_FAMILY_TOKENS if t in s), None)


@mcp.tool()
def query_worst_attacks(model_family: str | None = None, limit: int = 10) -> dict[str, Any]:
    """Highest-breach-rate attacks — optionally against the model closest to yours.

    The fast "am I exposed?" answer: the attacks that breach hardest, all-time.

    IMPORTANT for assistants: when a user asks "what would hit a model like me?",
    pass YOUR OWN model identity as ``model_family`` (you know what model you are
    — e.g. Claude Opus 4.8 → pass ``"claude-opus-4-8"`` or ``"opus"``). ROGUE maps
    it to the closest deployment config and scopes results to it, so you never
    need the user to name the model.

    Args:
        model_family: optional — your model's name or family. Accepts a full id
            ("claude-opus-4-8"), a tier ("opus"/"sonnet"/"haiku"), or a provider
            ("gpt"/"openai", "gemini"/"google", "llama"/"meta", "mistral",
            "claude"/"anthropic"). Specific tiers win over the generic provider,
            so "claude-opus-4-8" → the Opus config (not Haiku). None = worst
            attacks across ALL configs.
        limit: max attacks to return (default 10, max 50).

    Returns:
        {matched_config: {config_id, config_name, target_model} | null,
         note: str,
         attacks: [{primitive_id, title, family, vector, config_name,
                    target_model, any_breach_rate, full_breach_rate, n_trials}]}
        sorted worst-first (any-breach desc, then full-breach desc).
    """
    limit = max(1, min(50, limit))

    with _get_session() as session:
        matched = None
        cfg_id = None
        if model_family:
            token = _resolve_family_token(model_family)
            if token is None:
                return {
                    "matched_config": None,
                    "note": (
                        f"couldn't map model_family {model_family!r} to a known "
                        f"model token {list(_MODEL_FAMILY_TOKENS)}. Returning "
                        "nothing — retry with your model name or omit for all-configs."
                    ),
                    "attacks": [],
                }
            row = session.execute(
                text(
                    "SELECT config_id, name, target_model FROM deployment_configs "
                    "WHERE lower(target_model) LIKE :t OR lower(name) LIKE :t LIMIT 1"
                ),
                {"t": f"%{token}%"},
            ).first()
            if row is not None:
                cfg_id = row.config_id
                matched = {
                    "config_id": row.config_id,
                    "config_name": row.name,
                    "target_model": row.target_model,
                }

        rows = session.execute(
            text(
                f"""
                WITH agg AS (
                    SELECT br.primitive_id, br.deployment_config_id,
                        COUNT(*) FILTER (WHERE br.verdict != 'error') AS n,
                        COUNT(*) FILTER (WHERE br.verdict IN ('partial_breach','full_breach'))::float
                            / NULLIF(COUNT(*) FILTER (WHERE br.verdict != 'error'), 0) AS any_rate,
                        COUNT(*) FILTER (WHERE br.verdict = 'full_breach')::float
                            / NULLIF(COUNT(*) FILTER (WHERE br.verdict != 'error'), 0) AS full_rate
                    FROM breach_results br
                    {"WHERE br.deployment_config_id = :cfg" if cfg_id else ""}
                    GROUP BY 1, 2
                )
                SELECT a.primitive_id, a.deployment_config_id, a.n, a.any_rate, a.full_rate,
                       ap.title, ap.family, ap.vector, dc.name AS config_name, dc.target_model
                FROM agg a
                JOIN attack_primitives ap ON ap.primitive_id = a.primitive_id
                JOIN deployment_configs dc ON dc.config_id = a.deployment_config_id
                WHERE a.any_rate > 0
                ORDER BY a.any_rate DESC, a.full_rate DESC, a.n DESC
                LIMIT :limit
                """
            ),
            {"cfg": cfg_id, "limit": limit} if cfg_id else {"limit": limit},
        ).all()

        note = (
            f"worst attacks against {matched['target_model']} (closest config to "
            f"{model_family!r})" if matched else
            (f"no config matched {model_family!r}; showing worst across all configs"
             if model_family else "worst attacks across all configs")
        )
        return {
            "matched_config": matched,
            "note": note,
            "attacks": [
                {
                    "primitive_id": r.primitive_id,
                    "title": r.title,
                    "family": _enum_str(r.family),
                    "vector": _enum_str(r.vector),
                    "config_name": r.config_name,
                    "target_model": r.target_model,
                    "any_breach_rate": round(float(r.any_rate or 0.0), 3),
                    "full_breach_rate": round(float(r.full_rate or 0.0), 3),
                    "n_trials": int(r.n or 0),
                }
                for r in rows
            ],
        }


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _parse_iso_date(date_str: str | None) -> date:
    """Resolve a report date for the diff/brief tools.

    An explicit ``YYYY-MM-DD`` always wins. Otherwise default to the
    **most-recent run day with breach data** (mirrors the dashboard), falling
    back to today UTC only if the matrix is empty. Defaulting to a bare "today"
    made ``query_diff`` look empty whenever the latest run was an earlier day —
    e.g. data landed on the 30th but "today" is the 31st, so the diff computed
    ``breach_set(31) - breach_set(30)`` = nothing, hiding that day's new attacks.
    """
    if date_str:
        return date.fromisoformat(date_str)
    try:
        with _get_session() as session:
            latest = session.execute(
                text("SELECT max(run_date) FROM breach_matrix")
            ).scalar()
        if latest:
            return latest
    except Exception:
        logger.warning(
            "could not resolve most-recent run date; defaulting to today UTC",
            exc_info=True,
        )
    return datetime.now(timezone.utc).date()


def _enum_str(v: Any) -> Any:
    """Stringify an enum member to its `.value`, pass through everything else.

    SQLAlchemy with native-enum columns returns Python enum members on read
    (not strings) — those don't serialize via the JSON-RPC layer Claude
    Desktop speaks. Coerce here so the tool surface is always JSON-clean.
    """
    if v is None:
        return None
    if hasattr(v, "value"):  # enum.Enum, IntEnum, StrEnum all expose `.value`
        return v.value
    return v


def _primitive_to_dict(
    primitive: AttackPrimitiveORM,
    *,
    include_payload: bool = False,
    truncate_payload: bool = True,
) -> dict[str, Any]:
    """ORM → JSON-safe dict for MCP responses."""
    payload = primitive.payload_template or ""
    if truncate_payload and len(payload) > 500:
        payload = payload[:500] + "...[truncated]"

    return {
        "primitive_id": primitive.primitive_id,
        "title": primitive.title,
        "family": _enum_str(primitive.family),
        "vector": _enum_str(primitive.vector),
        "base_severity": _enum_str(primitive.base_severity),
        "short_description": primitive.short_description,
        "payload_template": payload if include_payload else None,
        "payload_slots": dict(primitive.payload_slots or {}),
        "reproducibility_score": primitive.reproducibility_score,
        "canonical": primitive.canonical,
        "cluster_id": primitive.cluster_id,
        "discovered_at": primitive.discovered_at.isoformat() if primitive.discovered_at else None,
        "requires_multi_turn": primitive.requires_multi_turn,
        "requires_system_prompt_access": primitive.requires_system_prompt_access,
        "requires_tools": list(primitive.requires_tools or []),
        "sources": [
            {
                "url": s.url,
                "source_type": _enum_str(s.source_type),
                "bright_data_product": _enum_str(s.bright_data_product),
                "author": s.author,
                "fetched_at": s.fetched_at.isoformat() if s.fetched_at else None,
            }
            for s in (primitive.sources or [])
        ],
    }


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #


_VALID_TRANSPORTS = ("stdio", "sse", "streamable-http")


def main() -> None:
    """Run the MCP server.

    Default transport is **stdio** — Claude Desktop spawns this process and
    talks to it via stdin/stdout per the MCP protocol. Logs go to stderr
    (basicConfig's default) to avoid corrupting the JSON-RPC stream on stdout.

    Set ``ROGUE_MCP_TRANSPORT=streamable-http`` (or the legacy ``sse``) to serve
    over HTTP on ``ROGUE_MCP_PORT`` instead (default **8001** — a dedicated port
    alongside the FastAPI dashboard backend on 8000). This is the remote-access
    path: Cursor / Windsurf / a hosted client can query the threat DB over HTTP
    without spawning a local subprocess. Override the bind address with
    ``ROGUE_MCP_HOST`` (default 127.0.0.1; set 0.0.0.0 to expose off-box).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        # basicConfig defaults to a StreamHandler on stderr — never stdout,
        # which is the MCP JSON-RPC channel for the stdio transport.
    )
    transport = os.getenv("ROGUE_MCP_TRANSPORT", "stdio").strip().lower()
    if transport not in _VALID_TRANSPORTS:
        raise SystemExit(
            f"ROGUE_MCP_TRANSPORT={transport!r} invalid; "
            f"expected one of {', '.join(_VALID_TRANSPORTS)}"
        )

    if transport == "stdio":
        logger.info(
            "ROGUE MCP server starting — 6 read-only tools (scan/workflow action tools register "
            "when mounted in the /v1 API) — transport=stdio"
        )
    else:
        # HTTP transports bind a real port; default 8001 so we never collide
        # with the FastAPI dashboard backend on 8000.
        mcp.settings.host = os.getenv("ROGUE_MCP_HOST", "127.0.0.1")
        mcp.settings.port = int(os.getenv("ROGUE_MCP_PORT", "8001"))
        logger.info(
            "ROGUE MCP server starting — 6 read-only tools (scan/workflow action tools register "
            "when mounted in the /v1 API) — transport=%s on http://%s:%d",
            transport,
            mcp.settings.host,
            mcp.settings.port,
        )

    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
