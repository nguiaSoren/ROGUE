"""The default :class:`ScanEngine` — the platform's single execution path.

This is a thin wrapper over the existing SDK reproduction pipeline (``render`` → ``TargetPanel`` →
``JudgeAgent``). The non-ladder ``run`` path reimplements no scan logic of its own: it builds the
``DeploymentConfig`` + primitive list from the :class:`ScanSpec`, then **calls**
:func:`rogue.scan.run_scan` — the one provider-agnostic single-turn loop — forwarding the optional
``progress`` callback as run_scan's per-primitive hook so a worker can stream completion percentage
into a :class:`ScanRecord`. There is no second copy of the loop to drift: how a ``Finding`` is built,
how cost is summed, how the 0.4 breach threshold decides ``n_breaches``, how the final ``ScanReport``
is shaped — all live in ``run_scan``. The ladder path (:meth:`_run_ladder`) is a genuinely different
per-goal escalation loop and stays separate.

``validate`` and ``benchmark`` delegate straight to the SDK's ``Client`` / ``run_benchmark`` so there
is exactly one place each of those behaviours lives.

The ``panel`` / ``judge`` / ``judge_model`` constructor arguments are dependency-injection seams for
tests: a fake panel and fake judge let the whole engine run offline with no network, no LLM, no DB,
and no spend.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from .interfaces import ProgressCallback, ScanEngine

if TYPE_CHECKING:
    from rogue.report import BenchmarkReport, ScanReport, ValidationResult
    from rogue.schemas import DeploymentConfig

    from .schemas import ScanSpec

# Ladder mode is the expensive path (attacker + target + judge across tiers); a missing budget falls
# back to this hard cap so an uncapped ladder scan can't run away to tens of dollars.
_DEFAULT_LADDER_BUDGET = 5.0
_DEFAULT_DATABASE_URL = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"


class DefaultScanEngine(ScanEngine):
    """The one execution path for every platform surface (worker, SDK-in-process, API)."""

    def __init__(
        self,
        *,
        panel: Any = None,
        judge: Any = None,
        judge_model: str | None = None,
        repertoire_loader: Any = None,
        escalation_ctx_builder: Any = None,
        ladder_runner: Any = None,
        policy_runner: Any = None,
        grader: Any = None,
        snapshot_store: Any = None,
    ) -> None:
        # All injectable so tests run fully offline. When left None, the real panel / judge are built
        # lazily inside ``run`` (so importing this module never needs API keys), the repertoire is
        # loaded from the live corpus via ``DATABASE_URL``, and the ladder uses the real escalation
        # machinery (``rogue.reproduce.escalation_ladder``).
        self._panel = panel
        self._judge = judge
        self._judge_model = judge_model
        self._repertoire_loader = repertoire_loader
        self._escalation_ctx_builder = escalation_ctx_builder
        self._ladder_runner = ladder_runner
        # policy-mode (build-04 §6 per-rule scanner) seams. ``policy_runner`` is the test seam: a fake
        # returns a RuleBreachReport with no network; when None the real ``run_policy_scan`` is used.
        # ``grader`` is a finer seam INSIDE the live path: a fake grader (no judge network) lets a test
        # exercise the REAL live_responder + run_policy_scan offline; when None the real ``default_grade``
        # (one judge LLM call per trial) is used.
        # ``snapshot_store`` is optional transcript capture; when None, capture is skipped gracefully.
        self._policy_runner = policy_runner
        self._grader = grader
        self._snapshot_store = snapshot_store

    def _load_repertoire(self, spec: ScanSpec) -> list:
        """Source primitives for a ``mode="repertoire"`` scan from the live harvested corpus."""
        if self._repertoire_loader is not None:
            return self._repertoire_loader(spec)
        from .repertoire import default_repertoire_loader

        return default_repertoire_loader(spec)

    def _build_escalation_ctx(self, config: DeploymentConfig, n_goals: int, n_trials: int):
        """Build the escalation context (planner + graduated rotation + active renderers) for the ladder.

        Reads the live repertoire in a SHORT session and closes it before the ladder's LLM calls (the
        Neon idle-in-transaction rule). The planner survives the session close (the strategy library is
        materialized in-memory)."""
        if self._escalation_ctx_builder is not None:
            return self._escalation_ctx_builder(config, n_goals, n_trials)
        import os

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from rogue.reproduce.escalation_ladder import build_escalation_context

        url = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
        engine = create_engine(url, pool_pre_ping=True, pool_recycle=300, pool_timeout=10)
        try:
            with sessionmaker(bind=engine)() as session:
                return build_escalation_context(
                    session, configs=[config], n_parents_est=max(1, n_goals), n_trials=n_trials
                )
        finally:
            engine.dispose()

    # --- config construction (shared by run / validate / benchmark) ---------------------------

    def _build_config(self, spec: ScanSpec) -> DeploymentConfig:
        """Turn a :class:`ScanSpec` target into the internal :class:`DeploymentConfig`.

        An ``endpoint`` target routes through ``make_endpoint_config`` (the custom-HTTP path); a
        ``provider`` target is constructed directly, normalising the model id to a ``provider/model``
        slug and falling back to the SDK's per-provider default when no model is given.
        """
        from rogue.reproduce.endpoint_scan import make_endpoint_config
        from rogue.schemas import DeploymentConfig

        target = spec.target
        if target.endpoint:
            return make_endpoint_config(
                target.endpoint,
                target.model or "default",
                system_prompt=target.system_prompt,
            )

        # provider-mode: normalise the model id exactly as rogue.client.Client does.
        if target.model and "/" in target.model:
            target_model = target.model
        elif target.model:
            target_model = f"{target.provider}/{target.model}"
        else:
            target_model = _default_model(target.provider)

        return DeploymentConfig(
            config_id="plat-scan-0001",
            customer_id="platform",
            name=target_model,
            target_model=target_model,
            system_prompt=target.system_prompt,
            base_url=None,
        )

    def _adapter_extra(self, spec: ScanSpec) -> dict[str, Any]:
        return {"api_key": spec.target.api_key} if spec.target.api_key else {}

    def _log_ladder_telemetry(self, results, config, ctx) -> None:
        """Best-effort: append each goal's ladder trace (incl. §10.10 vendor/family tags) to
        ``ladder_attempts`` so HOSTED customer scans feed the contextual priors — the same write the
        reproduce sweep does. Telemetry only: any failure is swallowed (a logging error must never
        fail a customer's scan), and it is skipped on the injected/offline test path (a fake ctx
        builder or ladder runner means there is no real DB to write to)."""
        if self._escalation_ctx_builder is not None or self._ladder_runner is not None:
            return
        try:
            import os
            from datetime import datetime, timezone

            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker

            from rogue.reproduce.strategy_lifecycle import log_ladder_attempts

            from .memory import _new_id

            run_id = _new_id("platladder")
            now = datetime.now(timezone.utc)
            candidate_ids = frozenset(getattr(ctx, "candidate_ids", ()) or ())
            quota = getattr(ctx, "effective_quota", 0)
            url = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
            engine = create_engine(url, pool_pre_ping=True, pool_recycle=300, pool_timeout=10)
            try:
                with sessionmaker(bind=engine)() as session:
                    for goal, res in results:
                        parent_id = getattr(res, "parent_id", None) or getattr(
                            goal, "primitive_id", None
                        )
                        if parent_id is None:
                            continue
                        log_ladder_attempts(
                            session,
                            run_id=run_id,
                            parent_id=parent_id,
                            attempts=res.attempts,
                            winning_strategy=res.winning_strategy,
                            breached_on=res.breached_on,
                            candidate_ids=candidate_ids,
                            quota=quota,
                            now=now,
                            configs=[config],  # single-config scan ⇒ vendor/family tagged
                        )
                    session.commit()
            finally:
                engine.dispose()
        except Exception as exc:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).warning(
                "ladder telemetry logging failed (non-fatal): %s", exc
            )

    # --- operation #1a: policy (per-rule) scan ------------------------------------------------

    async def _run_policy(self, spec: ScanSpec, config, progress: ProgressCallback | None = None):
        """Per-rule policy scan (build-04 §6 path A): score the target rule-by-rule against this
        cycle's corpus and roll the :class:`RuleBreachReport` into a :class:`ScanReport`.

        The corpus is the newly-landed selection the trigger chose (``spec.attacks`` = primitive ids)
        out of the live repertoire; ``run_policy_scan`` re-aims it per rule. The per-rule report is
        carried verbatim into the persisted payload (``ScanReport.rule_breach_report``) so §4's
        diff_post can render "holds N/M" for each rule.

        The injected ``policy_runner`` is the offline test seam:
        ``policy_runner(policy, config, corpus, *, n_trials) -> RuleBreachReport``. The finer
        ``grader`` seam stays INSIDE the live path (real ``live_responder`` + ``run_policy_scan``)
        and only swaps the judge: ``grader(rule, judge, primitive, response, config) -> bool``.
        """
        from rogue.governance.scan_runner import default_grade, live_responder, run_policy_scan
        from rogue.report import Finding, ScanReport, technique_label

        if spec.policy is None:
            raise ValueError(
                "policy-mode scan requires spec.policy (a decomposed ClientPolicy)"
            )

        # Source the corpus from the live repertoire, filtered to the trigger's selection when given.
        corpus = self._load_repertoire(spec)
        if spec.attacks:
            wanted = set(spec.attacks)
            corpus = [p for p in corpus if getattr(p, "primitive_id", None) in wanted]

        # The scan body is synchronous (``live_responder`` drives the target panel via its OWN
        # event loop). Run it in a worker thread so that loop is created and used entirely there,
        # never colliding with the outer loop ``run`` is awaited inside (the worker / the API) —
        # which would otherwise raise "Cannot run the event loop while another loop is running".
        def _blocking_policy_scan():
            if self._policy_runner is not None:
                return self._policy_runner(spec.policy, config, corpus, n_trials=spec.n_trials)
            # LIVE path: real per-rule judge + real target trials (one model call per trial). When
            # no panel is injected, build one carrying the target key so a keyed endpoint actually
            # authenticates (no api_key ⇒ no Authorization header ⇒ 401).
            from rogue.reproduce.target_panel import TargetPanel

            panel = self._panel or TargetPanel(adapter_extra=self._adapter_extra(spec))
            respond, _stats = live_responder(panel)
            return run_policy_scan(
                spec.policy,
                config,
                corpus,
                respond=respond,
                grade=(self._grader or default_grade),
                n_trials=spec.n_trials,
            )

        report = await asyncio.to_thread(_blocking_policy_scan)

        verdicts = list(report.rule_verdicts)
        n_tests = sum(v.n_trials for v in verdicts)
        n_breaches = sum(v.n_breaches for v in verdicts)

        # One Finding per rule verdict. A rule is not an attack family, so populate the shared Finding
        # faithfully where it maps (family from the verdict's attack_family, hit rate from the trials)
        # and rely on the carried `rule_breach_report` for per-rule detail diff_post renders.
        findings: list[Finding] = []
        for v in verdicts:
            family = v.attack_family.value if v.attack_family is not None else "unknown"
            findings.append(
                Finding(
                    family=family,
                    technique=technique_label(family),
                    vector="user_turn",
                    severity="high" if v.n_breaches > 0 else "low",
                    title=f"Policy rule {v.rule_id}",
                    success_rate=v.breach_rate,
                    n_trials=v.n_trials,
                    n_breach=v.n_breaches,
                    example_attack=None,
                    example_response=None,
                )
            )

        # Capture transcripts as pointers when a snapshot store is wired. NOTE: the §6 runner records
        # transcripts as `transcript_refs` strings (rule::primitive::trial markers), not raw blobs, and
        # the engine has no `org_id` (it lives on the worker's LeasedJob, not on ScanSpec). So there is
        # no transcript text to content-address here — this is a thin, explicitly-marked seam that §4's
        # diff_post fills (it has the org_id + the live transcripts). When a store IS injected we put a
        # small audit marker so the wiring is exercised end-to-end; the real per-breach capture is
        # diff_post's job. The marker ref is NOT threaded back into findings (no per-finding transcript
        # exists at this layer), keeping this strictly a capability seam.
        if self._snapshot_store is not None:
            try:
                org_id = getattr(spec.policy, "customer_id", None) or "platform"
                self._snapshot_store.put(
                    f"policy-scan:{report.policy_id}:{report.config_id}",
                    org_id=org_id,
                    content_type="policy_scan_marker",
                )
            except Exception:  # noqa: BLE001 — capture is best-effort, never fails a scan.
                pass

        # top_attack falls out of the breached findings (ScanReport.top_attack); surface the
        # highest-breach-rate rule's family as the example_response on its finding is N/A here.
        # mode="json" so str-Enums (AttackFamily/BreachType) serialize to their wire VALUES, not enum
        # objects — otherwise a consumer reading the in-process ScanReport (before it crosses the
        # JSON-column boundary in the durable path) would render enum reprs like "AttackFamily.X".
        report_dict = report.model_dump(mode="json")
        return ScanReport(
            target=config.base_url or config.target_model,
            n_tests=n_tests,
            n_breaches=n_breaches,
            cost_usd=0.0,  # best-effort: the §6 runner doesn't surface spend on the report object.
            findings=findings,
            rule_breach_report=report_dict,
            # Additive: ride the Surface-1 context (agent identity + ground-truth refs) the Slack
            # cycle threaded through into the persisted payload, so the auto-signed attestation
            # entry is self-describing (build-06 §5). Absent ⇒ None ⇒ report dict unchanged.
            surface1_context=spec.surface1_context,
        )

    # --- operation #1b: ladder scan -----------------------------------------------------------

    async def _run_ladder(self, spec: ScanSpec, config, progress: ProgressCallback | None):
        """Escalation-ladder scan: throw the full multi-tier arsenal at each goal (the pack primitives
        act as the goals). Mirrors ``benchmark_run._run_one_cell`` — one shared panel/judge, a
        per-goal budget, bounded concurrency, first-breach-wins per goal. Budget is effectively
        mandatory here (the ladder is the expensive path): an unset budget defaults to a safe cap."""
        import asyncio

        from rogue.packs import filter_attacks, load_pack
        from rogue.report import Finding, ScanReport, humanize_technique, technique_label
        from rogue.reproduce.escalation_ladder import run_escalation_ladder_one
        from rogue.reproduce.judge import JudgeAgent
        from rogue.reproduce.target_panel import TargetPanel

        goals = filter_attacks(load_pack(spec.pack), spec.attacks)[: spec.max_tests]
        ctx = self._build_escalation_ctx(config, len(goals), spec.n_trials)
        runner = self._ladder_runner or run_escalation_ladder_one

        owns_panel = self._panel is None
        panel = self._panel if self._panel is not None else TargetPanel(adapter_extra=self._adapter_extra(spec))
        owns_judge = self._judge is None
        judge = self._judge if self._judge is not None else (
            JudgeAgent(model=self._judge_model) if self._judge_model else JudgeAgent()
        )

        budget = spec.budget if spec.budget is not None else _DEFAULT_LADDER_BUDGET
        per_goal = budget / max(1, len(goals))
        sem = asyncio.Semaphore(3)
        n_total = len(goals)
        progressed = {"n": 0}

        async def _one(goal):
            async with sem:
                res = await runner(
                    goal,
                    planner=ctx.planner,
                    panel=panel,
                    judge=judge,
                    configs=[config],
                    n_trials=spec.n_trials,
                    strategies=ctx.rotation,
                    image_renderers=ctx.image_renderers,
                    coj_operations=ctx.coj_operations,
                    structured_formats=ctx.structured_formats,
                    audio_styles=ctx.audio_styles,
                    budget_usd=per_goal,
                    candidate_attempt_quota=ctx.effective_quota,
                    candidate_ids=ctx.candidate_ids,
                    # §10.10 contextual mode — cross-tier blended order (None ⇒ fixed
                    # tier sequence). getattr keeps injected test-double ctxs working.
                    cross_tier_order=getattr(ctx, "cross_tier_order", None),
                )
            progressed["n"] += 1
            if progress is not None:
                await progress(progressed["n"], n_total, res.winning_strategy or "held")
            return goal, res

        try:
            results = await asyncio.gather(*[_one(g) for g in goals])
        finally:
            if owns_panel:
                await panel.aclose()
            if owns_judge and hasattr(judge, "aclose"):
                await judge.aclose()
            planner = getattr(ctx, "planner", None)
            if planner is not None and hasattr(planner, "aclose"):
                await planner.aclose()

        # §10.10 — feed the contextual priors from hosted scans too (best-effort; never fatal).
        self._log_ladder_telemetry(results, config, ctx)

        findings: list[Finding] = []
        n_breaches = 0
        total_cost = 0.0
        for goal, res in results:
            breached = res.winning_strategy is not None
            if breached:
                n_breaches += 1
            total_cost += getattr(res, "spend_usd", 0.0)
            # A ladder run is ONE test per goal: the goal was either achieved (the escalation broke
            # through) or held. success_rate / n_breach / n_trials all reflect that single outcome
            # (1/1 = achieved, 0/1 = held) so they AGREE with the headline score (severity × success).
            # Reporting the raw escalation-attempt count as n_trials made a finding read "breached
            # 1/18 (6%)" next to a critical-100 score — the same number meaning two different things.
            # The escalation DEPTH (how many techniques it took to break through — a real signal of how
            # hard the model was to crack) is surfaced in the title instead.
            depth = len(res.attempts)
            title = goal.title
            if breached and depth > 1:
                title = f"{goal.title} — broke through after escalating through {depth} techniques"
            findings.append(
                Finding(
                    family=goal.family.value,
                    # The winning transform (e.g. "crescendo", "image:ocr") is richer than the family;
                    # humanize it so the PERSISTED technique is already customer-facing (a graduated
                    # candidate's raw ULID never reaches a report). Fall back to the family label when
                    # the goal held (no breach).
                    technique=(
                        humanize_technique(res.winning_strategy)
                        if res.winning_strategy
                        else technique_label(goal.family.value)
                    ),
                    vector=goal.vector.value,
                    severity=goal.base_severity.value,
                    title=title,
                    success_rate=1.0 if breached else 0.0,
                    n_trials=1,
                    n_breach=1 if breached else 0,
                    example_attack=(goal.payload_template or "")[:400] or None,
                    example_response=None,
                )
            )

        findings.sort(key=lambda f: f.success_rate, reverse=True)
        return ScanReport(
            target=config.base_url or config.target_model,
            n_tests=len(findings),
            n_breaches=n_breaches,
            cost_usd=round(total_cost, 6),
            findings=findings,
        )

    # --- operation #1: scan -------------------------------------------------------------------

    async def run(self, spec: ScanSpec, *, progress: ProgressCallback | None = None) -> ScanReport:
        """Run the scan. The ladder path has its own per-goal loop; every other mode delegates to
        :func:`rogue.scan.run_scan` (the one provider-agnostic single-turn loop), passing ``progress``
        straight through as that function's per-primitive hook."""
        from rogue.packs import filter_attacks, load_pack
        from rogue.scan import run_scan

        config = self._build_config(spec)
        if spec.mode == "policy":
            # Path A: scan a decomposed ClientPolicy rule-by-rule against this cycle's corpus
            # (build-04 §6 per-rule scanner). Separate branch — returns early, like the ladder.
            return await self._run_policy(spec, config, progress)
        if spec.mode == "ladder":
            # The deepest path: escalate each goal through the full multi-tier ladder (graduated
            # techniques + CoJ + structured + image/audio renderers). Separate loop — return early.
            return await self._run_ladder(spec, config, progress)
        if spec.mode == "repertoire":
            # The full harvested arsenal (corpus, most-reproducible first), capped at max_tests —
            # not a frozen JSON pack. Still the single-turn run_scan loop below.
            primitives = self._load_repertoire(spec)
        else:
            primitives = filter_attacks(load_pack(spec.pack), spec.attacks)[: spec.max_tests]

        # run_scan builds/owns the panel + judge unless we inject them (the test seams), applies the
        # 0.4 breach threshold, sums cost, and shapes the ScanReport — the exact logic this engine
        # used to mirror inline. ``progress`` is forwarded as run_scan's per-primitive hook.
        return await run_scan(
            config,
            primitives,
            n_trials=spec.n_trials,
            budget=spec.budget,
            adapter_extra=self._adapter_extra(spec),
            panel=self._panel,
            judge=self._judge,
            judge_model=self._judge_model,
            progress=progress,
            # Agent-exec is auto-on for tool-bearing configs; a ScanSpec may override per-scan.
            agent_exec=getattr(spec, "agent_exec", True),
            agent_exec_seeds=getattr(spec, "agent_exec_seeds", 3),
            agent_exec_framing=getattr(spec, "agent_exec_framing", "raw"),
        )

    # --- operation #2: validate ---------------------------------------------------------------

    async def validate(self, spec: ScanSpec) -> ValidationResult:
        """Cheap pre-flight: delegate to the SDK ``Client``'s validate path."""
        from rogue.client import Client

        client = Client(
            endpoint=spec.target.endpoint,
            provider=spec.target.provider,
            model=spec.target.model,
            api_key=spec.target.api_key,
            system_prompt=spec.target.system_prompt,
            _adapter_extra=self._adapter_extra(spec),
        )
        return await client._validate_async()

    # --- operation #3: benchmark --------------------------------------------------------------

    async def benchmark(self, spec: ScanSpec, *, dataset: str, max_goals: int) -> BenchmarkReport:
        """Research-grade ASR on a standard dataset; delegate to the shared benchmark runner."""
        from rogue.benchmark import run_benchmark

        config = self._build_config(spec)
        return await run_benchmark(
            config,
            dataset=dataset,
            max_goals=max_goals,
            adapter_extra=self._adapter_extra(spec),
            judge_model=self._judge_model,
            panel=self._panel,
            judge=self._judge,
        )


def _default_model(provider: str | None) -> str:
    """The SDK's per-provider default model (raises for an unknown provider, like ``Client`` does)."""
    from rogue.client import _DEFAULT_MODELS

    if provider in _DEFAULT_MODELS:
        return _DEFAULT_MODELS[provider]
    raise ValueError(
        f"no default model for provider {provider!r}; set spec.target.model "
        f"(known providers with defaults: {', '.join(sorted(_DEFAULT_MODELS))})"
    )


__all__ = ["DefaultScanEngine"]
