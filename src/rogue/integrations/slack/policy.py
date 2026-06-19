"""Derive a typed `ClientPolicy` for a registered Slack agent (build-06 §4 path A).

The per-rule policy scan re-aims attacks per rule, so it needs the agent's policy as the
decomposed `ClientPolicy` rows that area-04's `decompose_policy` produces — not the raw
`forbidden_topics` strings. This module bridges area-06's `SlackAgentTarget` to area-04's
decomposer, and caches the result on the agent row so the next sandbox cycle skips the
(paid) decomposition.

Side-effect-free import: importing this module builds no client and opens no DB connection.
The live `PolicyDecomposer` is only constructed inside `decompose_policy` when no `decomposer`
is injected — tests pass a mock and never touch a model.
"""

from __future__ import annotations

import logging

from rogue.governance.decompose import decompose_policy
from rogue.schemas.governance import ClientPolicy

from .registration import SlackAgentTarget, config_id_for

logger = logging.getLogger("rogue.integrations.slack.policy")

__all__ = ["ensure_client_policy"]


def _source_text_for(target: SlackAgentTarget) -> str:
    """Compose the policy source text from the agent's own signals.

    Primarily the `forbidden_topics` (each a rule line); the `system_prompt` is appended for
    context so the decomposer can type each rule's breach shape correctly. Raises if there is
    nothing to derive a policy from — we fail loud rather than emit an empty policy.
    """
    topics = [t for t in target.forbidden_topics if t and t.strip()]
    system_prompt = (target.system_prompt or "").strip()
    if not topics and not system_prompt:
        raise ValueError(
            "ensure_client_policy: cannot derive a policy — "
            f"agent {target.agent_name!r} has no forbidden_topics and no system_prompt"
        )

    parts: list[str] = []
    if topics:
        parts.append("The following are the deployment's forbidden topics / rules:")
        parts.extend(f"- {t.strip()}" for t in topics)
    if system_prompt:
        parts.append("System prompt for context:")
        parts.append(system_prompt)
    return "\n".join(parts)


def ensure_client_policy(
    target: SlackAgentTarget,
    *,
    decomposer=None,
    agent_store=None,
) -> ClientPolicy:
    """Return the `ClientPolicy` for a registered Slack agent, decomposing only when needed.

    1. If `agent_store` has a cached policy for `(org_id, agent_name)`, deserialize and return
       it — no decompose, no spend.
    2. Otherwise build the source text from the agent's `forbidden_topics` + `system_prompt`,
       call `decompose_policy(source_text, agent=decomposer)`, then pin `policy_id`/`customer_id`
       for tenancy.
    3. If `agent_store` is given, cache the policy back (best-effort) so the next cycle skips
       decomposition.

    Args:
        target: the registered Slack agent.
        decomposer: an injectable `DecomposeAgent`. `None` ⇒ a live `PolicyDecomposer` (paid).
        agent_store: optional store with `get_client_policy`/`set_client_policy` for caching.

    Raises:
        ValueError: if the agent has neither `forbidden_topics` nor a `system_prompt`.
    """
    if agent_store is not None:
        cached = agent_store.get_client_policy(target.org_id, target.agent_name)
        if cached:
            return ClientPolicy.model_validate(cached)

    source_text = _source_text_for(target)
    policy = decompose_policy(source_text, agent=decomposer)
    # Pin tenancy fields: the decomposer may set its own placeholders, but the caller knows the
    # tenant and the stable id, so these two are authoritative.
    policy = policy.model_copy(
        update={
            "policy_id": f"slackpol-{config_id_for(target)}",
            "customer_id": target.org_id,
        }
    )

    if agent_store is not None:
        try:
            agent_store.set_client_policy(
                target.org_id, target.agent_name, policy.model_dump()
            )
        except Exception:  # best-effort cache write — a failure must not fail the scan
            logger.warning(
                "failed to cache client_policy for agent %s/%s",
                target.org_id,
                target.agent_name,
                exc_info=True,
            )

    return policy
