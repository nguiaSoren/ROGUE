"""`rogue.integrations.slack` — Slack-agent self-registration (build-area 06 §2).

A consented Slack agent registers its OpenAI-compatible endpoint + effective system prompt
(customer-supplied; no Slack introspection) and ROGUE turns it into a `base_url`-carrying
`DeploymentConfig` that routes through `CustomHTTPAdapter` for continuous red-teaming.

Side-effect-free import: these are plain re-exports — no engine is built and no DB connection
is opened at import time (mirrors the `mcp_server.server` lazy-DB discipline; the Postgres
store builds its engine only inside `build_postgres_slack_agent_store`).

06 §3 (built): the sandbox-cycle trigger (`run_sandbox_cycle`) + the harvest hook
(`newly_landed_primitives`) it depends on. These are plain re-exports (no DB side effects).
"""

from __future__ import annotations

from .agent_store import (
    InMemorySlackAgentStore,
    PostgresSlackAgentStore,
    SlackAgentStore,
    build_postgres_slack_agent_store,
)
from .change_witness import (
    ChangeWitnessSummary,
    append_cycle_mitigations,
    latest_agent_scan_entry,
    latest_change_witness,
)
from .diff_post import build_security_post, post_breach_diff
from .harvest_hook import newly_landed_primitives
from .policy import ensure_client_policy
from .registration import (
    RegisteredSlackAgent,
    SlackAgentTarget,
    config_id_for,
    register_slack_agent,
    slack_agent_to_config,
)
from .redline_guard import RedlineScore, score_inbound
from .tripwire import TripwirePrediction, classify_inbound_family, predict_breach
from .trigger import run_sandbox_cycle

__all__ = [
    "SlackAgentTarget",
    "RegisteredSlackAgent",
    "register_slack_agent",
    "slack_agent_to_config",
    "config_id_for",
    "SlackAgentStore",
    "InMemorySlackAgentStore",
    "PostgresSlackAgentStore",
    "build_postgres_slack_agent_store",
    "run_sandbox_cycle",
    "newly_landed_primitives",
    "ensure_client_policy",
    "build_security_post",
    "post_breach_diff",
    "ChangeWitnessSummary",
    "latest_agent_scan_entry",
    "latest_change_witness",
    "append_cycle_mitigations",
    "TripwirePrediction",
    "predict_breach",
    "classify_inbound_family",
    "RedlineScore",
    "score_inbound",
]
