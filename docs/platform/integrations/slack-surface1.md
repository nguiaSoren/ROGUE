# Surface 1 Slack Delivery (build-06)

> The **live delivery surface** for Surface 1 (Offensive Governance Assurance). A customer self-registers their own consented AI agent — endpoint + effective system prompt + tool list + a sandbox and a security channel — and ROGUE registers it as a `DeploymentConfig` target. On each harvest cycle, the attack families that landed *this cycle* are fired at the registered agent **in a sandbox channel** via a per-rule policy scan, judged by area-02's calibrated per-rule judge, and a diff of which rule broke is posted to the **security channel** with per-rule "holds N/M", a trial CI, a content-addressed transcript pointer, and (when one verified) an inline area-05 patch. Every cycle is signed as a self-describing **ChangeWitness** attestation (area 03), reproducible from the stored report. Two advisory inbound modes — **Tripwire** and **RedlineGuard** — predict/score an inbound message before the agent acts. Code lives in `src/rogue/integrations/slack/` (plus `platform/snapshot_store.py` and the platform engine's `mode="policy"` branch). Spec: [`../../v2/surface1_agent_spec.md`](../../v2/surface1_agent_spec.md) §5. This is a distinct package from `src/rogue/platform/integrations/slack.py` — that one is the per-tenant *outbound scan-complete webhook dispatcher* ([`./slack-github-jira.md`](./slack-github-jira.md)); this one is a *surface* (registration + sandbox-scan orchestration + the inbound advisory modes), at the same altitude as `mcp_server/`.

Status: **§2–§8 (code-only half) BUILT, offline-proven (2026-06-09/10), local on branch `v2-phase1`.** v1 is **prediction-only**: there is no live Slack Events inbound endpoint, no request-signature verification, and the inbound modes operate on a message handed in as a plain argument (a test / MCP call / sandbox replay), not a production interceptor — that work is deferred (see §6). The config secrets `SLACK_BOT_TOKEN` / `SLACK_SIGNING_SECRET` exist in `config.py`/`.env.example`. The five MCP tools that surface this layer are registered in `api/main.py` `_wire_platform` (org bound at the server, never a tool argument) and catalogued in `docs/mcp/CONTRACT.md`. Migrations `0033` (registered-agents) + `0034` (snapshot captures) are applied to the local container only — live application to Neon, the real Slack-app credentials/scopes/channels, the live Slack Events endpoint, and the production auto-fire (worker-finalize → post) remain the deploy-time / deferred work.

## The advisory-only boundary (ADR-0010) — read first

ROGUE **never sits in the request path.** Nothing in this surface intercepts, modifies, blocks, or enforces a production message. The sandbox scan fires attacks at the consented agent in a *sandbox* channel, never a channel real employees use. The two inbound modes (Tripwire, RedlineGuard) **predict and advise** from prior scan results and the calibrated judge — they emit a recommendation or a deploy-by-client rule, and the customer is the one who acts on it in their own runtime. Both entrypoints are pure functions with no enforcing field, no outbound call, and no message mutation; the build verifiers proved this invariant directly. A production interceptor is permanently out of v1 scope (ADR-0010 plus Slack platform-permission limits). The companion invariant is ADR-0011 (independence): every breach verdict is the calibrated judge's, scored against the per-rule independently-labeled set (area 02) — never the agent's own claim of what it did.

## The end-to-end flow

```
self-register agent            harvest cycle lands new families
  (DeploymentConfig)                       │
        │                                  ▼
        └──────────────►  run_sandbox_cycle  ──►  ScanService.create_scan  (one per agent, idempotent)
                                                          │  queue → worker → ScanEngine (mode="policy")
                                                          ▼
                                          governance.run_policy_scan
                                          (decompose → per-rule re-aim → scan → per-rule judge → per-rule CI)
                                                          │
                          ┌───────────────────────────────┼───────────────────────────────┐
                          ▼                                ▼                               ▼
                  post_breach_diff               worker auto-signs a                snapshot_store.put
                  → SECURITY channel             self-describing `scan`             (content-addressed
                  (per-rule holds N/M,           attestation entry                  transcript pointer)
                   CI, snapshot_ref,             (ChangeWitness, area 03)
                   inline area-05 patch)
```

### 1. Self-registration — a Slack agent becomes a `DeploymentConfig`

The customer registers their own agent's OpenAI-compatible endpoint. `registration.py` builds a frozen `SlackAgentTarget` (`.create(...)` normalizes list fields to tuples) carrying `{org_id, agent_name, workspace, base_url, model, system_prompt, declared_tools, forbidden_topics, sandbox_channel_id, security_channel_id}`, and `slack_agent_to_config(...)` turns it into a frozen `DeploymentConfig` whose `config_id` is the stable `slack-<workspace>-<agent_name>`. Because `base_url` is set, the config routes through `CustomHTTPAdapter` (provider resolves to `"custom"`) — the same ad-hoc endpoint-scan path the rest of the platform uses; no adapter routing is duplicated.

The **effective system prompt is customer-supplied** in v1: the customer pastes or exports their agent's system prompt and tool list at registration. It is *not* obtained via Slack-API introspection — Slack exposes no API to read a third-party bot's prompt — so there is zero Slack-scraping code in the package. Both the sandbox channel id and the security channel id are **fail-closed mandatory**: `SlackAgentTarget.__post_init__` rejects a blank either, enforcing the spec's "sandbox not production" constraint at the registration boundary.

Persistence (`agent_store.py`, `SlackAgentStore` abc + `InMemory`/`Postgres` implementations): the target itself is a `slack_registered_agents` row (migration `0033`, keyed `UNIQUE(org_id, agent_name)`); a sensitive system prompt is stored behind a `secref_…` handle in `system_prompt_ref` and resolved on read. The Slack-app bot credential is stored separately, reusing the existing per-org `integrations` store (kind `"slack"`), not the agent row — different cardinality and lifecycle. **Self-registered targets only:** ROGUE never auto-discovers or probes arbitrary workspace bots.

### 2. Harvest-cycle trigger — fire newly-landed families at each agent

`harvest_hook.newly_landed_primitives(since)` enumerates corpus primitives with `discovered_at >= since` — newly *harvested* this cycle (the area thesis, "this week's corpus"), grouped by `AttackFamily`. It is **not** `ThreatBriefBuilder.build_diff`'s breach-state diff.

`trigger.run_sandbox_cycle(org_id=None, *, agent_store, scan_service, since, ...)` iterates every registered agent, selects its newly-landed families, and enqueues **exactly one** sandbox scan per agent via `ScanService.create_scan` — the single queue → worker → `ScanEngine` execution path the MCP/SDK/dashboard spine already uses. It skips agents with no newly-landed family and **never runs the engine inline**. Idempotency is a deterministic key `slkcyc-<sha1(org/agent_name/run_day/family_set)>`, so replaying a cycle enqueues nothing new.

This is **COSTLY and deliberate** — each enqueued scan, when the worker runs it, makes real target endpoint calls and judge-LLM calls. It is exposed only as `scripts/ops/slack_sandbox_cycle.py`, invoked by hand *after* a harvest/reproduce run completes. There is no cron, no timer, no auto-fire on import.

### 3. Sandbox scan + diff post to the security channel

The enqueued scan runs through the platform `ScanEngine` with the additive `mode="policy"` branch (`platform/engine.py`'s `_run_policy`), which routes to area-04's `governance.run_policy_scan` — decompose the agent's `ClientPolicy` → per-rule re-aim → scan the registered `DeploymentConfig` → per-rule judge → per-rule CI. This is strictly additive (existing pack/repertoire/ladder paths stay byte-identical, regression-gated); the per-rule `RuleBreachReport` rides into the persisted report under `rule_breach_report`. The agent's `ClientPolicy` comes from `slack/policy.py:ensure_client_policy` (reuses area-04's `decompose_policy` on the agent's forbidden topics / system prompt, cached on the `slack_registered_agents.client_policy` column).

`diff_post.py:build_security_post` builds the Block Kit message — one section per **breaching** rule, rendered from `rule_breach_report["rule_verdicts"]` (the judged per-rule numbers, not the approximate `ScanReport.findings` map): family, breach type (the consummation shape — information-disclosure / unauthorized-action / capability-transfer), per-rule "breaks N/M" / "holds (M−N)/M", the trial CI, the calibration status, and a transcript `snapshot_ref`. `post_breach_diff` orchestrates: it captures the transcript evidence to the content-addressed snapshot store (it has the `org_id` the engine layer lacks), runs the injected area-05 remediation, and posts via an injectable `Sender` to **`security_channel_id` only** — never the sandbox channel, never any other channel. A send failure is logged and swallowed (a Slack outage must not crash the red-team cycle), mirroring the outbound dispatcher's posture.

The transcript is captured as a pointer, not a blob: `platform/snapshot_store.py` is content-addressed (`put(content, *, org_id, content_type) -> "sha256:<hexdigest>"`, org-scoped, idempotent dedup, durable in the `snapshot_captures` table, migration `0034`). The post links the ref so the ChangeWitness can replay against it rather than inlining the transcript into Slack.

The inline patch honors the honesty filter: the "🛠 Patch below" section renders the area-05 `RemediationResult.candidate.artifact` **only when the result is `accepted`**; otherwise the post says "mitigation pending (Surface 1b)". ROGUE never claims a verified patch that was not verified.

One seam remains for live: the production auto-fire (worker-finalize → `post_breach_diff`) is not yet wired — the posting *logic* is gate-proven offline with fakes, and `run_policy_scan` currently surfaces `transcript_refs` marker strings (`rule::primitive::trial`) rather than raw transcript blobs (a governance follow-up); `post_breach_diff` captures whatever text it is handed.

### 4. ChangeWitness — the signed attestation

Each Slack cycle is a signed, replayable attestation: "agent X tested against the open-web corpus as of date D; here are the breaches and the verified mitigations." The worker already auto-signs one `scan` entry per cycle onto the per-org hash chain (area 03, `attestation/`); the build made that entry **self-describing** by threading a frozen `surface1_context` block — `{agent: {org_id, agent_name, workspace, config_id}, families: [...], ground_truth_refs: {breach_type: ref}}` — plus the per-rule `rule_breach_report` through `ScanSpec.surface1_context → engine._run_policy → ScanReport → emit.payload_for_scan → worker.append(...)`. The threading is strictly additive: a non-Slack scan's signed payload stays byte-identical, which is the load-bearing invariant for the entry hash and replay chain.

`change_witness.py` is the **reader**: `latest_change_witness(org, agent) -> ChangeWitnessSummary` returns the agent identity, the framing line, the breaching rules (with holds N/M + trial CI from the rule verdicts), the verified mitigations, and `replay_ok`. Replay reconstructs the verdict from the stored `ScanReport` via `reproducibility_ref = scan_id` (ADR-0012) and recomputes the hash; a tampered report flips `replay_ok` to false. `append_cycle_mitigations` folds the cycle's accepted patches onto the same chain via area-05's `append_mitigation`.

**Framing discipline:** the summary reuses `emit.framing_line(corpus_as_of)` verbatim — "threat-informed assurance … as of D; **not a safety guarantee**." This is a constant, never re-phrased by any caller, so the attestation can never be presented as a safety guarantee.

### 5. Tripwire — advisory inbound breach prediction (prediction-only v1)

`tripwire.py:predict_breach(org_id, agent_name, inbound_message, *, attestation_service, matcher=None) -> TripwirePrediction`. It classifies the inbound message to an `AttackFamily` (a deterministic keyword heuristic over the 15-family taxonomy in v1; an embedding retriever from `retrieval/` is the injectable `matcher` upgrade), reads **this agent's own** latest signed ChangeWitness scan entry, looks up the matched family's per-rule verdict, and returns `{matched_family, calibrated, prior_breach_rate, ci, n_trials, n_breaches, recommendation, advisory}` — "this inbound matches family F; #agent broke to F in N/M prior sandbox trials (CI …) — review before it acts." The calibration is precisely what a generic message classifier cannot claim: *this exact agent × this exact family*, measured.

It is **advisory-only** (ADR-0010): `predict_breach` is pure — no Slack/HTTP call, no message mutation, no enforcing field, frozen result, read-only attestation access. The `advisory` string is always prefixed "⚠️ Tripwire (advisory — not a block)". A matched-but-untested family returns an honest uncalibrated prediction; no match or no prior degrades gracefully.

### 6. RedlineGuard — a deploy-by-client gate rule, judge-calibrated

`redline_guard.py:score_inbound(org_id, agent_name, message, *, matcher=None, attestation_service=None) -> RedlineScore`. It classifies the message to a family (reusing Tripwire's shared `classify_inbound_family`), maps it to its breach class via `governance.reaim.FAMILY_BREACH_TYPE`, and sets the confidence to `governance.rule_judge.calibration_for_breach_type(breach_type)` — the **area-02 judge's measured precision** for that class. This is not a bespoke moderation classifier (the foil the spec rejects); the confidence is a number ROGUE already earned and can attest. A class with no shipped calibration report returns `calibration_status="uncalibrated"`, `confidence=None` — never a fabricated number (ADR-0011).

The output is a deploy-by-client `MitigationCandidate(mitigation_type=GUARDRAIL_RULE, artifact=<rule text + measured precision>)`: **DATA the client deploys** into their own filter/guardrail, never something ROGUE executes. `score_inbound` is pure (ADR-0010) — ROGUE generates and verifies the rule and its precision; the client enforces. The measured over-block check (`over_block`) is `None` in v1 — wiring it needs area-05's legit-corpus run with the same judge, which is the calibrated upgrade.

The contrast with Tripwire: Tripwire predicts breakage from *this agent's empirical prior breach-rate*; RedlineGuard is target-agnostic and reports *the judge's calibrated precision* plus a deployable rule.

## v1 deferrals (honest scope)

- **No live Slack inbound.** There is no Slack Events API endpoint and no request-signature verification in the codebase. Both inbound modes take the message as a plain argument (test / MCP call / sandbox replay). The live inbound route + signature verification are deferred; a production interceptor is permanently out of scope (ADR-0010 + Slack permissions).
- **MCP surface — DONE.** The five Slack action tools (`register_slack_agent`, `run_sandbox_cycle`, `get_change_witness`, `tripwire_predict`, `redline_score`) live in `mcp_server/slack_tools.py`, are wired in `api/main.py` `_wire_platform` (org bound at the server, never a tool argument; secrets as module-level seams, not tool params), and are catalogued in `docs/mcp/CONTRACT.md`. Each is `async` and returns `{"error": …}` on recoverable failure (never raises across MCP).
- **Production auto-fire** of the diff post (worker-finalize → `post_breach_diff`) is the live delivery-hookup seam; the logic is gate-proven offline.
- **Neon.** Migrations `0033`/`0034` are local-container only; live application is the v2 deploy step.

## Config

| Secret | Env var | Use |
|---|---|---|
| `slack_bot_token` | `SLACK_BOT_TOKEN` | Slack-app bot OAuth token (posting; stored via the per-org `integrations` store, Fernet-encrypted). |
| `slack_signing_secret` | `SLACK_SIGNING_SECRET` | Request-signature verification for the (deferred) live Slack inbound endpoint. |

Both are `SecretStr` in `config.py` (mirroring `slack_webhook_url`) and listed in `.env.example`. No new secret mechanism.

## Security channel vs sandbox channel

Two distinct bound channel ids per registered agent, and conflating them would violate the spec:

- **Sandbox channel** (`sandbox_channel_id`) — where the red-team *runs*. Live attacks fire against the registered agent here, in isolation from channels real employees use. Mandatory and fail-closed at registration.
- **Security channel** (`security_channel_id`) — where the *diff posts*. `post_breach_diff` delivers the breach diff to this channel **and nothing else** (the e2e test asserts no post ever lands on the sandbox or any other channel). Mandatory and fail-closed at registration.

## See also

- [`../../v2/surface1_agent_spec.md`](../../v2/surface1_agent_spec.md) §5 — the Slack delivery layer spec (and §1–§4 for the offense/remediation core this delivers).
- [`./slack-github-jira.md`](./slack-github-jira.md) — the *other* Slack package: the per-tenant outbound scan-complete webhook dispatcher (`platform/integrations/slack.py`). Distinct from this surface.
- [`./mcp.md`](./mcp.md) — the producer-side MCP server the §8 action tools extend.
- [`../attestation.md`](../attestation.md) — the area-03 hash-chained attestation layer ChangeWitness consumes.
- `docs/v2/build/06_surface1_slack.md` — the build plan + STATUS for this area (local/gitignored).
