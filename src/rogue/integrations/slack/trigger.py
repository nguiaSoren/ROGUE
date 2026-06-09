"""Sandbox-cycle trigger — build-area 06 §3 / §4 path A.

After a harvest/reproduce run lands new attack primitives, fan a per-rule *policy* scan
(`mode="policy"`) across every registered Slack agent that has at least one newly-landed
family, aiming the new selection at the agent's own deployed configuration (model × system
prompt × tools, reached through its `base_url` endpoint) and re-aiming it rule-by-rule
against the agent's decomposed `ClientPolicy`. This is the continuous-red-team loop's
enqueue step.

CONSTRAINTS (§3):
  * Invoked DELIBERATELY after a harvest/reproduce run — NOT a cron/loop/timer. The caller
    decides when a cycle fires; this module never schedules itself.
  * COSTLY downstream: each enqueued scan, when the worker actually runs it, makes target
    endpoint calls + judge-LLM calls. We only WRITE the scan record + enqueue here — we never
    run the scan engine inline (`ScanService.create_scan` is queue-backed by contract).
  * Idempotent: replaying the same cycle (same `since`/`now`/corpus) yields the same
    idempotency keys, so `create_scan` returns the originals and enqueues nothing new.

Side-effect-free import: no DB connection or engine is opened at module load.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from rogue.platform.schemas import ScanRecord, ScanSpec, TargetSpec

from .harvest_hook import newly_landed_primitives
from .policy import ensure_client_policy
from .registration import config_id_for, slack_agent_to_config

logger = logging.getLogger("rogue.integrations.slack.trigger")


async def run_sandbox_cycle(
    org_id: str | None = None,
    *,
    agent_store,  # SlackAgentStore
    scan_service,  # platform ScanService
    since: datetime,  # newly-landed cutoff (discovered_at >= since)
    now: datetime | None = None,  # run_day stamp; injected for determinism
    corpus=None,  # optional in-memory primitives, passed to newly_landed_primitives(primitives=...)
    decomposer=None,  # injectable DecomposeAgent; None ⇒ live PolicyDecomposer (paid)
    max_tests: int = 50,
    n_trials: int = 1,
) -> list[ScanRecord]:
    """Enqueue one per-rule policy scan per registered agent that has newly-landed families.

    Returns the list of `ScanRecord`s (one per agent enqueued; agents with no newly-landed
    families are skipped and contribute nothing). An agent whose policy cannot be derived
    (no `forbidden_topics` and no `system_prompt`, so `ensure_client_policy` raises
    `ValueError`) is logged and skipped rather than crashing the cycle. See module docstring
    for the §3 constraints.
    """
    records: list[ScanRecord] = []

    for target in agent_store.all_targets(org_id):
        # When corpus is None the harvest hook resolves the live corpus from the DB itself —
        # that's its job, not ours.
        newly = newly_landed_primitives(since, primitives=corpus)
        if not newly:
            # Exit gate: no newly-landed families for this agent ⇒ enqueue nothing.
            continue

        config = slack_agent_to_config(target)

        # §4 path A: derive THIS agent's decomposed policy. A live PolicyDecomposer is paid;
        # tests inject a mock (decomposer=None ⇒ live). Cached on the agent row by
        # ensure_client_policy, so subsequent cycles skip decomposition.
        try:
            policy = ensure_client_policy(
                target, decomposer=decomposer, agent_store=agent_store
            )
        except ValueError:
            # The agent has neither forbidden_topics nor a system_prompt to decompose — there is
            # no policy to scan rule-by-rule. Skip this agent (log it) rather than crash the cycle.
            logger.info(
                "skipping slack agent %s/%s: no policy to derive (no forbidden_topics, no system_prompt)",
                target.org_id,
                target.agent_name,
            )
            continue

        # The newly-landed selection. In policy mode the engine re-aims `attacks` per rule, so we
        # keep passing it to filter the corpus down to THIS cycle's primitives.
        selected = sorted(p.primitive_id for prims in newly.values() for p in prims)

        # Surface-1 context (build-06 §5): make the worker's auto-signed `scan` attestation entry
        # self-describing — agent identity + the families fired this cycle + per-breach-type pointers
        # to area-02's independent label provenance (ADR-0011). Frozen shape the §5 reader depends on.
        surface1_context = {
            "agent": {
                "org_id": target.org_id,
                "agent_name": target.agent_name,
                "workspace": target.workspace,
                "config_id": config_id_for(target),
            },
            "families": sorted(f.value for f in newly),
            "ground_truth_refs": {
                rule.breach_type.value: "area02-calibration:" + rule.breach_type.value
                for rule in policy.rules
            },
        }

        spec = ScanSpec(
            target=TargetSpec(
                endpoint=config.base_url,
                model=config.target_model,
                system_prompt=config.system_prompt,
            ),
            mode="policy",
            policy=policy,
            attacks=selected,
            max_tests=max(max_tests, len(selected)),
            n_trials=n_trials,
            surface1_context=surface1_context,
        )

        # Deterministic idempotency key encoding (agent identity, run_day, family-set), ≤80 chars
        # (the durable column cap). We key off the STABLE (org_id, agent_name) identity rather than
        # the store's random agent_id — that avoids an extra round-trip to fetch the id and stays
        # deterministic across replays. Resulting key is ≤47 chars, safely under 80.
        run_day = (now or datetime.now(timezone.utc)).date().isoformat()
        fam_hash = hashlib.sha1(
            ",".join(sorted(f.value for f in newly)).encode()
        ).hexdigest()[:12]
        idem = "slkcyc-" + hashlib.sha1(
            f"{target.org_id}/{target.agent_name}/{run_day}/{fam_hash}".encode()
        ).hexdigest()[:40]

        rec = await scan_service.create_scan(
            spec,
            org_id=target.org_id,
            actor="slack-sandbox-cycle",
            idempotency_key=idem,
        )
        records.append(rec)

    return records


__all__ = ["run_sandbox_cycle"]
